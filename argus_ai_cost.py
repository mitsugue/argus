"""ARGUS AI cost ledger (v10.50) — pure, stdlib, unit-tested.

Application-side cost accounting + HARD budget stops for the AI judge. The point
(GPT Pro cost-control patch): do NOT rely on the OpenAI prepaid balance or a
provider-side project budget as the stop — enforce a deterministic ARGUS-side
daily/monthly USD ceiling so a loop or a bad config can never run the bill up.

All money values are ESTIMATES from a configurable per-token price table — token
counts come from the providers' own usage metadata, prices are env-overridable
(real list prices change; we never hard-code a number we can't let the owner fix).

Nothing here does I/O or imports Flask: scanner owns the in-memory accumulator,
the persistence to the ledger branch, and the env wiring; this module is the math.
"""

# Default unit prices in USD per 1,000,000 tokens. Override per-model in scanner
# from env (OPENAI_PRICE_INPUT_PER_1M, etc.) — these are conservative placeholders,
# NOT authoritative list prices. Cost is always surfaced as "estimated".
DEFAULT_PRICING = {
    "gpt-5.5":           {"in": 1.25, "out": 10.00},
    # v13.5.63: official list prices (developers.openai.com/api/docs/pricing,
    # read 2026-09-07). GPT-6 Astra is the event-analysis default; the 5.6
    # rows keep the fallback priced. cachedIn = cached-input rate.
    "gpt-6-astra":       {"in": 10.00, "out": 50.00, "cachedIn": 1.00},
    "gpt-5.6-terra":     {"in": 2.00, "out": 12.00, "cachedIn": 0.20},
    "gpt-5.6-sol":       {"in": 4.00, "out": 20.00, "cachedIn": 0.40},
    "gemini-2.5-pro":    {"in": 1.25, "out": 10.00},
    "gemini-2.5-flash":  {"in": 0.30, "out": 2.50},
}
# A Google-Search grounding call carries its own per-request charge on some tiers.
DEFAULT_GROUNDING_USD = 0.035


def _num(x, default=0.0):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else default


def estimate_cost(model, input_tokens, output_tokens, pricing=None,
                  grounding=False, grounding_usd=DEFAULT_GROUNDING_USD):
    """USD estimate for one model call. Unknown model → 0-priced (still counted
    as a run, just $0 estimate — better an honest 0 than a fabricated number).
    output_tokens should already INCLUDE reasoning/thinking tokens (they bill as
    output). Always returns a non-negative float rounded to 6 dp."""
    table = pricing or DEFAULT_PRICING
    p = table.get(model) or {}
    cost = (_num(input_tokens) / 1_000_000.0) * _num(p.get("in"))
    cost += (_num(output_tokens) / 1_000_000.0) * _num(p.get("out"))
    if grounding:
        cost += _num(grounding_usd, DEFAULT_GROUNDING_USD)
    return round(max(0.0, cost), 6)


def month_key(dt):
    """'YYYY-MM' for a datetime (the monthly budget bucket)."""
    return dt.strftime("%Y-%m")


def day_key(dt):
    """'YYYY-MM-DD' for a datetime (the daily budget bucket)."""
    return dt.strftime("%Y-%m-%d")


def budget_check(day_spent, month_spent, day_budget, month_budget,
                 reserve_usd=0.0, force=False):
    """Pure HARD-STOP decision evaluated BEFORE a run (so it weighs ALREADY-spent
    vs the ceiling — a single run is cents and can't blow past materially).

    Returns (allowed: bool, reason: str|None, usedReserve: bool).
      - Normal stop: block once day_spent >= day_budget or month_spent >= month_budget.
      - Emergency reserve: a manual force=True may dip ABOVE the ceiling but only up
        to budget + reserve_usd, and only the MONTHLY reserve is honored (the daily
        cap is advisory under force). This is the 'small manual emergency reserve'.
    A budget of 0 or negative is treated as 'unlimited' (disabled stop)."""
    d_lim = day_budget if isinstance(day_budget, (int, float)) and day_budget > 0 else None
    m_lim = month_budget if isinstance(month_budget, (int, float)) and month_budget > 0 else None
    reserve = max(0.0, _num(reserve_usd))

    if m_lim is not None and month_spent >= m_lim:
        if force and month_spent < (m_lim + reserve):
            return True, None, True
        ceil = m_lim + (reserve if force else 0.0)
        return False, (f"monthly AI budget reached: ${month_spent:.2f} / ${m_lim:.2f}"
                       + (f" (+${reserve:.2f} reserve exhausted)" if force else "")), False
    if d_lim is not None and day_spent >= d_lim and not force:
        return False, f"daily AI budget reached: ${day_spent:.2f} / ${d_lim:.2f}", False
    return True, None, False


