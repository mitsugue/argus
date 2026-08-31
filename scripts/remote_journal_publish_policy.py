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
LONG_HASH_RE = re.compile(r"[0-9a-f]{64}")
GENERATION_RE = re.compile(r"rrg-[0-9a-f]{32}")
KEY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}")
NATURAL_EVENT = "schedule"
MANUAL_EVENT = "workflow_dispatch"
OPERATIONAL_DIAGNOSTICS_SCHEMA = "argus-operational-diagnostics-v1"


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
            data_quality.get("schemaVersion") != OPERATIONAL_DIAGNOSTICS_SCHEMA:
        raise PublishPolicyError("runtime_data_quality_invalid")
    truth = data_quality.get("remoteJournal")
    if not isinstance(truth, Mapping):
        raise PublishPolicyError("runtime_remote_journal_truth_missing")

    values = {}
    for key in (
            "localCommittedCount", "pendingCount",
            "committedCount", "failedCount"):
        value = truth.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PublishPolicyError("runtime_remote_journal_truth_invalid")
        values[key] = value
    if values["localCommittedCount"] != (
            values["pendingCount"] +
            values["committedCount"]):
        raise PublishPolicyError("runtime_remote_journal_truth_inconsistent")
    durable = data_quality.get("durability")
    if not isinstance(durable, Mapping) or \
            durable.get("integrityStatus") != "ok":
        raise PublishPolicyError("runtime_durable_integrity_invalid")
    for key in ("journalCorruptCount", "missionWalCorruptCount"):
        value = durable.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            raise PublishPolicyError("runtime_durable_integrity_invalid")
    return {
        "pendingCount": values["pendingCount"],
        "failureCount": values["failedCount"],
    }


