#!/usr/bin/env python3
"""Pure, privacy-safe policy for natural Remote Journal publication.

The GitHub workflow owns the remote write.  This module deliberately performs
no network or filesystem mutation beyond reading its input JSON.  It gives a
delayed natural Watchtower run one deterministic reason to bypass the ordinary
hourly write slot: the newly-built, verified compact proof has signed journal
or exact-WAL progress which the verified ledger proof does not yet contain.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any, Dict, Mapping, Optional, Tuple

import argus_remote_journal


SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{16}")
NATURAL_EVENT = "schedule"
MANUAL_EVENT = "workflow_dispatch"
DATA_QUALITY_SCHEMA = "data-quality-v1"


class PublishPolicyError(ValueError):
    """Fail-closed policy or receipt input error."""


def _read_json(path: pathlib.Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublishPolicyError(f"not_a_json_object:{path.name}")
    return value


def _verified_receipt(
        value: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not \
            argus_remote_journal.verify_compact_readback_snapshot(dict(value)):
        raise PublishPolicyError(f"{label}_compact_readback_not_verifiable")
    return value


def _signed_event_set(receipt: Mapping[str, Any]) -> Tuple[Any, ...]:
    """Return an order-insensitive, non-exported signed-event identity.

    ``integrityManifest.generatedAt`` and ``manifestHash`` intentionally do not
    participate.  They change on every snapshot even when no remotely durable
    event or WAL boundary changed, and therefore cannot be a liveness signal.
    The receipt and manifest are verified before this projection is used.
    """
    manifest = receipt.get("integrityManifest")
    if not isinstance(manifest, Mapping):
        raise PublishPolicyError("integrity_manifest_missing")
    ids = manifest.get("eventIds")
    keys = manifest.get("idempotencyKeys")
    hashes = manifest.get("eventHashes")
    sequences = manifest.get("highestSequenceByAggregate")
    criticality = manifest.get("criticalityByEventId")
    if not isinstance(ids, list) or not isinstance(keys, list) or not \
            isinstance(hashes, Mapping) or not isinstance(sequences, Mapping) \
            or not isinstance(criticality, Mapping):
        raise PublishPolicyError("signed_event_manifest_invalid")
    if any(not isinstance(value, str) or not value for value in ids + keys):
        raise PublishPolicyError("signed_event_identifier_invalid")
    try:
        sequence_rows = tuple(sorted(
            (str(name), int(value)) for name, value in sequences.items()))
    except (TypeError, ValueError) as exc:
        raise PublishPolicyError("signed_event_sequence_invalid") from exc
    return (
        str(manifest.get("schemaVersion") or ""),
        int(manifest.get("eventCount") or 0),
        tuple(sorted(ids)),
        tuple(sorted(keys)),
        tuple(sorted((str(name), str(value))
                     for name, value in hashes.items())),
        sequence_rows,
        tuple(sorted((str(name), str(value))
                     for name, value in criticality.items())),
    )


def _wal_target(receipt: Mapping[str, Any], *, label: str) -> int:
    durability = receipt.get("missionTickDurability")
    if not isinstance(durability, Mapping):
        raise PublishPolicyError(f"{label}_mission_tick_durability_missing")
    try:
        local = int(durability.get("walAppliedSequence") or 0)
        remote = int(durability.get("remoteWalAppliedSequence"))
    except (TypeError, ValueError) as exc:
        raise PublishPolicyError(f"{label}_wal_sequence_invalid") from exc
    if local <= 0 or remote != local:
        raise PublishPolicyError(f"{label}_wal_sequence_mismatch")
    return local


def remote_progress(
        source_readback: Mapping[str, Any],
        ledger_readback: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compare current and ledger proofs without trusting stale projections."""
    source = _verified_receipt(source_readback, label="source")
    source_events = _signed_event_set(source)
    source_wal = _wal_target(source, label="source")
    source_count = len(source_events[3])
    if ledger_readback is None:
        return {
            "remoteProofMissing": True,
            "eventSetChanged": source_count > 0,
            "walAdvanced": True,
            "sourceEventCount": source_count,
            "remoteEventCount": 0,
            "sourceWalTarget": source_wal,
            "remoteWalTarget": 0,
            "forwardProgress": True,
        }

    ledger = _verified_receipt(ledger_readback, label="ledger")
    ledger_events = _signed_event_set(ledger)
    ledger_wal = _wal_target(ledger, label="ledger")
    if source_wal < ledger_wal:
        raise PublishPolicyError("source_wal_regressed")
    event_changed = source_events != ledger_events
    wal_advanced = source_wal > ledger_wal
    return {
        "remoteProofMissing": False,
        "eventSetChanged": event_changed,
        "walAdvanced": wal_advanced,
        "sourceEventCount": source_count,
        "remoteEventCount": len(ledger_events[3]),
        "sourceWalTarget": source_wal,
        "remoteWalTarget": ledger_wal,
        "forwardProgress": bool(event_changed or wal_advanced),
    }