# Cumulative compatibility accounting is carried by the existing cost-policy
# checkpoint. Each process owns one monotone counter per JST day. Restoration
# takes the later prefix of each counter, then sums independent writers; it
# never derives money from a recent-record display window.
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta

ACCOUNTING_SCHEMA = 'argus-ai-cost-accounting-v1'
_JST = timezone(timedelta(hours=9))


def _micros(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid_cost_amount')
    return int(round(value * 1_000_000))


def _cost_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _cost_day(value):
    instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('cost_timestamp_requires_timezone')
    return instant.astimezone(_JST).date().isoformat()


def normalize_accounting(state=None):
    if state is None:
        return {'schemaVersion': ACCOUNTING_SCHEMA, 'writers': {},
                'legacyMonths': {}, 'legacyDays': {}, 'recent': {}}
    if not isinstance(state, dict) or state.get('schemaVersion') != ACCOUNTING_SCHEMA:
        raise ValueError('cost_accounting_schema_invalid')
    result = copy.deepcopy(state)
    if set(result) != {'schemaVersion', 'writers', 'legacyMonths', 'legacyDays', 'recent'}:
        raise ValueError('cost_accounting_fields_invalid')
    for key in ('writers', 'legacyMonths', 'legacyDays', 'recent'):
        if not isinstance(result[key], dict):
            raise ValueError('cost_accounting_map_invalid')
    for identity, row in result['writers'].items():
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}:\d{4}-\d{2}-\d{2}', identity):
            raise ValueError('cost_writer_identity_invalid')
        if set(row) != {'day', 'count', 'micros'} or row['day'] != identity[33:]:
            raise ValueError('cost_writer_day_invalid')
        datetime.fromisoformat(row['day'])
        if any(isinstance(row[k], bool) or not isinstance(row[k], int) or row[k] < 0 for k in ('count', 'micros')):
            raise ValueError('cost_counter_invalid')
    for kind, pattern in [('legacyMonths', r'\d{4}-\d{2}'), ('legacyDays', r'\d{4}-\d{2}-\d{2}')]:
        for period, row in result[kind].items():
            if not re.fullmatch(pattern, period) or set(row) != {'micros', 'snapshotDigest', 'asOf'}:
                raise ValueError('legacy_cost_period_invalid')
            if isinstance(row['micros'], bool) or not isinstance(row['micros'], int) or row['micros'] < 0:
                raise ValueError('legacy_cost_amount_invalid')
            if not re.fullmatch(r'[a-f0-9]{64}', row['snapshotDigest']):
                raise ValueError('legacy_cost_digest_invalid')
            datetime.fromisoformat(period + '-01' if kind == 'legacyMonths' else period)
            _cost_day(row['asOf'])
    for identity, row in result['recent'].items():
        if not isinstance(identity, str) or len(identity) > 160 or not isinstance(row, dict):
            raise ValueError('cost_recent_identity_invalid')
        _cost_day(row.get('at')); _micros(row.get('totalUsd'))
    if len(result['recent']) > 50:
        raise ValueError('cost_recent_window_invalid')
    return result


def merge_accounting(left, right):
    """Union snapshots without dropping new calls or billing shared prefixes twice."""
    out, saved = normalize_accounting(left), normalize_accounting(right)
    for identity, row in saved['writers'].items():
        current = out['writers'].get(identity)
        if current is not None:
            if current['count'] == row['count'] and current != row:
                raise ValueError('cost_counter_prefix_conflict')
            newer, older = (row, current) if row['count'] > current['count'] else (current, row)
            if newer['micros'] < older['micros']:
                raise ValueError('cost_counter_nonmonotone')
            row = newer
        out['writers'][identity] = copy.deepcopy(row)
    # Legacy totals are an opaque reported amount, not additional calls.
    # Keep their provenance and strongest reported value once per period.
    for kind in ('legacyMonths', 'legacyDays'):
        for period, row in saved[kind].items():
            current = out[kind].get(period)
            if current is None or (row['micros'], row['asOf'], row['snapshotDigest']) > (current['micros'], current['asOf'], current['snapshotDigest']):
                out[kind][period] = copy.deepcopy(row)
    for identity, row in saved['recent'].items():
        if identity in out['recent'] and out['recent'][identity] != row:
            raise ValueError('cost_receipt_conflict')
        out['recent'][identity] = copy.deepcopy(row)
    out['recent'] = dict(sorted(out['recent'].items(), key=lambda item: (item[1]['at'], item[0]))[-50:])
    return out


