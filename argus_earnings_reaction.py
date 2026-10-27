"""How a registered Japanese stock moved after its earnings releases (N-07).

2026-10-27 (owner): 「決算の反応は対象にできるのか? できるならする」. From the
saved J-Quants earnings summaries (disclosure date and time) and the stock's
own daily bars, each past release gets the session it first traded on, the gap
at that session's open and the move to its close against the previous close,
and the same-day TOPIX move. Measured facts only: no judgement of whether the
results were good, no forecast, no probability. Pure functions only.

The reaction session: before 09:00 → that day; 09:00–15:30 → that day, marked
INTRADAY because part of the move happened before the release; from 15:30 or
with no time → the next session.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "argus-earnings-reaction-v1"
LIMIT = 8


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _timing(stamp: str) -> str:
    if not stamp or len(stamp) < 5 or not stamp[:2].isdigit() or not stamp[3:5].isdigit():
        return "AFTER_CLOSE"
    minutes = int(stamp[:2]) * 60 + int(stamp[3:5])
    return "BEFORE_OPEN" if minutes < 9 * 60 else "INTRADAY" if minutes < 15 * 60 + 30 else "AFTER_CLOSE"


def _bars(data: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The stock's daily bars (J-Quants adjusted), oldest first."""
    if not isinstance(data, Mapping):
        return []
    dates, opens, closes = data.get("dates") or [], data.get("opens") or [], data.get("closes") or []
    rows = []
    for day, opening, closing in zip(dates, opens, closes):
        close = _finite(closing)
        if isinstance(day, str) and len(day) >= 10 and close is not None:
            rows.append({"date": day[:10], "open": _finite(opening), "close": close})
    return sorted({row["date"]: row for row in rows}.values(), key=lambda row: row["date"])


def _index_closes(rows: Iterable[Mapping[str, Any]]) -> Dict[str, float]:
    out = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        day = str(row.get("date") or row.get("Date") or "")[:10]
        close = _finite(row.get("close") if row.get("close") is not None else row.get("C"))
        if len(day) == 10 and close is not None:
            out[day] = close
    return out


def releases(observations: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Distinct earnings releases (financial statements only), oldest first."""
    seen = {}
    for observation in observations or ():
        row = observation.get("summary") if isinstance(observation, Mapping) else None
        if not isinstance(row, Mapping) or "FinancialStatements" not in str(row.get("DocType", "")):
            continue
        day = str(row.get("DiscDate") or "")[:10]
        if len(day) != 10:
            continue
        stamp = str(row.get("DiscTime") or "")[:5]
        seen[(day, stamp)] = {"date": day, "time": stamp or None, "timing": _timing(stamp),
                              "periodType": str(row.get("CurPerType") or "")[:8] or None}
    return [seen[key] for key in sorted(seen)]


def reactions(observations, stock_data, index_rows=(), *, limit: int = LIMIT) -> Dict[str, Any]:
    bars = _bars(stock_data)
    topix = _index_closes(index_rows)
    out = []
    for release in releases(observations):
        after = release["timing"] == "AFTER_CLOSE"
        index = next((i for i, row in enumerate(bars)
                      if (row["date"] > release["date"] if after else row["date"] >= release["date"])), None)
        if index is None or index == 0:
            continue                           # not traded yet, or no previous close in the bars
        session, base = bars[index], bars[index - 1]
        day_pct = (session["close"] / base["close"] - 1) * 100
        gap_pct = (session["open"] / base["close"] - 1) * 100 if session["open"] else None
        index_pct = ((topix[session["date"]] / topix[base["date"]] - 1) * 100
                     if session["date"] in topix and base["date"] in topix else None)
        out.append({"disclosedDate": release["date"], "disclosedTime": release["time"],
                    "timing": release["timing"], "periodType": release["periodType"],
                    "session": session["date"], "gapPct": None if gap_pct is None else round(gap_pct, 2),
                    "dayPct": round(day_pct, 2), "topixPct": None if index_pct is None else round(index_pct, 2),
                    "excessPct": None if index_pct is None else round(day_pct - index_pct, 2)})
    out = out[-limit:][::-1]
    ups = sum(1 for row in out if row["dayPct"] > 0)
    return {"schemaVersion": SCHEMA, "rows": out, "count": len(out), "ups": ups,
            "source": "J-Quants 決算短信の発表日時と日足", "actionAuthority": False,
            "predictiveProbability": None}