def _runtime_remote_truth(
        data_quality: Optional[Mapping[str, Any]]) -> Optional[Dict[str, int]]:
    """Validate public runtime ACK truth used only as a secondary signal.

    This scalar closes the state where the ledger write succeeded but the
    asynchronous receipt POST was lost.  It never replaces compact-proof
    verification and never authorizes a ledger write by itself.

    ``remoteFailedCount`` is cumulative historical telemetry, not a current
    failure latch.  It is therefore reported but must never suppress a later
    verified publication or idempotent receipt recovery.
    """
    if data_quality is None:
        return None
    if not isinstance(data_quality, Mapping) or \
            data_quality.get("schemaVersion") != DATA_QUALITY_SCHEMA:
        raise PublishPolicyError("runtime_data_quality_invalid")
    truth = data_quality.get("remoteJournalTruth")
    if not isinstance(truth, Mapping):
        raise PublishPolicyError("runtime_remote_journal_truth_missing")

    values = {}
    for key in (
            "localCommittedCount", "remotePendingCount",
            "remoteCommittedCount", "remoteFailedCount"):
        value = truth.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PublishPolicyError("runtime_remote_journal_truth_invalid")
        values[key] = value
    if values["localCommittedCount"] != (
            values["remotePendingCount"] +
            values["remoteCommittedCount"]):
        raise PublishPolicyError("runtime_remote_journal_truth_inconsistent")
    durable = data_quality.get("durableState")
    if not isinstance(durable, Mapping) or \
            durable.get("integrityStatus") != "ok":
        raise PublishPolicyError("runtime_durable_integrity_invalid")
    for key in ("journalCorrupt", "missionWalCorrupt"):
        value = durable.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            raise PublishPolicyError("runtime_durable_integrity_invalid")
    return {
        "pendingCount": values["remotePendingCount"],
        "failureCount": values["remoteFailedCount"],
    }


def runtime_remote_pending_count(
        data_quality: Optional[Mapping[str, Any]]) -> Optional[int]:
    """Return the validated pending count for callers and focused tests."""
    truth = _runtime_remote_truth(data_quality)
    return truth["pendingCount"] if truth is not None else None


def publication_decision(
        source_readback: Mapping[str, Any],
        ledger_readback: Optional[Mapping[str, Any]], *, event_name: str,
        utc_minute: int,
        runtime_data_quality: Optional[Mapping[str, Any]] = None,
        ) -> Dict[str, Any]:
    """Return a scalar-only decision; payloads and identifiers never escape."""
    try:
        minute = int(utc_minute)
    except (TypeError, ValueError) as exc:
        raise PublishPolicyError("utc_minute_invalid") from exc
    if minute < 0 or minute > 59:
        raise PublishPolicyError("utc_minute_invalid")
    event = str(event_name or "")
    if event not in (NATURAL_EVENT, MANUAL_EVENT):
        raise PublishPolicyError("workflow_event_invalid")

    progress = remote_progress(source_readback, ledger_readback)
    runtime_truth = _runtime_remote_truth(runtime_data_quality)
    runtime_pending = (
        runtime_truth["pendingCount"] if runtime_truth is not None else None)
    runtime_failures = (
        runtime_truth["failureCount"] if runtime_truth is not None else None)
    ordinary_hourly_slot = minute < 15
    if event == MANUAL_EVENT:
        action, reason = "publish", "manual"
    elif ordinary_hourly_slot:
        action, reason = "publish", "ordinary_hourly_slot"
    elif progress["forwardProgress"]:
        action, reason = "publish", "natural_remote_backlog"
    elif runtime_pending is not None and runtime_pending > 0:
        action, reason = "receipt_only", "natural_receipt_recovery"
    else:
        action, reason = "skip", "bounded_churn_skip"
    return {
        "schemaVersion": "argus-remote-journal-publish-decision-v1",
        "action": action,
        "publish": action == "publish",
        "receiptOnly": action == "receipt_only",
        "reason": reason,
        "natural": event == NATURAL_EVENT,
        "utcMinute": minute,
        "runtimeTruthAvailable": runtime_pending is not None,
        "runtimeRemotePendingCount": runtime_pending,
        "runtimeRemoteFailureCount": runtime_failures,
        **progress,
    }


