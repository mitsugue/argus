#!/usr/bin/env python3
"""Exact-cgroup proof for the configured encrypted-recovery producer.

The probe creates only synthetic local state under one temporary directory.
It exercises the real verified-checkpoint, encrypted sidecar, read-back and
WAL-compaction lifecycle.  Key material and per-cycle cryptographic values are
generated inside this process, retained only long enough to verify each pair,
and never included in the scalar report.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import resource
import secrets
import sys
import tempfile
import types
from typing import Any, Dict
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_persistent_storage as storage
import argus_remote_journal as journal
import argus_remote_recovery as recovery
import argus_state_journal
import argus_tick_durability as durability


# The resource fixture never contacts a quote provider.  Avoid provider SDK
# startup side effects (including host log files) while retaining scanner's
# real persistence and recovery implementation.
_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules["moomoo"] = _moomoo
import scanner


GIB = 1024 * 1024 * 1024
REQUIRED_CYCLES = 8
EXACT_4_GIB = 4 * GIB
BUILD_SHA = "a" * 40
LEDGER_BASE = "b" * 40
AT = "2026-08-13T01:02:03Z"
CURRENT_ID = "resource-current-v1"
PREVIOUS_ID = "resource-previous-v1"
KEY_ENVIRONMENT_NAMES = (
    "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID",
    "ARGUS_REMOTE_RECOVERY_CURRENT_KEY",
    "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID",
    "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY",
    "RENDER_GIT_COMMIT",
)
REPORT_FIELDS = {
    "schemaVersion", "processTopology", "cycles",
    "verifiedCycleCount", "walCompactionCount", "uniqueNonceCount",
    "uniqueKeyDerivationSaltCount",
    "fixedEncryptedBodyBytes", "maximumSidecarBytes",
    "targetCoverageCount", "opsJournalCount", "opsJournalMetaCount",
    "opsJournalCompactedCount", "opsSequenceCount", "missionsCount",
    "missionWindowsCount", "forecastsCount", "outcomesCount",
    "incidentsCount", "postmortemsCount", "periodicReportsCount",
    "challengerRunsCount", "agentQueueCount", "soakFieldCount",
    "processPeakRssBytes", "cgroupObservedPeakBytes",
    "cgroupSampledPeakBytes", "cgroupMaxBytes", "oomDelta",
    "oomKillDelta", "temporaryRootRemoved", "abnormalExitCount",
    "passed",
}


def _encoded_key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _read_scalar(path: pathlib.Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
        return None if text == "max" else int(text)
    except (FileNotFoundError, PermissionError, OSError, UnicodeError,
            ValueError):
        return None


def _memory_events() -> Dict[str, int | None]:
    values: Dict[str, int] = {}
    try:
        lines = pathlib.Path("/sys/fs/cgroup/memory.events").read_text(
            encoding="ascii").splitlines()
    except (FileNotFoundError, PermissionError, OSError, UnicodeError):
        lines = []
    for line in lines:
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            values[fields[0]] = int(fields[1])
        except ValueError:
            continue
    return {"oom": values.get("oom"), "oomKill": values.get("oom_kill")}


def _event_delta(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return after - before


def _peak_rss_bytes() -> int | None:
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (OSError, TypeError, ValueError, OverflowError):
        return None


def _configure_temporary_root(root: pathlib.Path) -> Dict[str, str]:
    paths = storage.configured_paths(
        {"ARGUS_PERSISTENT_ROOT": str(root)}, production=False)
    scanner._DURABILITY_PRODUCTION = False
    scanner._DURABILITY_PATHS = paths
    scanner._OSINT_PERSIST_FILE = paths["checkpoint"]
    scanner._MISSION_WAL_FILE = paths["wal"]
    scanner._MISSION_LEASE_FILE = paths["lease"]
    scanner._MISSION_CURSOR_FILE = paths["cursor"]
    scanner._MISSION_RECEIPT_FILE = paths["receipt"]
    scanner._REMOTE_RECEIPT_QUEUE_FILE = paths["receiptQueue"]
    scanner._REMOTE_RECOVERY_FILE = paths["recovery"]
    scanner._CHECKPOINT_V2_ROOT = str(root / "argus_checkpoint_v2")
    scanner._CHECKPOINT_V2_STAGE1_ENABLED = False
    scanner._CHECKPOINT_V2_STATUS = {
        "schemaVersion": scanner.argus_checkpoint_v2.SCHEMA,
        "state": "disabled",
    }
    scanner._DURABLE_STORAGE_STATUS.update({
        "valid": True, "errorClass": None, "errorReason": None,
        "runtimeVerified": True,
    })
    scanner._DURABLE_STATE.clear()
    scanner._DURABLE_STATE.update({
        "schemaVersion": "argus-durable-v3",
        "lastWriteAt": None, "lastRestoreAt": None,
        "integrityStatus": "unknown", "lastKnownGoodAt": None,
        "restoreSource": None,
    })
    return paths


def _activate_clean_legacy_nonce_authority(paths: Dict[str, str]) -> None:
    """Exercise the production genesis proof against synthetic Git evidence."""
    storage.write_checkpoint(
        paths["checkpoint"], {"schemaVersion": "argus-durable-v3"},
        temp_directory=paths["tempDirectory"])
    checkpoint = storage.load_checkpoint(
        paths["checkpoint"], require_seal=True)
    pinned = {
        "base": (
            "https://raw.githubusercontent.com/owner/repository/" +
            BUILD_SHA + "/ledger"),
        "commitSha": BUILD_SHA,
        "owner": "owner",
        "repository": "repository",
        "pathPrefix": "ledger",
    }
    # The resource job has no live network.  Replace only the two immutable
    # Git evidence boundaries; checkpoint sealing, reread/identity checks,
    # capability mint/consume, locking and nonce-authority creation remain the
    # production implementation.
    with mock.patch.object(
            scanner, "_probe_pinned_remote_recovery_nonce_floor",
            return_value=None), mock.patch.object(
            scanner, "_pinned_recovery_path_never_existed",
            return_value=True):
        result = scanner._prepare_keyed_local_recovery_nonce_boot(
            checkpoint, recovery.configured_keys(), pinned)
    if result.get("status") != "activated_genesis":
        raise RuntimeError("resource_nonce_genesis_activation_failed")


def _synthetic_event(index: int) -> Dict[str, Any]:
    event = argus_state_journal.event(
        event_type="mission_completed", aggregate_type="mission",
        aggregate_id=f"resource-{index:04d}", sequence=index + 1,
        occurred_at=AT, payload={"missionType": "ordinary"})
    if event is None:
        raise RuntimeError("resource_event_construction_failed")
    return event


def _seed_maximum_targets() -> None:
    events = [_synthetic_event(index)
              for index in range(recovery.LIST_LIMITS["opsJournal"])]
    sequences = {
        f"mission:resource-{index:04d}": index + 1
        for index in range(len(events))
    }
    limit = journal.OPS_SEQUENCE_BY_AGGREGATE_LIMIT
    for index in range(len(sequences), limit):
        sequences[f"archive:{index:04d}"] = index + 1
    meta = {
        "totalObserved": len(events),
        journal.OPS_SEQUENCE_HIGH_WATER_FIELD: limit,
    }
    bounded, bounded_meta = journal.bounded_sequence_allocator_state(
        sequences=sequences, events=events, meta=meta)
    if bounded != sequences or bounded_meta != meta:
        raise RuntimeError("resource_allocator_shape_invalid")

    scanner._OPS_JOURNAL[:] = events
    scanner._OPS_JOURNAL_META.clear()
    scanner._OPS_JOURNAL_META.update(meta)
    scanner._OPS_JOURNAL_COMPACT[:] = [
        {"batch": index} for index in range(
            recovery.LIST_LIMITS["opsJournalCompacted"])]
    scanner._OPS_SEQ.clear()
    scanner._OPS_SEQ.update(sequences)
    scanner._MISSIONS[:] = [
        {"missionId": f"mission-{index:03d}"} for index in range(
            recovery.LIST_LIMITS["missions"])]
    scanner._MISSION_WINDOWS[:] = [
        {"missionWindowId": f"window-{index:03d}"} for index in range(
            recovery.LIST_LIMITS["missionWindows"])]
    scanner._FORECAST_LEDGER[:] = [
        {"id": f"forecast-{index:03d}"} for index in range(
            recovery.LIST_LIMITS["forecasts"])]
    outcomes = []
    for index in range(recovery.LIST_LIMITS["outcomes"]):
        outcome = {"id": f"outcome-{index:03d}", "status": "resolved"}
        outcome["integrityHash"] = journal._h(outcome)
        outcomes.append(outcome)
    scanner._OUTCOME_LEDGER[:] = outcomes
    scanner._INCIDENTS[:] = [
        {"incidentId": f"incident-{index:02d}"} for index in range(
            recovery.LIST_LIMITS["incidents"])]
    scanner._POSTMORTEMS[:] = [
        {"postmortemId": f"postmortem-{index:02d}"} for index in range(
            recovery.LIST_LIMITS["postmortems"])]
    scanner._PERIODIC_REPORTS[:] = [
        {"reportId": f"report-{index:02d}"} for index in range(
            recovery.LIST_LIMITS["periodicReports"])]
    scanner._CHALLENGER_RUNS[:] = [
        {"runId": f"run-{index:02d}"} for index in range(
            recovery.LIST_LIMITS["challengerRuns"])]
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._OSINT_AGENT_QUEUE.update({
        f"QUEUE{index:02d}": {"mode": "deep"}
        for index in range(recovery.DICT_LIMITS["agentQueue"])
    })
    scanner._SOAK.clear()
    scanner._SOAK.update({
        f"field{index:02d}": index
        for index in range(recovery.DICT_LIMITS["soak"])
    })
    scanner._MISSION_BATCH_STATE.clear()
    scanner._MISSION_BATCH_STATE.update({
        "schemaVersion": "argus-mission-batch-v1",
        "cursor": 0,
        "remainingCount": 0,
        "lastJobId": "resource-probe",
        "lastResult": "completed",
        "lastCompletedAt": AT,
        "walAppliedSequence": 0,
    })


def _install_verified_remote_receipt(paths: Dict[str, str], sequence: int) -> None:
    proof = f"{sequence:016x}"
    scanner._REMOTE_CYCLE.clear()
    scanner._REMOTE_CYCLE.update({
        "remoteCommitSha": LEDGER_BASE,
        "receiptCommitSha": LEDGER_BASE,
        "committedAt": AT,
        "readBackAt": AT,
        "readBackVerified": True,
        "walReadBackVerified": True,
        "expectedHash": proof,
        "actualHash": proof,
        "remoteWalAppliedSequence": sequence,
        "verifiedWalSequence": sequence,
        "compactReceiptHash": proof,
        "errorClass": None,
        "walErrorClass": None,
        "remoteDurabilityState": "verified",
        "receiptCreatedAt": AT,
        "receiptVerifiedAt": AT,
        "receiptAgeSeconds": 0,
        "receiptAttempts": 1,
        "receiptErrorClass": None,
    })
    result = scanner._persist_remote_wal_receipt(saved_at=AT)
    if result.get("readBackVerified") is not True or not \
            durability.verify_remote_receipt(json.loads(
                pathlib.Path(paths["receipt"]).read_text(encoding="utf-8"))):
        raise RuntimeError("resource_receipt_write_failed")


def _shape(payload: Dict[str, Any]) -> Dict[str, int]:
    targets = payload["targets"]
    return {
        "targetCoverageCount": len(targets),
        "opsJournalCount": len(targets["opsJournal"]),
        "opsJournalMetaCount": len(targets["opsJournalMeta"]),
        "opsJournalCompactedCount": len(targets["opsJournalCompacted"]),
        "opsSequenceCount": len(targets["opsSequenceByAggregate"]),
        "missionsCount": len(targets["missions"]),
        "missionWindowsCount": len(targets["missionWindows"]),
        "forecastsCount": len(targets["forecasts"]),
        "outcomesCount": len(targets["outcomes"]),
        "incidentsCount": len(targets["incidents"]),
        "postmortemsCount": len(targets["postmortems"]),
        "periodicReportsCount": len(targets["periodicReports"]),
        "challengerRunsCount": len(targets["challengerRuns"]),
        "agentQueueCount": len(targets["agentQueue"]),
        "soakFieldCount": len(targets["soak"]),
    }


def _expected_shape() -> Dict[str, int]:
    return {
        "targetCoverageCount": len(recovery.TARGET_KEYS),
        "opsJournalCount": recovery.LIST_LIMITS["opsJournal"],
        "opsJournalMetaCount": 2,
        "opsJournalCompactedCount":
            recovery.LIST_LIMITS["opsJournalCompacted"],
        "opsSequenceCount": journal.OPS_SEQUENCE_BY_AGGREGATE_LIMIT,
        "missionsCount": recovery.LIST_LIMITS["missions"],
        "missionWindowsCount": recovery.LIST_LIMITS["missionWindows"],
        "forecastsCount": recovery.LIST_LIMITS["forecasts"],
        "outcomesCount": recovery.LIST_LIMITS["outcomes"],
        "incidentsCount": recovery.LIST_LIMITS["incidents"],
        "postmortemsCount": recovery.LIST_LIMITS["postmortems"],
        "periodicReportsCount": recovery.LIST_LIMITS["periodicReports"],
        "challengerRunsCount": recovery.LIST_LIMITS["challengerRuns"],
        "agentQueueCount": recovery.DICT_LIMITS["agentQueue"],
        "soakFieldCount": recovery.DICT_LIMITS["soak"],
    }


def _assert_scalar_report(report: Dict[str, Any]) -> None:
    if set(report) != REPORT_FIELDS or any(
            isinstance(value, (dict, list, tuple, set, bytes, bytearray))
            for value in report.values()):
        raise RuntimeError("resource_report_not_scalar")


def run(cycles: int = REQUIRED_CYCLES, *,
        require_cgroup_max_bytes: int = 0) -> Dict[str, Any]:
    if int(cycles) != REQUIRED_CYCLES:
        raise ValueError("resource_cycles_must_equal_eight")
    required_cgroup = max(0, int(require_cgroup_max_bytes))
    before_events = _memory_events()
    cgroup_max = _read_scalar(pathlib.Path("/sys/fs/cgroup/memory.max"))
    sampled_cgroup_peak = _read_scalar(
        pathlib.Path("/sys/fs/cgroup/memory.current")) or 0
    current_key = secrets.token_bytes(32)
    previous_key = secrets.token_bytes(32)
    saved_environment = {
        name: os.environ.get(name) for name in KEY_ENVIRONMENT_NAMES}
    temp_root: pathlib.Path | None = None
    verified_cycles = 0
    compacted_cycles = 0
    unique_nonces: set[bytes] = set()
    unique_derivation_salts: set[bytes] = set()
    encrypted_body_lengths: set[int] = set()
    sidecar_lengths: set[int] = set()
    observed_shape: Dict[str, int] | None = None
    try:
        os.environ.update({
            "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": CURRENT_ID,
            "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(current_key),
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": PREVIOUS_ID,
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY":
                _encoded_key(previous_key),
            "RENDER_GIT_COMMIT": BUILD_SHA,
        })
        with tempfile.TemporaryDirectory(
                prefix="argus-recovery-resource-") as temporary:
            temp_root = pathlib.Path(temporary)
            paths = _configure_temporary_root(temp_root)
            _seed_maximum_targets()
            _activate_clean_legacy_nonce_authority(paths)
            for cycle in range(REQUIRED_CYCLES):
                sequence = int(durability.read_valid_wal(
                    paths["wal"])["maximumSequence"]) + 1
                durability.append_wal(
                    paths["wal"], sequence=sequence,
                    kind="journal_transition", job_id="resource-probe",
                    payload={"transitionId": f"cycle-{cycle + 1}"},
                    occurred_at=AT)
                _install_verified_remote_receipt(paths, sequence)
                checkpoint = scanner._osint_persist()
                if checkpoint.get("verified") is not True or \
                        (checkpoint.get("postVerify") or {}).get(
                            "status") != "verified":
                    raise RuntimeError("resource_checkpoint_unverified")
                compaction = checkpoint.get("walCompaction") or {}
                if compaction.get("compactedThrough") != sequence:
                    raise RuntimeError("resource_wal_compaction_invalid")
                compacted_cycles += 1

                raw_sidecar = pathlib.Path(paths["recovery"]).read_bytes()
                sidecar_lengths.add(len(raw_sidecar))
                sidecar = recovery.validate_sidecar(json.loads(
                    raw_sidecar.decode("utf-8")))
                envelope = sidecar["recovery"]
                payload = recovery.validate_pair(
                    sidecar["readback"], envelope, current_key,
                    key_identifier=CURRENT_ID)
                if recovery.decrypt_configured(
                        envelope, recovery.configured_keys()) != payload:
                    raise RuntimeError("resource_configured_decrypt_invalid")
                marker = storage.load_checkpoint(
                    paths["checkpoint"], require_seal=True).get(
                        "remoteRecoveryRequired") or {}
                if payload.get("checkpointId") != marker.get(
                        "checkpointId") or payload.get(
                            "ledgerBaseCommitSha") != LEDGER_BASE:
                    raise RuntimeError("resource_checkpoint_binding_invalid")
                cycle_shape = _shape(payload)
                if observed_shape is None:
                    observed_shape = cycle_shape
                elif cycle_shape != observed_shape:
                    raise RuntimeError("resource_target_shape_changed")
                unique_nonces.add(recovery._b64_decode(
                    envelope["nonce"], "resource_nonce_invalid"))
                if envelope.get("keyDerivation") != recovery.KEY_DERIVATION:
                    raise RuntimeError("resource_key_derivation_invalid")
                unique_derivation_salts.add(
                    recovery._decode_key_derivation_salt(
                        envelope["keyDerivationSalt"]))
                encrypted_body_lengths.add(len(recovery._b64_decode(
                    envelope["ciphertext"],
                    "resource_encrypted_body_invalid")))
                verified_cycles += 1
                sampled_cgroup_peak = max(
                    sampled_cgroup_peak,
                    _read_scalar(pathlib.Path(
                        "/sys/fs/cgroup/memory.current")) or 0)
    finally:
        for name, value in saved_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        current_key = b""
        previous_key = b""

    temporary_removed = temp_root is not None and not temp_root.exists()
    after_events = _memory_events()
    oom_delta = _event_delta(before_events["oom"], after_events["oom"])
    oom_kill_delta = _event_delta(
        before_events["oomKill"], after_events["oomKill"])
    observed_cgroup_peak = _read_scalar(
        pathlib.Path("/sys/fs/cgroup/memory.peak"))
    shape = observed_shape or {}
    expected_shape = _expected_shape()
    fixed_encrypted_body = next(iter(encrypted_body_lengths), 0)
    fixed_sidecar = max(sidecar_lengths, default=0)
    exact_cgroup = (
        cgroup_max == required_cgroup if required_cgroup else True)
    telemetry_complete = (
        cgroup_max is not None and observed_cgroup_peak is not None and
        oom_delta is not None and oom_kill_delta is not None)
    passed = all((
        verified_cycles == REQUIRED_CYCLES,
        compacted_cycles == REQUIRED_CYCLES,
        len(unique_nonces) == REQUIRED_CYCLES,
        len(unique_derivation_salts) == REQUIRED_CYCLES,
        encrypted_body_lengths == {
            recovery.PADDED_PLAINTEXT_BYTES + 16},
        bool(sidecar_lengths) and fixed_sidecar > 0 and
            fixed_sidecar <= recovery.MAX_SIDECAR_BYTES,
        shape == expected_shape,
        temporary_removed,
        exact_cgroup,
        telemetry_complete if required_cgroup else True,
        oom_delta == 0 if required_cgroup else oom_delta in (None, 0),
        oom_kill_delta == 0 if required_cgroup else
            oom_kill_delta in (None, 0),
    ))
    report: Dict[str, Any] = {
        "schemaVersion": "argus-encrypted-producer-resource-proof-v1",
        "processTopology": "single-process-temporary-production-path",
        "cycles": REQUIRED_CYCLES,
        "verifiedCycleCount": verified_cycles,
        "walCompactionCount": compacted_cycles,
        "uniqueNonceCount": len(unique_nonces),
        "uniqueKeyDerivationSaltCount": len(unique_derivation_salts),
        "fixedEncryptedBodyBytes": fixed_encrypted_body,
        "maximumSidecarBytes": fixed_sidecar,
        **expected_shape,
        "processPeakRssBytes": _peak_rss_bytes() or 0,
        "cgroupObservedPeakBytes": observed_cgroup_peak or 0,
        "cgroupSampledPeakBytes": sampled_cgroup_peak,
        "cgroupMaxBytes": cgroup_max or 0,
        "oomDelta": oom_delta if oom_delta is not None else -1,
        "oomKillDelta": oom_kill_delta if oom_kill_delta is not None else -1,
        "temporaryRootRemoved": temporary_removed,
        "abnormalExitCount": 0,
        "passed": passed,
    }
    _assert_scalar_report(report)
    return report


def _failure_report() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "schemaVersion": "argus-encrypted-producer-resource-proof-v1",
        "processTopology": "single-process-temporary-production-path",
        "cycles": REQUIRED_CYCLES,
        "verifiedCycleCount": 0,
        "walCompactionCount": 0,
        "uniqueNonceCount": 0,
        "uniqueKeyDerivationSaltCount": 0,
        "fixedEncryptedBodyBytes": 0,
        "maximumSidecarBytes": 0,
        **_expected_shape(),
        "processPeakRssBytes": _peak_rss_bytes() or 0,
        "cgroupObservedPeakBytes": 0,
        "cgroupSampledPeakBytes": 0,
        "cgroupMaxBytes": 0,
        "oomDelta": -1,
        "oomKillDelta": -1,
        "temporaryRootRemoved": False,
        "abnormalExitCount": 1,
        "passed": False,
    }
    _assert_scalar_report(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=REQUIRED_CYCLES)
    parser.add_argument("--require-cgroup-max-bytes", type=int, default=0)
    parser.add_argument("--output")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        report = run(
            args.cycles,
            require_cgroup_max_bytes=max(
                0, int(args.require_cgroup_max_bytes)))
    except Exception:
        report = _failure_report()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if not args.quiet:
        print(encoded)
    if args.output:
        pathlib.Path(args.output).write_text(
            encoded + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
