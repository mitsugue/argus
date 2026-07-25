"""Fail-closed persistent storage contract for mission-tick durability.

The live Render service is dashboard-managed.  This module proves only what
the running process can observe: path containment, filesystem durability
primitives, and free capacity.  It never claims that a Render Disk is attached
merely because ``render.yaml`` describes one.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from typing import Any, Dict, Mapping, Optional


UTC = dt.timezone.utc
LOCAL_SEAL_SCHEMA = "argus-local-checkpoint-integrity-v1"
MINIMUM_SAFETY_RESERVE = 64 * 1024 * 1024
MINIMUM_WAL_ALLOWANCE = 8 * 1024 * 1024


class PersistentStorageError(RuntimeError):
    """A redacted, operator-actionable persistent-storage failure."""

    error_class = "persistent_storage_unavailable"

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _iso_now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _without_seal(blob: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in blob.items()
            if key != "localCheckpointIntegrity"}


def seal_checkpoint(blob: Mapping[str, Any]) -> Dict[str, Any]:
    sealed = dict(_without_seal(blob))
    sealed["localCheckpointIntegrity"] = {
        "schemaVersion": LOCAL_SEAL_SCHEMA,
        "algorithm": "sha256",
        "snapshotHash": hashlib.sha256(_canonical(sealed)).hexdigest(),
    }
    return sealed


def verify_checkpoint(blob: Any, *, require_seal: bool = True) -> bool:
    if not isinstance(blob, dict) or \
            blob.get("schemaVersion") != "argus-durable-v3":
        return False
    seal = blob.get("localCheckpointIntegrity")
    if not isinstance(seal, dict):
        return not require_seal
    if seal.get("schemaVersion") != LOCAL_SEAL_SCHEMA or \
            seal.get("algorithm") != "sha256":
        return False
    expected = hashlib.sha256(_canonical(_without_seal(blob))).hexdigest()
    return bool(seal.get("snapshotHash") == expected)


def production_mode(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    if str(env.get("ARGUS_DURABILITY_TEST_MODE", "")).strip() == "1":
        return False
    return str(env.get("RENDER", "")).strip().lower() in (
        "1", "true", "yes") or \
        str(env.get("ARGUS_RUNTIME_ENV", "")).strip().lower() == "production"


def configured_paths(
    environ: Optional[Mapping[str, str]] = None,
        *, production: Optional[bool] = None) -> Dict[str, str]:
    env = os.environ if environ is None else environ
    is_production = production_mode(env) if production is None else production
    root_default = "/var/data" if is_production else tempfile.gettempdir()
    root = os.path.realpath(str(
        env.get("ARGUS_PERSISTENT_ROOT") or root_default))

    def value(name: str, filename: str) -> str:
        return os.path.abspath(str(env.get(name) or os.path.join(root, filename)))

    return {
        "root": root,
        "wal": value("ARGUS_MISSION_WAL_FILE", "argus_mission_tick.wal"),
        "checkpoint": value(
            "ARGUS_OSINT_PERSIST_FILE", "argus_osint_memory.json"),
        "lease": value(
            "ARGUS_MISSION_LEASE_FILE", "argus_mission_tick.lease"),
        "cursor": value(
            "ARGUS_MISSION_CURSOR_FILE", "argus_mission_tick.cursor.json"),
        "receipt": value(
            "ARGUS_MISSION_RECEIPT_FILE", "argus_mission_tick.receipt.json"),
        "tempDirectory": os.path.abspath(str(
            env.get("ARGUS_CHECKPOINT_TEMP_DIR") or root)),
    }


def _under(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False


def _resolve_candidate(path: str) -> str:
    parent = os.path.realpath(os.path.dirname(os.path.abspath(path)) or ".")
    return os.path.join(parent, os.path.basename(path))


def _file_bytes(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _temp_bytes(directory: str, checkpoint_name: str) -> int:
    total = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(checkpoint_name + ".") and \
                        (entry.name.endswith(".tmp") or
                         ".bootstrap-" in entry.name):
                    with contextlib.suppress(OSError):
                        total += entry.stat(follow_symlinks=False).st_size
    except OSError:
        return 0
    return total


def required_free_bytes(*, checkpoint_bytes: int, wal_bytes: int) -> int:
    """Capacity for current + temp + WAL growth + a dynamic safety reserve."""
    checkpoint = max(1, int(checkpoint_bytes))
    wal = max(0, int(wal_bytes))
    safety = max(MINIMUM_SAFETY_RESERVE, checkpoint)
    wal_growth = max(MINIMUM_WAL_ALLOWANCE, wal * 4)
    return checkpoint * 2 + wal_growth + safety


def _fsync_directory(path: str) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_storage(
        paths: Mapping[str, str], *, production: bool,
        disk_usage_fn=shutil.disk_usage,
        approved_root: Optional[str] = None) -> Dict[str, Any]:
    """Probe the runtime mount without exposing durable payload contents."""
    root = os.path.realpath(paths["root"])
    if approved_root is not None and root != os.path.realpath(approved_root):
        raise PersistentStorageError("persistent_root_configuration_drift")
    if not os.path.exists(root):
        raise PersistentStorageError("persistent_root_missing")
    if not os.path.isdir(root):
        raise PersistentStorageError("persistent_root_not_directory")
    if not os.access(root, os.W_OK | os.X_OK):
        raise PersistentStorageError("persistent_root_unwritable")

    resolved: Dict[str, str] = {"root": root}
    for key in ("wal", "checkpoint", "lease", "cursor", "receipt"):
        raw = os.path.abspath(paths[key])
        if production and raw.startswith("/tmp/"):
            raise PersistentStorageError(f"{key}_temporary_path_rejected")
        if os.path.lexists(raw) and os.path.islink(raw):
            raise PersistentStorageError(f"{key}_symlink_rejected")
        candidate = _resolve_candidate(raw)
        if not _under(root, candidate):
            raise PersistentStorageError(f"{key}_outside_persistent_root")
        resolved[key] = candidate

    temp_directory = os.path.realpath(paths["tempDirectory"])
    if not _under(root, temp_directory):
        raise PersistentStorageError("temp_outside_persistent_root")
    if not os.path.isdir(temp_directory):
        raise PersistentStorageError("temp_directory_missing")
    resolved["tempDirectory"] = temp_directory

    root_device = os.stat(root).st_dev
    checkpoint_device = os.stat(
        os.path.dirname(resolved["checkpoint"])).st_dev
    temp_device = os.stat(temp_directory).st_dev
    if root_device != checkpoint_device or checkpoint_device != temp_device:
        raise PersistentStorageError("checkpoint_temp_filesystem_mismatch")

    probe_name = f".argus-storage-probe-{os.getpid()}-{uuid.uuid4().hex}"
    probe = os.path.join(temp_directory, probe_name)
    published = os.path.join(root, probe_name + ".published")
    payload = os.urandom(32)
    try:
        with open(probe, "xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        with open(probe, "rb") as handle:
            if handle.read() != payload:
                raise PersistentStorageError("storage_probe_readback_failed")
        os.replace(probe, published)
        _fsync_directory(root)
        with open(published, "rb") as handle:
            if handle.read() != payload:
                raise PersistentStorageError("atomic_rename_readback_failed")
        os.unlink(published)
        _fsync_directory(root)
    except PersistentStorageError:
        raise
    except PermissionError as exc:
        raise PersistentStorageError("persistent_root_unwritable") from exc
    except OSError as exc:
        raise PersistentStorageError(
            f"storage_durability_probe_failed:{type(exc).__name__}") from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(probe)
        with contextlib.suppress(OSError):
            os.unlink(published)

    checkpoint_bytes = _file_bytes(resolved["checkpoint"])
    wal_bytes = _file_bytes(resolved["wal"])
    checkpoint_temp_bytes = _temp_bytes(
        temp_directory, os.path.basename(resolved["checkpoint"]))
    usage = disk_usage_fn(root)
    required = required_free_bytes(
        checkpoint_bytes=checkpoint_bytes, wal_bytes=wal_bytes)
    if int(usage.free) < required:
        raise PersistentStorageError("persistent_storage_insufficient_space")
    safety_ratio = round(int(usage.free) / required, 3) if required else None
    return {
        "valid": True,
        "errorClass": None,
        "validatedAt": _iso_now(),
        "paths": resolved,
        "sameFilesystem": True,
        "atomicRename": True,
        "fsync": True,
        "totalBytes": int(usage.total),
        "usedBytes": int(usage.used),
        "freeBytes": int(usage.free),
        "requiredFreeBytes": required,
        "checkpointBytes": checkpoint_bytes,
        "walBytes": wal_bytes,
        "checkpointTempBytes": checkpoint_temp_bytes,
        "estimatedSafetyRatio": safety_ratio,
        "warning": "low_free_space" if safety_ratio is not None and
        safety_ratio < 2 else None,
        "lastSuccessfulFsync": _iso_now(),
    }


def atomic_write_json(
        path: str, value: Mapping[str, Any], *,
        temp_directory: Optional[str] = None,
        validator=None, temp_label: str = "tmp") -> Dict[str, Any]:
    final = os.path.abspath(path)
    directory = os.path.realpath(temp_directory or os.path.dirname(final))
    if os.stat(directory).st_dev != os.stat(os.path.dirname(final)).st_dev:
        raise PersistentStorageError("checkpoint_temp_filesystem_mismatch")
    temporary = os.path.join(
        directory,
        f"{os.path.basename(final)}.{os.getpid()}.{uuid.uuid4().hex}.{temp_label}")
    encoded = _canonical(value)
    try:
        with open(temporary, "xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        with open(temporary, "rb") as handle:
            read_back = handle.read()
        parsed = json.loads(read_back.decode("utf-8"))
        if validator is not None and not validator(parsed):
            raise PersistentStorageError("checkpoint_readback_invalid")
        if hashlib.sha256(_canonical(parsed)).digest() != \
                hashlib.sha256(encoded).digest():
            raise PersistentStorageError("checkpoint_readback_hash_mismatch")
        os.replace(temporary, final)
        _fsync_directory(os.path.dirname(final))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    return {
        "path": final,
        "temporaryPath": temporary,
        "bytes": len(encoded),
        "snapshotHash": hashlib.sha256(encoded).hexdigest(),
        "verifiedAt": _iso_now(),
    }


def write_checkpoint(
        path: str, blob: Mapping[str, Any], *,
        temp_directory: Optional[str] = None) -> Dict[str, Any]:
    sealed = seal_checkpoint(blob)
    return atomic_write_json(
        path, sealed, temp_directory=temp_directory,
        validator=lambda value: verify_checkpoint(value, require_seal=True))


def load_checkpoint(path: str, *, require_seal: bool) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        blob = json.load(handle)
    if not verify_checkpoint(blob, require_seal=require_seal):
        raise PersistentStorageError("local_checkpoint_integrity_invalid")
    return blob


def quarantine(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    stamp = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = f"{path}.quarantine-{stamp}-{uuid.uuid4().hex[:8]}"
    os.replace(path, destination)
    _fsync_directory(os.path.dirname(os.path.abspath(path)))
    return destination


def public_diagnostics(
        status: Mapping[str, Any], paths: Mapping[str, str],
        *, production: bool) -> Dict[str, Any]:
    expected_root = os.path.realpath("/var/data") if production else None
    configured_root = os.path.realpath(str(paths.get("root") or ""))
    drift = ([] if not production or configured_root == expected_root else
             ["persistentRoot"])
    return {
        "required": bool(production),
        "valid": bool(status.get("valid")),
        "errorClass": status.get("errorClass"),
        "errorReason": status.get("errorReason"),
        "persistentRoot": paths.get("root"),
        "walPath": paths.get("wal"),
        "checkpointPath": paths.get("checkpoint"),
        "leasePath": paths.get("lease"),
        "cursorPath": paths.get("cursor"),
        "receiptPath": paths.get("receipt"),
        "sameFilesystem": status.get("sameFilesystem"),
        "atomicRename": status.get("atomicRename"),
        "fsync": status.get("fsync"),
        "totalBytes": status.get("totalBytes"),
        "usedBytes": status.get("usedBytes"),
        "freeBytes": status.get("freeBytes"),
        "requiredFreeBytes": status.get("requiredFreeBytes"),
        "checkpointBytes": status.get("checkpointBytes"),
        "walBytes": status.get("walBytes"),
        "checkpointTempBytes": status.get("checkpointTempBytes"),
        "estimatedSafetyRatio": status.get("estimatedSafetyRatio"),
        "warning": status.get("warning"),
        "lastSuccessfulFsync": status.get("lastSuccessfulFsync"),
        "lastCheckpointVerification": status.get(
            "lastCheckpointVerification"),
        "runtimeVerified": bool(status.get("valid")),
        "dashboardDiskAttached": (
            "runtime_path_verified" if status.get("valid") and production
            else "not_proven"),
        "configurationDrift": drift,
        "singleInstanceRuntimeProof": "dashboard_confirmation_required",
    }