def _runtime_wal_truth(data_quality: Optional[Mapping[str, Any]]) \
        -> Dict[str, int]:
    """Validate the stricter WAL/checkpoint truth for an explicit re-arm."""
    if data_quality is None:
        raise PublishPolicyError("runtime_data_quality_required_for_rearm")
    # Reuse schema, event counts, cumulative failure and corruption validation.
    _runtime_remote_truth(data_quality)
    durable = data_quality.get("durability")
    if not isinstance(durable, Mapping):
        raise PublishPolicyError("runtime_durable_integrity_invalid")
    checkpoint = durable.get("checkpoint")
    if not isinstance(checkpoint, Mapping) or \
            checkpoint.get("verified") is not True or \
            checkpoint.get("readBackVerified") is not True:
        raise PublishPolicyError("runtime_checkpoint_unverified")
    remote = data_quality.get("remoteJournal")
    if not isinstance(remote, Mapping) or \
            remote.get("readBackVerified") is not True or \
            remote.get("walReadBackVerified") is not True or \
            remote.get("state") != "verified":
        raise PublishPolicyError("runtime_remote_readback_unverified")
    wal_values = (
        checkpoint.get("includedWalSequence"),
        remote.get("remoteWalAppliedSequence"),
        remote.get("verifiedWalSequence"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in wal_values):
        raise PublishPolicyError("runtime_wal_sequence_invalid")
    local_wal, remote_applied, remote_verified = wal_values
    if local_wal <= 0 or remote_verified <= 0 or \
            remote_applied != remote_verified or local_wal < remote_verified:
        raise PublishPolicyError("runtime_wal_sequence_invalid")
    if remote.get("errorPresent") is not False:
        raise PublishPolicyError("runtime_remote_readback_unverified")
    return {
        "localIncludedWalSequence": local_wal,
        "runtimeVerifiedWalSequence": remote_verified,
        "runtimeWalGap": local_wal - remote_verified,
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
        natural_rearm: bool = False,
        scheduled_writer: bool = False,
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
    if natural_rearm and event != MANUAL_EVENT:
        raise PublishPolicyError("natural_rearm_event_invalid")
    if scheduled_writer and event != MANUAL_EVENT:
        raise PublishPolicyError("scheduled_writer_event_invalid")
    if natural_rearm and scheduled_writer:
        raise PublishPolicyError("scheduled_writer_rearm_mixed")

    progress = remote_progress(source_readback, ledger_readback)
    runtime_truth = _runtime_remote_truth(runtime_data_quality)
    runtime_pending = (
        runtime_truth["pendingCount"] if runtime_truth is not None else None)
    runtime_failures = (
        runtime_truth["failureCount"] if runtime_truth is not None else None)
    runtime_wal_truth = (
        _runtime_wal_truth(runtime_data_quality) if natural_rearm else None)
    runtime_wal_gap = (
        runtime_wal_truth["runtimeWalGap"]
        if runtime_wal_truth is not None else None)
    if natural_rearm and (
            progress["remoteProofMissing"] or
            progress["sourceWalTarget"] !=
            runtime_wal_truth["localIncludedWalSequence"] or
            progress["remoteWalTarget"] <
            runtime_wal_truth["runtimeVerifiedWalSequence"] or
            progress["remoteWalTarget"] > progress["sourceWalTarget"]):
        raise PublishPolicyError("natural_rearm_proof_runtime_mismatch")
    natural = event == NATURAL_EVENT or natural_rearm or scheduled_writer
    policy_source = (
        "remote_journal_rearm" if natural_rearm else
        "ec2_systemd_writer" if scheduled_writer else
        "github_schedule" if event == NATURAL_EVENT else "manual")
    ordinary_hourly_slot = natural and not natural_rearm and minute < 15
    if not natural:
        action, reason = "publish", "manual"
    elif natural_rearm and runtime_wal_gap == 0:
        action, reason = "skip", "natural_rearm_caught_up"
    elif ordinary_hourly_slot:
        action, reason = "publish", "ordinary_hourly_slot"
    elif progress["forwardProgress"]:
        action, reason = "publish", "natural_remote_backlog"
    elif runtime_pending is not None and runtime_pending > 0:
        action, reason = "receipt_only", "natural_receipt_recovery"
    elif runtime_wal_gap is not None and runtime_wal_gap > 0:
        action, reason = "receipt_only", "natural_runtime_wal_recovery"
    else:
        action, reason = "skip", "bounded_churn_skip"
    return {
        "schemaVersion": "argus-remote-journal-publish-decision-v1",
        "action": action,
        "publish": action == "publish",
        "receiptOnly": action == "receipt_only",
        "reason": reason,
        "natural": natural,
        "eventName": event,
        "naturalRearm": bool(natural_rearm),
        "scheduledWriter": bool(scheduled_writer),
        "policySource": policy_source,
        "utcMinute": minute,
        "runtimeTruthAvailable": runtime_pending is not None,
        "runtimeRemotePendingCount": runtime_pending,
        "runtimeRemoteFailureCount": runtime_failures,
        "runtimeLocalIncludedWalSequence": (
            runtime_wal_truth["localIncludedWalSequence"]
            if runtime_wal_truth is not None else None),
        "runtimeVerifiedWalSequence": (
            runtime_wal_truth["runtimeVerifiedWalSequence"]
            if runtime_wal_truth is not None else None),
        "runtimeWalGap": runtime_wal_gap,
        **progress,
    }


def receipt_request(
        readback: Mapping[str, Any], *, remote_commit_sha: str,
        backend_build_sha: str, expected_hash: str,
        idempotency_prefix: str = "caos-watchtower",
        expected_receipt_hash: Optional[str] = None,
        artifact_mode: Optional[str] = None,
        recovery_bundle_hash: Optional[str] = None,
        recovery_generation_id: Optional[str] = None,
        recovery_key_id: Optional[str] = None,
        ledger_base_commit_sha: Optional[str] = None) -> Dict[str, Any]:
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
    receipt_hash = str(readback.get("receiptHash") or "").lower()
    if expected_receipt_hash is not None and (
            not HASH_RE.fullmatch(str(expected_receipt_hash).lower()) or
            receipt_hash != str(expected_receipt_hash).lower()):
        raise PublishPolicyError("compact_receipt_hash_mismatch")
    mode = str(artifact_mode or "")
    recovery_fields = (
        recovery_bundle_hash, recovery_generation_id, recovery_key_id,
        ledger_base_commit_sha)
    if mode and mode not in ("legacy_full", "encrypted_recovery_v1"):
        raise PublishPolicyError("artifact_mode_invalid")
    if mode == "legacy_full" and any(value not in (None, "")
                                      for value in recovery_fields):
        raise PublishPolicyError("legacy_recovery_metadata_invalid")
    if mode == "encrypted_recovery_v1":
        recovery_hash = str(recovery_bundle_hash or "").lower()
        generation = str(recovery_generation_id or "")
        key_id = str(recovery_key_id or "")
        base_commit = str(ledger_base_commit_sha or "").lower()
        if not LONG_HASH_RE.fullmatch(recovery_hash) or not \
                GENERATION_RE.fullmatch(generation) or not \
                KEY_ID_RE.fullmatch(key_id) or not SHA_RE.fullmatch(base_commit):
            raise PublishPolicyError("recovery_receipt_metadata_invalid")
    prefix = str(idempotency_prefix or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,39}", prefix):
        raise PublishPolicyError("idempotency_prefix_invalid")
    key = f"{prefix}-{commit}-{remote_sequence}"
    if len(key) > 128:
        raise PublishPolicyError("idempotency_key_too_long")
    payload = {
        "remoteCommitSha": commit,
        "expectedHash": manifest_hash,
        "backendBuildSha": build,
        "targetWalSequence": remote_sequence,
    }
    # Backward-compatible direct callers may omit the strengthened artifact
    # contract.  Production workflows always provide it; the backend endpoint
    # rejects newly submitted payloads without an exact compact receipt hash.
    if expected_receipt_hash is not None or mode:
        if expected_receipt_hash is None or not mode:
            raise PublishPolicyError("receipt_artifact_contract_incomplete")
        payload.update({
            "expectedReceiptHash": receipt_hash,
            "artifactMode": mode,
            "recoveryBundleHash": (
                str(recovery_bundle_hash).lower()
                if mode == "encrypted_recovery_v1" else None),
            "recoveryGenerationId": (
                str(recovery_generation_id)
                if mode == "encrypted_recovery_v1" else None),
            "recoveryKeyId": (
                str(recovery_key_id)
                if mode == "encrypted_recovery_v1" else None),
            "ledgerBaseCommitSha": (
                str(ledger_base_commit_sha).lower()
                if mode == "encrypted_recovery_v1" else None),
        })
    return {
        "schemaVersion": "argus-remote-journal-receipt-request-v1",
        "idempotencyKey": key,
        "payload": payload,
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
    decision.add_argument("--natural-rearm", action="store_true")
    decision.add_argument("--scheduled-writer", action="store_true")
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--readback", required=True, type=pathlib.Path)
    receipt.add_argument("--remote-commit-sha", required=True)
    receipt.add_argument("--backend-build-sha", required=True)
    receipt.add_argument("--expected-hash", required=True)
    receipt.add_argument("--expected-receipt-hash")
    receipt.add_argument("--artifact-mode")
    receipt.add_argument("--recovery-bundle-hash")
    receipt.add_argument("--recovery-generation-id")
    receipt.add_argument("--recovery-key-id")
    receipt.add_argument("--ledger-base-commit-sha")
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
            natural_rearm=args.natural_rearm,
            scheduled_writer=args.scheduled_writer,
            runtime_data_quality=(
                _read_json(args.runtime_data_quality)
                if args.runtime_data_quality else None))
    else:
        result = receipt_request(
            _read_json(args.readback),
            remote_commit_sha=args.remote_commit_sha,
            backend_build_sha=args.backend_build_sha,
            expected_hash=args.expected_hash,
            idempotency_prefix=args.idempotency_prefix,
            expected_receipt_hash=args.expected_receipt_hash,
            artifact_mode=args.artifact_mode,
            recovery_bundle_hash=args.recovery_bundle_hash,
            recovery_generation_id=args.recovery_generation_id,
            recovery_key_id=args.recovery_key_id,
            ledger_base_commit_sha=args.ledger_base_commit_sha)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
