"""ARGUS V11.3.4 — mover-cause refresh queue (pure, deterministic).

Decides WHICH movers need evidence refresh or an AI explanation, in what order,
within an explicit budget. The scanner owns execution (admin/cron only); the
public GET serves the queue read-only from records already in the store.

Priority (mirrors argus_mover_cause.derive_priority):
- urgent : |move| >= 7, or owner-relevant + unresolved
- high   : |move| >= 4 and (unresolved or stale)
- normal : probable without full market confirmation
- low    : confirmed and fresh
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import argus_mover_cause

SCHEMA_VERSION = "mover-cause-refresh-v1"

_PRIO_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
# SLA: an URGENT record older than 15min without refresh is a breach (etc.)
SLA_MAX_AGE_MIN = {"urgent": 15, "high": 30, "normal": 120}


def _epoch(iso: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _cooldown_active(rec: Dict[str, Any], now_iso: str, cooldown_min: int) -> bool:
    rp = rec.get("refreshPolicy") or {}
    until = _epoch(rp.get("aiExplainCooldownUntil"))
    now = _epoch(now_iso)
    if until and now and now < until:
        return True
    last = _epoch((rec.get("freshness") or {}).get("lastAiExplainAt")
                  or rec.get("explanationGeneratedAt"))
    return bool(last and now and (now - last) < cooldown_min * 60)


def build_queue(records: List[Dict[str, Any]], now_iso: str, *,
                max_provider_refresh: int = 20, max_ai_explain: int = 5,
                ai_cooldown_min: int = 30, ai_min_abs_move: float = 3.0,
                ai_enabled: bool = True,
                owner_map: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """records = today's mover-cause records. Pure; never mutates inputs.
    owner_map (symbol → relevant) is ADMIN-PATH ONLY: it boosts ordering
    transiently and must never be passed on public GETs — records themselves
    carry no owner data (privacy invariant)."""
    import json as _json
    queue: List[Dict[str, Any]] = []
    ai_slots = max_ai_explain if ai_enabled else 0
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("symbol"):
            continue
        # deep copy: annotate_freshness mutates nested dicts and the store's own
        # records must never be written by a read path
        rec = argus_mover_cause.annotate_freshness(_json.loads(_json.dumps(rec)), now_iso)
        fr = rec.get("freshness") or {}
        rp = rec.get("refreshPolicy") or {}
        status = str(rec.get("causeStatus") or "")
        stale = bool(fr.get("isStale"))
        chg = rec.get("changePct")
        owner_rel = bool((owner_map or {}).get(str(rec.get("symbol") or "").upper()))
        prio, reason = argus_mover_cause.derive_priority(
            status, chg, owner_relevant=owner_rel, is_stale=stale,
            mc_status=str((rec.get("marketConfirmation") or {}).get("status") or ""))
        if owner_rel:
            reason = reason.replace("保有/高関連銘柄", "高関連銘柄")   # no holdings hints in output
        refresh_needed = stale or status in ("candidate_catalyst", "no_lead_yet") \
            or (rec.get("marketConfirmation") or {}).get("status") in ("missing", None)
        ai_eligible = (ai_slots > 0 and bool(rp.get("eligibleForAiExplain"))
                       and not rec.get("explanationJa")
                       and isinstance(chg, (int, float)) and abs(chg) >= ai_min_abs_move
                       and not _cooldown_active(rec, now_iso, ai_cooldown_min))
        if not refresh_needed and not ai_eligible and prio == "low":
            continue
        queue.append({
            "symbol": rec.get("symbol"), "market": rec.get("market"),
            "direction": rec.get("direction"),
            "changePct": chg,
            "causeStatus": status,
            "priority": prio, "reasonJa": reason,
            "refreshNeeded": bool(refresh_needed),
            "aiExplainNeeded": bool(ai_eligible),   # provisional — budgeted below
            "isStale": stale,
            "nextCheckAt": fr.get("nextAutoCheckAt"),
        })
    queue.sort(key=lambda q: (_PRIO_ORDER.get(q["priority"], 9),
                              -abs(q.get("changePct") or 0), str(q["symbol"])))
    queue = queue[:max(1, max_provider_refresh * 2)]
    # budget AFTER sorting AND truncation — slots must go to items actually served
    ai_used = 0
    for q in queue:
        if q["aiExplainNeeded"]:
            if ai_used < ai_slots:
                ai_used += 1
            else:
                q["aiExplainNeeded"] = False
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": now_iso,
        "queue": queue,
        "budget": {"maxProviderRefreshPerRun": max_provider_refresh,
                   "maxAiExplainPerRun": max_ai_explain,
                   "aiExplainUsed": ai_used,
                   "aiEnabled": bool(ai_enabled)},
    }


def quality_and_sla(records: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    """The stricter status diagnostics (spec §5) over today's records."""
    stale = missing_mc = ai_pending = no_fresh = 0
    breaches: List[Dict[str, Any]] = []
    total = 0
    covered = 0
    now = _epoch(now_iso)
    for rec in records:
        if not isinstance(rec, dict):
            continue
        total += 1
        import json as _json
        rec = argus_mover_cause.annotate_freshness(_json.loads(_json.dumps(rec)), now_iso)
        fr = rec.get("freshness") or {}
        if fr.get("isStale"):
            stale += 1
        mc = rec.get("marketConfirmation") or {}
        if mc.get("status") in ("missing", None):
            missing_mc += 1
        if (rec.get("refreshPolicy") or {}).get("eligibleForAiExplain") \
                and not rec.get("explanationJa"):
            ai_pending += 1
        cov = rec.get("evidenceCoverage") or {}
        n_checked = sum(1 for v in cov.values() if v)
        covered += n_checked / max(len(cov), 1)
        if n_checked == 0:
            no_fresh += 1
        prio = (rec.get("refreshPolicy") or {}).get("priority") or "normal"
        max_age = SLA_MAX_AGE_MIN.get(prio)
        last = _epoch(fr.get("lastEvidenceRefreshAt"))
        if max_age and last and now and (now - last) > max_age * 60:
            breaches.append({"symbol": rec.get("symbol"), "priority": prio,
                             "ageMin": int((now - last) / 60), "maxAgeMin": max_age})
    unresolved = sum(1 for r in records if isinstance(r, dict)
                     and r.get("causeStatus") in ("no_lead_yet",))
    return {
        "quality": {
            "allUnknownFailure": bool(total > 0 and unresolved == total),
            "staleCount": stale,
            "missingMarketConfirmationCount": missing_mc,
            "aiExplainPendingCount": ai_pending,
            "noFreshEvidenceCount": no_fresh,
            "coverageScore": round(covered / total, 2) if total else 0.0,
        },
        "sla": {
            "urgentMaxAgeMin": SLA_MAX_AGE_MIN["urgent"],
            "highMaxAgeMin": SLA_MAX_AGE_MIN["high"],
            "normalMaxAgeMin": SLA_MAX_AGE_MIN["normal"],
            "breaches": breaches[:10],
        },
    }
