"""急落警戒(案E)の事前記録と採点(2026-10-24)。

Today のタイルの割合は過去(2015-01〜2026-10-15)の固定値。配信後の日を、
その日の引けまでの値だけで記録し、5営業日後に同じ定義で採点して足していく。
- 段階: σ = (VIX/100 + 直近20日の日次騰落率の標準偏差(n-1)×√250) / 2。
  0.1473未満は低、0.2608以上は高、その間は普段並み。
- 一段上げ: 当日-2%以下か5営業日で-5%以下なら、低→普段並み・普段並み→高(高はそのまま)。
- VIX は東京の日付より前の米国の営業日の終値。
- 採点: 翌営業日〜5営業日後の日中安値の最小が、記録した終値×0.95以下なら「起きた」。
定義は画面(web/src/lib/todayDecision.ts)と研究側の事前記録と同じ。RULES を変えたら
RULES_VERSION を上げ、前の記録とは別に数える。記録は追記だけ(既存の候補の事前記録と
同じ保存先)。純粋な計算だけで、通信も時計も使わない。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

SCHEMA = "drop_alert_record.v1"
CANDIDATE = "ALERT_E"
RULES = {
    'sigma': '(VIX/100 + stdev(20 daily simple returns, n-1) * sqrt(250)) / 2',
    'lowBelow': 0.1473, 'highFrom': 0.2608,
    'raise': {'dayPct': -2, 'fiveDayPct': -5, 'steps': 'low->normal, normal->high, high stays'},
    'outcome': 'min low of sessions t+1..t+5 <= close(t) * 0.95',
    'pastRecord': {'low': [24, 818], 'normal': [136, 1592], 'high': [81, 468], 'raisedHigh': [27, 145]},
}
RULES_VERSION = 'alert-e-forward-2026-10-22'
RULES_SHA256 = hashlib.sha256(json.dumps(RULES, sort_keys=True).encode()).hexdigest()
WINDOW = 20
HORIZON = 5
FALL = 0.95
LEVELS = ("low", "normal", "high")
TALLY_KEYS = ("low", "normal", "high", "raisedHigh", "raisedNormal")


def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def _bars(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Completed sessions with a close (the low may be absent: it only blocks scoring)."""
    out = {}
    for row in rows or ():
        day = str(row.get("date") or "")[:10]
        close = _num(row.get("close"))
        if len(day) == 10 and close is not None:
            out[day] = {"date": day, "close": close, "low": _num(row.get("low"))}
    return [out[day] for day in sorted(out)]


def _complete(first: str, last: str, present: set, is_trading_day: Callable[[str], bool]) -> bool:
    """Every official session from first to last is in the data (gaps are never filled)."""
    day, end = date.fromisoformat(first), date.fromisoformat(last)
    while day <= end:
        iso = day.isoformat()
        if is_trading_day(iso) and iso not in present:
            return False
        day += timedelta(days=1)
    return True


def level(sigma: float, day_pct: float, five_day_pct: float) -> Dict[str, Any]:
    base = 'low' if sigma < RULES['lowBelow'] else 'high' if sigma >= RULES['highFrom'] else 'normal'
    fell = day_pct <= RULES['raise']['dayPct'] or five_day_pct <= RULES['raise']['fiveDayPct']
    shown = {'low': 'normal', 'normal': 'high'}.get(base, base) if fell else base
    return {"base": base, "level": shown, "raised": shown != base}


