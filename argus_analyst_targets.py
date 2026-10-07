"""Analyst consensus target prices for watched stocks (2026-10-04).

Owner decision 2026-10-04: watched and held stocks only, once a day, from
Yahoo Finance's quote summary (the same unofficial source ARGUS already uses
for index prices), with the source, the day ARGUS fetched it and the number
of analysts shown as a small note. Kept: mean, median, high, low, analyst
count, currency, the price at fetch. Not kept: the recommendation label (a
buy/sell word). The high and low are the spread of the collected forecasts,
not a range the price will stay in. Pure: no network, no clock.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

SCHEMA = "argus-analyst-targets-v1"
SOURCE_LABEL = "Yahoo Finance"


def _raw(block: Any) -> Optional[float]:
    value = block.get("raw") if isinstance(block, Mapping) else block
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def parse_financial_data(symbol: str, payload: Mapping[str, Any], *, fetched_at: str) -> Optional[Dict[str, Any]]:
    """One row from a quoteSummary financialData response, or None when it has no target."""
    try:
        data = payload["quoteSummary"]["result"][0]["financialData"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(data, Mapping):
        return None
    mean = _raw(data.get("targetMeanPrice"))
    count = _raw(data.get("numberOfAnalystOpinions"))
    if mean is None or mean <= 0 or count is None or count < 1 or not count.is_integer():
        return None
    price = _raw(data.get("currentPrice"))
    price = price if price is not None and price > 0 else None
    return {"symbol": symbol, "mean": round(mean, 2), "median": _raw(data.get("targetMedianPrice")),
            "high": _raw(data.get("targetHighPrice")), "low": _raw(data.get("targetLowPrice")),
            "analysts": int(count), "currency": str(data.get("financialCurrency") or "")[:3] or None,
            "priceAtFetch": price,
            "gapPct": round((mean / price - 1) * 100, 1) if price else None,
            "fetchedAt": fetched_at, "source": SOURCE_LABEL, "actionAuthority": False}


def yahoo_symbol(market: str, symbol: str) -> Optional[str]:
    text = str(symbol or "").strip().upper()
    if market == "JP" and 4 <= len(text) <= 5 and text[:4].isalnum():
        return text[:4] + ".T"
    if market == "US" and text and text.replace(".", "").replace("-", "").isalnum():
        return text
    return None


def due(row: Optional[Mapping[str, Any]], today_jst: str) -> bool:
    """Once a day (JST): a row fetched today is kept as it is."""
    return not row or str(row.get("attemptDayJst") or row.get("fetchedDayJst") or "") != today_jst


def attempt_result(previous, row, *, market, symbol, today, at, status):
    """Retain the last valid target across a failed daily acquisition."""
    meta = {"market": market, "symbol": symbol, "attemptDayJst": today,
            "lastAttemptAt": at, "acquisitionStatus": status}
    if row:
        return {**row, **meta, "fetchedDayJst": today}
    if isinstance(previous, Mapping) and _raw(previous.get("mean")) is not None and previous["mean"] > 0:
        return {**previous, **meta}
    return {**meta, "unavailable": True, "fetchedDayJst": today}
