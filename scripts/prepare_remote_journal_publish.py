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
import base64
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
from typing import Any, Dict, Mapping, Optional

import argus_remote_journal


DEFAULT_FULL_SNAPSHOT_SOFT_LIMIT = 95 * 1024 * 1024
RECOVERY_SIDECAR_SCHEMA = "argus-remote-recovery-sidecar-v1"
RECOVERY_ENVELOPE_SCHEMA = "argus-remote-recovery-envelope-v1"
RECOVERY_ALGORITHM = "AES-256-GCM"
RECOVERY_KEY_DERIVATION = "HKDF-SHA-256"
MAX_READBACK_BYTES = 1024 * 1024
MAX_RECOVERY_BYTES = 8 * 1024 * 1024
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA64_RE = re.compile(r"[0-9a-f]{64}")
GENERATION_RE = re.compile(r"rrg-[0-9a-f]{32}")
CHECKPOINT_ID_RE = re.compile(r"rcp-[0-9a-f]{32}")
KEY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}")
URLSAFE_B64_UNPADDED_RE = re.compile(r"[A-Za-z0-9_-]+")


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


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decode_b64(value: Any, classification: str) -> bytes:
    text = str(value or "")
    if len(text) > ((MAX_RECOVERY_BYTES * 4) // 3 + 8):
        raise ValueError(classification)
    try:
        padding = "=" * ((4 - len(text) % 4) % 4)
        return base64.b64decode(
            (text + padding).encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ValueError(classification) from exc


def _decode_exact_derivation_salt(value: Any) -> bytes:
    """Decode the public 256-bit HKDF salt in its one canonical encoding."""
    text = value if isinstance(value, str) else ""
    if len(text) != 43 or not URLSAFE_B64_UNPADDED_RE.fullmatch(text):
        raise ValueError("recovery_key_derivation_salt_invalid")
    decoded = _decode_b64(text, "recovery_key_derivation_salt_invalid")
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if len(decoded) != 32 or canonical != text:
        raise ValueError("recovery_key_derivation_salt_invalid")
    return decoded


def validate_recovery_sidecar(
    sidecar: Any, *, exact_readback: Mapping[str, Any],
    ledger_base_commit_sha: Optional[str] = None,
) -> Dict[str, str]:
    """Verify the public envelope/pair contract without recovery key material.

    The backend endpoint authenticates the GCM tag before export.  The writer
    additionally checks the complete public envelope, ciphertext digest,
    bundle hash, compact proof equality, and the CAS base commit.  It never
    decrypts or prints the recovery payload.
    """
    if not isinstance(sidecar, Mapping) or set(sidecar) != {
            "schemaVersion", "readback", "recovery"} or sidecar.get(
                "schemaVersion") != RECOVERY_SIDECAR_SCHEMA:
        raise ValueError("recovery_sidecar_schema_invalid")
    if len(_canonical(sidecar)) > MAX_RECOVERY_BYTES:
        raise ValueError("recovery_sidecar_oversized")
    readback = sidecar.get("readback")
    if not isinstance(readback, Mapping) or dict(readback) != dict(exact_readback):
        raise ValueError("recovery_sidecar_readback_mismatch")
    if len(_canonical(readback)) > MAX_READBACK_BYTES or not \
            argus_remote_journal.verify_strict_compact_readback_snapshot(
                dict(readback)):
        raise ValueError("recovery_sidecar_readback_invalid")
    envelope = sidecar.get("recovery")
    required = {
        "schemaVersion", "algorithm", "generatedAt", "buildIdentity",
        "targetWalSequence", "compactReceiptHash", "checkpointVerifiedAt",
        "checkpointId", "ledgerBaseCommitSha", "keyId", "keyDerivation",
        "keyDerivationSalt", "generationId", "nonce", "ciphertext",
        "ciphertextSha256", "bundleHash",
    }
    if not isinstance(envelope, Mapping) or set(envelope) != required or \
            envelope.get("schemaVersion") != RECOVERY_ENVELOPE_SCHEMA or \
            envelope.get("algorithm") != RECOVERY_ALGORITHM or \
            envelope.get("keyDerivation") != RECOVERY_KEY_DERIVATION:
        raise ValueError("recovery_envelope_invalid")
    target = (readback.get("missionTickDurability") or {}).get(
        "walAppliedSequence")
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0 or \
            envelope.get("targetWalSequence") != target or \
            envelope.get("compactReceiptHash") != readback.get("receiptHash") or \
            envelope.get("generatedAt") != readback.get("generatedAt") or \
            envelope.get("buildIdentity") != readback.get("buildIdentity"):
        raise ValueError("recovery_pair_mismatch")
    base = str(envelope.get("ledgerBaseCommitSha") or "").lower()
    generation = str(envelope.get("generationId") or "")
    checkpoint_id = str(envelope.get("checkpointId") or "")
    key_id = str(envelope.get("keyId") or "")
    if not SHA40_RE.fullmatch(base) or not GENERATION_RE.fullmatch(generation) or \
            not CHECKPOINT_ID_RE.fullmatch(checkpoint_id) or \
            not KEY_ID_RE.fullmatch(key_id):
        raise ValueError("recovery_envelope_identity_invalid")
    if ledger_base_commit_sha is not None and base != str(
            ledger_base_commit_sha).lower():
        raise ValueError("recovery_ledger_base_commit_mismatch")
    _decode_exact_derivation_salt(envelope.get("keyDerivationSalt"))
    nonce = _decode_b64(envelope.get("nonce"), "recovery_nonce_invalid")
    ciphertext = _decode_b64(
        envelope.get("ciphertext"), "recovery_ciphertext_invalid")
    if len(nonce) != 12 or len(ciphertext) < 17 or \
            not SHA64_RE.fullmatch(str(envelope.get("ciphertextSha256") or "")) or \
            hashlib.sha256(ciphertext).hexdigest() != envelope.get(
                "ciphertextSha256"):
        raise ValueError("recovery_ciphertext_invalid")
    bundle_hash = str(envelope.get("bundleHash") or "")
    unsigned = {key: value for key, value in envelope.items()
                if key != "bundleHash"}
    if not SHA64_RE.fullmatch(bundle_hash) or _sha256(unsigned) != bundle_hash:
        raise ValueError("recovery_bundle_hash_mismatch")
    return {
        "artifactMode": "encrypted_recovery_v1",
        "recoveryBundleHash": bundle_hash,
        "recoveryGenerationId": generation,
        "recoveryKeyId": key_id,
        "ledgerBaseCommitSha": base,
    }


def verify_ledger_base_ancestor(
    *, repository: pathlib.Path, recovery_ledger_base: str,
    cas_ledger_head: str,
) -> Dict[str, str]:
    """Prove that authenticated base C belongs to CAS head X's history.

    The recovery envelope authenticates C, while a writer may observe a newer
    ledger head X after unrelated ledger-only commits.  Equality is therefore
    too strict.  Only C == X or C being an ancestor of X is safe; siblings and
    descendants are rejected before any files are staged or pushed.
    """
    recovery_base = str(recovery_ledger_base or "").lower()
    cas_head = str(cas_ledger_head or "").lower()
    if not SHA40_RE.fullmatch(recovery_base) or not SHA40_RE.fullmatch(cas_head):
        raise ValueError("recovery_ledger_ancestry_identity_invalid")

    for commit in (recovery_base, cas_head):
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=repository, capture_output=True, check=False, text=True)
        if exists.returncode != 0:
            raise ValueError("recovery_ledger_ancestry_commit_missing")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", recovery_base, cas_head],
        cwd=repository, capture_output=True, check=False, text=True)
    if ancestor.returncode != 0:
        raise ValueError("recovery_ledger_base_not_ancestor")
    return {
        "status": "verified",
        "recoveryLedgerBase": recovery_base,
        "casLedgerHead": cas_head,
    }


