"""Nikkei 225 morning level map: PER multiple lines, distance guides and
their pre-registered record (2026-10-04).

What this is
------------
Every morning, before the open, the map lists the price levels above and
below the previous close: whole-number multiples of the index EPS (the line
moves with the EPS every day), the line at the same multiple as the last
confirmed top or bottom, and the previous close +/- 1, 2, 3 ATR. Each level
carries how often, in the past, the next 4 % turning point came within 1 %
of a level at that distance, how often such a level was reached within ten
sessions and after how many sessions. Those are past frequencies, not
probabilities, and the accuracy is the same as "previous close +/- 2 ATR"
without looking at levels at all. The research behind it found no level type
with a forward edge (2010-2023 the PER lines were at chance; June to October
2026 they were unusually close to the turns). So the product's job is the
record: a map fixed before the open, scored afterwards by fixed rules.

The EPS is an ARGUS estimate, never the official figure: Nikkei's weighted
average PER is market-capitalisation weighted, so the estimate is
sum(market cap) / sum(forecast net income) over that day's constituents,
with loss-making forecasts entering signed and members without a forecast
filled from their trailing figures (counted). The official series is not an
input.

Pure arithmetic on declared inputs: no network, no clock, no file.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date as _date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SCHEMA = "jp-market-level-map-v1"
RULE_VERSION = "level-map-rule-v1"
FREQUENCY_TABLE_VERSION = "freq-table-2026"
DAYS_TABLE_VERSION = "days-table-2026"
EPS_BASIS = "ARGUS_ESTIMATE_MARKET_CAP_WEIGHTED_FORWARD"
EPS_LABEL_JA = "ARGUS推計（構成銘柄の時価総額加重の予想EPS。公式値ではありません）"
ZIGZAG_THRESHOLD = 0.04
PER_LINE_RANGE = 0.15          # integer lines within +/-15 % of the previous close
MERGE_TOLERANCE = 0.005        # rows within 0.5 % become one row
ATR_SESSIONS = 14
EPS_JUMP_FLAG = 0.03           # the line "jumped": EPS moved 3 % or more

# Distance (ATR) -> how often the next close 4 % turning point came within
# +/-1 % of a level at that distance. Research table for 2026, fitted only on
# answers known by the end of 2025 (rebuilt each January, versioned).
FREQUENCY_TABLE = (
    # lower, upper, upper side %, lower side %
    (0.0, 0.5, 8.0, 6.9), (0.5, 1.0, 13.6, 10.9), (1.0, 1.5, 17.7, 14.0),
    (1.5, 2.0, 19.8, 18.6), (2.0, 3.0, 18.4, 19.6), (3.0, 4.0, 17.0, 17.6),
    (4.0, 6.0, 12.1, 13.6), (6.0, math.inf, 7.1, 6.3),
)
# Distance (ATR) -> reached within ten sessions (%), sessions to reach
# (median, 25th, 75th percentile) among levels reached within 60 sessions.
DAYS_TABLE = {
    "UP": ((0.0, 0.5, 93, 0, 0, 0), (0.5, 1.0, 85, 0, 0, 3), (1.0, 1.5, 71, 3, 1, 8),
           (1.5, 2.0, 56, 6, 2, 14), (2.0, 3.0, 38, 10, 4, 21), (3.0, 4.0, 20, 16, 7, 28),
           (4.0, 6.0, 10, 21, 11, 35), (6.0, math.inf, 2, 31, 21, 44)),
    "DOWN": ((0.0, 0.5, 89, 0, 0, 0), (0.5, 1.0, 77, 1, 0, 4), (1.0, 1.5, 64, 3, 0, 9),
             (1.5, 2.0, 50, 5, 1, 14), (2.0, 3.0, 35, 9, 3, 22), (3.0, 4.0, 22, 13, 6, 29),
             (4.0, 6.0, 11, 18, 9, 34), (6.0, math.inf, 3, 26, 16, 41)),
}
EVIDENCE_JA = {
    "PER_LINE": "保留（2010〜2023年は偶然並み、2024年以降は兆し）",
    "SAME_MULTIPLE": "保留・弱い（直前の転換点と同じ倍率）",
    "PIVOT_PRICE": "参考（効く証拠なし）",
    "ATR_GUIDE": "距離の目安",
}
FIXED_NOTES_JA = (
    "精度は今の値±2ATRと同程度（±2ATRの1本が次の転換点の±1%に入った割合は24〜29%、±1・2・3ATRのどれかなら56〜59%）。",
    "整数PER線（公式の加重平均PERから求めた線）は2026年6〜10月によく効き、2010〜2023年は偶然並み。",
    "この地図の線は推計EPSから引いた線で、公式の値の線と1〜2%ずれることがある。上の成績はそのまま当てはまらず、この線の成績は下の答え合わせで数える。",
    "水準に届いた後に先に2%戻った割合は約5割（ずらした水準でも約5割）。",
)


class LevelMapError(ValueError):
    pass


def estimate_input_usable(record, *, strict=False):
    """Reject known missing constituent valuations; new inputs need coverage.

    Legacy records without this metadata retain their unknown coverage. They
    are not a means to admit a newly collected partial day.
    """
    if not isinstance(record, dict):
        return False
    coverage = record.get('coverage')
    if coverage is None:
        return not strict
    if not (isinstance(coverage, dict) and type(coverage.get('members')) is int
            and coverage['members'] > 0 and type(coverage.get('missingMarketCap')) is int
            and coverage['missingMarketCap'] == 0):
        return False
    # Older coverage metadata may omit these fields; preserve its unknown
    # status, but never admit a new receipt or a known partial aggregate.
    for key, expected in [('missingEarnings', 0), ('marketCapShareUsed', 1.0)]:
        if key not in coverage:
            if strict:
                return False
        elif isinstance(coverage[key], bool) or coverage[key] != expected:
            return False
    return True


def morning_input_usable(record):
    return isinstance(record,dict) and estimate_input_usable({'coverage':record.get('epsCoverage')})


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


# --- EPS estimate --------------------------------------------------------------

def _price(row: Mapping[str, Any]) -> Optional[float]:
    per, eps = _finite(row.get("PER")), _finite(row.get("EPS"))
    if per and eps and per * eps > 0:
        return per * eps
    pbr, bps = _finite(row.get("PBR")), _finite(row.get("BPS"))
    if pbr and bps and pbr * bps > 0:
        return pbr * bps
    # Only the dated daily-bar join below can supply this fallback. Adjusted
    # prices and the OHLC endpoint's differently defined market cap are not
    # substitutes for valuation inputs.
    close = _finite(row.get('unadjustedClose'))
    if close is not None and close > 0:
        return close
    return None


def valuation_with_daily_closes(valuation, daily_bars, *, date):
    """Copy rows, adding only same-code/date unadjusted closes when needed.

    Valuation EPS is in that session's share units. Do not borrow AdjC,
    another date's price, or OHLC MktCap (which includes treasury shares).
    Duplicate common-share bars are rejected rather than choosing one.
    """
    result = {code: dict(row) for code, row in valuation.items()}
    prices, duplicates = {}, set()
    for row in daily_bars.values():
        if not isinstance(row, dict) or row.get('Date') != date:
            continue
        code = str(row.get('Code') or '')
        code = code[:4] if len(code) == 5 and code.endswith('0') else code
        if code in prices:
            duplicates.add(code)
        prices[code] = row.get('C')
    used = {}
    for code, row in result.items():
        if (code in duplicates or _price(row) is not None
                or (_finite(row.get('EPS')) is None and _finite(row.get('FwdEPS')) is None)):
            continue
        price = _finite(prices.get(code))
        if price is not None and price > 0:
            row['unadjustedClose'] = price
            used[code] = price
    return result, used


# 2026-10-21 (owner decision, docs/PER_CURRENT_AUTHORITY.md): a member whose
# valuation row is entirely blank (new holding companies before their first
# statement under the new code: 9147 in 2022, 5831 in 2022-23, 543A in 2026)
# is supplied from the same-day daily-bar market cap and the latest forecast
# net income disclosed before that day. Measured against complete days
# (2026-10-21): median 0.004 %, 99th percentile 0.76 %, maximum 3.18 % on the
# estimate. Supplied estimates are kept apart by their coverage counts.
SUPPLY_MAX_MEMBERS = 3
_EARNINGS_FIELDS = ('MktCap', 'FwdPER', 'PER', 'FwdEPS', 'EPS')


def blank_members(valuation, constituents):
    """Members listed for the day whose market cap and earnings are all blank."""
    return sorted(code for code in set(constituents)
                  if isinstance(valuation.get(code), dict)
                  and all(_finite(valuation[code].get(key)) is None for key in _EARNINGS_FIELDS))


def forecast_net_income(disclosures, *, before):
    """(million yen, disclosure) from the newest forecast disclosed before `before`.

    Full-year statements carry the next year's forecast (NxFNp); other
    documents the current year's (FNP). Non-consolidated figures stand in only
    when the consolidated one is absent. A disclosure on the day itself is not
    used (it comes at or after the close); nothing older is borrowed when the
    newest disclosure has no forecast at all.
    """
    rows = []
    for row in disclosures or ():
        if not isinstance(row, dict):
            continue
        day = str(row.get('DiscDate') or '')
        if len(day) != 10 or day >= before:
            continue
        full_year = str(row.get('DocType') or '').startswith('FY')
        value = _finite(row.get('NxFNp') if full_year else row.get('FNP'))
        if value is None:
            value = _finite(row.get('NxFNCNP') if full_year else row.get('FNCNP'))
        if value is None or value == 0:
            continue
        rows.append(((day, str(row.get('DiscTime') or ''), str(row.get('DiscNo') or '')), value, row))
    if not rows:
        return None
    key, value, row = max(rows, key=lambda item: item[0])
    return value / 1e6, {'discDate': key[0], 'discTime': key[1] or None, 'discNo': key[2] or None,
                         'docType': str(row.get('DocType') or '') or None, 'forecastNetIncomeYen': value}


def valuation_with_supplied_members(valuation, constituents, bars_by_code, disclosures_by_code, *, date):
    """Copy rows, filling only blank members from dated bars and prior forecasts.

    Returns (rows, supplied) where supplied maps each filled code to the exact
    inputs used. Every blank member must be fillable, otherwise nothing is
    supplied (a partial supplement is not a complete day). Duplicate bars for
    one code and date are rejected rather than choosing one.
    """
    blanks = blank_members(valuation, constituents)
    if not blanks or len(blanks) > SUPPLY_MAX_MEMBERS:
        return {code: dict(row) for code, row in valuation.items()}, {}
    supplied = {}
    for code in blanks:
        bars = [row for row in (bars_by_code.get(code) or ())
                if isinstance(row, dict) and row.get('Date') == date
                and str(row.get('Code') or '')[:4] == code]
        if len(bars) != 1:
            return {c: dict(r) for c, r in valuation.items()}, {}
        cap = _finite(bars[0].get('MktCap'))
        forecast = forecast_net_income(disclosures_by_code.get(code), before=date)
        predecessor = None
        if forecast is None and code in PREDECESSORS:
            # 2026-10-25 (owner): before the holding company's first forecast,
            # the forecast of the company it replaced one for one.
            predecessor = PREDECESSORS[code]
            forecast = forecast_net_income(disclosures_by_code.get(predecessor), before=date)
        if cap is None or cap <= 0 or forecast is None:
            return {c: dict(r) for c, r in valuation.items()}, {}
        supplied[code] = {'marketCap': cap, 'barDate': date, 'forecastNetIncome': forecast[0],
                          'disclosure': forecast[1]}
        if predecessor:
            supplied[code]['predecessorCode'] = predecessor
    result = {code: dict(row) for code, row in valuation.items()}
    for code, row in supplied.items():
        result[code].update(MktCap=row['marketCap'], suppliedForecastNetIncome=row['forecastNetIncome'])
    return result, supplied


# 2026-10-25 (owner decision, docs/PER_CURRENT_AUTHORITY.md): the remaining
# incomplete days were (production 2026-10-25) 323 with one to three members
# whose forecast was "undecided" (no forecast or trailing figure in the
# valuation row), 79 with a new holding company before its first forecast,
# 2 with Hino Motors after its last trading day and 1 holiday row from the
# price history. The owner allowed computing them from received data.
PREDECESSORS = {'9147': '9062', '5831': '8355'}
CARRY_FORWARD_MAX_DAYS = 7


def earnings_missing_members(valuation, constituents):
    """Members with a market cap but no forecast, trailing figure or EPS at all."""
    out = []
    for code in sorted(set(constituents)):
        row = valuation.get(code)
        if not isinstance(row, dict) or _finite(row.get('suppliedForecastNetIncome')) is not None:
            continue
        cap = _finite(row.get('MktCap'))
        if cap is None or cap <= 0:
            continue
        if any(_finite(row.get(key)) is not None for key in ('FwdPER', 'PER', 'FwdEPS', 'EPS')):
            continue
        out.append(code)
    return out


def earnings_stand_in(disclosures, *, before):
    """(million yen, provenance) for a member whose forecast is undecided.

    The newest statement disclosed before the day gives its forecast (next
    year's on a full-year statement). When that statement has none, the
    latest full-year actual net income stands in; a loss counts as zero
    (measured 2026-10-25 against the official weighted series: median
    difference to neighbouring complete days 0.1-1.3 % per company).
    """
    rows = [row for row in disclosures or ()
            if isinstance(row, dict) and len(str(row.get('DiscDate') or '')) == 10
            and str(row['DiscDate']) < before]
    if not rows:
        return None
    order = lambda row: (str(row['DiscDate']), str(row.get('DiscTime') or ''), str(row.get('DiscNo') or ''))
    newest = max(rows, key=order)
    full_year = str(newest.get('DocType') or '').startswith('FY')
    value = _finite(newest.get('NxFNp') if full_year else newest.get('FNP'))
    if value is None:
        value = _finite(newest.get('NxFNCNP') if full_year else newest.get('FNCNP'))
    source, method = newest, 'forecast'
    if value is None:
        actual = [row for row in rows if str(row.get('DocType') or '').startswith('FY')
                  and (_finite(row.get('NP')) is not None or _finite(row.get('NCNP')) is not None)]
        if not actual:
            return None
        source = max(actual, key=order)
        value = _finite(source.get('NP'))
        if value is None:
            value = _finite(source.get('NCNP'))
        method = 'prior_actual' if value > 0 else 'prior_actual_loss_as_zero'
        value = max(value, 0.0)
    return value / 1e6, {'method': method, 'discDate': source['DiscDate'],
                         'discNo': str(source.get('DiscNo') or '') or None,
                         'docType': str(source.get('DocType') or '') or None, 'netIncomeYen': value}


def valuation_with_earnings_stand_ins(valuation, constituents, disclosures_by_code, *, date):
    """Copy rows, filling every earnings-missing member or none of them."""
    missing = earnings_missing_members(valuation, constituents)
    if not missing or len(missing) > SUPPLY_MAX_MEMBERS:
        return {code: dict(row) for code, row in valuation.items()}, {}
    supplied = {}
    for code in missing:
        found = earnings_stand_in(disclosures_by_code.get(code), before=date)
        if found is None:
            return {code: dict(row) for code, row in valuation.items()}, {}
        supplied[code] = {'forecastNetIncome': found[0], 'disclosure': found[1]}
    result = {code: dict(row) for code, row in valuation.items()}
    for code, row in supplied.items():
        result[code].update(suppliedForecastNetIncome=row['forecastNetIncome'], earningsStandIn=True)
    return result, supplied


def valuation_with_carried_rows(valuation, constituents, rows_by_code, *, date):
    """Members without a row: their last trading day's row, as the index does.

    The index computes a delisted member at its last traded price until its
    removal (Hino Motors on 2026-03-30/31). Only a row from at most seven
    calendar days before is carried; otherwise nothing is filled.
    """
    from datetime import date as calendar_date
    absent = sorted(code for code in set(constituents) if code not in valuation)
    if not absent or len(absent) > SUPPLY_MAX_MEMBERS:
        return {code: dict(row) for code, row in valuation.items()}, {}
    day = calendar_date.fromisoformat(date)
    carried = {}
    for code in absent:
        earlier = [row for row in (rows_by_code.get(code) or ())
                   if isinstance(row, dict) and str(row.get('Code') or '')[:4] == code
                   and len(str(row.get('Date') or '')) == 10 and str(row['Date']) < date]
        if not earlier:
            return {c: dict(r) for c, r in valuation.items()}, {}
        last = max(earlier, key=lambda row: str(row['Date']))
        if (day - calendar_date.fromisoformat(str(last['Date']))).days > CARRY_FORWARD_MAX_DAYS:
            return {c: dict(r) for c, r in valuation.items()}, {}
        carried[code] = dict(last)
    result = {code: dict(row) for code, row in valuation.items()}
    for code, row in carried.items():
        result[code] = {**row, 'carriedFrom': row['Date']}
    return result, {code: row['Date'] for code, row in carried.items()}


def daily_close_repairable(valuation, constituents):
    """Spend the bounded price request only when prices can fill every gap.

    A daily close cannot supply absent EPS or valuation market cap. Keep such
    dates gated without consuming the one dated price join for this warm.
    This only selects a request; the normal complete-input admission still
    evaluates its received, same-session prices and aggregate earnings.
    """
    needed = False
    members = set(constituents)
    for code in members:
        row = valuation.get(code) or {}
        cap = _finite(row.get('MktCap'))
        if cap is None or cap <= 0:
            return False
        if _finite(row.get('suppliedForecastNetIncome')) is not None:
            continue
        forward_per, trailing_per = _finite(row.get('FwdPER')), _finite(row.get('PER'))
        forward_eps, trailing_eps = _finite(row.get('FwdEPS')), _finite(row.get('EPS'))
        if (forward_per or trailing_per or
                (_price(row) is not None and (forward_eps is not None or trailing_eps is not None))):
            continue
        if forward_eps is None and trailing_eps is None:
            return False
        needed = True
    return bool(members) and needed


def pending_eps_sessions(wanted, admitted, *, limit, cursor=None):
    """Keep the latest session first; rotate historical attempts fairly.

    The cursor is an in-process collection position, not a completion record
    or a new scheduling clock. Failed newest dates cannot starve older gaps.
    """
    pending = list(dict.fromkeys(day for day in wanted if day not in admitted))
    if not pending or limit <= 0:
        return []
    latest = wanted[0] if wanted else None
    head = [latest] if latest in pending else []
    rest = sorted((day for day in pending if day != latest), reverse=True)
    if cursor:
        rest = [day for day in rest if day < cursor] + [day for day in rest if day >= cursor]
    return (head + rest)[:limit]


def weighted_eps(valuation: Mapping[str, Mapping[str, Any]], constituents: Iterable[str], *,
                 index_close: float, date: str, constituents_as_of: str) -> Dict[str, Any]:
    """Market-cap weighted forward PER and index EPS from one day's rows.

    valuation: J-Quants /equities/valuation rows by four-character code
    (MktCap in million yen; FwdPER, FwdEPS, PER, EPS, PBR, BPS).
    Forecast net income of a member = MktCap / FwdPER (signed). A member
    without FwdPER uses MktCap * FwdEPS / price when a price is derivable,
    otherwise its trailing figure (counted as filled). A member supplied by
    valuation_with_supplied_members uses its supplied forecast net income
    (counted as suppliedMarketCap/suppliedEarnings). Members with no
    market cap or no earnings at all are left out of both sums (counted).
    """
    close = _finite(index_close)
    if not close or close <= 0:
        raise LevelMapError("index_close_required")
    members = sorted({str(code) for code in constituents if str(code)})
    if not members:
        raise LevelMapError("constituents_required")
    cap_total = income_total = 0.0
    counts = {"members": len(members), "forward": 0, "filledFromTrailing": 0, "negativeForecast": 0,
              "missingMarketCap": 0, "missingEarnings": 0}
    cap_all = cap_used = 0.0
    for code in members:
        row = valuation.get(code) or {}
        cap = _finite(row.get("MktCap"))
        if cap is None or cap <= 0:
            counts["missingMarketCap"] += 1
            continue
        cap_all += cap
        income = None
        forward_per = _finite(row.get("FwdPER"))
        forward_eps = _finite(row.get("FwdEPS"))
        supplied = _finite(row.get("suppliedForecastNetIncome"))
        if supplied is not None:
            income = supplied
            kind = "standIn" if row.get("earningsStandIn") else "supplied"
            counts[kind] = counts.get(kind, 0) + 1
        elif forward_per:
            income = cap / forward_per
        elif forward_eps is not None and _price(row):
            income = cap * forward_eps / _price(row)
        if row.get("carriedFrom"):
            counts["carriedForward"] = counts.get("carriedForward", 0) + 1
        if income is not None:
            counts["forward"] += 1
            if income < 0:
                counts["negativeForecast"] += 1
        else:
            trailing_per, trailing_eps = _finite(row.get("PER")), _finite(row.get("EPS"))
            if trailing_per:
                income = cap / trailing_per
            elif trailing_eps is not None and _price(row):
                income = cap * trailing_eps / _price(row)
            if income is None:
                counts["missingEarnings"] += 1
                continue
            counts["filledFromTrailing"] += 1
        cap_total += cap
        income_total += income
        cap_used += cap
    if income_total <= 0 or cap_total <= 0:
        raise LevelMapError("aggregate_earnings_not_positive")
    # Only supplied days carry these counts, so every other record is unchanged.
    supplied_count = counts.pop("supplied", 0)
    stand_in_count = counts.pop("standIn", 0)
    if supplied_count or stand_in_count:
        counts.update(suppliedMarketCap=supplied_count,
                      suppliedEarnings=supplied_count + stand_in_count)
    per = cap_total / income_total
    # The same aggregate over members with a forecast only, kept beside the
    # chosen estimate so the effect of filling from trailing figures is
    # measurable against the official series (2026-10-04: +1.4 %).
    forward_cap = forward_income = 0.0
    for code in members:
        row = valuation.get(code) or {}
        cap, forward_per = _finite(row.get("MktCap")), _finite(row.get("FwdPER"))
        if cap and cap > 0 and forward_per:
            forward_cap += cap
            forward_income += cap / forward_per
    forward_only = ({"per": forward_cap / forward_income, "eps": close / (forward_cap / forward_income)}
                    if forward_income > 0 and forward_cap > 0 else None)
    return {"date": date, "eps": close / per, "per": per, "indexClose": close, "forwardOnly": forward_only,
            "basis": EPS_BASIS, "labelJa": EPS_LABEL_JA, "constituentsAsOf": constituents_as_of,
            "coverage": {**counts, "marketCapShareUsed": round(cap_used / cap_all, 6) if cap_all else None},
            "officialValue": False}


def constituents_on(day: str, base_codes: Iterable[str], base_as_of: Optional[str],
                    changes: Optional[Mapping[str, Any]]) -> tuple:
    """The constituents on `day`: the weight table's members with every
    published change effective after the table's date and on or before `day`
    applied (2026-10-04: the 9/30 table predates the 10/1 review). Returns
    (codes, label of what was applied)."""
    codes = {str(code) for code in base_codes}
    applied, reversed_ = [], []
    rows = sorted((changes or {}).get("rows") or [], key=lambda r: str(r.get("effective")))
    for row in rows:
        effective = str(row.get("effective") or "")
        if len(effective) == 10 and (not base_as_of or effective > base_as_of) and effective <= day:
            codes -= {str(c) for c in row.get("removed") or ()}
            codes |= {str(c) for c in row.get("added") or ()}
            applied.append(effective)
    # Before the table's date: undo the later changes, newest first.
    for row in reversed(rows):
        effective = str(row.get("effective") or "")
        if base_as_of and len(effective) == 10 and day < effective <= base_as_of:
            codes -= {str(c) for c in row.get("added") or ()}
            codes |= {str(c) for c in row.get("removed") or ()}
            reversed_.append(effective)
    label = (base_as_of or "unknown") + ("+入れ替え" + ",".join(applied) if applied else "") \
        + ("−逆算" + ",".join(sorted(reversed_)) if reversed_ else "")
    return sorted(codes), label


# --- prices --------------------------------------------------------------------

def _bars(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = {}
    for row in rows or ():
        day = str(row.get("date") or "")[:10]
        high, low, close = (_finite(row.get(k)) for k in ("high", "low", "close"))
        if len(day) == 10 and high and low and close and high >= low > 0:
            out[day] = {"date": day, "high": high, "low": low, "close": close}
    return [out[day] for day in sorted(out)]


def atr(bars: Sequence[Mapping[str, Any]], sessions: int = ATR_SESSIONS) -> Optional[float]:
    """Simple mean of the last `sessions` true ranges of the given bars
    (all before the morning), TR = max(H, prev C) - min(L, prev C)."""
    if len(bars) < sessions + 1:
        return None
    ranges = [max(bars[i]["high"], bars[i - 1]["close"]) - min(bars[i]["low"], bars[i - 1]["close"])
              for i in range(len(bars) - sessions, len(bars))]
    return sum(ranges) / sessions


def zigzag(bars: Sequence[Mapping[str, Any]], threshold: float = ZIGZAG_THRESHOLD) -> List[Dict[str, Any]]:
    """Confirmed turning points of a close zigzag, price = intraday extreme.

    A top is confirmed on the day the close falls `threshold` below the
    highest close since the last bottom; its price is the highest intraday
    high from the session after the previous turning point to the confirming
    session (never a later session). Bottoms mirror it.
    """
    closes = [bar["close"] for bar in bars]
    found, direction, high_i, low_i = [], 0, 0, 0
    for i in range(1, len(closes)):
        close = closes[i]
        if direction == 0:
            if close > closes[high_i]:
                high_i = i
            if close < closes[low_i]:
                low_i = i
            if close <= closes[high_i] * (1 - threshold) and high_i < i:
                found.append((high_i, "TOP", i)); direction = -1; low_i = i
            elif close >= closes[low_i] * (1 + threshold) and low_i < i:
                found.append((low_i, "BOTTOM", i)); direction = 1; high_i = i
        elif direction == 1:
            if close > closes[high_i]:
                high_i = i
            elif close <= closes[high_i] * (1 - threshold):
                found.append((high_i, "TOP", i)); direction = -1; low_i = i
        else:
            if close < closes[low_i]:
                low_i = i
            elif close >= closes[low_i] * (1 + threshold):
                found.append((low_i, "BOTTOM", i)); direction = 1; high_i = i
    result = []
    for n, (pivot, kind, confirm) in enumerate(found):
        start = found[n - 1][0] + 1 if n else max(0, pivot - 5)
        start = min(start, pivot)
        window = range(start, confirm + 1)
        if kind == "TOP":
            j = max(window, key=lambda k: (bars[k]["high"], -k))
            price = bars[j]["high"]
        else:
            j = min(window, key=lambda k: (bars[k]["low"], k))
            price = bars[j]["low"]
        result.append({"kind": kind, "closeDate": bars[pivot]["date"], "date": bars[j]["date"],
                       "price": price, "confirmedOn": bars[confirm]["date"]})
    return result


# --- EPS series ------------------------------------------------------------------

class _ScoringEpsSeries(Mapping):
    """一回の採点内だけ、同じ日の厳密な前日EPSを再利用する。"""
    def __init__(self, source):
        self._source = source
        self._before = {}

    def __getitem__(self, key):
        return self._source[key]

    def __iter__(self):
        return iter(self._source)

    def __len__(self):
        return len(self._source)

    def before(self, day):
        if day not in self._before:
            self._before[day] = eps_before(self._source, day)
        return self._before[day]


def eps_before(eps_series: Mapping[str, float], day: str) -> Optional[tuple]:
    """(date, eps) of the latest estimate dated strictly before `day`."""
    if isinstance(eps_series, _ScoringEpsSeries):
        return eps_series.before(day)
    earlier = [d for d in eps_series if d < day and _finite(eps_series[d])]
    if not earlier:
        return None
    latest = max(earlier)
    return latest, float(eps_series[latest])


# --- tables ------------------------------------------------------------------------

def frequency(side: str, distance_atr: float) -> Dict[str, Any]:
    distance = abs(distance_atr)
    for lower, upper, up_pct, down_pct in FREQUENCY_TABLE:
        if lower <= distance < upper:
            value = up_pct if side == "UP" else down_pct
            band = "2割前後" if value >= 17 else "1〜2割" if value >= 10 else "1割未満"
            return {"bandJa": band, "pastFrequencyPct": value, "table": FREQUENCY_TABLE_VERSION}
    raise LevelMapError("distance_out_of_table")


def reach(side: str, distance_atr: float) -> Dict[str, Any]:
    distance = abs(distance_atr)
    for lower, upper, within10, median, q25, q75 in DAYS_TABLE[side]:
        if lower <= distance < upper:
            return {"reachedWithin10SessionsPct": within10, "sessionsMedian": median,
                    "sessions25": q25, "sessions75": q75, "table": DAYS_TABLE_VERSION}
    raise LevelMapError("distance_out_of_table")


# --- the morning map -----------------------------------------------------------------

def _row(side, kinds, price, close, atr_value, *, multiple=None, tier="MAP"):
    distance_pct = (price / close - 1) * 100
    distance_atr = (price - close) / atr_value
    row = {"side": side, "kinds": list(kinds), "price": round(price, 2),
           "distancePct": round(distance_pct, 3), "distanceAtr": round(distance_atr, 3),
           "multiple": multiple, "moving": any(k in ("PER_LINE", "SAME_MULTIPLE") for k in kinds),
           "tier": tier, "evidenceJa": [EVIDENCE_JA[k] for k in kinds]}
    if tier in ("MAP", "DETAIL") and "PIVOT_PRICE" not in kinds:
        row.update(frequency(side, distance_atr), **reach(side, distance_atr))
    return row


def _merge(rows):
    """Rows within 0.5 % become one row, the nearer price kept."""
    merged = []
    for row in sorted(rows, key=lambda r: abs(r["distancePct"])):
        twin = next((m for m in merged if abs(m["price"] / row["price"] - 1) <= MERGE_TOLERANCE), None)
        if twin is None:
            merged.append(dict(row))
            continue
        twin["kinds"] = twin["kinds"] + [k for k in row["kinds"] if k not in twin["kinds"]]
        twin["evidenceJa"] = [EVIDENCE_JA[k] for k in twin["kinds"]]
        twin.setdefault("mergedMultiples", [twin.get("multiple")]).append(row.get("multiple"))
    return merged


def morning_map(day: str, price_rows: Sequence[Mapping[str, Any]], eps_series: Mapping[str, float], *,
                eps_records: Optional[Mapping[str, Mapping[str, Any]]] = None,
                created_at: str) -> Dict[str, Any]:
    """The map for the morning of `day`, from sessions and estimates before it only."""
    _date.fromisoformat(day)
    bars = [bar for bar in _bars(price_rows) if bar["date"] < day]
    if len(bars) < ATR_SESSIONS + 1:
        raise LevelMapError("price_history_too_short")
    previous = bars[-1]
    close = previous["close"]
    atr_value = atr(bars)
    line_eps = eps_before(eps_series, day)
    if not atr_value or not line_eps:
        raise LevelMapError("atr_or_eps_missing")
    eps_date, eps = line_eps
    prior = eps_before(eps_series, eps_date)
    jump = prior is not None and abs(eps / prior[1] - 1) >= EPS_JUMP_FLAG
    pivots = [p for p in zigzag(bars) if p["confirmedOn"] < day]
    last = {kind: next((p for p in reversed(pivots) if p["kind"] == kind), None) for kind in ("TOP", "BOTTOM")}
    for kind, pivot in last.items():
        if pivot:
            pivot_eps = eps_before(eps_series, pivot["date"])
            pivot["lineEps"] = pivot_eps[1] if pivot_eps else None
            pivot["lineEpsDate"] = pivot_eps[0] if pivot_eps else None
            pivot["multiple"] = round(pivot["price"] / pivot_eps[1], 4) if pivot_eps else None
    rows = {"UP": [], "DOWN": []}
    detail = []
    lines = []
    for k in range(1, 100):
        price = eps * k
        if abs(price / close - 1) <= PER_LINE_RANGE and price != close:
            lines.append((k, price))
    for side in ("UP", "DOWN"):
        candidates = [(k, p) for k, p in lines if (p > close if side == "UP" else p < close)]
        candidates.sort(key=lambda item: abs(item[1] - close))
        for k, price in candidates[:2]:
            rows[side].append(_row(side, ["PER_LINE"], price, close, atr_value, multiple=k))
        for k, price in candidates[2:]:
            detail.append(_row(side, ["PER_LINE"], price, close, atr_value, multiple=k, tier="DETAIL"))
    for kind, side in (("TOP", "UP"), ("BOTTOM", "DOWN")):
        pivot = last[kind]
        if pivot and pivot.get("multiple"):
            price = eps * pivot["multiple"]
            if (price > close) if side == "UP" else (price < close):
                rows[side].append(_row(side, ["SAME_MULTIPLE"], price, close, atr_value,
                                       multiple=pivot["multiple"]))
        if pivot:
            side_of_price = "UP" if pivot["price"] > close else "DOWN"
            detail.append(_row(side_of_price, ["PIVOT_PRICE"], pivot["price"], close, atr_value,
                               tier="DETAIL"))
    map_rows = []
    for side in ("UP", "DOWN"):
        merged = _merge(rows[side])
        map_rows += merged[:3]
        detail += [{**row, "tier": "DETAIL"} for row in merged[3:]]
    guides = {side: [round(close + sign * n * atr_value, 2) for n in (1, 2, 3)]
              for side, sign in (("UP", 1), ("DOWN", -1))}
    inputs = {"previousClose": close, "previousSession": previous["date"], "atr14": round(atr_value, 4),
              "eps": round(eps, 4), "epsDate": eps_date, "per": round(close / eps, 4)}
    record = {
        "schemaVersion": SCHEMA, "morningOf": day, "createdAt": created_at,
        "ruleVersion": RULE_VERSION, "frequencyTable": FREQUENCY_TABLE_VERSION, "daysTable": DAYS_TABLE_VERSION,
        **inputs, "epsBasis": EPS_BASIS, "epsLabelJa": EPS_LABEL_JA, "epsJumped": jump,
        "epsCoverage": (eps_records or {}).get(eps_date, {}).get("coverage"),
        "constituentsAsOf": (eps_records or {}).get(eps_date, {}).get("constituentsAsOf"),
        "lastTop": last["TOP"], "lastBottom": last["BOTTOM"],
        "rows": map_rows, "detail": detail, "atrGuides": guides,
        "fixedNotesJa": list(FIXED_NOTES_JA),
        "pastFrequencyIsNotProbability": True, "actionAuthority": False, "automaticAiCalls": 0,
    }
    record["recordId"] = "lm-" + _digest({k: v for k, v in record.items() if k != "createdAt"})[:32]
    return record


# --- scoring (after the close; the morning record itself never changes) ---------------

REACH_TOLERANCE = 0.005        # reached: within 0.5 % of the line
REACH_SESSIONS = 10            # the morning is session 0
DECISION_BAND = 0.02           # stopped / broke: 2 % back or 2 % through
DECISION_SESSIONS = 20
PHASE_SESSIONS = 10            # touches of the same line within 10 sessions are one phase
TURN_TOLERANCE = 0.01
FAKE_MULTIPLE_SHIFTS = (-0.5, -0.25, 0.25, 0.5)


def _line_value(row: Mapping[str, Any], day: str, eps_series: Mapping[str, float]) -> Optional[float]:
    """A PER line moves with the EPS known before each day; other rows are fixed."""
    if row.get("moving") and _finite(row.get("multiple")):
        known = eps_before(eps_series, day)
        return known[1] * float(row["multiple"]) if known else None
    return _finite(row.get("price"))


def touch_outcome(row: Mapping[str, Any], sessions: Sequence[Mapping[str, Any]],
                  eps_series: Mapping[str, float]) -> Dict[str, Any]:
    """Reached within ten sessions, then stopped (2 % back first) or broke (2 %
    through first). On the touching session only a close 2 % back counts as
    stopped; a session with both is decided by its close."""
    side = row["side"]
    reached = None
    for index, bar in enumerate(sessions[:REACH_SESSIONS]):
        line = _line_value(row, bar["date"], eps_series)
        if line is None:
            continue
        if (side == "UP" and bar["high"] >= line * (1 - REACH_TOLERANCE)) or \
                (side == "DOWN" and bar["low"] <= line * (1 + REACH_TOLERANCE)):
            reached = (index, line)
            break
    if reached is None:
        state = "NOT_REACHED" if len(sessions) >= REACH_SESSIONS else "PENDING"
        return {"state": state, "reachedSession": None, "reachedOn": None, "lineAtReach": None}
    index, value = reached
    upper, lower = value * (1 + DECISION_BAND), value * (1 - DECISION_BAND)
    for k in range(index, min(index + DECISION_SESSIONS + 1, len(sessions))):
        bar = sessions[k]
        if side == "DOWN":                       # support
            stop = bar["close"] >= upper if k == index else bar["high"] >= upper
            broke = bar["low"] <= lower
            if stop and broke:
                state = "STOPPED" if bar["close"] >= value else "BROKE"
            else:
                state = "STOPPED" if stop else "BROKE" if broke else None
        else:                                    # wall
            stop = bar["close"] <= lower if k == index else bar["low"] <= lower
            broke = bar["high"] >= upper
            if stop and broke:
                state = "STOPPED" if bar["close"] <= value else "BROKE"
            else:
                state = "STOPPED" if stop else "BROKE" if broke else None
        if state:
            return {"state": state, "reachedSession": index, "reachedOn": sessions[index]["date"],
                    "lineAtReach": round(value, 2), "decidedOn": bar["date"]}
    state = "UNDECIDED" if len(sessions) > index + DECISION_SESSIONS else "OPEN"
    return {"state": state, "reachedSession": index, "reachedOn": sessions[index]["date"],
            "lineAtReach": round(value, 2)}


def _fakes(row: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if row.get("moving") and _finite(row.get("multiple")):
        return [{**row, "multiple": float(row["multiple"]) + shift, "fakeShift": shift}
                for shift in FAKE_MULTIPLE_SHIFTS]
    price = _finite(row.get("price"))
    return [{**row, "price": price * (1 + shift), "fakeShift": shift}
            for shift in (-0.03, -0.015, 0.015, 0.03)] if price else []


def score_records(mornings: Sequence[Mapping[str, Any]], price_rows: Sequence[Mapping[str, Any]],
                  eps_series: Mapping[str, float]) -> Dict[str, Any]:
    """Pre-registered record, scored with the moving lines.

    Counts are per phase: the same side and line (kind and multiple) touched
    again within ten sessions of its previous touch is the same phase and is
    counted once, by its first touch. Turning points (close 4 % zigzag,
    intraday extreme) are compared with each morning's rows at the answer
    date; +/-1 % is a hit. The +/-2 ATR guide and shifted fake lines are the
    baselines. Nothing here is a probability.
    """
    eps_series = _ScoringEpsSeries(eps_series)
    bars = _bars(price_rows)
    index_of = {bar["date"]: i for i, bar in enumerate(bars)}
    pivots = zigzag(bars)
    phases: Dict[tuple, Dict[str, Any]] = {}
    per_morning = []
    turning = {"evaluated": 0, "perLineHits": 0, "atr2Hits": 0, "chanceExpected": 0.0, "answers": []}
    seen_answers = set()
    for record in sorted(mornings, key=lambda r: r.get("morningOf") or ""):
        day = record.get("morningOf")
        start = next((i for i, bar in enumerate(bars) if bar["date"] >= day), None)
        sessions = bars[start:] if start is not None else []
        rows = [r for r in record.get("rows") or [] if r.get("tier") == "MAP"]
        guides = [{"side": side, "kinds": ["ATR_GUIDE"], "price": price, "moving": False, "atrMultiple": n}
                  for side in ("UP", "DOWN") for n, price in zip((1, 2, 3), (record.get("atrGuides") or {}).get(side, []))]
        scored = []
        for row in rows + guides:
            outcome = touch_outcome(row, sessions, eps_series)
            fakes = [touch_outcome(fake, sessions, eps_series)["state"] for fake in _fakes(row)]
            scored.append({"side": row["side"], "kinds": row["kinds"], "multiple": row.get("multiple"),
                           "atrMultiple": row.get("atrMultiple"), "price": row.get("price"),
                           **outcome, "fakeStates": fakes})
            if outcome["reachedOn"] and "ATR_GUIDE" not in row["kinds"]:
                key = (row["side"], tuple(row["kinds"]), round(float(row.get("multiple") or row.get("price")), 4))
                reach_index = index_of[outcome["reachedOn"]]
                previous = phases.get(key)
                if previous is None or reach_index - previous["lastReachIndex"] > PHASE_SESSIONS:
                    phases[key] = {"lastReachIndex": reach_index, "count": True,
                                   "phases": (previous or {}).get("phases", []) + [
                                       {"morningOf": day, "state": outcome["state"], "fakeStates": fakes}]}
                else:
                    previous["lastReachIndex"] = reach_index
        # Turning points: the first top and bottom whose extreme is on or after the morning.
        for kind, side in (("TOP", "UP"), ("BOTTOM", "DOWN")):
            answer = next((p for p in pivots if p["kind"] == kind and p["date"] >= day), None)
            if not answer:
                continue
            known = eps_before(eps_series, answer["date"])
            multiple = answer["price"] / known[1] if known else None
            # Any whole-number line on the answer date (the line moves with the EPS).
            hit = bool(multiple) and abs(multiple / round(multiple) - 1) <= TURN_TOLERANCE
            atr2 = ((record.get("atrGuides") or {}).get(side) or [None, None])[1]
            if (kind, answer["date"]) not in seen_answers:
                seen_answers.add((kind, answer["date"]))
                turning["evaluated"] += 1
                turning["perLineHits"] += int(hit)
                turning["atr2Hits"] += int(bool(atr2) and abs(answer["price"] / atr2 - 1) <= TURN_TOLERANCE)
                turning["chanceExpected"] += 0.02 * multiple if multiple else 0.0
                turning["answers"].append({"kind": kind, "date": answer["date"], "price": answer["price"],
                                           "confirmedOn": answer["confirmedOn"], "firstMorning": day,
                                           "perLineHit": hit})
        per_morning.append({"morningOf": day, "recordId": record.get("recordId"), "rows": scored})
    counted = [phase for value in phases.values() for phase in value["phases"]]
    def tally(states):
        return {state: sum(1 for s in states if s == state)
                for state in ("STOPPED", "BROKE", "UNDECIDED", "OPEN")}
    fake_states = [s for phase in counted for s in phase["fakeStates"] if s not in ("NOT_REACHED", "PENDING")]
    turning["chanceExpected"] = round(turning["chanceExpected"], 3)
    return {"schemaVersion": "jp-market-level-map-score-v1", "ruleVersion": RULE_VERSION,
            "firstMorning": per_morning[0]["morningOf"] if per_morning else None,
            "mornings": len(per_morning), "phases": len(counted),
            "phaseOutcomes": tally([phase["state"] for phase in counted]),
            "fakeLineOutcomes": tally(fake_states), "turningPoints": turning,
            "perMorning": per_morning[-20:], "preRegisteredOnly": True,
            "pastFrequencyIsNotProbability": True, "actionAuthority": False}
