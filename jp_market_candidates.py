"""Pre-registered candidate signals and their automatic scoring (2026-10-04).

Research could not establish any condition under which ARGUS may show a
direction. A few candidates were left that chance could not fully explain;
they are recorded here before the outcome is known and scored by one fixed
rule: enter at the open of the session after the signal (S1/S2: at the
signal's own open), and see whether the Nikkei 225 reaches the target before
the break level within 20 sessions (10 shown beside it). Nothing here is a
trading signal: BUY stays disabled and these never reach Today's decision.

Outcomes: reached (target first), broken (break level first), ambiguous
(both on one session: the intraday order is unknown), expired (neither in
20 sessions), skipped_at_entry (already beyond the target at entry), open.
The PER lines use the ARGUS market-cap weighted EPS estimate (about 1.4 %
above the official series), so research frequencies are not product
results. Pure: no network, no clock.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import jp_market_level_map as level_map

SCHEMA = "candidate_record.v1"
RULE_VERSION = "candidate-rule-v1"
DEADLINE_SESSIONS = 20
SHORT_DEADLINE = 10
STOP_PCT = 0.05
EPISODE_GAP = 5            # a signal seen in the previous 5 sessions is the same episode
COMBO_WINDOW = 5           # S5: both parts within 5 sessions
ROUND_TRIP_COST = 0.002

CANDIDATES = {
    "R1": {"labelJa": "波の61.8%戻し", "target": "RETRACE_618"},
    "S1": {"labelJa": "夜間に大きく上げた朝", "direction": "up", "target": "PER_LINE"},
    "S2": {"labelJa": "夜間に大きく下げた朝", "direction": "down", "target": "PER_LINE"},
    "S3": {"labelJa": "恐怖指数30以上", "direction": "up", "target": "PER_LINE"},
    "S4": {"labelJa": "25日で5%下落", "direction": "up", "target": "ATR2"},
    "S5": {"labelJa": "売られた後の組", "direction": "up", "target": "ATR2"},
    "S6": {"labelJa": "需給の下落条件すべて", "direction": "down", "dataStatus": "NOT_IN_PRODUCT"},
    "S7": {"labelJa": "需給の上昇条件の組", "direction": "up", "dataStatus": "NOT_IN_PRODUCT"},
}
INSTRUMENT = {"up": "1579", "down": "1360"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _bars_with_open(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = {}
    for row in rows or ():
        day = str(row.get("date") or "")[:10]
        values = [row.get(k) for k in ("open", "high", "low", "close")]
        if len(day) == 10 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in values):
            out[day] = {"date": day, "open": float(values[0]), "high": float(values[1]),
                        "low": float(values[2]), "close": float(values[3])}
    return [out[day] for day in sorted(out)]


def _episodes(days: Sequence[str], sessions: Sequence[str]) -> List[str]:
    """Signal days with no signal of the same kind in the previous five sessions."""
    index = {day: i for i, day in enumerate(sessions)}
    marks = sorted(day for day in set(days) if day in index)
    out = []
    for day in marks:
        i = index[day]
        if not any(index.get(other, -99) in range(i - EPISODE_GAP, i) for other in marks):
            out.append(day)
    return out


def _crosses(flags: Sequence[tuple]) -> List[str]:
    """Days a condition becomes true (true today, false the session before)."""
    return [day for (day, now), (_, before) in zip(flags[1:], flags[:-1]) if now and not before]


# --- detectors: each returns signal days (the close that decides; S1/S2: the morning) ---

def detect_r1(bars) -> List[Dict[str, Any]]:
    closes = {bar["date"]: bar["close"] for bar in bars}
    pivots = level_map.zigzag(bars)
    out = []
    for previous, pivot in zip(pivots, pivots[1:]):
        peak, trough = closes[pivot["closeDate"]], closes[previous["closeDate"]]
        target = peak - 0.618 * (peak - trough)
        out.append({"candidate": "R1", "signalDate": pivot["confirmedOn"],
                    "direction": "down" if pivot["kind"] == "TOP" else "up",
                    "fixedTarget": round(target, 2), "stop": round(pivot["price"], 2),
                    "targetBasis": f"61.8%戻し({'山' if pivot['kind'] == 'TOP' else '谷'} {peak:,.0f} / 直前の"
                                   f"{'谷' if pivot['kind'] == 'TOP' else '山'} {trough:,.0f}・終値)",
                    "stopBasis": f"確定した{'山の日中高値' if pivot['kind'] == 'TOP' else '谷の日中安値'}"})
    return out


def detect_gap(etf_bars, sessions) -> List[Dict[str, Any]]:
    """S1/S2: the 1579 open against the previous close, decided and entered at that open."""
    out, previous = [], None
    by_day = {bar["date"]: bar for bar in etf_bars}
    for day in sessions:
        bar = by_day.get(day)
        if bar and previous:
            gap = bar["open"] / previous["close"] - 1
            if gap >= 0.04:
                out.append({"candidate": "S1", "signalDate": day, "sameSessionEntry": True, "gapPct": round(gap * 100, 2)})
            elif gap <= -0.04:
                out.append({"candidate": "S2", "signalDate": day, "sameSessionEntry": True, "gapPct": round(gap * 100, 2)})
        previous = bar or previous
    return out


def detect_vix(vix_rows, sessions) -> List[str]:
    """S3: VIX close (US date on or before the Tokyo session) rising to 30 or above."""
    closes = sorted((str(r.get("date"))[:10], r.get("close")) for r in vix_rows or ()
                    if isinstance(r.get("close"), (int, float)))
    flags, j, latest = [], 0, None
    for day in sessions:
        while j < len(closes) and closes[j][0] <= day:
            latest = closes[j][1]; j += 1
        flags.append((day, latest is not None and latest >= 30))
    return _crosses(flags)


def detect_drop25(bars) -> List[str]:
    """S4: close at least 5 % below the close 25 sessions earlier (cross)."""
    flags = [(bars[i]["date"], i >= 25 and bars[i]["close"] / bars[i - 25]["close"] - 1 <= -0.05)
             for i in range(len(bars))]
    return _crosses(flags)


def detect_breadth80(breadth: Mapping[str, Mapping[str, int]], sessions) -> List[str]:
    """Advance/decline ratio over 25 sessions under 80 (cross); needs 25 complete days."""
    flags = []
    for i, day in enumerate(sessions):
        window = sessions[max(0, i - 24):i + 1]
        if len(window) < 25 or any(d not in breadth for d in window):
            flags.append((day, False)); continue
        advancers = sum(breadth[d]["advancers"] for d in window)
        decliners = sum(breadth[d]["decliners"] for d in window)
        flags.append((day, decliners > 0 and advancers / decliners * 100 < 80))
    return _crosses(flags)


def detect_combo(a: Sequence[str], b: Sequence[str], sessions) -> List[str]:
    """S5: the first session both parts are active (each active for five sessions from its day)."""
    index = {day: i for i, day in enumerate(sessions)}
    def active(days, i):
        return any(0 <= i - index[d] < COMBO_WINDOW for d in days if d in index)
    flags = [(day, active(a, i) and active(b, i)) for i, day in enumerate(sessions)]
    return _crosses(flags)


# --- records -------------------------------------------------------------------------

def pre_record(signal: Mapping[str, Any], *, entry_date: str, recorded_at: str) -> Dict[str, Any]:
    """What is fixed before the entry open: the signal and the rule. Values that
    depend on the entry open are derived later by the same rule (materialize)."""
    candidate = signal["candidate"]
    meta = CANDIDATES[candidate]
    direction = signal.get("direction") or meta["direction"]
    body = {"schema": SCHEMA, "ruleVersion": RULE_VERSION, "candidate": candidate, "labelJa": meta["labelJa"],
            "signalDate": signal["signalDate"], "entryDate": entry_date, "recordedAt": recorded_at,
            "direction": direction, "instrument": INSTRUMENT[direction], "targetKind": meta["target"],
            "fixedTarget": signal.get("fixedTarget"), "fixedStop": signal.get("stop"),
            "targetBasis": signal.get("targetBasis"), "stopBasis": signal.get("stopBasis"),
            "signalDetail": {k: v for k, v in signal.items() if k in ("gapPct",)},
            "sameSessionEntry": bool(signal.get("sameSessionEntry")),
            "epsBasis": level_map.EPS_BASIS, "tradingSignal": False, "actionAuthority": False}
    body["recordId"] = "cr-" + _digest({k: v for k, v in body.items() if k != "recordedAt"})[:32]
    return body


def materialize(record: Mapping[str, Any], *, bars, eps_series, etf_bars_by_code) -> Optional[Dict[str, Any]]:
    """Entry, target and break level from the fixed rule, once the entry open exists."""
    sessions = [bar["date"] for bar in bars]
    if record["entryDate"] not in sessions or record["signalDate"] not in sessions:
        return None
    i, k = sessions.index(record["signalDate"]), sessions.index(record["entryDate"])
    p0 = bars[k]["open"]
    up = record["direction"] == "up"
    etf = {bar["date"]: bar for bar in (etf_bars_by_code or {}).get(record["instrument"]) or ()}
    eps = level_map.eps_before(eps_series, record["entryDate"])
    atr_value = level_map.atr(bars[:i + 1])
    kind = record["targetKind"]
    if kind == "PER_LINE":
        if not eps:
            return None
        multiple = (math.floor(p0 / eps[1]) + 1) if up else (math.ceil(p0 / eps[1]) - 1)
        target = {"kind": kind, "multiple": multiple, "nikkei": round(eps[1] * multiple, 2),
                  "basis": f"一つ{'上' if up else '下'}の整数PER線({multiple}倍・ARGUS推計EPS・毎日動く)"}
    elif kind == "ATR2":
        if not atr_value:
            return None
        target = {"kind": kind, "nikkei": round(p0 + 2 * atr_value if up else p0 - 2 * atr_value, 2),
                  "basis": f"入った値±2ATR(14日、{atr_value:,.0f})"}
    else:
        target = {"kind": kind, "nikkei": record["fixedTarget"], "basis": record.get("targetBasis")}
    stop = record.get("fixedStop") or (p0 * (1 - STOP_PCT) if up else p0 * (1 + STOP_PCT))
    deadline = {f"bd{n}": sessions[k + n - 1] if k + n - 1 < len(sessions) else None
                for n in (SHORT_DEADLINE, DEADLINE_SESSIONS)}
    return {**record, "entry": {"date": record["entryDate"], "etfOpen": (etf.get(record["entryDate"]) or {}).get("open"),
                                "nikkeiAtEntry": round(p0, 2)},
            "target": target, "stop": {"nikkei": round(stop, 2), "basis": record.get("stopBasis")
                                       or f"入った値から{'−' if up else '+'}5%"},
            "epsUsed": round(eps[1], 2) if eps else None, "epsDate": eps[0] if eps else None,
            "atr14": round(atr_value, 2) if atr_value else None, "deadline": deadline,
            "skippedAtEntry": bool(p0 >= target["nikkei"] if up else p0 <= target["nikkei"])}


def score(record: Mapping[str, Any], bars, eps_series, etf_bars_by_code=None) -> Dict[str, Any]:
    """Outcome from the Nikkei's intraday highs and lows, entry session = day 1."""
    if record.get("skippedAtEntry"):
        return {"outcome": "skipped_at_entry", "outcomeDate": record["entry"]["date"], "daysToOutcome": 0}
    sessions = [bar["date"] for bar in bars]
    start = record["entry"]["date"]
    if start not in sessions:
        return {"outcome": "open", "sessionsSeen": 0}
    up = record["direction"] == "up"
    stop = record["stop"]["nikkei"]
    window = bars[sessions.index(start):sessions.index(start) + DEADLINE_SESSIONS]
    short = None
    for n, bar in enumerate(window, start=1):
        target = record["target"]["nikkei"]
        if record["target"]["kind"] == "PER_LINE":
            eps = level_map.eps_before(eps_series, bar["date"])
            target = eps[1] * record["target"]["multiple"] if eps else target
        hit = bar["high"] >= target if up else bar["low"] <= target
        broke = bar["low"] <= stop if up else bar["high"] >= stop
        outcome = "ambiguous" if hit and broke else "reached" if hit else "broken" if broke else None
        if outcome:
            result = {"outcome": outcome, "outcomeDate": bar["date"], "daysToOutcome": n,
                      "exitNikkei": round(target if outcome == "reached" else stop, 2) if outcome != "ambiguous" else None}
            result["withinBd10"] = n <= SHORT_DEADLINE
            result["etfReturnAtOutcome"] = _etf_return(record, bars, result, etf_bars_by_code)
            return result
        if n == SHORT_DEADLINE:
            short = "open_at_bd10"
    if len(window) >= DEADLINE_SESSIONS:
        result = {"outcome": "expired", "outcomeDate": window[-1]["date"], "daysToOutcome": DEADLINE_SESSIONS,
                  "withinBd10": False, "exitNikkei": None}
        result["etfReturnAtOutcome"] = _etf_return(record, bars, result, etf_bars_by_code)
        return result
    return {"outcome": "open", "sessionsSeen": len(window), "bd10": short}


