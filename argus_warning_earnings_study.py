"""Offline replay of adopted D07 using retained, dated original inputs.

No collection or store writes. This evaluator deliberately does not turn a
recent download into a vintage that was observable ten years ago.
"""
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, time

from argus_warning_candidates import RULE_VERSION, TOKYO, _calendar, _closes, _row_time, earnings_rule
from jp_market_engine import _instant, _sha256
from jp_market_sign_event_study import _condition

METHOD = 'jp-warning-earnings-original-replay-v1'

def _reconstruct(row, limit, *, financial=False):
    # This copy is explicitly hypothetical. Keep original timestamps in the
    # source digest; never write this assumption back into the original store.
    known = _row_time(row)
    if known is None or known > limit:
        return None
    day = (row.get('summary') or {}).get('DiscDate') if financial else row.get('date') or row.get('queryDate')
    try:
        assumed = datetime.combine(date.fromisoformat(day), time(18), TOKYO)
    except (TypeError, ValueError):
        return None
    if financial:
        published = _instant(row.get('publishedAt'))
        if published is None or published > limit:
            return None
        assumed = max(assumed, published)
    if assumed > limit:
        return None
    return {**row, 'knownAt':assumed.isoformat(), 'receivedAt':assumed.isoformat()}



def study(*, sessions, nikkei_rows, financial_rows, membership_by_day,
          stock_bars, topix_rows, coverage_by_day, cutoff, reconstruct=False):
    """Replay known originals after each close; forward outcomes are separate.

    Called offline, never from a public GET. Each replay uses only receipts
    observable by 18:00 JST that day; earnings_rule additionally requires the
    original prior forecast, the dated 225-member scope and next-session bars.
    Missing windows reset activation continuity, not become clear conditions.
    Explicit reconstruct=True is a separate first-retrieved-version study with
    assumed publication availability; it never certifies an archived vintage.
    """
    if type(reconstruct) is not bool:
        raise ValueError('earnings_replay_explicit_availability_basis')
    days, limit = _calendar(sessions, cutoff)
    if (len(financial_rows) > 30000 or not isinstance(stock_bars, Mapping)
            or len(stock_bars) > 400 or sum(len(rows) for rows in stock_bars.values()) > 1200000
            or len(membership_by_day) > 3001 or len(coverage_by_day) > 3001):
        raise ValueError('earnings_replay_input_bound')
    original_inputs = {'sessions': days, 'nikkei': nikkei_rows, 'financial': financial_rows,
        'membership': membership_by_day, 'stocks': stock_bars, 'topix': topix_rows, 'coverage': coverage_by_day}
    source_digest = _sha256(original_inputs)
    if reconstruct:
        first = {}
        for row in financial_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get('summary'), Mapping):
                continue
            summary = row['summary']; key = (summary.get('Code'),summary.get('DiscDate'),summary.get('DiscNo'))
            known = _row_time(row)
            if known is None or known > limit:
                continue
            if key in first and known == _row_time(first[key]) and summary != first[key]['summary']:
                raise ValueError('earnings_replay_ambiguous_original')
            if key not in first or known < _row_time(first[key]):
                first[key] = row
        financial_rows = [r for row in first.values() if (r := _reconstruct(row, limit, financial=True)) is not None]
        stock_bars = {code:[r for row in rows if (r := _reconstruct(row, limit)) is not None]
                      for code,rows in stock_bars.items()}
        topix_rows = [r for row in topix_rows if (r := _reconstruct(row, limit)) is not None]
        coverage_by_day = {day:r for day,row in coverage_by_day.items()
                           if (r := _reconstruct({**row,'queryDate':day}, limit)) is not None}
    prices = _closes(nikkei_rows, 'NIKKEI_225_INDEX', limit)
    closes = {day: value[0] for day, value in prices.items() if day in days}
    events, measured, reasons = {}, [], Counter()
    previous = None
    for index, day in enumerate(days):
        if index < 10:
            continue
        instant = datetime.combine(date.fromisoformat(day), time(18), TOKYO)
        if instant > limit:
            continue
        row = earnings_rule(sessions=days[:index+1], financial_rows=financial_rows,
            membership_by_day=membership_by_day, stock_bars=stock_bars, topix_rows=topix_rows,
            coverage_by_day=coverage_by_day, cutoff=instant.isoformat())
        if row.get('status') != 'AVAILABLE' or type(row.get('conditionMet')) is not bool:
            previous = None
            reasons['INPUT_OR_FOLLOWING_REACTION_NOT_OBSERVABLE'] += 1
            continue
        known = _instant(row.get('knowledgeTime'))
        if known is None or known > instant:
            raise ValueError('earnings_replay_future_knowledge')
        met = row['conditionMet']
        measured.append(day)
        if previous is not None and previous[0] == index-1 and previous[1] != met:
            events[(RULE_VERSION + '.D07', day)] = (instant, 1 if met else -1)
        previous = (index, met)
    result = _condition('D07', {'seriesId': RULE_VERSION + '.D07', 'value': 1, 'expects': 'FALL'},
                        events, closes, days)
    condition = {**result, 'ruleId': RULE_VERSION + '.D07', 'expects': 'FALL',
        'evaluated': result.get('horizons', {}).get('5', {}).get('evaluated', 0),
        'inputDays': len(measured), 'inputStart': measured[0] if measured else None,
        'inputEnd': measured[-1] if measured else None, 'gatedDays': sum(reasons.values()),
        'historicalVintageVerified': False, 'validationStatus': 'UNVALIDATED',
        'actionAuthority': False, 'predictiveProbabilities': None}
    body = {'schemaVersion': METHOD, 'informationCutoff': cutoff, 'ruleVersion': RULE_VERSION,
        'availabilityBasis': ('RECONSTRUCTED_PUBLICATION_18JST_NOT_ARCHIVED_VINTAGE' if reconstruct
            else 'ACTUAL_RETAINED_RECEIPTS_AT_DAILY_18JST'), 'condition': condition,
        'correctionBasis': 'FIRST_RETRIEVED_VERSION_NOT_ARCHIVED' if reconstruct else 'ACTUAL_RECEIPT_ORDER',
        'missingCounts': dict(reasons), 'requestedSessions': len(days),
        'tenYearOriginalCoverageComplete': False,
        'historicalVintageVerified': False, 'validationStatus': 'UNVALIDATED',
        'sourceDigest': source_digest,
        'legacySupportResultsReused': False, 'actionAuthority': False,
        'automaticAiCalls': 0, 'providerCalls': 0, 'predictiveProbabilities': None}
    return {**body, 'artifactId': 'jp-warning-earnings-study-' + _sha256(body)}
