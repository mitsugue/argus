"""Short-lived Checkpoint V2 writer and bounded parent/child contracts.

The production parent persists only a small immutable descriptor.  A fresh
Python interpreter reads the already verified legacy checkpoint, constructs
and validates a candidate V2 generation, writes a bounded result, and exits.
Only the parent may promote the candidate into the active V2 manifest.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import resource
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Callable, Dict, Mapping, Optional

import argus_checkpoint_v2 as v2
import argus_persistent_storage as storage
import argus_tick_durability


UTC = dt.timezone.utc
DESCRIPTOR_SCHEMA = "argus-checkpoint-v2-isolated-job-v1"
RESULT_SCHEMA = "argus-checkpoint-v2-isolated-result-v1"
WRITER_MODE = "isolated_process"
MAXIMUM_CONTRACT_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 15 * 60
TERMINATION_GRACE_SECONDS = 5
MAXIMUM_STDIO_BYTES = 16 * 1024
MAXIMUM_STALE_JOBS = 16
JOB_PREFIX = ".v2-isolated-job-"
GLOBAL_LOCK_NAME = "checkpoint-v2.writer.lock"


class IsolatedWriterError(RuntimeError):
    def __init__(self, classification: str, **details: Any):
        super().__init__(classification)
        self.classification = classification
        self.details = details


def _now() -> str:
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _diagnostic_phase(callback: Optional[Callable[[str, Mapping[str, Any]],
                                                  None]],
                      phase: str, **metadata: Any) -> None:
    """Invoke optional scalar telemetry without affecting writer behavior."""
    if callback is None:
        return
    safe = {
        str(key)[:80]: (value if value is None or isinstance(
            value, (bool, int, float)) else str(value)[:160])
        for key, value in metadata.items()
    }
    try:
        callback(phase, safe)
    except Exception:
        return


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_stats(path: pathlib.Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _stable_file_identity(path: pathlib.Path, *, expected_bytes: int,
                          expected_sha256: str) -> tuple[int, int, int, int]:
    """Hash a regular file between two identical stat observations."""
    if not path.is_file() or path.is_symlink():
        raise IsolatedWriterError("source_missing")
    before = path.stat()
    size, digest = _file_stats(path)
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size,
                       before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size,
                      after.st_mtime_ns)
    if identity_before != identity_after:
        raise IsolatedWriterError("source_changed")
    if size != expected_bytes or digest != expected_sha256:
        raise IsolatedWriterError("source_hash_mismatch")
    return identity_after


def _safe_name(value: str, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 128 or not all(
            character.isalnum() or character in "-_." for character in text):
        raise IsolatedWriterError("descriptor_invalid", field=label)
    return text


def _exact_sequence(mapping: Mapping[str, Any], key: str) -> int:
    """Read an explicit JSON integer sequence; zero is a value, not a default."""
    if key not in mapping:
        raise IsolatedWriterError("WAL_boundary_invalid", field=key,
                                  reason="missing")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IsolatedWriterError("WAL_boundary_invalid", field=key,
                                  reason="not_exact_nonnegative_integer")
    return value


def _validate_wal_contract(path: pathlib.Path, *, lower: int,
                           upper: int) -> Dict[str, Any]:
    """Verify the exact live-WAL interval represented by one checkpoint.

    ``lower`` is inclusive checkpoint coverage (records at or below it may
    have been compacted). ``upper`` is the inclusive generation target.  A
    single ``checkpoint_verified`` receipt at ``upper + 1`` is the only
    permitted post-target record because production compaction writes that
    receipt after the checkpoint has fixed its included sequence.
    """
    try:
        raw_lines = path.read_bytes().splitlines() if path.exists() else []
    except OSError as exc:
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="read_failed") from exc
    state = argus_tick_durability.read_valid_wal(str(path))
    if int(state.get("corruptCount") or 0) != 0:
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="corrupt_record")
    records = []
    try:
        for raw in raw_lines:
            record = json.loads(raw.decode("utf-8"))
            if not isinstance(record, dict):
                raise ValueError("record_not_mapping")
            sequence = record.get("sequence")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or \
                    sequence <= 0:
                raise ValueError("sequence_not_exact_positive_integer")
            records.append(record)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError,
            ValueError) as exc:
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="framing_invalid") from exc
    sequences = [record["sequence"] for record in records]
    if len(sequences) != len(set(sequences)):
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="duplicate_sequence")
    if sequences != sorted(sequences):
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="out_of_order_sequence")
    if any(sequence <= lower for sequence in sequences):
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="compacted_record_retained")

    target_records = [record for record in records
                      if record["sequence"] <= upper]
    expected = list(range(lower + 1, upper + 1))
    if [record["sequence"] for record in target_records] != expected:
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="target_range_incomplete")
    trailing = [record for record in records
                if record["sequence"] > upper]
    if trailing:
        if len(trailing) != 1 or trailing[0]["sequence"] != upper + 1 or \
                trailing[0].get("kind") != "checkpoint_verified":
            raise IsolatedWriterError("WAL_boundary_invalid",
                                      reason="durable_upper_exceeds_target")
        receipt_payload = trailing[0].get("payload")
        if not isinstance(receipt_payload, dict) or \
                _exact_sequence(receipt_payload, "includedWalSequence") != lower:
            raise IsolatedWriterError("WAL_boundary_invalid",
                                      reason="compaction_receipt_mismatch")

    previous = None
    for record in records:
        sequence = record["sequence"]
        if previous is None:
            expected_previous = lower if lower > 0 else None
            if record.get("previousSequence") != expected_previous:
                raise IsolatedWriterError("WAL_boundary_invalid",
                                          reason="chain_anchor_mismatch")
            prior_hash = record.get("previousRecordHash")
            if lower == 0 and prior_hash is not None:
                raise IsolatedWriterError("WAL_boundary_invalid",
                                          reason="genesis_hash_mismatch")
            if lower > 0 and prior_hash is not None and not (
                    isinstance(prior_hash, str) and len(prior_hash) == 64 and
                    all(character in "0123456789abcdef"
                        for character in prior_hash.lower())):
                raise IsolatedWriterError("WAL_boundary_invalid",
                                          reason="chain_anchor_hash_invalid")
        else:
            if record.get("previousSequence") != previous["sequence"] or \
                    record.get("previousRecordHash") != previous.get(
                        "recordHash"):
                raise IsolatedWriterError("WAL_boundary_invalid",
                                          reason="chain_mismatch")
        previous = record

    return {
        "lowerSequence": lower, "targetSequence": upper,
        "reconstructedSequence": upper, "recordCount": len(records),
        "targetRecordCount": len(target_records),
        "postTargetReceiptCount": len(trailing),
        "hashVerified": True, "framingVerified": True,
        "sequenceVerified": True,
    }


def _confined(root: pathlib.Path, candidate: str) -> pathlib.Path:
    resolved = pathlib.Path(candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise IsolatedWriterError("descriptor_path_not_confined") from exc
    return resolved


def _envelope(schema: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    body = dict(payload)
    return {"schemaVersion": schema, "payload": body,
            "payloadSha256": _digest(body)}


def _validate_envelope(value: Any, schema: str) -> bool:
    return bool(isinstance(value, dict) and
                value.get("schemaVersion") == schema and
                isinstance(value.get("payload"), dict) and
                value.get("payloadSha256") == _digest(value["payload"]))


def _read_contract(path: pathlib.Path, schema: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file() or \
            path.stat().st_size > MAXIMUM_CONTRACT_BYTES:
        raise IsolatedWriterError("descriptor_invalid")
    before = path.stat()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IsolatedWriterError("descriptor_invalid") from exc
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != \
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or \
            not _validate_envelope(value, schema):
        raise IsolatedWriterError("descriptor_invalid")
    return dict(value["payload"])


def _write_contract(path: pathlib.Path, schema: str,
                    payload: Mapping[str, Any]) -> Dict[str, Any]:
    envelope = _envelope(schema, payload)
    if len(_canonical(envelope)) > MAXIMUM_CONTRACT_BYTES:
        raise IsolatedWriterError("result_contract_oversized")
    return storage.atomic_write_json(
        str(path), envelope, temp_directory=str(path.parent),
        maximum_bytes=MAXIMUM_CONTRACT_BYTES,
        validator=lambda value: _validate_envelope(value, schema),
        temp_label="v2-contract")


def _rss_bytes() -> Optional[int]:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass
    try:
        raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return raw if sys.platform == "darwin" else raw * 1024
    except (OSError, ValueError):
        return None


def _pss_bytes() -> Optional[int]:
    try:
        with open("/proc/self/smaps_rollup", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return None
    return None


def _fd_count() -> Optional[int]:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def _thread_count() -> int:
    return threading.active_count()


def _process_peak_bytes() -> Optional[int]:
    try:
        raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return raw if sys.platform == "darwin" else raw * 1024
    except (OSError, ValueError):
        return None


def _cgroup_current() -> Optional[int]:
    return v2._cgroup_current_bytes()


def _cgroup_peak() -> Optional[int]:
    return v2._cgroup_peak_bytes()


class _ParentSampler:
    def __init__(self):
        self.maximum_rss = _rss_bytes()
        self.maximum_cgroup = _cgroup_current()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(0.025):
            rss = _rss_bytes()
            cgroup = _cgroup_current()
            if rss is not None:
                self.maximum_rss = max(self.maximum_rss or 0, rss)
            if cgroup is not None:
                self.maximum_cgroup = max(self.maximum_cgroup or 0, cgroup)

    def start(self):
        self._thread.start()

    def finish(self):
        self._stop.set()
        self._thread.join(timeout=1)


def _set_parent_death_signal() -> None:
    """Linux child exits if its launching backend dies."""
    if sys.platform.startswith("linux"):
        try:
            libc = ctypes.CDLL(None)
            libc.prctl(1, signal.SIGTERM, 0, 0, 0)  # PR_SET_PDEATHSIG
        except (AttributeError, OSError):
            pass


def _descriptor_payload(*, persistent_root: pathlib.Path, v2_root: pathlib.Path,
                        job_id: str, source_path: pathlib.Path,
                        source_bytes: int, source_sha256: str,
                        source_generation: str, wal_path: pathlib.Path,
                        wal_lower: int, wal_upper: int, build_sha: str,
                        boot_id: str, mission_window_id: Optional[str],
                        trigger_source: str, formal_soak_state: str,
                        deadline: str) -> Dict[str, Any]:
    return {
        "jobId": job_id, "backendBuildSha": build_sha,
        "backendBootId": boot_id, "missionWindowId": mission_window_id,
        "triggerSource": trigger_source,
        "sourceCheckpoint": {
            "path": str(source_path), "bytes": int(source_bytes),
            "sha256": source_sha256, "generation": source_generation,
        },
        "wal": {"path": str(wal_path), "lowerSequence": int(wal_lower),
                "upperSequence": int(wal_upper)},
        "persistentRoot": str(persistent_root), "v2Root": str(v2_root),
        "outputGenerationId": uuid.uuid4().hex,
        "stagingDirectoryId": job_id, "createdAt": _now(),
        "deadline": deadline, "expectedV2SchemaVersion": v2.SCHEMA,
        "formalSoakState": formal_soak_state,
    }


def _validate_descriptor(payload: Mapping[str, Any], descriptor_path: pathlib.Path,
                         *, check_source: bool = True) -> Dict[str, Any]:
    job_id = _safe_name(payload.get("jobId"), "jobId")
    _safe_name(payload.get("outputGenerationId"), "outputGenerationId")
    if payload.get("expectedV2SchemaVersion") != v2.SCHEMA or \
            payload.get("stagingDirectoryId") != job_id:
        raise IsolatedWriterError("descriptor_invalid")
    # The filesystem location is the authority.  Contract fields must agree
    # with it; they can never widen confinement by naming another root.
    job_root = descriptor_path.parent.resolve()
    v2_root = job_root.parent.resolve()
    persistent_root = v2_root.parent.resolve()
    if pathlib.Path(str(payload.get("persistentRoot") or "")).resolve() != \
            persistent_root or \
            pathlib.Path(str(payload.get("v2Root") or "")).resolve() != v2_root:
        raise IsolatedWriterError("descriptor_path_not_confined")
    job_root = _confined(v2_root, str(job_root))
    expected_job_root = v2_root / f"{JOB_PREFIX}{job_id}"
    if job_root != expected_job_root.resolve():
        raise IsolatedWriterError("descriptor_path_not_confined")
    source = payload.get("sourceCheckpoint") or {}
    wal = payload.get("wal") or {}
    source_path = _confined(persistent_root, str(source.get("path") or ""))
    wal_path = _confined(persistent_root, str(wal.get("path") or ""))
    if not isinstance(wal, dict):
        raise IsolatedWriterError("WAL_boundary_invalid", field="wal")
    lower = _exact_sequence(wal, "lowerSequence")
    upper = _exact_sequence(wal, "upperSequence")
    if lower < 0 or upper < lower:
        raise IsolatedWriterError("WAL_boundary_invalid")
    try:
        deadline = dt.datetime.fromisoformat(
            str(payload.get("deadline")).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IsolatedWriterError("descriptor_invalid") from exc
    if deadline <= dt.datetime.now(UTC):
        raise IsolatedWriterError("descriptor_stale")
    if check_source:
        source_identity = _stable_file_identity(
            source_path, expected_bytes=int(source.get("bytes") or -1),
            expected_sha256=str(source.get("sha256") or ""))
    else:
        source_identity = None
    return {"jobRoot": job_root, "v2Root": v2_root,
            "persistentRoot": persistent_root, "sourcePath": source_path,
            "walPath": wal_path, "walLower": lower, "walUpper": upper,
            "sourceIdentity": source_identity}


def _child_result(payload: Mapping[str, Any], *, state: str,
                  classification: Optional[str], started: float,
                  **values: Any) -> Dict[str, Any]:
    return {
        "jobId": payload.get("jobId"),
        "generationId": payload.get("outputGenerationId"),
        "backendBuildSha": payload.get("backendBuildSha"),
        "backendBootId": payload.get("backendBootId"),
        "missionWindowId": payload.get("missionWindowId"),
        "sourceGeneration": (payload.get("sourceCheckpoint") or {}).get(
            "generation"),
        "sourceSha256": (payload.get("sourceCheckpoint") or {}).get("sha256"),
        "walUpperSequence": (payload.get("wal") or {}).get("upperSequence"),
        "writerMode": WRITER_MODE, "state": state,
        "classification": classification,
        "durationMs": round((time.monotonic() - started) * 1000, 3),
        "childProcessId": os.getpid(), "childPeakRssBytes": _process_peak_bytes(),
        "childRssBeforeExitBytes": _rss_bytes(), **values,
    }


def run_child(descriptor_path: str, *, fault: Optional[str] = None,
              expected_build_sha: Optional[str] = None,
              expected_boot_id: Optional[str] = None) -> int:
    """Child entry point.  It never writes the active production manifest."""
    _set_parent_death_signal()
    started = time.monotonic()
    path = pathlib.Path(descriptor_path).resolve()
    payload: Dict[str, Any] = {}
    result_path = path.parent / "result.json"
    try:
        payload = _read_contract(path, DESCRIPTOR_SCHEMA)
        if (expected_build_sha is not None and
                payload.get("backendBuildSha") != expected_build_sha) or \
                (expected_boot_id is not None and
                 payload.get("backendBootId") != expected_boot_id):
            raise IsolatedWriterError("descriptor_identity_mismatch")
        checked = _validate_descriptor(payload, path)
        source_path = checked["sourcePath"]
        before_identity = checked["sourceIdentity"]
        if fault == "source_sigterm":
            os.kill(os.getpid(), signal.SIGTERM)
        if fault == "source_pause":
            (checked["jobRoot"] / "source-validated.marker").write_bytes(b"1")
            time.sleep(2)
        wal_validation = _validate_wal_contract(
            checked["walPath"], lower=checked["walLower"],
            upper=checked["walUpper"])
        snapshot = storage.load_checkpoint(
            str(source_path), require_seal=True, allow_legacy_file_seal=True)
        durability = snapshot.get("missionTickDurability")
        if not isinstance(durability, dict):
            raise IsolatedWriterError("WAL_boundary_invalid",
                                      reason="source_cursor_missing")
        snapshot_wal = _exact_sequence(durability, "walAppliedSequence")
        if snapshot_wal != checked["walUpper"]:
            raise IsolatedWriterError("WAL_boundary_invalid")
        after_load = source_path.stat()
        if before_identity != \
                (after_load.st_dev, after_load.st_ino, after_load.st_size,
                 after_load.st_mtime_ns):
            raise IsolatedWriterError("source_changed")
        if fault == "serialization_sigkill":
            os.kill(os.getpid(), signal.SIGKILL)
        candidate_root = checked["jobRoot"] / "candidate"
        candidate_root.mkdir(mode=0o700)
        fault_after = ({"transaction_kill": "segment",
                        "post_transaction_kill": "transaction"}.get(fault))
        written = v2.write_generation(
            str(candidate_root), snapshot,
            source_generation=str((payload.get("sourceCheckpoint") or {}).get(
                "generation") or ""),
            generation_id=str(payload["outputGenerationId"]),
            consume_snapshot=True,
            fault_after=fault_after,
            validation_context={
                "triggerSource": payload.get("triggerSource"),
                "missionWindowId": payload.get("missionWindowId"),
                "natural": payload.get("triggerSource") == "ec2_systemd",
                "formalSoakState": payload.get("formalSoakState"),
                "legacyCheckpointPath": str(source_path),
                "legacyTempDirectory": str(checked["persistentRoot"]),
            })
        # Full reconstruction and row/hash verification occurs only in child.
        verified = v2.restore_generation(str(candidate_root))
        del verified["snapshot"]
        if verified.get("generationId") != payload.get("outputGenerationId"):
            raise IsolatedWriterError("validation_failed")
        manifest_path = candidate_root / v2.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["candidateOnly"] = True
        manifest["stage1Validation"]["manifestPromoted"] = False
        storage.atomic_write_json(
            str(manifest_path), manifest, temp_directory=str(candidate_root),
            maximum_bytes=1024 * 1024)
        database_path = candidate_root / \
            f"v2-generation-{payload['outputGenerationId']}" / v2.DATABASE_NAME
        database_bytes, database_hash = _file_stats(database_path)
        manifest_bytes, manifest_hash = _file_stats(manifest_path)
        if fault == "post_result_pause":
            time.sleep(60)
        result = _child_result(
            payload, state="verified_candidate", classification=None,
            started=started, databaseBytes=database_bytes,
            generationSha256=database_hash, candidateManifestBytes=manifest_bytes,
            candidateManifestSha256=manifest_hash,
            sectionCount=int(written.get("sectionCount") or 0),
            rowCount=int((written.get("resourceTelemetry") or {}).get(
                "rowCount") or 0),
            diskFreeBeforeBytes=(written.get("resourceTelemetry") or {}).get(
                "diskFreeBeforeBytes"),
            diskFreeAfterBytes=(written.get("resourceTelemetry") or {}).get(
                "diskFreeAfterBytes"),
            walLowerSequence=checked["walLower"],
            walTargetSequence=checked["walUpper"],
            walReconstructedSequence=wal_validation[
                "reconstructedSequence"],
            walRecordCount=wal_validation["recordCount"],
            walHashVerified=wal_validation["hashVerified"],
            walFramingVerified=wal_validation["framingVerified"],
            walSequenceVerified=wal_validation["sequenceVerified"],
            validationVerified=True,
            childResourceTelemetry=written.get("resourceTelemetry") or {})
        _write_contract(result_path, RESULT_SCHEMA, result)
        return 0
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        classification = (exc.classification if isinstance(
            exc, (IsolatedWriterError, v2.CheckpointV2Error)) else {
                storage.PersistentStorageError: "source_integrity_invalid",
                MemoryError: "child_oom",
            }.get(type(exc), "serialization_failed"))
        if payload:
            with contextlib.suppress(Exception):
                _write_contract(result_path, RESULT_SCHEMA, _child_result(
                    payload, state="failed", classification=classification,
                    started=started, validationVerified=False))
        return 2


def _verify_candidate(job_root: pathlib.Path, result: Mapping[str, Any],
                      payload: Mapping[str, Any]) -> Dict[str, Any]:
    generation_id = _safe_name(result.get("generationId"), "generationId")
    candidate_root = job_root / "candidate"
    manifest_path = candidate_root / v2.MANIFEST_NAME
    generation = candidate_root / f"v2-generation-{generation_id}"
    database = generation / v2.DATABASE_NAME
    if generation.is_symlink() or database.is_symlink() or \
            not generation.is_dir() or not database.is_file():
        raise IsolatedWriterError("candidate_missing")
    database_bytes, database_hash = _file_stats(database)
    manifest_bytes, manifest_hash = _file_stats(manifest_path)
    if database_bytes != int(result.get("databaseBytes") or -1) or \
            database_hash != result.get("generationSha256") or \
            manifest_bytes != int(result.get("candidateManifestBytes") or -1) or \
            manifest_hash != result.get("candidateManifestSha256"):
        raise IsolatedWriterError("output_hash_mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("generationId") != generation_id or \
            manifest.get("sourceGeneration") != result.get("sourceGeneration") or \
            manifest.get("candidateOnly") is not True:
        raise IsolatedWriterError("result_identity_mismatch")
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise IsolatedWriterError("validation_failed")
    finally:
        connection.close()
    return {"manifest": manifest, "generation": generation,
            "databaseBytes": database_bytes}


def _promote(root: pathlib.Path, job_root: pathlib.Path,
             payload: Mapping[str, Any], result: Mapping[str, Any],
             parent_telemetry: Mapping[str, Any]) -> Dict[str, Any]:
    checked = _verify_candidate(job_root, result, payload)
    generation_id = str(result["generationId"])
    final = root / f"v2-generation-{generation_id}"
    manifest_path = root / v2.MANIFEST_NAME
    if final.exists():
        # An identical successful reconciliation is idempotent.
        if _file_stats(final / v2.DATABASE_NAME)[1] != result.get(
                "generationSha256"):
            raise IsolatedWriterError("generation_identity_collision")
    else:
        os.replace(checked["generation"], final)
        v2._fsync_directory(str(root))
    manifest = checked["manifest"]
    manifest.pop("candidateOnly", None)
    provenance = manifest.get("stage1Validation") or {}
    provenance.update({
        "manifestPromoted": True, "writerMode": WRITER_MODE,
        "childProcessId": result.get("childProcessId"),
        "childPeakRssBytes": result.get("childPeakRssBytes"),
        "childDurationMs": result.get("durationMs"),
        "childExitClassification": result.get("classification") or "success",
        "walLowerSequence": result.get("walLowerSequence"),
        "walTargetSequence": result.get("walTargetSequence"),
        "walReconstructedSequence": result.get("walReconstructedSequence"),
        "walHashVerified": result.get("walHashVerified"),
        "walFramingVerified": result.get("walFramingVerified"),
        "walSequenceVerified": result.get("walSequenceVerified"),
        "resourceTelemetry": dict(parent_telemetry),
    })
    manifest["stage1Validation"] = provenance
    manifest["generationHistory"] = (
        v2._prior_generation_history(root) + [provenance])[-v2.MAXIMUM_GENERATIONS:]
    manifest_write = storage.atomic_write_json(
        str(manifest_path), manifest, temp_directory=str(root),
        maximum_bytes=1024 * 1024)
    v2._prune_generations(root, (generation_id,))
    disk = v2.disk_budget_status(str(root))
    return {
        "verified": True, "state": "verified", "generationId": generation_id,
        "createdAt": manifest.get("createdAt"), "databaseBytes":
            checked["databaseBytes"],
        "sourceSerializedBytes": manifest.get("sourceSerializedBytes"),
        "sectionCount": len(manifest.get("sections") or {}),
        "validation": provenance, "manifestWrite": manifest_write,
        "resourceTelemetry": dict(parent_telemetry),
        "writerMode": WRITER_MODE, "diskBudgetAfter": disk,
    }


def _remove_job(path: pathlib.Path) -> None:
    """Delete only tightly shaped V2 job artifacts."""
    if path.is_symlink() or not path.is_dir() or \
            not path.name.startswith(JOB_PREFIX):
        raise IsolatedWriterError("orphan_shape_rejected")
    for current_root, directories, files in os.walk(path, topdown=False):
        current = pathlib.Path(current_root)
        for name in files:
            target = current / name
            if target.is_symlink() or not target.is_file():
                raise IsolatedWriterError("orphan_shape_rejected")
            target.unlink()
        for name in directories:
            target = current / name
            if target.is_symlink() or not target.is_dir():
                raise IsolatedWriterError("orphan_shape_rejected")
            target.rmdir()
    path.rmdir()


def reconcile_stale_jobs(root: str) -> Dict[str, Any]:
    root_path = pathlib.Path(root).resolve()
    candidates = sorted(
        (path for path in root_path.glob(f"{JOB_PREFIX}*")
         if path.is_dir() and not path.is_symlink()),
        key=lambda path: path.stat().st_mtime_ns)
    if len(candidates) > MAXIMUM_STALE_JOBS:
        raise IsolatedWriterError("isolated_writer_orphan_limit_exceeded",
                                  detectedCount=len(candidates))
    removed = malformed = 0
    for path in candidates:
        try:
            _remove_job(path)
            removed += 1
        except (OSError, IsolatedWriterError):
            malformed += 1
    if malformed:
        raise IsolatedWriterError("isolated_writer_orphan_malformed",
                                  malformedCount=malformed)
    return {"detectedCount": len(candidates), "removedCount": removed,
            "malformedCount": malformed}


def launch_isolated_generation(root: str, *, source_path: str,
                               legacy_checkpoint: Mapping[str, Any],
                               wal_path: str, wal_upper_sequence: int,
                               backend_build_sha: str, backend_boot_id: str,
                               mission_window_id: Optional[str],
                               trigger_source: str,
                               formal_soak_state: str = "not_started",
                               timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
                               fault: Optional[str] = None,
                               diagnostic_callback: Optional[
                                   Callable[[str, Mapping[str, Any]], None]] =
                               None) -> Dict[str, Any]:
    """Run exactly one fresh child and promote only its verified candidate."""
    started = time.monotonic()
    root_path = pathlib.Path(root).resolve()
    persistent_root = root_path.parent.resolve()
    source = _confined(persistent_root, source_path)
    wal = _confined(persistent_root, wal_path)
    root_path.mkdir(parents=True, exist_ok=True)
    source_bytes, source_hash = _file_stats(source)
    if source_bytes != int(legacy_checkpoint.get("snapshotBytes") or -1) or \
            source_hash != legacy_checkpoint.get("snapshotHash"):
        raise IsolatedWriterError("source_hash_mismatch")
    included_sequence = _exact_sequence(
        legacy_checkpoint, "includedWalSequence")
    if isinstance(wal_upper_sequence, bool) or not isinstance(
            wal_upper_sequence, int) or wal_upper_sequence < 0 or \
            included_sequence != wal_upper_sequence:
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="checkpoint_target_mismatch")
    source_generation = str(legacy_checkpoint.get("snapshotHash") or "")
    wal_compaction = legacy_checkpoint.get("walCompaction")
    if not isinstance(wal_compaction, dict):
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="compaction_boundary_missing")
    wal_lower = _exact_sequence(wal_compaction, "compactedThrough")
    if wal_lower > included_sequence:
        raise IsolatedWriterError("WAL_boundary_invalid",
                                  reason="compaction_exceeds_target")
    job_id = uuid.uuid4().hex
    job_root = root_path / f"{JOB_PREFIX}{job_id}"
    descriptor_path = job_root / "descriptor.json"
    result_path = job_root / "result.json"
    lock = open(root_path / GLOBAL_LOCK_NAME, "a+b")
    sampler = _ParentSampler()
    parent_before = {"rss": _rss_bytes(), "pss": _pss_bytes(),
                     "fds": _fd_count(), "threads": _thread_count(),
                     "cgroup": _cgroup_current(), "cgroupPeak": _cgroup_peak()}
    try:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IsolatedWriterError("writer_lock_failed") from exc
        reconciliation = reconcile_stale_jobs(str(root_path))
        disk_before = v2._preflight_disk_budget(
            root_path, maximum_total_bytes=v2.MAXIMUM_TOTAL_BYTES,
            disk_usage_fn=__import__("shutil").disk_usage,
            minimum_free_space_reserve=v2.MINIMUM_FREE_SPACE_RESERVE)
        job_root.mkdir(mode=0o700)
        deadline = (dt.datetime.now(UTC) + dt.timedelta(
            seconds=max(1, int(timeout_seconds)))).isoformat().replace(
                "+00:00", "Z")
        payload = _descriptor_payload(
            persistent_root=persistent_root, v2_root=root_path, job_id=job_id,
            source_path=source, source_bytes=source_bytes,
            source_sha256=source_hash, source_generation=source_generation,
            wal_path=wal, wal_lower=wal_lower,
            wal_upper=int(wal_upper_sequence), build_sha=backend_build_sha,
            boot_id=backend_boot_id, mission_window_id=mission_window_id,
            trigger_source=trigger_source, formal_soak_state=formal_soak_state,
            deadline=deadline)
        _write_contract(descriptor_path, DESCRIPTOR_SCHEMA, payload)
        _diagnostic_phase(
            diagnostic_callback, "T6", generationAttempted=True,
            missionWindowId=mission_window_id, triggerSource=trigger_source)
        command = [sys.executable, "-m", "argus_checkpoint_v2_isolated",
                   "--job", str(descriptor_path),
                   "--expected-build-sha", backend_build_sha,
                   "--expected-boot-id", backend_boot_id]
        if fault:
            command.extend(["--fault", fault])
        try:
            process = subprocess.Popen(
                command, cwd=str(pathlib.Path(__file__).resolve().parent),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, text=False)
        except OSError as exc:
            raise IsolatedWriterError("child_spawn_failed") from exc
        sampler.start()
        _diagnostic_phase(
            diagnostic_callback, "T7", childActive=True,
            childProcessId=process.pid)
        classification = None
        try:
            stdout, stderr = process.communicate(timeout=max(1, timeout_seconds))
        except subprocess.TimeoutExpired:
            classification = "timeout"
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(
                    timeout=TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
        finally:
            sampler.finish()
        _diagnostic_phase(
            diagnostic_callback, "T7", childActive=False,
            sampledParentPeakRssBytes=sampler.maximum_rss,
            sampledCgroupPeakBytes=sampler.maximum_cgroup)
        _diagnostic_phase(
            diagnostic_callback, "T8", childExitCode=process.returncode,
            childReaped=process.poll() is not None)
        stdout = (stdout or b"")[-MAXIMUM_STDIO_BYTES:]
        stderr = (stderr or b"")[-MAXIMUM_STDIO_BYTES:]
        if classification:
            raise IsolatedWriterError(classification,
                                      childExitCode=process.returncode)
        if process.returncode != 0:
            if process.returncode < 0:
                sig = -process.returncode
                classification = ("child_oom" if sig == signal.SIGKILL
                                  else "child_signal")
            elif result_path.exists():
                failure = _read_contract(result_path, RESULT_SCHEMA)
                classification = str(failure.get("classification") or
                                     "child_failed")
            else:
                classification = "child_failed"
            raise IsolatedWriterError(classification,
                                      childExitCode=process.returncode)
        if stdout.strip() or stderr.strip() or not result_path.exists():
            raise IsolatedWriterError("child_stdio_or_result_invalid")
        result = _read_contract(result_path, RESULT_SCHEMA)
        expected = {
            "jobId": job_id, "generationId": payload["outputGenerationId"],
            "backendBuildSha": backend_build_sha,
            "backendBootId": backend_boot_id,
            "missionWindowId": mission_window_id,
            "sourceGeneration": source_generation,
            "sourceSha256": source_hash,
            "walUpperSequence": int(wal_upper_sequence),
            "walLowerSequence": wal_lower,
            "walTargetSequence": included_sequence,
            "walReconstructedSequence": included_sequence,
            "walHashVerified": True,
            "walFramingVerified": True,
            "walSequenceVerified": True,
        }
        if result.get("state") != "verified_candidate" or \
                result.get("validationVerified") is not True or any(
                    result.get(key) != value for key, value in expected.items()):
            raise IsolatedWriterError("result_identity_mismatch")
        # Re-check immutable source immediately before promotion.
        current_bytes, current_hash = _file_stats(source)
        if current_bytes != source_bytes or current_hash != source_hash:
            raise IsolatedWriterError("source_changed")
        _diagnostic_phase(
            diagnostic_callback, "T9", parentValidationVerified=True,
            generationId=result.get("generationId"),
            childPeakRssBytes=result.get("childPeakRssBytes"),
            childDurationMs=result.get("durationMs"))
        # A short bounded quiet point makes the post-child reading explicit;
        # it is not an unbounded allocator-reclaim wait.
        time.sleep(0.05)
        parent_after = {"rss": _rss_bytes(), "pss": _pss_bytes(),
                        "fds": _fd_count(), "threads": _thread_count(),
                        "cgroup": _cgroup_current(), "cgroupPeak": _cgroup_peak()}
        child = result.get("childResourceTelemetry") or {}
        telemetry = {
            "success": True, "writerMode": WRITER_MODE,
            "processRssBeforeBytes": parent_before["rss"],
            "processRssPeakBytes": sampler.maximum_rss,
            "processRssAfterBytes": parent_after["rss"],
            "parentQuietRssBytes": parent_after["rss"],
            "processRssDeltaBytes": (
                parent_after["rss"] - parent_before["rss"]
                if parent_after["rss"] is not None and
                parent_before["rss"] is not None else None),
            "parentPssBeforeBytes": parent_before["pss"],
            "parentPssAfterBytes": parent_after["pss"],
            "parentFdBefore": parent_before["fds"],
            "parentFdAfter": parent_after["fds"],
            "parentThreadBefore": parent_before["threads"],
            "parentThreadAfter": parent_after["threads"],
            "childPeakRssBytes": result.get("childPeakRssBytes"),
            "childDurationMs": result.get("durationMs"),
            "childExitCode": process.returncode,
            "childExitClassification": "success",
            "cgroupMemoryBeforeBytes": parent_before["cgroup"],
            # memory.peak is lifetime-cumulative for the cgroup.  Keep it
            # separate from the per-generation sampled current maximum.
            "cgroupMemoryPeakBytes": sampler.maximum_cgroup,
            "cgroupMemoryLifetimePeakBytes": parent_after["cgroupPeak"],
            "cgroupMemoryAfterBytes": parent_after["cgroup"],
            "generationBytes": result.get("databaseBytes"),
            "generationRowCount": result.get("rowCount"),
            "generationSectionCount": result.get("sectionCount"),
            "generationDurationMs": result.get("durationMs"),
            "diskFreeBeforeBytes": disk_before.get("freeBytes"),
            "diskFreeAfterBytes": child.get("diskFreeAfterBytes"),
            "pendingGenerationCount": 0, "newLegacyTempCount": 0,
            "staleJobReconciliation": reconciliation,
        }
        promoted = _promote(root_path, job_root, payload, result, telemetry)
        _remove_job(job_root)
        _diagnostic_phase(
            diagnostic_callback, "T10", promotionVerified=True,
            pruningComplete=True,
            generationId=promoted.get("generationId"),
            retainedGenerationCount=(promoted.get("resourceTelemetry") or {})
            .get("retainedGenerationCount"),
            pendingGenerationCount=(promoted.get("resourceTelemetry") or {})
            .get("pendingGenerationCount"))
        return promoted
    except IsolatedWriterError as exc:
        exc.details.setdefault("writerMode", WRITER_MODE)
        exc.details.setdefault("durationMs", round(
            (time.monotonic() - started) * 1000, 3))
        raise
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def public_telemetry(status: Mapping[str, Any]) -> Dict[str, Any]:
    telemetry = status.get("resourceTelemetry") or {}
    return {
        "writerMode": WRITER_MODE,
        "jobState": status.get("state"),
        "generationId": status.get("generationId"),
        "parentRssBeforeBytes": telemetry.get("processRssBeforeBytes"),
        "parentRssAfterBytes": telemetry.get("processRssAfterBytes"),
        "parentQuietRssBytes": telemetry.get("parentQuietRssBytes"),
        "childPeakRssBytes": telemetry.get("childPeakRssBytes"),
        "childDurationMs": telemetry.get("childDurationMs"),
        "childExitClassification": telemetry.get("childExitClassification"),
        "totalCgroupPeakBytes": telemetry.get("cgroupMemoryPeakBytes"),
        "pendingGenerationCount": telemetry.get("pendingGenerationCount"),
        "retainedGenerationCount": (
            status.get("diskBudgetAfter") or {}).get("retainedGenerationCount"),
        "lastSuccess": status.get("createdAt") if status.get("verified") else None,
        "lastFailure": status.get("lastErrorClass"),
        "acceptanceBlocker": status.get("lastErrorClass"),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--fault")
    parser.add_argument("--expected-build-sha")
    parser.add_argument("--expected-boot-id")
    args = parser.parse_args(argv)
    return run_child(
        args.job, fault=args.fault,
        expected_build_sha=args.expected_build_sha,
        expected_boot_id=args.expected_boot_id)


if __name__ == "__main__":
    raise SystemExit(main())