def _existing_proof(
    full_path: pathlib.Path, readback_path: pathlib.Path, *, strict: bool = False,
) -> Optional[Dict[str, Any]]:
    if readback_path.exists():
        try:
            receipt = _read_json(readback_path)
            verifier = (
                argus_remote_journal.verify_strict_compact_readback_snapshot
                if strict else
                argus_remote_journal.verify_compact_readback_snapshot)
            if verifier(receipt):
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
    if not new_as_of:
        raise ValueError("missing_snapshot_timestamp")
    if not new_receipt_hash:
        raise ValueError("missing_receipt_hash")

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
        "fullSnapshotBytes": full_bytes,
        "fullSnapshotSoftLimit": int(full_snapshot_soft_limit),
        "fullSnapshotPublished": bool(status == "prepared" and publish_full),
        "fullSnapshotRetained": bool(status == "prepared" and not publish_full),
        "readbackPublished": bool(status == "prepared"),
        "artifactMode": "legacy_full",
        "recoveryPublished": False,
    }


def prepare_pair(
    *, source_readback: pathlib.Path, source_recovery: pathlib.Path,
    ledger_readback: pathlib.Path, ledger_recovery: pathlib.Path,
    ledger_base_commit_sha: str,
) -> Dict[str, Any]:
    """Prepare an exact compact+encrypted-recovery CAS pair.

    The full snapshot is deliberately left untouched.  A ledger commit is the
    atomic publication boundary for the two bounded files.
    """
    readback = _read_json(source_readback)
    if not argus_remote_journal.verify_strict_compact_readback_snapshot(
            readback):
        raise ValueError("compact_readback_not_verifiable")
    sidecar = _read_json(source_recovery)
    metadata = validate_recovery_sidecar(
        sidecar, exact_readback=readback,
        ledger_base_commit_sha=ledger_base_commit_sha)
    existing = _existing_proof(
        pathlib.Path("/__no_full__"), ledger_readback, strict=True)
    old_as_of = _as_of(existing or {})
    new_as_of = _as_of(readback)
    old_receipt_hash = _receipt_hash(existing or {})
    new_receipt_hash = _receipt_hash(readback)
    if not new_as_of or not new_receipt_hash:
        raise ValueError("compact_readback_identity_missing")

    existing_pair_matches = False
    if old_receipt_hash == new_receipt_hash and ledger_recovery.exists():
        try:
            existing_sidecar = _read_json(ledger_recovery)
            existing_metadata = validate_recovery_sidecar(
                existing_sidecar, exact_readback=readback,
                ledger_base_commit_sha=ledger_base_commit_sha)
            existing_pair_matches = (
                existing_metadata["recoveryBundleHash"] ==
                metadata["recoveryBundleHash"])
        except (OSError, ValueError, json.JSONDecodeError):
            existing_pair_matches = False
    if old_receipt_hash and old_receipt_hash == new_receipt_hash and \
            existing_pair_matches:
        status = "already_committed"
    elif old_receipt_hash and old_receipt_hash == new_receipt_hash:
        status = "prepared"
    elif not old_as_of or new_as_of > old_as_of:
        status = "prepared"
    else:
        status = "stale"
    if status == "prepared":
        ledger_readback.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_readback, ledger_readback)
        shutil.copyfile(source_recovery, ledger_recovery)
    return {
        "status": status,
        "expectedHash": _manifest_hash(readback),
        "expectedReceiptHash": new_receipt_hash,
        "generatedAt": new_as_of,
        "previousGeneratedAt": old_as_of or None,
        "readbackPublished": status == "prepared",
        "recoveryPublished": status == "prepared",
        **metadata,
    }


