"""When the integrated view is written again (owner decisions 2026-10-17, 2026-11-10, 2026-11-22).

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
SCHEDULE_VERSION = "brief-schedule-v3"
# Trading days (owner, 2026-11-10 「1日3回にする」「10/17から3つ」): three of
# the times fixed on 2026-10-17 (07:00, 08:00, 09:15, 10:00, 12:00, 13:00,
# 15:45, 17:00, 20:00, 22:00, 24:00) -- before the open, the lunch break and
# after the close. A "24:00" label would still mean midnight after that day.
# 2026-11-22 (owner 【15:45を16:10にずらす】): the after-close time moved from
# 15:45 to 16:10. Measured 2026-11-11..20: every 15:45 edition was written
# while the day's Nikkei close was still pending (the 1-session fact read
# 「最新営業日…は取得待ち」) and its six-sign count dropped (5/6 to 3/6 or
# 4/6) only to return the next morning. The close is read at the 16:05
# close-refresh slot (jp_market_close_refresh) and the delayed quote is read
# once more after 16:05 (argus_index_live.SETTLED_CLOSE_MINUTE), so a 16:10
# edition is written from the day's close.
TRADING_DAY_SLOTS = ("08:00", "12:00", "16:10")
# Weekends and Tokyo exchange holidays (unchanged since 2026-10-17).
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


# ── Material change (owner decision 2026-11-22 【見立ては変わった時だけ】) ──
#
# Measured 2026-11-11..21 (market_analysis_history views): every update time
# wrote a new paid edition (33 editions, one per due time plus one release).
# The unchanged-input reuse never applied at an update time, because its
# digest binds the whole cached input set (index bars, feature history,
# market-position memory, receipt times, eligible input times), and several
# of those move every few minutes. Each edition also listed "market_position"
# and "other" among the changed fact groups, i.e. text that moves on every
# collection without being a new market fact.
#
# From 2026-11-22 an update time after the morning one rewrites the view only
# when one of the owner's material inputs changed since the saved edition.
# Otherwise the saved edition stands and only its check time moves. When a
# rule cannot be evaluated the view is rewritten (an old view must not stay up
# silently).
MATERIAL_BASIS_VERSION = "brief-material-basis-v2"
# The first update time of every JST day (both day kinds start at 08:00):
# one edition a day is always written, so the screen's 24-hour age rule
# (web/src/lib/todayDecision.ts BRIEF_TONE_MAX_AGE_HOURS) is never reached by
# design; the longest gap between update times is 16:10 to 08:00 (15h50m).
MORNING_SLOT = TRADING_DAY_SLOTS[0]   # CLOSED_DAY_SLOTS[0] is the same time (tested)
# A Nikkei 225 move of 1% or more from the level the saved edition was written
# with. 2026-11-11..20 the close-to-close moves were +1.31, -0.70, +0.53,
# -2.42, -1.34, +0.28, +0.71, -5.06%: a 1% move is a day the view's numbers
# and tone may no longer hold; smaller moves are inside a normal session.
NIKKEI_MOVE_PCT = 1.0
_SIGN_ROW = "six-signs"


def _sha(value):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _p0_identity(fact):
    """One P0 fact as compared between editions.

    The source, its event id and its text: a new or replaced official result,
    material headline, imminent event or release news, or a change in its
    confirmation (市場確認待ち → 市場確認済み), is a change. One exception: an
    objective market-shock sensor (official_sensor) with an event id is
    compared by its id only, so the same sensor's value moving (米30年債利回り
    5.41% → 5.40%) does not rewrite the view; a shock appearing or clearing
    does. Market moves are covered by the Nikkei rule.
    """
    provenance = fact.get("provenance") if isinstance(fact.get("provenance"), dict) else {}
    event_id = provenance.get("eventId")
    source = str(fact.get("source") or "")
    if source == "official_sensor" and event_id:
        return [source, event_id, None]
    return [source, event_id, _sha(str(fact.get("text") or ""))[:16]]


def _six_signs(facts):
    """Lit sign names from the breakdown row, else the count from the market view."""
    import re
    for fact in facts:
        provenance = fact.get("provenance") if isinstance(fact.get("provenance"), dict) else {}
        if fact.get("source") == "market_view" and provenance.get("eventId") == _SIGN_ROW:
            body = str(fact.get("text") or "").split(": ", 1)[-1].rstrip("。")
            lit = sorted(part.rsplit("=", 1)[0] for part in body.split("、")
                         if part.rsplit("=", 1)[-1] == "点灯")
            return {"lit": lit, "count": len(lit)}
    for fact in facts:
        if fact.get("source") == "market_view":
            match = re.search(r"6サイン成立(\d+)/(\d+)", str(fact.get("text") or ""))
            if match:
                return {"lit": None, "count": int(match.group(1))}
    return {"lit": None, "count": None}


def _fiscal_warning(fiscal):
    """The Japanese fiscal warning state (owner 【入れる】 2026-11-22).

    The levels the fiscal monitor decided (argus_jp_fiscal_monitor): each
    case's warningLevel and the market side's warningLevel and adverse groups
    (long and super-long JGB yields, USD/JPY), from the brief's
    fiscalEnvironment (argus_jp_fiscal_runtime.context_reference). The fact
    texts are not compared: 「更新確認が未完了」 follows the acquisition of
    every poll and the projection numbers carry no level of their own.
    Measured 2026-11-11..21: the cases went UNKNOWN to WATCH once (11/12
    12:00) and the market side moved between WATCH and UNKNOWN four times.
    The earlier unused urgent signature (scanner) also counted these facts.
    """
    if not isinstance(fiscal, dict) or not fiscal:
        return None
    cases = fiscal.get("cases") if isinstance(fiscal.get("cases"), dict) else {}
    market = fiscal.get("market") if isinstance(fiscal.get("market"), dict) else {}
    adverse = market.get("adverseGroups") if isinstance(market.get("adverseGroups"), list) else []
    return {"cases": {str(case): (row or {}).get("warningLevel") for case, row in sorted(cases.items())},
            "market": {"warningLevel": market.get("warningLevel"),
                       "adverseGroups": sorted(str(group) for group in adverse)}}


def material_basis(*, facts, nikkei_price=None, nikkei_at=None, checked_at=None, fiscal=None):
    """What the material-change rule compares, from the composed (pre-AI) brief."""
    rows = [f for f in facts or () if isinstance(f, dict)]
    p0 = sorted({tuple(_p0_identity(f)) for f in rows if f.get("priority") == "P0"},
                key=lambda key: tuple("" if part is None else str(part) for part in key))
    price = (float(nikkei_price) if isinstance(nikkei_price, (int, float))
             and not isinstance(nikkei_price, bool) and nikkei_price > 0 else None)
    return {"schemaVersion": MATERIAL_BASIS_VERSION, "p0": [list(key) for key in p0],
            "sixSigns": _six_signs(rows), "fiscalWarning": _fiscal_warning(fiscal),
            "nikkei": {"price": price, "at": nikkei_at if isinstance(nikkei_at, str) else None},
            "checkedAt": checked_at}


def _signs_changed(before, after):
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    if before.get("lit") is not None and after.get("lit") is not None:
        return before["lit"] != after["lit"]
    return before.get("count") != after.get("count")


def material_change(*, previous_basis, basis, slot, previous_edition_at, now, event_ids=()):
    """Whether a due update time must write a new edition.

    Returns {"material": bool, "reasons": [...], "nikkeiMovePct": float|None}.
    Any one reason writes. Reasons, in the owner's order:
      morning_edition    the first update time of the JST day (once a day, always)
      new_day            the saved edition is from an earlier JST day (a missed
                         or failed morning edition is written at the next time)
      release_received   an important official result arrived with this time
      no_previous_basis  the saved edition predates this rule or its version
      p0_changed         a P0 fact was added, removed or replaced
      six_signs_changed  the lit six signs (or their count) differ
      fiscal_warning_changed  the Japanese fiscal warning levels differ
      nikkei_moved       the Nikkei 225 moved 1% or more from the saved level
      nikkei_unknown     either level is missing, so the move cannot be judged
    """
    now = _jst(now)
    reasons = []
    label = str(slot or "")
    if label.endswith(" " + MORNING_SLOT):
        reasons.append("morning_edition")
    last = _jst(previous_edition_at) if isinstance(previous_edition_at, datetime) else None
    if last is None or last.date() != now.date():
        reasons.append("new_day")
    if event_ids:
        reasons.append("release_received")
    move = None
    if not isinstance(previous_basis, dict) or previous_basis.get("schemaVersion") != MATERIAL_BASIS_VERSION:
        reasons.append("no_previous_basis")
    else:
        if previous_basis.get("p0") != basis.get("p0"):
            reasons.append("p0_changed")
        if _signs_changed(previous_basis.get("sixSigns"), basis.get("sixSigns")):
            reasons.append("six_signs_changed")
        if previous_basis.get("fiscalWarning") != basis.get("fiscalWarning"):
            reasons.append("fiscal_warning_changed")
        before = (previous_basis.get("nikkei") or {}).get("price")
        after = (basis.get("nikkei") or {}).get("price")
        if isinstance(before, (int, float)) and isinstance(after, (int, float)) and before > 0:
            move = (after / before - 1) * 100
            if abs(move) >= NIKKEI_MOVE_PCT:
                reasons.append("nikkei_moved")
        else:
            reasons.append("nikkei_unknown")
    return {"material": bool(reasons), "reasons": reasons,
            "nikkeiMovePct": None if move is None else round(move, 3)}