def record_accounting(state, record, writer_id):
    out = normalize_accounting(state)
    if not isinstance(writer_id, str) or not re.fullmatch(r'[a-f0-9]{32}', writer_id):
        raise ValueError('cost_writer_id_invalid')
    day = _cost_day(record.get('at')); amount = _micros(record.get('totalUsd'))
    key = writer_id + ':' + day
    previous = out['writers'].get(key, {'day': day, 'count': 0, 'micros': 0})
    row = {'day': day, 'count': previous['count'] + 1, 'micros': previous['micros'] + amount}
    out['writers'][key] = row
    out['recent'][key + ':' + f"{row['count']:020d}"] = copy.deepcopy(record)
    out['recent'] = dict(sorted(out['recent'].items(), key=lambda item: (item[1]['at'], item[0]))[-50:])
    return out


def import_legacy_snapshot(state, snapshot):
    """New snapshots merge by writer identity. Old snapshots remain labelled reported amounts."""
    if 'accounting' in snapshot:
        return merge_accounting(state, snapshot['accounting'])
    month, day, stamp = snapshot.get('month'), snapshot.get('day'), snapshot.get('asOf')
    if not isinstance(month, str) or not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('legacy_cost_month_missing')
    if _cost_day(stamp)[:7] != month:
        raise ValueError('legacy_cost_month_mismatch')
    saved = normalize_accounting(); digest = _cost_digest(snapshot)
    saved['legacyMonths'][month] = {'micros': _micros(snapshot.get('monthSpentUsd')), 'snapshotDigest': digest, 'asOf': stamp}
    if day is not None:
        if day != _cost_day(stamp):
            raise ValueError('legacy_cost_day_mismatch')
        saved['legacyDays'][day] = {'micros': _micros(snapshot.get('daySpentUsd')), 'snapshotDigest': digest, 'asOf': stamp}
    occurrences = {}
    for record in snapshot.get('recentRuns') or []:
        if not isinstance(record, dict):
            raise ValueError('legacy_cost_record_invalid')
        fingerprint = _cost_digest(record); occurrences[fingerprint] = occurrences.get(fingerprint, 0) + 1
        saved['recent']['legacy:' + fingerprint + ':' + str(occurrences[fingerprint])] = copy.deepcopy(record)
    saved['recent'] = dict(sorted(saved['recent'].items(), key=lambda item: (item[1]['at'], item[0]))[-50:])
    return merge_accounting(state, saved)


def accounting_totals(state, now):
    saved = normalize_accounting(state)
    if now.tzinfo is None:
        raise ValueError('cost_timestamp_requires_timezone')
    day = now.astimezone(_JST).date().isoformat(); month = day[:7]
    day_rows = [r for r in saved['writers'].values() if r['day'] == day]
    month_rows = [r for r in saved['writers'].values() if r['day'][:7] == month]
    prior_month = saved['legacyMonths'].get(month, {}).get('micros', 0)
    prior_day = saved['legacyDays'].get(day, {}).get('micros', 0)
    recent = [r for _, r in sorted(saved['recent'].items(), key=lambda item: (item[1]['at'], item[0]), reverse=True)]
    return {'day': day, 'month': month,
            'daySpentUsd': (prior_day + sum(r['micros'] for r in day_rows)) / 1_000_000,
            'monthSpentUsd': (prior_month + sum(r['micros'] for r in month_rows)) / 1_000_000,
            'recordedMonthCalls': sum(r['count'] for r in month_rows),
            'recentRuns': recent[:20], 'lastRun': recent[0] if recent else None,
            'historyCoverage': 'legacy_reported_amount_plus_recorded_calls',
            'legacyBaselinePresent': month in saved['legacyMonths'],
            'historicalCallsReconstructed': False, 'displayWindowAffectsTotals': False}
