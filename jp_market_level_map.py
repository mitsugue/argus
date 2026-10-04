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
    "水準を見ずに今の値±2ATRと言うのと同じ精度です（±2ATRの1本が次の転換点の±1%に入った割合は24〜29%、±1・2・3ATRのどれかなら56〜59%）。",
    "整数PER線は2026年6〜10月によく効きましたが、2010〜2023年は偶然並みでした。効く時期を前もって見分ける方法は見つかっていません。",
    "数字は過去の頻度であり、確率ではありません。止まる・反発すると言い切るものではなく、売買の合図ではありません。",
    "水準に届いた後に先に2%戻った割合は約5割で、ずらした水準でも約5割でした。",
)


class LevelMapError(ValueError):
    pass


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
    return None


def weighted_eps(valuation: Mapping[str, Mapping[str, Any]], constituents: Iterable[str], *,
                 index_close: float, date: str, constituents_as_of: str) -> Dict[str, Any]:
    """Market-cap weighted forward PER and index EPS from one day's rows.

    valuation: J-Quants /equities/valuation rows by four-character code
    (MktCap in million yen; FwdPER, FwdEPS, PER, EPS, PBR, BPS).
    Forecast net income of a member = MktCap / FwdPER (signed). A member
    without FwdPER uses MktCap * FwdEPS / price when a price is derivable,
    otherwise its trailing figure (counted as filled). Members with no
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
        if forward_per:
            income = cap / forward_per
        elif forward_eps is not None and _price(row):
            income = cap * forward_eps / _price(row)
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
    per = cap_total / income_total
    return {"date": date, "eps": close / per, "per": per, "indexClose": close,
            "basis": EPS_BASIS, "labelJa": EPS_LABEL_JA, "constituentsAsOf": constituents_as_of,
            "coverage": {**counts, "marketCapShareUsed": round(cap_used / cap_all, 6) if cap_all else None},
            "officialValue": False}


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

def eps_before(eps_series: Mapping[str, float], day: str) -> Optional[tuple]:
    """(date, eps) of the latest estimate dated strictly before `day`."""
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