def receipt_request(
        readback: Mapping[str, Any], *, remote_commit_sha: str,
        backend_build_sha: str, expected_hash: str,
        idempotency_prefix: str = "caos-watchtower") -> Dict[str, Any]:
    """Build the same exact-WAL async intent contract used by caos-scan."""
    commit = str(remote_commit_sha or "").lower()
    build = str(backend_build_sha or "").lower()
    manifest_hash = str(expected_hash or "").lower()
    if not SHA_RE.fullmatch(commit):
        raise PublishPolicyError("remote_commit_sha_invalid")
    if not SHA_RE.fullmatch(build):
        raise PublishPolicyError("backend_build_sha_invalid")
    if not HASH_RE.fullmatch(manifest_hash):
        raise PublishPolicyError("expected_hash_invalid")
    _verified_receipt(readback, label="source")
    actual_hash = str(
        (readback.get("integrityManifest") or {}).get("manifestHash") or ""
    ).lower()
    if actual_hash != manifest_hash:
        raise PublishPolicyError("compact_readback_hash_mismatch")
    remote_sequence = _wal_target(readback, label="source")
    prefix = str(idempotency_prefix or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,39}", prefix):
        raise PublishPolicyError("idempotency_prefix_invalid")
    key = f"{prefix}-{commit}-{remote_sequence}"
    if len(key) > 128:
        raise PublishPolicyError("idempotency_key_too_long")
    return {
        "schemaVersion": "argus-remote-journal-receipt-request-v1",
        "idempotencyKey": key,
        "payload": {
            "remoteCommitSha": commit,
            "expectedHash": manifest_hash,
            "backendBuildSha": build,
            "targetWalSequence": remote_sequence,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    decision = sub.add_parser("decision")
    decision.add_argument("--source-readback", required=True, type=pathlib.Path)
    decision.add_argument("--ledger-readback", type=pathlib.Path)
    decision.add_argument("--runtime-data-quality", type=pathlib.Path)
    decision.add_argument("--event-name", required=True)
    decision.add_argument("--utc-minute", required=True, type=int)
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--readback", required=True, type=pathlib.Path)
    receipt.add_argument("--remote-commit-sha", required=True)
    receipt.add_argument("--backend-build-sha", required=True)
    receipt.add_argument("--expected-hash", required=True)
    receipt.add_argument(
        "--idempotency-prefix", default="caos-watchtower")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "decision":
        ledger = (
            _read_json(args.ledger_readback)
            if args.ledger_readback and args.ledger_readback.exists()
            else None
        )
        result = publication_decision(
            _read_json(args.source_readback), ledger,
            event_name=args.event_name,
            utc_minute=args.utc_minute,
            runtime_data_quality=(
                _read_json(args.runtime_data_quality)
                if args.runtime_data_quality else None))
    else:
        result = receipt_request(
            _read_json(args.readback),
            remote_commit_sha=args.remote_commit_sha,
            backend_build_sha=args.backend_build_sha,
            expected_hash=args.expected_hash,
            idempotency_prefix=args.idempotency_prefix)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