def level_on(rows, vix_rows, day: str, is_trading_day: Callable[[str], bool]) -> Dict[str, Any]:
    """The plan-E level from the closes up to `day` and the VIX before it."""
    bars = _bars(rows)
    days = [bar["date"] for bar in bars]
    if day not in days:
        return {"status": "NO_CLOSE"}
    i = days.index(day)
    if i < WINDOW:
        return {"status": "DATA_SHORT"}
    if not _complete(days[i - WINDOW], day, set(days), is_trading_day):
        return {"status": "DATA_GAP"}
    vix = sorted((str(r.get("date") or "")[:10], _num(r.get("close"))) for r in vix_rows or ()
                 if len(str(r.get("date") or "")[:10]) == 10 and _num(r.get("close")) is not None
                 and str(r.get("date"))[:10] < day)
    if not vix:
        return {"status": "NO_VIX"}
    closes = [bar["close"] for bar in bars[i - WINDOW:i + 1]]
    returns = [closes[k] / closes[k - 1] - 1 for k in range(1, WINDOW + 1)]
    mean = sum(returns) / WINDOW
    rv = math.sqrt(sum((x - mean) ** 2 for x in returns) / (WINDOW - 1)) * math.sqrt(250)
    vix_date, vix_close = vix[-1]
    sigma = (vix_close / 100 + rv) / 2
    day_pct = (closes[-1] / closes[-2] - 1) * 100
    five_pct = (closes[-1] / closes[-6] - 1) * 100
    return {"status": "AVAILABLE", "date": day, "close": round(closes[-1], 2), "vix": vix_close, "vixDate": vix_date,
            "rv20": round(rv, 4), "sigma": round(sigma, 4), **level(sigma, day_pct, five_pct),
            "dayPct": round(day_pct, 2), "fiveDayPct": round(five_pct, 2)}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def pre_record(row: Mapping[str, Any], *, recorded_at: str) -> Dict[str, Any]:
    """Fixed before the next session opens; stored in the candidate records (first body kept)."""
    if row.get("status") != "AVAILABLE":
        raise ValueError("drop_alert_level_required")
    body = {"schema": SCHEMA, "candidate": CANDIDATE, "signalDate": row["date"], "recordedAt": recorded_at,
            "rulesVersion": RULES_VERSION, "rulesSha256": RULES_SHA256,
            **{k: row[k] for k in ("close", "vix", "vixDate", "rv20", "sigma", "base", "level", "raised",
                                   "dayPct", "fiveDayPct")},
            "tradingSignal": False, "actionAuthority": False}
    body["recordId"] = "cr-" + _digest({k: v for k, v in body.items() if k != "recordedAt"})[:32]
    return body


def is_record(record: Mapping[str, Any]) -> bool:
    return isinstance(record, Mapping) and record.get("schema") == SCHEMA


def score(record: Mapping[str, Any], rows, is_trading_day: Callable[[str], bool]) -> Dict[str, Any]:
    """Matured after five later sessions with their intraday lows; the stored close is the yardstick."""
    bars = _bars(rows)
    days = [bar["date"] for bar in bars]
    day = record["signalDate"]
    if day not in days:
        return {"status": "PENDING"}
    i = days.index(day)
    window = bars[i + 1:i + 1 + HORIZON]
    if len(window) < HORIZON or any(bar["low"] is None for bar in window) \
            or not _complete(day, window[-1]["date"], set(days), is_trading_day):
        return {"status": "PENDING"}
    low = min(bar["low"] for bar in window)
    return {"status": "MATURED", "fell": low <= record["close"] * FALL, "windowEnd": window[-1]["date"],
            "minLow": round(low, 2)}


def summarize(records: Sequence[Mapping[str, Any]], outcomes: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    mine = sorted((r for r in records if is_record(r) and r.get("rulesVersion") == RULES_VERSION),
                  key=lambda r: r["signalDate"])
    tally = {key: {"matured": 0, "fell": 0} for key in TALLY_KEYS}
    pending = 0
    for record in mine:
        outcome = outcomes.get(record["recordId"]) or {}
        if outcome.get("status") != "MATURED":
            pending += 1
            continue
        keys = [record["level"]] + (["raised" + record["level"].capitalize()] if record["raised"] else [])
        for key in keys:
            tally[key]["matured"] += 1
            tally[key]["fell"] += int(bool(outcome["fell"]))
    return {"rulesVersion": RULES_VERSION, "rulesSha256": RULES_SHA256, "recordedDays": len(mine),
            "firstDay": mine[0]["signalDate"] if mine else None, "lastDay": mine[-1]["signalDate"] if mine else None,
            "pending": pending, "byLevel": tally, "tradingSignal": False, "actionAuthority": False}
