"""Prepare verified metadata migration without replacing a live checkpoint.

Original records and receipts remain private on the persistent disk. Their
retention is an explicit incomplete-removal condition, not a clean audit.
Only the normal checkpoint writer may persist and seal the restored state.
"""
import json
from pathlib import Path
import re

import argus_persistent_storage as storage
import argus_product_naming as naming
from scripts.migrate_analysis_names import digest, migrate


def _archive_directory(root):
    directory = Path(root).resolve() / "analysis-name-migration"
    if directory.is_symlink() or directory.resolve().is_relative_to(
            Path(__file__).resolve().parents[1]):
        raise ValueError("migration_archive_location_invalid")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _preserve_json(path, value):
    expected = storage._canonical_sha256(value)
    if path.is_symlink():
        raise ValueError("migration_archive_symlink_rejected")
    if path.exists():
        if not path.is_file() or storage._stream_sha256(str(path)) != expected:
            raise ValueError("migration_archive_conflict")
    else:
        written = storage.atomic_write_json(str(path), value, file_mode=0o600)
        if not written.get("readBackVerified") or written.get("snapshotHash") != expected:
            raise ValueError("migration_archive_readback_failed")
    return expected


def prepare_restore(snapshot, *, root, mapping_text=None, required=None):
    """Call after original checkpoint verification and before applying stores.

The result is an in-memory transformation, not a newly signed checkpoint.
No mapping or archive write may modify the original checkpoint file.
"""
    if not mapping_text:
        naming.require_allowed(snapshot, required=required)
        return snapshot, None
    try:
        mapping = json.loads(mapping_text)
    except (ValueError, TypeError):
        raise ValueError("migration_map_invalid") from None
    converted, receipt = migrate(snapshot, mapping)
    naming.require_allowed(converted, required=True)
    if not receipt["sections"]:
        return snapshot, None
    source_digest = storage._canonical_sha256(snapshot)
    directory = _archive_directory(root)
    archive_name = f"source-{source_digest}.json"
    _preserve_json(directory / archive_name, snapshot)
    prepared = {**receipt, "status": "PREPARED", "productionApplied": False,
                "checkpointVerified": False, "sourceSnapshotDigest": source_digest,
                "sourceArchive": archive_name}
    prepared["receiptId"] = digest(prepared)
    _preserve_json(directory / f"prepared-{prepared['receiptId']}.json", prepared)
    # The original signature only authenticates the original contents, which
    # are retained above. Do not carry it over to the transformed view.
    converted.pop("localCheckpointIntegrity", None)
    return converted, prepared


def record_restore_applied(receipt, *, root, production=False):
    """Record a successful memory restore; this is never checkpoint proof."""
    if not isinstance(receipt, dict) or receipt.get("status") != "PREPARED":
        raise ValueError("migration_receipt_invalid")
    receipt_id = receipt.get("receiptId")
    if digest({k: v for k, v in receipt.items() if k != "receiptId"}) != receipt_id:
        raise ValueError("migration_receipt_invalid")
    source_digest = receipt.get("sourceSnapshotDigest")
    if not isinstance(source_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", source_digest):
        raise ValueError("migration_source_identity_invalid")
    archive_name = f"source-{source_digest}.json"
    if receipt.get("sourceArchive") != archive_name:
        raise ValueError("migration_source_identity_invalid")
    directory = _archive_directory(root)
    archive = directory / archive_name
    if archive.is_symlink() or not archive.is_file() or storage._stream_sha256(str(archive)) != source_digest:
        raise ValueError("migration_source_archive_invalid")
    applied = {**receipt, "status": "APPLIED_TO_MEMORY",
               "productionApplied": bool(production), "checkpointVerified": False}
    _preserve_json(directory / f"applied-{receipt_id}.json", applied)
    return {"status": applied["status"], "receiptId": receipt_id,
            "sectionCount": len(receipt["sections"]),
            "identityChangeCount": len(receipt["identityChanges"]),
            "originalPreserved": True, "productionApplied": bool(production),
            "checkpointVerified": False}