def inspect_pair(
    *, readback_path: pathlib.Path, recovery_path: pathlib.Path,
) -> Dict[str, Any]:
    """Inspect an already-committed exact pair without modifying either file."""
    readback = _read_json(readback_path)
    if not argus_remote_journal.verify_strict_compact_readback_snapshot(
            readback):
        raise ValueError("committed_compact_readback_not_verifiable")
    expected_hash = _manifest_hash(readback)
    expected_receipt_hash = _receipt_hash(readback)
    if not expected_hash or not expected_receipt_hash:
        raise ValueError("committed_compact_readback_identity_missing")
    sidecar = _read_json(recovery_path)
    metadata = validate_recovery_sidecar(
        sidecar, exact_readback=readback)
    return {
        "status": "verified",
        "expectedHash": expected_hash,
        "expectedReceiptHash": expected_receipt_hash,
        "generatedAt": _as_of(readback),
        "readbackPublished": False,
        "recoveryPublished": False,
        **metadata,
    }


def inspect_sidecar(*, recovery_path: pathlib.Path) -> Dict[str, Any]:
    """Validate one endpoint sidecar without emitting its bounded payload.

    This is the pre-check used by workflow mode probes.  It rejects obsolete
    direct-root-key envelopes and malformed HKDF headers before a workflow can
    classify the endpoint as encrypted recovery.  Only scalar public identity
    metadata is returned; ciphertext, salt, nonce, and read-back content stay
    in the input file.
    """
    sidecar = _read_json(recovery_path)
    readback = sidecar.get("readback")
    if not isinstance(readback, Mapping):
        raise ValueError("recovery_sidecar_readback_invalid")
    metadata = validate_recovery_sidecar(
        sidecar, exact_readback=readback)
    return {"status": "verified", **metadata}


