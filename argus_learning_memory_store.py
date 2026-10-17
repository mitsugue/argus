"""ARGUS V11.4.0 — durable store for the Learning Memory document (pure).

Learning Memory is a SINGLE aggregate document (not keyed records), so the store
is one snapshot. Invariants:
  * recursive sanitization strips forbidden keys (secrets / private holdings /
    prompts / raw provider bodies);
  * merge NEVER reduces sample counts — a stale rebuild can't shrink what ARGUS
    has already learned; per-lesson the higher sampleSize wins;
  * restore merges, never wipes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "learning-memory-ledger-v1"

FORBIDDEN_KEYS = {
    "fullText", "pdf", "body", "holdings", "pnl", "netR", "costBasis", "quantity",
    "avgCost", "apiKey", "api_key", "headers", "token", "authorization", "cookie",
    "rawProviderBody", "rawBody", "prompt", "prompts", "messages", "privateRepo",
    "requestBody", "searchTrace", "searchTraces", "ownerRelevant", "ownerState",
}


def sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if k not in FORBIDDEN_KEYS}
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    return obj


def serialize_snapshot(memory: Dict[str, Any], *, as_of: str) -> Dict[str, Any]:
    """Wrap the (already sanitized-by-construction) memory doc for the ledger.
    Deterministic: lessons are already sorted by build_memory."""
    mem = sanitize(dict(memory or {}))
    counts = mem.get("counts") or {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": as_of,
        "sampleStage": mem.get("sampleStage") or "none",
        "summary": {
            "sampleStage": mem.get("sampleStage") or "none",
            "lessons": int(counts.get("lessons", 0)),
            "usableLessons": int(counts.get("usableLessons", 0)),
            "totalScoredSamples": int(counts.get("totalScoredSamples", 0)),
        },
        "memory": mem,
    }


def restore_from_snapshot(snapshot: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return None
    mem = snapshot.get("memory")
    return sanitize(dict(mem)) if isinstance(mem, dict) else None


def _lessons_by_id(mem: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(L.get("lessonId")): L for L in (mem.get("lessons") or [])
            if isinstance(L, dict) and L.get("lessonId")}


def merge_memory(existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]],
                 *, now_iso: str) -> Optional[Dict[str, Any]]:
    """Merge two memory documents so counts NEVER go backward. The newer asOf wins
    the top-level narrative, but every per-lesson/aggregate count takes the max, so
    a stale rebuild can't erase learned sample size."""
    if not incoming:
        return sanitize(dict(existing)) if existing else None
    if not existing:
        return sanitize(dict(incoming))

    ex_new = str(incoming.get("asOf") or "") >= str(existing.get("asOf") or "")
    base = dict(incoming) if ex_new else dict(existing)
    other = existing if ex_new else incoming

    # per-lesson: keep the version with the larger sampleSize (counts never shrink)
    merged_lessons = dict(_lessons_by_id(other))
    for lid, L in _lessons_by_id(base).items():
        prev = merged_lessons.get(lid)
        if prev is None or int(L.get("sampleSize", 0)) >= int(prev.get("sampleSize", 0)):
            merged_lessons[lid] = L
    base["lessons"] = sorted(merged_lessons.values(),
                             key=lambda L: (str(L.get("cohortType")), str(L.get("cohortKey"))))

    # aggregate counts: take the max of each field across both docs
    bc, oc = dict(base.get("counts") or {}), dict(other.get("counts") or {})
    keys = set(bc) | set(oc)
    base["counts"] = {k: max(int(bc.get(k, 0) or 0), int(oc.get(k, 0) or 0)) for k in keys}
    base["counts"]["lessons"] = len(base["lessons"])
    base["counts"]["usableLessons"] = sum(
        1 for L in base["lessons"] if L.get("stage") in ("usable", "mature"))

    return sanitize(base)
