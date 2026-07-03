"""ARGUS V11.5.4 — C.A.O.S. Always-On Patrol plan (pure, stdlib-only).

C.A.O.S. must keep sweeping WITHOUT clicks. This turns the watchtower targets
into a patrol schedule with second-level cadence and per-target sweep state:

    active movers  → critical (|chg|>=7) / urgent, 300s cadence
    watchlist      → high, 900s
    macro-linked   → high, 900s
    Core Portfolio baseline → normal, 1800s (crypto/FX/gold/bonds run 24/7 —
                     they never pause outside stock sessions)
    cash/funds     → low, 3600s (posture / underlying exposure only)

The scanner supplies the v11.5.3 watchtower targets + the sweep-state map
{key → lastSweepAt}; this module only schedules. Pure: caller passes now_iso.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "caos-patrol-plan-v1"

CADENCE_SEC = {"critical": 300, "urgent": 300, "high": 900, "normal": 1800, "low": 3600}


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_patrol_plan(watchtower_targets: List[Dict[str, Any]],
                      sweep_state: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Watchtower targets (v11.5.3 plan) + sweep state → PatrolTargets with
    critical tier, refreshCadenceSec, last/next sweep and staleness."""
    now = _parse(now_iso) or datetime.now(timezone.utc)
    out = []
    for t in watchtower_targets or []:
        prio = str(t.get("priority") or "normal")
        # movers escalate: urgent watchtower targets with a big move → critical
        if t.get("reason") == "active_mover" and prio == "urgent":
            prio = "critical"
        cadence = CADENCE_SEC.get(prio, 1800)
        key = f"{t.get('assetClass')}:{t.get('symbol') or 'CLASS'}"
        st = (sweep_state or {}).get(key) or {}
        last = _parse(st.get("lastSweepAt"))
        nxt = (last + timedelta(seconds=cadence)) if last else now
        stale = last is None or nxt <= now
        out.append({
            "targetId": f"patrol-{key}",
            "assetClass": t.get("assetClass"), "symbol": t.get("symbol") or "",
            "name": t.get("name") or "", "themes": t.get("themes") or [],
            "priority": prio, "reason": t.get("reason") or "core_portfolio",
            "sources": t.get("sources") or [],
            "refreshCadenceSec": cadence,
            "lastSweepAt": st.get("lastSweepAt"),
            "nextSweepAt": _iso(nxt if last else now),
            "stale": bool(stale),
            "limitationsJa": t.get("limitationsJa") or [],
        })
    rank = {"critical": 0, "urgent": 1, "high": 2, "normal": 3, "low": 4}
    out.sort(key=lambda x: (rank.get(x["priority"], 5), x["targetId"]))
    due = [x for x in out if x["stale"]]
    return {"schemaVersion": SCHEMA_VERSION, "asOf": now_iso,
            "targets": out, "count": len(out), "dueCount": len(due),
            "noteJa": "クリックなしで常時巡回(near-real-time)。急変銘柄5分・ウォッチリスト15分・"
                      "基線30分。暗号/為替/金/債券は株式セッション外も監視。"
                      "Bloomberg/Reuters端末の完全代替ではない。"}


def pick_due_targets(plan: Dict[str, Any], *, max_deep: int = 5,
                     max_light: int = 10) -> Dict[str, List[Dict[str, Any]]]:
    """Which targets get a DEEP sweep vs a light metadata pass this cycle."""
    due = [t for t in plan.get("targets", []) if t.get("stale")]
    deep = [t for t in due if t["priority"] in ("critical", "urgent")][:max_deep]
    deep_ids = {t["targetId"] for t in deep}
    light = [t for t in due if t["targetId"] not in deep_ids
             and t["priority"] == "high"][:max_light]
    return {"deep": deep, "light": light}
