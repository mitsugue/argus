"""When the integrated view is written again (owner decision 2026-10-17).

The measured cost (ai-usage-report, 2026-10-17) showed 80-99 saved editions a
day while the wording rarely changed. The owner fixed the update times in
Japan time; between them the saved edition is shown as it is. Right after an
important official release (the received results of CPI, PPI, PCE, NFP,
JOLTS, GDP, FOMC, BOJ) one more edition is written, at most three a day.

Pure functions only: no clock, no store, no network. The caller passes the
current time, the last edition's time and whether a JST day is a trading day.
"""
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SCHEDULE_VERSION = "brief-schedule-v1"
# Trading days (owner, 2026-10-17). "24:00" is midnight after that day.
TRADING_DAY_SLOTS = ("07:00", "08:00", "09:15", "10:00", "12:00", "13:00",
                     "15:45", "17:00", "20:00", "22:00", "24:00")
# Weekends and Tokyo exchange holidays.
CLOSED_DAY_SLOTS = ("08:00", "20:00")
EVENT_EDITIONS_PER_DAY = 3


def _jst(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("aware_datetime_required")
    return value.astimezone(JST)


def slots_for_day(day, trading_day):
    """The update instants (JST) that belong to one JST calendar day."""
    base = datetime(day.year, day.month, day.day, tzinfo=JST)
    out = []
    for text in (TRADING_DAY_SLOTS if trading_day else CLOSED_DAY_SLOTS):
        hour, minute = (int(part) for part in text.split(":"))
        out.append((base + timedelta(hours=hour, minutes=minute), text))
    return out


def latest_slot(now, is_trading_day):
    """The newest update instant at or before `now`, with its label.

    `is_trading_day(date)` says whether a JST date follows the trading-day
    times. Yesterday is read too: its "24:00" is today's midnight.
    """
    now = _jst(now)
    best = None
    for offset in (2, 1, 0):
        day = (now - timedelta(days=offset)).date()
        for at, label in slots_for_day(day, bool(is_trading_day(day))):
            if at <= now and (best is None or at > best[0]):
                best = (at, f"{day.isoformat()} {label}")
    return best


def decide(*, now, last_edition_at, covered_slot, is_trading_day,
           released_events=(), handled_event_ids=(), event_editions_today=0):
    """Whether to write a new edition now, and why.

    Returns {"due": bool, "kind": "SCHEDULED"|"EVENT"|None, "slot": label,
    "eventIds": [...], "reason": str}. A slot is due once: when the last
    edition is older than the slot and the slot was not already checked
    (inputs unchanged). A released result received after the last edition,
    not yet handled, is due while fewer than three event editions were written
    today (JST).
    """
    now = _jst(now)
    slot = latest_slot(now, is_trading_day)
    last = _jst(last_edition_at) if isinstance(last_edition_at, datetime) else None
    label = slot[1] if slot else None
    handled = set(handled_event_ids or ())
    fresh = sorted({str(e.get("eventId")) for e in released_events or ()
                    if isinstance(e, dict) and e.get("eventId") and str(e.get("eventId")) not in handled
                    and (last is None or _received_after(e, last))})
    if slot and (last is None or last < slot[0]) and covered_slot != label:
        return {"due": True, "kind": "SCHEDULED", "slot": label, "eventIds": fresh,
                "reason": "slot_due"}
    if fresh:
        if int(event_editions_today or 0) >= EVENT_EDITIONS_PER_DAY:
            return {"due": False, "kind": None, "slot": label, "eventIds": fresh,
                    "reason": "event_limit_reached"}
        return {"due": True, "kind": "EVENT", "slot": label, "eventIds": fresh,
                "reason": "release_received"}
    return {"due": False, "kind": None, "slot": label, "eventIds": [], "reason": "not_due"}


def _received_after(event, last):
    try:
        at = datetime.fromisoformat(str(event.get("sourceReceivedAt")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return at.tzinfo is not None and at > last


# The fact groups compared to say what changed between two editions.
FACT_GROUPS = (
    ("official_sensor", "公式の計測"), ("calendar", "日程"),
    ("official_macro_result", "公式の結果"), ("macro_release_news", "発表の関連報道"),
    ("jp_fiscal_environment", "財政"), ("trusted_mail", "ニュース"),
    ("market_position", "市場の現在位置"),
)


def changed_groups(previous_facts, facts, digest):
    """Names of the fact groups whose content differs; `digest(value)` -> str."""
    def by_group(rows):
        groups = {}
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or "")
            key = next((name for name, _ in FACT_GROUPS if source == name), "other")
            groups.setdefault(key, []).append(row.get("text"))
        return {key: digest(sorted(str(v) for v in values)) for key, values in groups.items()}
    before, after = by_group(previous_facts), by_group(facts)
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def wording_change(previous_text, text):
    """Which parts of the written view changed: {"conclusion": bool, "sections": [...]}."""
    previous_text = previous_text if isinstance(previous_text, dict) else {}
    text = text if isinstance(text, dict) else {}
    keys = sorted(set(previous_text) | set(text))
    return {"conclusion": previous_text.get("nowJa") != text.get("nowJa"),
            "sections": [k for k in keys if previous_text.get(k) != text.get(k)]}