def _etf_return(record, bars, result, etf_bars_by_code) -> Optional[float]:
    """Approximate ETF return: exit valued at twice the Nikkei's move from the
    previous close to the exit level, round trip 0.2 % deducted (approximate)."""
    etf = {bar["date"]: bar for bar in (etf_bars_by_code or {}).get(record["instrument"]) or ()}
    entry_open = record["entry"].get("etfOpen") or (etf.get(record["entry"]["date"]) or {}).get("open")
    sessions = [bar["date"] for bar in bars]
    day = result.get("outcomeDate")
    if not entry_open or day not in sessions:
        return None
    k = sessions.index(day)
    prev_day = sessions[k - 1] if k else None
    if result["outcome"] == "expired":
        exit_price = (etf.get(day) or {}).get("close")
    elif result.get("exitNikkei") and prev_day and etf.get(prev_day):
        move = result["exitNikkei"] / bars[k - 1]["close"] - 1
        exit_price = etf[prev_day]["close"] * (1 + 2 * (move if record["instrument"] == "1579" else -move))
    else:
        exit_price = None
    if not exit_price:
        return None
    return round((exit_price / entry_open - 1 - ROUND_TRIP_COST) * 100, 2)


def summarize(records: Iterable[Mapping[str, Any]], outcomes: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The scoreboard: per candidate counts; fewer than ten records say so."""
    rows = []
    for candidate, meta in CANDIDATES.items():
        mine = [r for r in records if r["candidate"] == candidate]
        done = [outcomes[r["recordId"]] for r in mine if outcomes.get(r["recordId"], {}).get("outcome") not in (None, "open")]
        count = lambda name: sum(1 for o in done if o["outcome"] == name)
        days = sorted(o["daysToOutcome"] for o in done if o["outcome"] == "reached")
        returns = [o["etfReturnAtOutcome"] for o in done if isinstance(o.get("etfReturnAtOutcome"), (int, float))]
        rows.append({"candidate": candidate, "labelJa": meta["labelJa"], "dataStatus": meta.get("dataStatus", "RECORDING"),
                     "records": len(mine), "open": len(mine) - len(done), "reached": count("reached"),
                     "broken": count("broken"), "ambiguous": count("ambiguous"), "expired": count("expired"),
                     "skipped": count("skipped_at_entry"),
                     "medianDaysToReach": days[len(days) // 2] if days else None,
                     "meanEtfReturnPct": round(sum(returns) / len(returns), 2) if returns else None,
                     "enoughRecords": len(done) >= 10})
    return rows
