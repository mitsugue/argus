"""ARGUS V11.3.2 — durable C.A.O.S. macro-event analysis store (pure).

Pre-event views must survive redeploys so the post-event answer-check can compare
against what ARGUS actually said. Merge policy: a non-empty pre is NEVER overwritten
by a blank; an older snapshot cannot wipe newer progress; the post record travels with
its preserved pre. Deterministic serialization; public-safe metadata only.
"""
import json
import hashlib
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "macro-event-analysis-v1"

FORBIDDEN_KEYS = {"fullText", "pdf", "body", "holdings", "pnl", "netR", "costBasis",
                  "quantity", "apiKey", "api_key", "headers", "token", "requestBody"}


def sanitize(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (record or {}).items() if k not in FORBIDDEN_KEYS}


def _has_pre(rec: Dict[str, Any]) -> bool:
    pre = (rec or {}).get("pre") or {}
    return bool(pre.get("argusScenarioJa") or pre.get("summaryJa"))


def _snapshot_digest(actual):
    return hashlib.sha256(json.dumps(actual, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def actual_revision_id(actual):
    if not isinstance(actual, dict) or not actual.get("available"):
        return None
    # Repeated receipts of the same values are not a new economic revision.
    keys = ("schemaVersion", "source", "sourceUrl", "metrics", "metricDefinitions", "metricInputs",
            "previousMetrics", "previousReferenceMonth", "referenceMatched")
    payload = {key: actual[key] for key in keys if key in actual}
    return "macro-result-" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _instant(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.timestamp() if dt.tzinfo is not None else float("-inf")
    except (ValueError, TypeError):
        return float("-inf")


def _result_time(record):
    actual = record.get("actual") or {}
    return _instant(actual.get("receivedAt") or record.get("updatedAt"))


def _preserve_revisions(merged, existing, incoming, now_iso):
    """Append observed results and explanations; existing snapshots keep their bytes."""
    results, analyses = {}, {}
    for record in (existing, incoming):
        for revision in record.get("resultRevisions") or []:
            if (revision.get("revisionId") != actual_revision_id(revision.get("actual"))
                    or revision.get("snapshotSha256") != _snapshot_digest(revision.get("actual"))):
                raise ValueError("macro_result_revision_integrity")
            results.setdefault(revision["revisionId"], deepcopy(revision))
        for revision in record.get("analysisRevisions") or []:
            payload = {key: revision.get(key) for key in ("phase", "analysis", "actualRevisionId", "inputLinkStatus")}
            identity = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            if revision.get("revisionId") != identity:
                raise ValueError("macro_analysis_revision_integrity")
            analyses.setdefault(identity, deepcopy(revision))
        actual = record.get("actual") or {}
        identity = actual_revision_id(actual)
        if identity:
            results.setdefault(identity, {"revisionId": identity, "recordedAt": now_iso,
                "firstObservedAt": actual.get("receivedAt"),
                "receiptStatus": "RECEIVED" if actual.get("receivedAt") else "LEGACY_UNVERIFIED",
                "actual": deepcopy(actual), "snapshotSha256": _snapshot_digest(actual)})
        for phase in ("pre", "post"):
            analysis = record.get(phase) or {}
            if not analysis.get("generatedAt"):
                continue
            payload = {"phase": phase, "analysis": deepcopy(analysis),
                       "actualRevisionId": analysis.get("actualRevisionId"),
                       "inputLinkStatus": "RECORDED" if analysis.get("actualRevisionId") else "LEGACY_UNVERIFIED"}
            key = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            analyses.setdefault(key, {"revisionId": key, "recordedAt": now_iso, **payload})
    merged["resultRevisions"] = sorted(results.values(), key=lambda row: row["revisionId"])
    merged["analysisRevisions"] = sorted(analyses.values(), key=lambda row: row["revisionId"])
    current_id = actual_revision_id(merged.get("actual"))
    merged["actualRevisionId"] = current_id
    previous_id = actual_revision_id(existing.get("actual"))
    post_id = (merged.get("post") or {}).get("actualRevisionId")
    if (post_id and post_id != current_id) or (previous_id and current_id != previous_id and post_id != current_id):
        merged["post"] = {"verdict": "not_scoreable", "generatedAt": None,
                          "limitationsJa": ["公式結果の入力が更新されました。以前の説明は改訂履歴に保存し、再照合を待っています。"]}
    return merged


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
    inc = deepcopy(sanitize(incoming))
    if not existing:
        rec = dict(inc)
        rec["updatedAt"] = now_iso
        return _preserve_revisions(rec, {}, inc, now_iso)
    ex = deepcopy(sanitize(existing))
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
        merged["actual"] = (in_act if _result_time(inc) >= _result_time(ex) else ex_act) or in_act or ex_act
    # post: newer generatedAt wins
    ex_post, in_post = (ex.get("post") or {}), (inc.get("post") or {})
    merged["post"] = (in_post if str(in_post.get("generatedAt") or "") >= str(ex_post.get("generatedAt") or "")
                      else ex_post)
    merged["firstSeenAt"] = min(filter(None, [ex.get("firstSeenAt"), inc.get("firstSeenAt")]),
                                default=now_iso)
    merged["updatedAt"] = now_iso
    return _preserve_revisions(merged, ex, inc, now_iso)


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
            rec = deepcopy(sanitize(r))
            out[r["eventId"]] = _preserve_revisions(rec, {}, rec, (snapshot or {}).get("asOf"))
    return out