def verify_committed(
    *, readback_path: pathlib.Path, expected_hash: str,
    expected_receipt_hash: Optional[str] = None,
    recovery_path: Optional[pathlib.Path] = None,
    expected_recovery_bundle_hash: Optional[str] = None,
    ledger_base_commit_sha: Optional[str] = None,
) -> Dict[str, Any]:
    readback = _read_json(readback_path)
    verifier = (
        argus_remote_journal.verify_strict_compact_readback_snapshot
        if recovery_path is not None else
        argus_remote_journal.verify_compact_readback_snapshot)
    if not verifier(readback):
        raise ValueError("committed_compact_readback_not_verifiable")
    actual_hash = _manifest_hash(readback)
    if actual_hash != str(expected_hash):
        raise ValueError("committed_compact_readback_hash_mismatch")
    actual_receipt_hash = _receipt_hash(readback)
    if expected_receipt_hash is not None and \
            actual_receipt_hash != str(expected_receipt_hash):
        raise ValueError("committed_compact_readback_receipt_mismatch")
    result = {
        "status": "verified",
        "expectedHash": str(expected_hash),
        "actualHash": actual_hash,
        "generatedAt": _as_of(readback),
        "receiptHash": actual_receipt_hash,
        "artifactMode": "legacy_full",
        "recoveryBundleHash": None,
        "recoveryGenerationId": None,
        "recoveryKeyId": None,
        "ledgerBaseCommitSha": None,
    }
    if recovery_path is not None:
        sidecar = _read_json(recovery_path)
        metadata = validate_recovery_sidecar(
            sidecar, exact_readback=readback,
            ledger_base_commit_sha=ledger_base_commit_sha)
        if expected_recovery_bundle_hash is not None and metadata[
                "recoveryBundleHash"] != str(expected_recovery_bundle_hash):
            raise ValueError("committed_recovery_bundle_hash_mismatch")
        result.update(metadata)
    return result


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
    pair_parser = sub.add_parser("prepare-pair")
    pair_parser.add_argument(
        "--source-readback", required=True, type=pathlib.Path)
    pair_parser.add_argument(
        "--source-recovery", required=True, type=pathlib.Path)
    pair_parser.add_argument(
        "--ledger-readback", required=True, type=pathlib.Path)
    pair_parser.add_argument(
        "--ledger-recovery", required=True, type=pathlib.Path)
    pair_parser.add_argument("--ledger-base-commit-sha", required=True)
    inspect_parser = sub.add_parser("inspect-pair")
    inspect_parser.add_argument(
        "--readback", required=True, type=pathlib.Path)
    inspect_parser.add_argument(
        "--recovery", required=True, type=pathlib.Path)
    sidecar_parser = sub.add_parser("validate-sidecar")
    sidecar_parser.add_argument(
        "--recovery", required=True, type=pathlib.Path)
    verify_parser = sub.add_parser("verify-committed")
    verify_parser.add_argument("--readback", required=True, type=pathlib.Path)
    verify_parser.add_argument("--expected-hash", required=True)
    verify_parser.add_argument("--expected-receipt-hash")
    verify_parser.add_argument("--recovery", type=pathlib.Path)
    verify_parser.add_argument("--expected-recovery-bundle-hash")
    verify_parser.add_argument("--ledger-base-commit-sha")
    ancestry_parser = sub.add_parser("verify-ledger-base-ancestor")
    ancestry_parser.add_argument(
        "--repository", required=True, type=pathlib.Path)
    ancestry_parser.add_argument("--recovery-ledger-base", required=True)
    ancestry_parser.add_argument("--cas-ledger-head", required=True)
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
    elif args.command == "prepare-pair":
        result = prepare_pair(
            source_readback=args.source_readback,
            source_recovery=args.source_recovery,
            ledger_readback=args.ledger_readback,
            ledger_recovery=args.ledger_recovery,
            ledger_base_commit_sha=args.ledger_base_commit_sha,
        )
    elif args.command == "inspect-pair":
        result = inspect_pair(
            readback_path=args.readback,
            recovery_path=args.recovery,
        )
    elif args.command == "validate-sidecar":
        result = inspect_sidecar(recovery_path=args.recovery)
    elif args.command == "verify-committed":
        result = verify_committed(
            readback_path=args.readback, expected_hash=args.expected_hash,
            expected_receipt_hash=args.expected_receipt_hash,
            recovery_path=args.recovery,
            expected_recovery_bundle_hash=args.expected_recovery_bundle_hash,
            ledger_base_commit_sha=args.ledger_base_commit_sha,
        )
    else:
        result = verify_ledger_base_ancestor(
            repository=args.repository,
            recovery_ledger_base=args.recovery_ledger_base,
            cas_ledger_head=args.cas_ledger_head,
        )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
