"""ARGUS V11.3.1 — durable Official Event store (pure).

Official-event history is the foundation of future scoring/learning, so it must not
die with a /tmp wipe. This module is the PURE half of durability: deterministic
serialization, dedupe/merge by officialEventId (never losing older reaction windows),
sanitization (no full text / PDFs / secrets / private portfolio), and restore.

The ledger-branch write itself is done by the existing workflow pattern (curl a
public-safe endpoint → commit ledger/official-events/*.json); scanner wires the
runtime store + boot restore.
"""
import json
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "official-event-ledger-v1"
ENGINE_VERSION = "official-event-lifecycle-v1"

# keys that must NEVER appear in a public snapshot (defensive strip + test contract)
FORBIDDEN_KEYS = {"fullText", "pdf", "pdfBytes", "body", "documentBody", "holdings",
                  "pnl", "netR", "costBasis", "quantity", "apiKey", "api_key",
                  "headers", "token", "requestBody"}

_STAGE_ORDER = ["discovered", "classified", "eventcard_created", "judged",
                "market_reaction_pending", "market_reaction_observed",
                "followup_1d", "followup_3d", "followup_5d", "scored"]
_WINDOW_KEYS = ("sameDay", "nextSession", "day3", "day5")


def _stage_rank(stage: Optional[str]) -> int:
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def sanitize(record: Dict[str, Any]) -> Dict[str, Any]:
    """Strip forbidden keys (recursively one level into marketReaction windows)."""
    out = {k: v for k, v in (record or {}).items() if k not in FORBIDDEN_KEYS}
    mr = out.get("marketReaction")
    if isinstance(mr, dict):
        out["marketReaction"] = {k: ({kk: vv for kk, vv in v.items() if kk not in FORBIDDEN_KEYS}
                                     if isinstance(v, dict) else v)
                                 for k, v in mr.items()}
    return out


def merge_record(existing: Optional[Dict[str, Any]], incoming: Dict[str, Any],
                 *, now_iso: str) -> Dict[str, Any]:
    """Merge one lifecycle record by officialEventId. Policy:
      * reaction windows are UNIONED — a non-empty window is never lost; when both
        sides have one, the newer observedAt wins;
      * lifecycleStage only advances (max by stage order);
      * the newer updatedAt side provides the scalar fields; an older snapshot can
        never overwrite a newer record's progress;
      * recordedAt = earliest firstSeen/recorded; updatedAt = now."""
    inc = sanitize(incoming)
    if not existing:
        rec = dict(inc)
        rec.setdefault("recordedAt", inc.get("firstSeenAt") or now_iso)
        rec["updatedAt"] = inc.get("updatedAt") or now_iso
        return rec
    ex = sanitize(existing)
    ex_upd = str(ex.get("updatedAt") or ex.get("firstSeenAt") or "")
    in_upd = str(inc.get("updatedAt") or inc.get("firstSeenAt") or "")
    newer, older = (inc, ex) if in_upd >= ex_upd else (ex, inc)
    merged = dict(older)
    merged.update({k: v for k, v in newer.items() if v is not None})
    # windows: union, never lose progress
    mr = {}
    for k in _WINDOW_KEYS:
        a = (ex.get("marketReaction") or {}).get(k) or {}
        b = (inc.get("marketReaction") or {}).get(k) or {}
        if a and b:
            mr[k] = b if str(b.get("observedAt") or "") >= str(a.get("observedAt") or "") else a
        else:
            mr[k] = a or b
    merged["marketReaction"] = mr
    # stage only advances
    merged["lifecycleStage"] = max((ex.get("lifecycleStage"), inc.get("lifecycleStage")),
                                   key=_stage_rank)
    # decision/scoring refs: union (order-stable, dedup)
    for key in ("decisionRefs", "scoringRefs"):
        seen, uni = set(), []
        for v in (ex.get(key) or []) + (inc.get(key) or []):
            s = json.dumps(v, sort_keys=True, ensure_ascii=False)
            if s not in seen:
                seen.add(s)
                uni.append(v)
        merged[key] = uni
    merged["recordedAt"] = min(filter(None, [ex.get("recordedAt"), inc.get("recordedAt"),
                                             ex.get("firstSeenAt"), inc.get("firstSeenAt")]),
                               default=now_iso)
    merged["updatedAt"] = now_iso
    return merged


def merge_records(existing: Dict[str, Dict[str, Any]], incoming: List[Dict[str, Any]],
                  *, now_iso: str) -> Dict[str, Dict[str, Any]]:
    """Merge a batch into an id-keyed dict (returns a NEW dict)."""
    out = dict(existing or {})
    for rec in (incoming or []):
        oid = (rec or {}).get("officialEventId")
        if not oid:
            continue
        out[oid] = merge_record(out.get(oid), rec, now_iso=now_iso)
    return out


def serialize_snapshot(records: List[Dict[str, Any]], *, as_of: str, date_jst: str,
                       source: str = "tdnet") -> Dict[str, Any]:
    """Deterministic public-safe snapshot: sanitized, sorted by officialEventId."""
    items = sorted((sanitize(r) for r in (records or [])),
                   key=lambda r: str(r.get("officialEventId") or ""))
    pending = sum(1 for r in items
                  if not any((r.get("marketReaction") or {}).get(k) for k in _WINDOW_KEYS))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": as_of,
        "dateJst": date_jst,
        "engineVersion": ENGINE_VERSION,
        "source": source,
        "items": items,
        "summary": {
            "total": len(items),
            "material": sum(1 for r in items if r.get("material")),
            "confirmedCause": sum(1 for r in items if r.get("causeStatus") == "confirmed_cause"),
            "pendingMarketReaction": pending,
            "scored": sum(1 for r in items if r.get("lifecycleStage") == "scored"),
        },
    }


def restore_from_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Snapshot → id-keyed record dict (sanitized). Tolerates junk input."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in ((snapshot or {}).get("items") or []):
        if isinstance(r, dict) and r.get("officialEventId"):
            out[r["officialEventId"]] = sanitize(r)
    return out
