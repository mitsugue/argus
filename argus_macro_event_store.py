"""ARGUS V11.3.2 — durable C.A.O.S. macro-event analysis store (pure).

Pre-event views must survive redeploys so the post-event answer-check can compare
against what ARGUS actually said. Merge policy: a non-empty pre is NEVER overwritten
by a blank; an older snapshot cannot wipe newer progress; the post record travels with
its preserved pre. Deterministic serialization; public-safe metadata only.
"""
import json
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "macro-event-analysis-v1"

FORBIDDEN_KEYS = {"fullText", "pdf", "body", "holdings", "pnl", "netR", "costBasis",
                  "quantity", "apiKey", "api_key", "headers", "token", "requestBody"}


def sanitize(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (record or {}).items() if k not in FORBIDDEN_KEYS}


def _has_pre(rec: Dict[str, Any]) -> bool:
    pre = (rec or {}).get("pre") or {}
    return bool(pre.get("argusScenarioJa") or pre.get("summaryJa"))


def merge_record(existing: Optional[Dict[str, Any]], incoming: Dict[str, Any],
                 *, now_iso: str) -> Dict[str, Any]:
    """Merge one analysis record by eventId.
      * pre: a real pre wins over a blank; between two real pres the newer generatedAt
        wins — but once the event is past its release, the pre is FROZEN (the
        answer-check must reference the pre-release view, so post-release regenerations
        cannot replace it);
      * actual: available=True wins; never regress to unavailable;
      * post: newer generatedAt wins;
      * scalars from the newer updatedAt side; updatedAt = now."""
    inc = sanitize(incoming)
    if not existing:
        rec = dict(inc)
        rec["updatedAt"] = now_iso
        return rec
    ex = sanitize(existing)
    ex_upd = str(ex.get("updatedAt") or "")
    in_upd = str(inc.get("updatedAt") or "")
    newer, older = (inc, ex) if in_upd >= ex_upd else (ex, inc)
    merged = dict(older)
    merged.update({k: v for k, v in newer.items() if v is not None})
    # pre: real beats blank; frozen after release
    ex_pre, in_pre = (ex.get("pre") or {}), (inc.get("pre") or {})
    released = str(merged.get("phase") or "").startswith(("released", "post"))
    if _has_pre(ex) and not _has_pre(inc):
        merged["pre"] = ex_pre
    elif _has_pre(ex) and _has_pre(inc):
        if released:
            # freeze: keep the OLDER (pre-release) view
            merged["pre"] = ex_pre if str(ex_pre.get("generatedAt") or "") <= str(in_pre.get("generatedAt") or "") else in_pre
        else:
            merged["pre"] = in_pre if str(in_pre.get("generatedAt") or "") >= str(ex_pre.get("generatedAt") or "") else ex_pre
    else:
        merged["pre"] = in_pre or ex_pre
    # actual: availability never regresses
    ex_act, in_act = (ex.get("actual") or {}), (inc.get("actual") or {})
    if ex_act.get("available") and not in_act.get("available"):
        merged["actual"] = ex_act
    elif in_act.get("available") and not ex_act.get("available"):
        merged["actual"] = in_act
    else:
        merged["actual"] = in_act or ex_act
    # post: newer generatedAt wins
    ex_post, in_post = (ex.get("post") or {}), (inc.get("post") or {})
    merged["post"] = (in_post if str(in_post.get("generatedAt") or "") >= str(ex_post.get("generatedAt") or "")
                      else ex_post)
    merged["firstSeenAt"] = min(filter(None, [ex.get("firstSeenAt"), inc.get("firstSeenAt")]),
                                default=now_iso)
    merged["updatedAt"] = now_iso
    return merged


def merge_records(existing: Dict[str, Dict[str, Any]], incoming: List[Dict[str, Any]],
                  *, now_iso: str) -> Dict[str, Dict[str, Any]]:
    out = dict(existing or {})
    for rec in (incoming or []):
        eid = (rec or {}).get("eventId")
        if not eid:
            continue
        out[eid] = merge_record(out.get(eid), rec, now_iso=now_iso)
    return out


def serialize_snapshot(records: List[Dict[str, Any]], *, as_of: str) -> Dict[str, Any]:
    items = sorted((sanitize(r) for r in (records or [])),
                   key=lambda r: str(r.get("eventId") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": as_of,
        "items": items,
        "summary": {
            "total": len(items),
            "withPre": sum(1 for r in items if _has_pre(r)),
            "withActual": sum(1 for r in items if (r.get("actual") or {}).get("available")),
            "scored": sum(1 for r in items
                          if (r.get("post") or {}).get("verdict") in ("hit", "partial", "miss")),
        },
    }


def restore_from_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in ((snapshot or {}).get("items") or []):
        if isinstance(r, dict) and r.get("eventId"):
            out[r["eventId"]] = sanitize(r)
    return out
