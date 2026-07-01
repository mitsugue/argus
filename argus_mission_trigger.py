"""argus_mission_trigger — decide WHICH events deserve a research mission.

Pure, dependency-injected, stdlib-only (mirrors argus_visibility / argus_downside).
Missions are expensive to run on everything, so this gates them: only owner-held +
high-severity drops, unexplained downside, imminent macro events, fresh institutional
comment on a watched name, and official disclosures earn a mission. It also builds a
REAL event dict (real moveStartedAt/severity) so link_to_event stays meaningful —
never a fabricated "now / high" for every held symbol.

No I/O, no LLM, no orders. It only plans; the caller runs the deterministic mission.
"""
from typing import Any, Dict, List, Optional

ENGINE_VERSION = "mission-trigger-v1"


def _norm(sym: Optional[str]) -> str:
    return str(sym or "").upper()


def plan_triggers(
    *,
    downside_incidents: Optional[List[Dict[str, Any]]] = None,
    important_events: Optional[List[Dict[str, Any]]] = None,
    new_intel: Optional[List[Dict[str, Any]]] = None,
    held_symbols: Optional[List[str]] = None,
    watch_symbols: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Return de-duplicated mission triggers, highest severity first. Each carries a
    REAL event dict fields {eventId, symbol, severity, moveStartedAt, ownerRelevant,
    reason, kind} — moveStartedAt is None when genuinely unknown (never faked)."""
    held = {_norm(s) for s in (held_symbols or [])}
    watch = {_norm(s) for s in (watch_symbols or [])} | held
    triggers: Dict[str, Dict[str, Any]] = {}   # symbol → best trigger

    def _consider(sym, severity, move_ts, reason, kind):
        sym = _norm(sym)
        if not sym:
            return
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "normal": 4}
        owner = sym in held
        cand = {"eventId": sym, "symbol": sym, "severity": severity, "moveStartedAt": move_ts,
                "ownerRelevant": owner, "reason": reason, "kind": kind}
        prev = triggers.get(sym)
        if prev is None or rank.get(severity, 9) < rank.get(prev["severity"], 9) or (owner and not prev["ownerRelevant"]):
            triggers[sym] = cand

    # 1) downside incidents — held/high/unexplained
    for inc in (downside_incidents or []):
        sym = inc.get("symbol")
        sev = str(inc.get("severity") or "medium")
        move_ts = inc.get("detectedAt") or inc.get("firstDetectedAt") or inc.get("asOf")
        unexplained = not (inc.get("caosLead") or inc.get("cause"))
        if _norm(sym) in held or sev in ("critical", "high") or unexplained:
            reason = ("保有銘柄の急落" if _norm(sym) in held else
                      "原因未確認の急落" if unexplained else f"{sev}の急落")
            _consider(sym, sev if _norm(sym) in held else (sev if sev in ("critical", "high") else "medium"),
                      move_ts, reason, "downside")

    # 2) imminent important macro/earnings events
    for ev in (important_events or []):
        impact = str(ev.get("displayImpact") or ev.get("impact") or "").lower()
        days = ev.get("daysUntil")
        imminent = isinstance(days, (int, float)) and days <= 1
        if impact in ("critical", "high") and imminent:
            for a in (ev.get("linkedAssets") or []):
                if _norm(a) in watch:
                    _consider(a, "high", ev.get("date"), f"重要イベント接近({ev.get('eventCode') or ev.get('title')})", "event")

    # 3) fresh institutional comment / official disclosure on a watched name
    for it in (new_intel or []):
        cat = it.get("category")
        for a in (it.get("linkedAssets") or []):
            if _norm(a) not in watch:
                continue
            if cat in ("ANALYST_ACTION", "DISCLOSED_POSITION", "OFFICIAL"):
                _consider(a, "high" if _norm(a) in held else "medium", it.get("publishedAt"),
                          f"機関の動き検知({cat})", "institutional")
            elif it.get("institutionId"):
                _consider(a, "medium", it.get("publishedAt"), "機関コメント検知", "institutional")

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "normal": 4}
    return sorted(triggers.values(), key=lambda t: (order.get(t["severity"], 9), 0 if t["ownerRelevant"] else 1))


def to_event(trigger: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger → the event dict run_mission / link_to_event expect (real fields)."""
    return {
        "eventId": trigger.get("eventId"),
        "linkedAssets": [trigger.get("symbol")],
        "moveStartedAt": trigger.get("moveStartedAt"),   # None when unknown — not faked
        "severity": trigger.get("severity"),
        "reason": trigger.get("reason"),
    }
