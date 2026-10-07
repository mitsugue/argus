"""Fixed external-forecast scoring, using the existing analysis history store.

First receipt is the registration time, not a date claimed by the document.
Price-range touches are not evidence of a turning point or a trading signal.
"""
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from math import isfinite
from zoneinfo import ZoneInfo

import argus_market_clock as calendar

METHOD = "future-map-touch-v1"
JST = ZoneInfo("Asia/Tokyo")
ROW_FIELDS = ("id", "start", "end", "view", "level", "tag", "reason", "alt")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("forecast_timezone_required")
    return parsed


def record_id(row):
    return "fm-" + digest({key: row.get(key) for key in ROW_FIELDS})


def registration(row, *, received_at):
    instant(received_at)
    body = {key: row.get(key) for key in ROW_FIELDS}
    return {"schemaVersion": "future-map-registration-v1", "recordId": record_id(row),
            "recordedAt": received_at, "row": body, "actionAuthority": False}


def _trading(day):
    return calendar.canonical_trading_day(calendar.JP_EQUITY, day)


def _offset(day, step, count):
    for _ in range(40):
        day += timedelta(days=step)
        if _trading(day):
            count -= 1
            if count == 0:
                return day
    raise ValueError("forecast_calendar_unavailable")


def window(row):
    start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
    if end < start or (end - start).days > 366:
        raise ValueError("forecast_period_invalid")
    if row.get("level") is not None:
        start, end = _offset(end, -1, 5), _offset(end, 1, 5)
    sessions = []
    day = start
    while day <= end:
        if _trading(day):
            sessions.append(day.isoformat())
        day += timedelta(days=1)
    return sessions


def _price(value):
    try:
        return (float(value) if type(value) in (int, float) and isfinite(value) and value > 0 else None)
    except (OverflowError, ValueError):
        return None


def completed_bars(rows, now):
    accepted, rejected = {}, set()
    for row in rows:
        try:
            day = date.fromisoformat(row["date"])
            close_at = datetime.combine(day, time(15, 30), JST)
            if not _trading(day) or close_at > now:
                continue
            if row.get("availableFrom") and instant(row["availableFrom"]) > now:
                continue
            high, low, close = (_price(row.get(key)) for key in ("high", "low", "close"))
            if None in (high, low, close) or not low <= close <= high:
                continue
            item = {"date": day.isoformat(), "high": high, "low": low, "close": close}
            key = item["date"]
            if key in accepted and accepted[key] != item:
                rejected.add(key)
            accepted[key] = item
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return {key: value for key, value in accepted.items() if key not in rejected}


def score(record, price_rows, *, now_iso):
    now = instant(now_iso)
    row = record["row"]
    out = {"schemaVersion": METHOD, "recordId": record["recordId"], "rowId": row["id"],
           "status": "WAITING_WINDOW", "result": None, "scoredAt": now_iso,
           "method": "LEVEL_TOUCH" if row.get("level") is not None else "DIRECTION_MOVE",
           "probability": None, "actionAuthority": False, "turningPointValidated": False}
    sessions = window(row)
    if not sessions:
        return {**out, "status": "NO_TRADING_SESSIONS"}
    out.update(windowStart=sessions[0], windowEnd=sessions[-1], expectedSessions=len(sessions))
    first_open = datetime.combine(date.fromisoformat(sessions[0]), time(9), JST)
    if instant(record["recordedAt"]) >= first_open:
        return {**out, "status": "LATE_REGISTRATION"}
    if now < datetime.combine(date.fromisoformat(sessions[-1]), time(15, 30), JST):
        return out
    bars = completed_bars(price_rows, now)
    missing = [day for day in sessions if day not in bars]
    level = row.get("level")
    baseline = None
    if level is None:
        direction = {"下落": -1, "急落": -1, "戻り": 1}.get(row["tag"])
        if direction is None:
            return {**out, "status": "DIRECTION_NOT_DEFINED"}
        previous = _offset(date.fromisoformat(sessions[0]), -1, 1).isoformat()
        baseline = bars.get(previous)
        if baseline is None:
            missing.append(previous)
    if missing:
        return {**out, "status": "PRICES_INCOMPLETE", "missingSessions": missing}
    used = [bars[day] for day in sessions]
    if level is not None:
        low, high = _price(level.get("low")), _price(level.get("high"))
        if low is None or high is None or low > high:
            raise ValueError("forecast_level_invalid")
        reached = any(bar["high"] >= low * .99 and bar["low"] <= high * 1.01 for bar in used)
    else:
        reached = any(bar["high"] >= baseline["close"] * 1.03 for bar in used) if direction > 0 else \
            any(bar["low"] <= baseline["close"] * .97 for bar in used)
        out.update(baselineDate=baseline["date"], baselineClose=baseline["close"], direction=direction)
    out.update(status="SCORED", result="reached" if reached else "missed",
               pricesDigest=digest({"bars": used, "baseline": baseline}))
    identity = {key: value for key, value in out.items() if key != "scoredAt"}
    out["outcomeId"] = "fmo-" + digest(identity)
    return out


def summarize(records, outcomes):
    # Changed wording/levels remain as immutable versions. Only the first
    # received version of each forecast ID counts in the primary cohort.
    first = {}
    for record in records:
        first.setdefault(record["row"]["id"], record)
    final = [outcomes[r["recordId"]] for r in first.values()
             if outcomes.get(r["recordId"], {}).get("status") == "SCORED"]
    return {"scored": len(final), "reached": sum(r["result"] == "reached" for r in final),
            "status": "INSUFFICIENT_SAMPLE" if len(final) < 10 else "UNVALIDATED",
            "minimumRecords": 10, "firstVersionOnly": True, "turningPointValidated": False,
            "probability": None, "actionAuthority": False}
