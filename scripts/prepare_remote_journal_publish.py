#!/usr/bin/env python3
"""Prepare and verify a GitHub-safe Remote Journal publication.

The full durable snapshot is still the boot-restore artifact, but GitHub
rejects a single blob larger than 100 MiB.  When the snapshot exceeds the
conservative soft limit, retain the last valid full snapshot and publish only
the bounded, cryptographically verified read-back receipt used for journal
acknowledgement.  No receipt is synthesized here: it must have been derived
from the exact full snapshot by ``compact_readback_snapshot``.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
from typing import Any, Dict, Optional

import argus_remote_journal


DEFAULT_FULL_SNAPSHOT_SOFT_LIMIT = 95 * 1024 * 1024


def _read_json(path: pathlib.Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"not_a_json_object:{path.name}")
    return value


def _as_of(value: Dict[str, Any]) -> str:
    return str(value.get("generatedAt") or value.get("asOf") or "")


def _manifest_hash(value: Dict[str, Any]) -> str:
    return str((value.get("integrityManifest") or {}).get("manifestHash") or "")


def _receipt_hash(value: Dict[str, Any]) -> str:
    return str(value.get("receiptHash") or "")


def _wal_applied_sequence(value: Dict[str, Any], *, label: str) -> int:
    durability = value.get("missionTickDurability")
    if not isinstance(durability, dict):
        raise ValueError(f"{label}_mission_tick_durability_missing")
    sequence = durability.get("walAppliedSequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or \
            sequence <= 0:
        raise ValueError(f"{label}_wal_sequence_invalid")
    remote = durability.get("remoteWalAppliedSequence")
    if remote is not None and (
            isinstance(remote, bool) or not isinstance(remote, int) or
            remote != sequence):
        raise ValueError(f"{label}_wal_sequence_mismatch")
    return sequence


def _existing_proof(
    full_path: pathlib.Path, readback_path: pathlib.Path
) -> Optional[Dict[str, Any]]:
    if readback_path.exists():
        try:
            receipt = _read_json(readback_path)
            if argus_remote_journal.verify_compact_readback_snapshot(receipt):
                return receipt
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    if full_path.exists():
        try:
            snapshot = _read_json(full_path)
            if argus_remote_journal.parse_remote_snapshot(snapshot).get(
                "status"
            ) == "ok":
                return argus_remote_journal.compact_readback_snapshot(snapshot)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return None


def prepare(
    *,
    source_full: pathlib.Path,
    source_readback: pathlib.Path,
    ledger_full: pathlib.Path,
    ledger_readback: pathlib.Path,
    full_snapshot_soft_limit: int = DEFAULT_FULL_SNAPSHOT_SOFT_LIMIT,
) -> Dict[str, Any]:
    full = _read_json(source_full)
    readback = _read_json(source_readback)
    if full.get("schemaVersion") != argus_remote_journal.SCHEMA_V3:
        raise ValueError("unexpected_full_snapshot_schema")
    if argus_remote_journal.parse_remote_snapshot(full).get("status") != "ok":
        raise ValueError("full_snapshot_not_verifiable")
    if not argus_remote_journal.verify_compact_readback_snapshot(readback):
        raise ValueError("compact_readback_not_verifiable")

    full_hash = _manifest_hash(full)
    readback_hash = _manifest_hash(readback)
    if not full_hash or full_hash != readback_hash:
        raise ValueError("full_and_readback_manifest_mismatch")
    if _as_of(full) != _as_of(readback):
        raise ValueError("full_and_readback_timestamp_mismatch")
    exact_readback = argus_remote_journal.compact_readback_snapshot(full)
    if _receipt_hash(exact_readback) != _receipt_hash(readback):
        raise ValueError("full_and_readback_receipt_mismatch")

    existing = _existing_proof(ledger_full, ledger_readback)
    old_as_of = _as_of(existing or {})
    old_receipt_hash = _receipt_hash(existing or {})
    new_as_of = _as_of(readback)
    new_receipt_hash = _receipt_hash(readback)
    new_wal_sequence = _wal_applied_sequence(readback, label="source")
    if not new_as_of:
        raise ValueError("missing_snapshot_timestamp")
    if not new_receipt_hash:
        raise ValueError("missing_receipt_hash")
    if existing is not None:
        old_wal_sequence = _wal_applied_sequence(existing, label="ledger")
        if new_wal_sequence < old_wal_sequence:
            raise ValueError("source_wal_regressed")

    # Manifest identity covers the signed journal, but not outcomes, state
    # hashes, or missionTickDurability.  Exact receipt identity is required so
    # a WAL-only advance is never suppressed as ``already_committed``.
    if old_receipt_hash and old_receipt_hash == new_receipt_hash:
        status = "already_committed"
    elif not old_as_of or new_as_of > old_as_of:
        status = "prepared"
    else:
        status = "stale"

    full_bytes = source_full.stat().st_size
    publish_full = full_bytes <= int(full_snapshot_soft_limit)
    if status == "prepared":
        ledger_readback.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_readback, ledger_readback)
        if publish_full:
            shutil.copyfile(source_full, ledger_full)

    return {
        "status": status,
        "expectedHash": full_hash,
        "expectedReceiptHash": new_receipt_hash,
        "generatedAt": new_as_of,
        "previousGeneratedAt": old_as_of or None,
        "walAppliedSequence": new_wal_sequence,
        "fullSnapshotBytes": full_bytes,
        "fullSnapshotSoftLimit": int(full_snapshot_soft_limit),
        "fullSnapshotPublished": bool(status == "prepared" and publish_full),
        "fullSnapshotRetained": bool(status == "prepared" and not publish_full),
        "readbackPublished": bool(status == "prepared"),
    }


def verify_committed(
    *, readback_path: pathlib.Path, expected_hash: str,
    expected_receipt_hash: Optional[str] = None,
) -> Dict[str, Any]:
    readback = _read_json(readback_path)
    if not argus_remote_journal.verify_compact_readback_snapshot(readback):
        raise ValueError("committed_compact_readback_not_verifiable")
    actual_hash = _manifest_hash(readback)
    if actual_hash != str(expected_hash):
        raise ValueError("committed_compact_readback_hash_mismatch")
    actual_receipt_hash = _receipt_hash(readback)
    if expected_receipt_hash is not None and \
            actual_receipt_hash != str(expected_receipt_hash):
        raise ValueError("committed_compact_readback_receipt_mismatch")
    return {
        "status": "verified",
        "expectedHash": str(expected_hash),
        "actualHash": actual_hash,
        "generatedAt": _as_of(readback),
        "receiptHash": actual_receipt_hash,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--source-full", required=True, type=pathlib.Path)
    prepare_parser.add_argument(
        "--source-readback", required=True, type=pathlib.Path
    )
    prepare_parser.add_argument("--ledger-full", required=True, type=pathlib.Path)
    prepare_parser.add_argument(
        "--ledger-readback", required=True, type=pathlib.Path
    )
    prepare_parser.add_argument(
        "--full-snapshot-soft-limit",
        type=int,
        default=DEFAULT_FULL_SNAPSHOT_SOFT_LIMIT,
    )
    verify_parser = sub.add_parser("verify-committed")
    verify_parser.add_argument("--readback", required=True, type=pathlib.Path)
    verify_parser.add_argument("--expected-hash", required=True)
    verify_parser.add_argument("--expected-receipt-hash")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare(
            source_full=args.source_full,
            source_readback=args.source_readback,
            ledger_full=args.ledger_full,
            ledger_readback=args.ledger_readback,
            full_snapshot_soft_limit=args.full_snapshot_soft_limit,
        )
    else:
        result = verify_committed(
            readback_path=args.readback, expected_hash=args.expected_hash,
            expected_receipt_hash=args.expected_receipt_hash,
        )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
