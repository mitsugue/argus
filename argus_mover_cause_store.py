"""ARGUS V11.3.3 — durable store semantics for mover-cause records (pure).

Invariants:
- merge by moverCauseId; a record with NO candidates never overwrites one WITH
  candidates for the same id (a degraded refresh can't blank a good analysis)
- the ladder never regresses to no_lead_yet from a record that had candidates
- explanationJa (admin-generated AI text) is preserved when the incoming
  record lacks one
- snapshots are deterministic, metadata-only, and structurally strip
  forbidden fields (full text / holdings / P&L / secrets / prompts)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "mover-cause-ledger-v1"

FORBIDDEN_KEYS = {"fullText", "pdf", "body", "holdings", "pnl", "netR", "costBasis",
                  "quantity", "avgCost", "apiKey", "api_key", "headers", "token",
                  "requestBody", "prompt", "prompts", "messages", "searchTrace",
                  "rawProviderBody", "rawBody", "searchTraces",
                  "ownerRelevant", "ownerState"}   # owner data never leaves private paths


def sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if k not in FORBIDDEN_KEYS}
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    return obj


def _has_candidates(rec: Optional[Dict[str, Any]]) -> bool:
    return bool(rec and (rec.get("causeCandidates") or []))


def _as_epoch(iso: Any) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def merge_record(existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]],
                 *, now_iso: str) -> Optional[Dict[str, Any]]:
    if not incoming:
        return existing
    if not existing:
        return sanitize(dict(incoming))
    newer = _as_epoch(incoming.get("asOf")) >= _as_epoch(existing.get("asOf"))
    base = dict(incoming) if newer else dict(existing)
    other = existing if newer else incoming
    # a blank refresh must not wipe a real analysis
    if not _has_candidates(base) and _has_candidates(other):
        for k in ("causeCandidates", "causeStatus", "causeStatusJa", "bestLeadJa",
                  "whyNotConfirmedJa", "confidence", "unknownShare",
                  "missingConfirmations", "nextChecksJa"):
            base[k] = other.get(k)
    # admin-generated explanation survives refreshes that lack one
    if not base.get("explanationJa") and other.get("explanationJa"):
        for k in ("explanationJa", "explanationGeneratedAt", "explanationStatus",
                  "unverifiedAssumptions", "whatWouldConfirmJa", "whatWouldRefuteJa"):
            if other.get(k) is not None:
                base[k] = other.get(k)
    # freshness bookkeeping (v11.3.4): the ORIGINAL createdAt survives; the AI
    # explain timestamps/cooldown survive a refresh that didn't run the AI
    bf, of = base.get("freshness") or {}, other.get("freshness") or {}
    if of.get("createdAt") and (not bf.get("createdAt") or str(of["createdAt"]) < str(bf.get("createdAt"))):
        bf["createdAt"] = of["createdAt"]
    if not bf.get("lastAiExplainAt") and of.get("lastAiExplainAt"):
        bf["lastAiExplainAt"] = of["lastAiExplainAt"]
    if bf:
        base["freshness"] = bf
    brp, orp = base.get("refreshPolicy") or {}, other.get("refreshPolicy") or {}
    if not brp.get("aiExplainCooldownUntil") and orp.get("aiExplainCooldownUntil"):
        brp["aiExplainCooldownUntil"] = orp["aiExplainCooldownUntil"]
        base["refreshPolicy"] = brp
    return sanitize(base)


def merge_records(store: Dict[str, Dict[str, Any]], records: List[Dict[str, Any]],
                  *, now_iso: str) -> Dict[str, Dict[str, Any]]:
    out = dict(store)
    for rec in records or []:
        mid = str((rec or {}).get("moverCauseId") or "")
        if not mid:
            continue
        merged = merge_record(out.get(mid), rec, now_iso=now_iso)
        if merged:
            out[mid] = merged
    return out


def serialize_snapshot(records: List[Dict[str, Any]], *, as_of: str) -> Dict[str, Any]:
    items = sorted((sanitize(dict(r)) for r in records if r and r.get("moverCauseId")),
                   key=lambda r: str(r.get("moverCauseId")))
    counts = {"confirmedCause": 0, "probableCatalyst": 0, "candidateCatalyst": 0,
              "noLeadYet": 0, "notScoreable": 0}
    keymap = {"confirmed_cause": "confirmedCause", "probable_catalyst": "probableCatalyst",
              "candidate_catalyst": "candidateCatalyst", "no_lead_yet": "noLeadYet",
              "not_scoreable": "notScoreable"}
    for r in items:
        k = keymap.get(str(r.get("causeStatus")))
        if k:
            counts[k] += 1
    return {"schemaVersion": SCHEMA_VERSION, "asOf": as_of,
            "summary": {"total": len(items), **counts}, "items": items}


def restore_from_snapshot(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(snapshot, dict):
        return out
    for r in snapshot.get("items") or []:
        mid = str((r or {}).get("moverCauseId") or "")
        if mid:
            out[mid] = sanitize(dict(r))
    return out
