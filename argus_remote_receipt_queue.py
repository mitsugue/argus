"""Restart-safe asynchronous Remote Journal receipt intents.

The queue is deliberately small and contains public proof metadata only.  A
POST acceptance fsyncs this file and never serializes the large legacy
checkpoint.  Natural mission ticks later coalesce pending intents by WAL
sequence and persist the resulting verified state through the existing
checkpoint writer.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping, Optional


SCHEMA = "argus-remote-receipt-queue-v1"
RECEIPT_SCHEMA = "argus-remote-receipt-intent-v1"
VALID_STATES = {"pending", "verified", "failed"}
MAX_RECEIPTS = 512
MAX_ATTEMPTS = 8
INITIAL_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 30 * 60
IDEMPOTENCY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{16}")


class ReceiptQueueError(ValueError):
    """A public-safe receipt validation or consistency failure."""

    def __init__(self, error_class: str):
        super().__init__(error_class)
        self.error_class = error_class


def _epoch(value: Any) -> Optional[float]:
    try:
        return dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def empty_store() -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "receipts": [],
        "lastFlush": None,
        "migration": None,
    }


def _operation_id(idempotency_key: str) -> str:
    return "rr-" + hashlib.sha256(
        idempotency_key.encode("utf-8")).hexdigest()[:24]


def _unsigned(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in receipt.items()
            if key != "recordHash"}


def _record_hash(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(_unsigned(receipt))).hexdigest()


def verify_receipt(receipt: Any) -> bool:
    if not isinstance(receipt, dict):
        return False
    try:
        target = int(receipt.get("targetWalSequence"))
        attempts = int(receipt.get("attempts") or 0)
    except (TypeError, ValueError):
        return False
    state = receipt.get("durabilityState")
    operation_id = str(receipt.get("operationId") or "")
    return bool(
        receipt.get("schemaVersion") == RECEIPT_SCHEMA and
        operation_id.startswith("rr-") and len(operation_id) == 27 and
        receipt.get("receiptId") == operation_id and
        IDEMPOTENCY_RE.fullmatch(str(receipt.get("idempotencyKey") or "")) and
        SHA_RE.fullmatch(str(receipt.get("backendBuildSha") or "")) and
        SHA_RE.fullmatch(str(receipt.get("remoteCommitSha") or "")) and
        HASH_RE.fullmatch(str(receipt.get("expectedHash") or "")) and
        target >= 0 and attempts >= 0 and state in VALID_STATES and
        _epoch(receipt.get("acceptedAt")) is not None and
        receipt.get("recordHash") == _record_hash(receipt))


def verify_store(store: Any) -> bool:
    if not isinstance(store, dict) or store.get("schemaVersion") != SCHEMA:
        return False
    receipts = store.get("receipts")
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS:
        return False
    ids = []
    keys = []
    for receipt in receipts:
        if not verify_receipt(receipt):
            return False
        ids.append(receipt["operationId"])
        keys.append(receipt["idempotencyKey"])
    return len(ids) == len(set(ids)) and len(keys) == len(set(keys))


def normalize_store(store: Any) -> Dict[str, Any]:
    if store is None:
        return empty_store()
    if not verify_store(store):
        raise ReceiptQueueError("receipt_queue_integrity_invalid")
    return copy.deepcopy(store)


def _seal(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(receipt)
    result["recordHash"] = _record_hash(result)
    return result


def _same_intent(existing: Mapping[str, Any], *, build_sha: str,
                 remote_commit_sha: str, expected_hash: str,
                 target_wal_sequence: int) -> bool:
    return bool(
        existing.get("backendBuildSha") == build_sha and
        existing.get("remoteCommitSha") == remote_commit_sha and
        existing.get("expectedHash") == expected_hash and
        int(existing.get("targetWalSequence") or 0) == target_wal_sequence)


def accept_intent(store: Mapping[str, Any], *, idempotency_key: str,
                  build_sha: str, remote_commit_sha: str,
                  expected_hash: str, target_wal_sequence: int,
                  accepted_at: str) -> tuple[Dict[str, Any], Dict[str, Any], bool]:
    state = normalize_store(store)
    key = str(idempotency_key or "")
    build = str(build_sha or "").lower()
    commit = str(remote_commit_sha or "").lower()
    manifest_hash = str(expected_hash or "").lower()
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise ReceiptQueueError("idempotency_key_invalid")
    if not SHA_RE.fullmatch(build):
        raise ReceiptQueueError("backend_build_sha_invalid")
    if not SHA_RE.fullmatch(commit):
        raise ReceiptQueueError("remote_commit_sha_invalid")
    if not HASH_RE.fullmatch(manifest_hash):
        raise ReceiptQueueError("expected_hash_invalid")
    try:
        target = int(target_wal_sequence)
    except (TypeError, ValueError) as exc:
        raise ReceiptQueueError("target_wal_sequence_invalid") from exc
    if target < 0:
        raise ReceiptQueueError("target_wal_sequence_invalid")
    if _epoch(accepted_at) is None:
        raise ReceiptQueueError("accepted_at_invalid")

    for existing in state["receipts"]:
        if existing.get("idempotencyKey") != key:
            continue
        if not _same_intent(
                existing, build_sha=build, remote_commit_sha=commit,
                expected_hash=manifest_hash,
                target_wal_sequence=target):
            raise ReceiptQueueError("idempotency_key_conflict")
        return state, copy.deepcopy(existing), True

    operation_id = _operation_id(key)
    receipt = _seal({
        "schemaVersion": RECEIPT_SCHEMA,
        "operationId": operation_id,
        "receiptId": operation_id,
        "idempotencyKey": key,
        "backendBuildSha": build,
        "remoteCommitSha": commit,
        "expectedHash": manifest_hash,
        "targetWalSequence": target,
        "acceptedAt": accepted_at,
        "durabilityState": "pending",
        "remoteVerifiedWalSequence": None,
        "remoteCommitVerifiedSha": None,
        "readBackVerified": False,
        "verifiedAt": None,
        "attempts": 0,
        "lastAttemptAt": None,
        "nextAttemptAt": accepted_at,
        "lastErrorClass": None,
        "poison": False,
    })
    state["receipts"].append(receipt)
    if len(state["receipts"]) > MAX_RECEIPTS:
        removable = [row for row in state["receipts"]
                     if row.get("durabilityState") == "verified"]
        remove_count = len(state["receipts"]) - MAX_RECEIPTS
        remove_ids = {row["operationId"] for row in removable[:remove_count]}
        state["receipts"] = [row for row in state["receipts"]
                             if row["operationId"] not in remove_ids]
    if len(state["receipts"]) > MAX_RECEIPTS:
        raise ReceiptQueueError("receipt_queue_capacity_exceeded")
    return state, copy.deepcopy(receipt), False


def get_receipt(store: Mapping[str, Any], operation_id: str) -> Optional[Dict[str, Any]]:
    state = normalize_store(store)
    for receipt in state["receipts"]:
        if receipt.get("operationId") == operation_id:
            return copy.deepcopy(receipt)
    return None


def pending_receipts(store: Mapping[str, Any], *, now_iso: str,
                     limit: int = MAX_RECEIPTS) -> list[Dict[str, Any]]:
    state = normalize_store(store)
    now_ep = _epoch(now_iso)
    selected = []
    for receipt in state["receipts"]:
        if receipt.get("durabilityState") != "pending" or receipt.get("poison"):
            continue
        next_ep = _epoch(receipt.get("nextAttemptAt"))
        if now_ep is not None and next_ep is not None and next_ep > now_ep:
            continue
        selected.append(copy.deepcopy(receipt))
    selected.sort(key=lambda row: (
        int(row.get("targetWalSequence") or 0),
        str(row.get("acceptedAt") or ""),
        str(row.get("operationId") or "")))
    return selected[:max(0, int(limit))]


def highest_pending(store: Mapping[str, Any], *, now_iso: str,
                    limit: int = MAX_RECEIPTS) -> Optional[Dict[str, Any]]:
    rows = pending_receipts(store, now_iso=now_iso, limit=limit)
    return rows[-1] if rows else None


def _replace(store: Mapping[str, Any], operation_id: str,
             updates: Mapping[str, Any]) -> Dict[str, Any]:
    state = normalize_store(store)
    replaced = False
    result = []
    for receipt in state["receipts"]:
        if receipt.get("operationId") == operation_id:
            updated = dict(receipt)
            updated.update(updates)
            result.append(_seal(updated))
            replaced = True
        else:
            result.append(receipt)
    if not replaced:
        raise ReceiptQueueError("receipt_operation_missing")
    state["receipts"] = result
    return state


def record_attempt(store: Mapping[str, Any], operation_id: str,
                   *, attempted_at: str) -> Dict[str, Any]:
    receipt = get_receipt(store, operation_id)
    if receipt is None:
        raise ReceiptQueueError("receipt_operation_missing")
    attempts = int(receipt.get("attempts") or 0) + 1
    return _replace(store, operation_id, {
        "attempts": attempts,
        "lastAttemptAt": attempted_at,
        "lastErrorClass": None,
    })


def record_retry(store: Mapping[str, Any], operation_id: str, *, now_iso: str,
                 error_class: str, permanent: bool = False,
                 retry_after_seconds: Optional[int] = None) -> Dict[str, Any]:
    receipt = get_receipt(store, operation_id)
    if receipt is None:
        raise ReceiptQueueError("receipt_operation_missing")
    attempts = int(receipt.get("attempts") or 0)
    poison = bool(permanent or attempts >= MAX_ATTEMPTS)
    delay = (int(retry_after_seconds) if retry_after_seconds is not None else
             min(MAX_RETRY_SECONDS,
                 INITIAL_RETRY_SECONDS * (2 ** max(0, attempts - 1))))
    now_ep = _epoch(now_iso)
    next_attempt = None
    if now_ep is not None and not poison:
        next_attempt = dt.datetime.fromtimestamp(
            now_ep + max(1, delay), tz=dt.timezone.utc
        ).isoformat().replace("+00:00", "Z")
    return _replace(store, operation_id, {
        "durabilityState": "failed" if poison else "pending",
        "nextAttemptAt": next_attempt,
        "lastErrorClass": str(error_class or "remote_verification_failed")[:80],
        "poison": poison,
    })


def mark_covered_verified(store: Mapping[str, Any], *, verified_sequence: int,
                          remote_commit_sha: str, verified_at: str
                          ) -> tuple[Dict[str, Any], list[str]]:
    state = normalize_store(store)
    covered = []
    updated = []
    for receipt in state["receipts"]:
        target = int(receipt.get("targetWalSequence") or 0)
        if receipt.get("durabilityState") == "pending" and \
                not receipt.get("poison") and target <= int(verified_sequence):
            row = dict(receipt)
            row.update({
                "durabilityState": "verified",
                "remoteVerifiedWalSequence": int(verified_sequence),
                "remoteCommitVerifiedSha": str(remote_commit_sha).lower(),
                "readBackVerified": True,
                "verifiedAt": verified_at,
                "nextAttemptAt": None,
                "lastErrorClass": None,
            })
            updated.append(_seal(row))
            covered.append(str(receipt.get("operationId")))
        else:
            updated.append(receipt)
    state["receipts"] = updated
    return state, covered


def status_view(receipt: Mapping[str, Any], *, now_iso: str) -> Dict[str, Any]:
    accepted = _epoch(receipt.get("acceptedAt"))
    now_ep = _epoch(now_iso)
    age = (max(0, int(now_ep - accepted))
           if accepted is not None and now_ep is not None else None)
    return {
        "operationId": receipt.get("operationId"),
        "receiptId": receipt.get("receiptId"),
        "acceptedAt": receipt.get("acceptedAt"),
        "targetWalSequence": int(receipt.get("targetWalSequence") or 0),
        "verifiedWalSequence": (
            int(receipt.get("remoteVerifiedWalSequence"))
            if receipt.get("remoteVerifiedWalSequence") is not None else None),
        "durabilityState": receipt.get("durabilityState"),
        # Keep the immutable commit requested by this operation distinct from
        # the newer cumulative commit that may have covered it during a
        # coalesced drain.
        "remoteCommitSha": receipt.get("remoteCommitSha"),
        "verifiedByRemoteCommitSha": receipt.get(
            "remoteCommitVerifiedSha"),
        "readBackVerified": bool(receipt.get("readBackVerified")),
        "verifiedAt": receipt.get("verifiedAt"),
        "attempts": int(receipt.get("attempts") or 0),
        "lastErrorClass": receipt.get("lastErrorClass"),
        "ageSeconds": age,
    }


def summary(store: Mapping[str, Any], *, now_iso: str) -> Dict[str, Any]:
    state = normalize_store(store)
    counts = {name: 0 for name in VALID_STATES}
    poison = 0
    for row in state["receipts"]:
        counts[row["durabilityState"]] += 1
        poison += int(bool(row.get("poison")))
    highest = max((int(row.get("targetWalSequence") or 0)
                   for row in state["receipts"]
                   if row.get("durabilityState") == "pending"), default=0)
    now_ep = _epoch(now_iso)
    pending_ages = []
    for row in state["receipts"]:
        if row.get("durabilityState") != "pending":
            continue
        accepted_ep = _epoch(row.get("acceptedAt"))
        if accepted_ep is not None and now_ep is not None:
            pending_ages.append(max(0, int(now_ep - accepted_ep)))
    return {
        "schemaVersion": SCHEMA,
        "pendingCount": counts["pending"],
        "verifiedCount": counts["verified"],
        "failedCount": counts["failed"],
        "poisonCount": poison,
        "highestPendingWalSequence": highest,
        "oldestPendingAgeSeconds": max(pending_ages, default=0),
        "lastFlush": copy.deepcopy(state.get("lastFlush")),
    }


def migrate_legacy_receipt(legacy: Any, *, backend_build_sha: str,
                           idempotency_key: str) -> Dict[str, Any]:
    """Create one auditable intent from the v13.4.1 sidecar when possible.

    The old sidecar held only the latest cumulative receipt, not a receipt
    list.  Its accepted time and proof fields are copied exactly.  A missing
    target sequence is never guessed beyond the explicitly persisted remote
    or verified WAL cursor.
    """
    state = empty_store()
    if not isinstance(legacy, dict):
        return state
    commit = str(legacy.get("remoteCommitSha") or "").lower()
    expected = str(legacy.get("expectedHash") or "").lower()
    accepted_at = legacy.get("committedAt") or legacy.get("savedAt")
    target = max(int(legacy.get("remoteWalAppliedSequence") or 0),
                 int(legacy.get("verifiedWalSequence") or 0))
    if not (SHA_RE.fullmatch(commit) and HASH_RE.fullmatch(expected) and
            SHA_RE.fullmatch(str(backend_build_sha or "").lower()) and
            _epoch(accepted_at) is not None):
        state["migration"] = {
            "sourceSchemaVersion": legacy.get("schemaVersion"),
            "status": "no_migratable_receipt",
        }
        return state
    state, receipt, _ = accept_intent(
        state, idempotency_key=idempotency_key,
        build_sha=str(backend_build_sha).lower(),
        remote_commit_sha=commit, expected_hash=expected,
        target_wal_sequence=target, accepted_at=str(accepted_at))
    # v13.4.1 did not persist the intended target independently.  The largest
    # durable cursor in that sidecar is therefore a lower bound; immutable
    # read-back may legitimately prove a newer cumulative sequence.
    state = _replace(state, receipt["operationId"], {
        "migrationLowerBound": True,
    })
    if legacy.get("readBackVerified") is True and \
            legacy.get("walReadBackVerified") is True and \
            int(legacy.get("verifiedWalSequence") or 0) >= target:
        state, _ = mark_covered_verified(
            state, verified_sequence=int(legacy["verifiedWalSequence"]),
            remote_commit_sha=commit,
            verified_at=str(legacy.get("receiptVerifiedAt") or
                            legacy.get("readBackAt") or accepted_at))
    state["migration"] = {
        "sourceSchemaVersion": legacy.get("schemaVersion"),
        "status": "migrated",
        "operationId": receipt["operationId"],
    }
    return state
