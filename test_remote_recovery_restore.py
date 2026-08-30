"""Focused acceptance for authenticated cold/new-disk recovery restore."""
from __future__ import annotations

import base64
import contextlib
import copy
import os
import pathlib
import tempfile
import types
from unittest import mock

import pytest

import argus_persistent_storage as storage
import argus_remote_journal as journal
import argus_remote_recovery as recovery
import argus_tick_durability as tick_durability


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner
from test_argus_persistent_mission_storage import (
    FakeResponse, remote_snapshot, scanner_storage,
)


PINNED_SHA = "d" * 40
BASE_SHA = "b" * 40
FULL_AT = "2026-08-11T20:37:25Z"
RECOVERY_AT = "2026-08-11T21:07:09Z"
FULL_WAL = 4659
RECOVERY_WAL = 4694
BUILD = {"appVersion": "13.4.13", "buildSha": "e" * 40}
CURRENT_ID = "recovery-current-v1"
PREVIOUS_ID = "recovery-previous-v1"
CURRENT_KEY = b"\x11" * 32
PREVIOUS_KEY = b"\x22" * 32
CHECKPOINT_ID = "rcp-" + "5" * 32


def _encoded_key(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _key_env(*, current=CURRENT_KEY, previous=None):
    value = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": CURRENT_ID,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(current),
        "RENDER_GIT_COMMIT": BUILD["buildSha"],
    }
    if previous is not None:
        value.update({
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": PREVIOUS_ID,
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY": _encoded_key(previous),
        })
    return value


def _event(sequence):
    body = {
        "eventId": f"event-{sequence}", "eventType": "mission_completed",
        "aggregateType": "mission", "aggregateId": f"mw-{sequence}",
        "sequence": sequence, "occurredAt": RECOVERY_AT,
        "idempotencyKey": f"mission:mw-{sequence}:completed",
        "privacyClassification": "public_safe",
        "payload": {"missionType": "ordinary"},
    }
    body["integrityHash"] = journal._h(body)
    return body


def _full(wal=FULL_WAL):
    value = remote_snapshot(wal)
    value.update({
        "generatedAt": FULL_AT, "asOf": FULL_AT,
        "buildIdentity": {
            "appVersion": "13.4.12", "buildSha": "f" * 40},
        "missions": [], "missionWindows": [], "forecasts": [],
        "outcomes": [], "incidents": [], "postmortems": [],
        "periodicReports": [], "challengerRuns": [], "agentQueue": {},
        "opsSequenceByAggregate": {},
        "marketLedgerStateHash": "a" * 16,
        "chartIntelligenceStateHash": "b" * 16,
        "todayIntelligenceStateHash": "c" * 16,
        "marketReplayStateHash": "d" * 16,
    })
    return value


def _artifacts(*, key=CURRENT_KEY, key_id=CURRENT_ID, mission_count=300,
               target_wal=RECOVERY_WAL, nonce=b"\xc1" * 12,
               generation_digit="c"):
    events = [_event(target_wal)]
    meta = {
        "totalObserved": 1,
        journal.OPS_SEQUENCE_HIGH_WATER_FIELD: target_wal,
    }
    section = journal.snapshot_journal_section(
        events=events, meta=meta, compacted=[],
        now_iso=RECOVERY_AT)
    durability = {
        "schemaVersion": "argus-mission-batch-v1", "cursor": 300,
        "remainingCount": 0, "lastJobId": f"job-{target_wal}",
        "lastResult": "completed", "lastCompletedAt": RECOVERY_AT,
        "walAppliedSequence": target_wal,
        "remoteWalAppliedSequence": target_wal,
        "verifiedWalSequence": FULL_WAL,
        "compactReceiptHash": None,
    }
    outcome = {"id": f"outcome-{target_wal}", "status": "resolved"}
    outcome["integrityHash"] = journal._h(outcome)
    compact = journal.build_compact_readback_snapshot(
        schema_version=journal.SCHEMA_V3, generated_at=RECOVERY_AT,
        as_of=RECOVERY_AT, build_identity=BUILD, ops_journal=events,
        integrity_manifest=section["integrityManifest"], outcomes=[outcome],
        mission_tick_durability=durability,
        market_ledger_state_hash="1" * 16,
        chart_intelligence_state_hash="2" * 16,
        today_intelligence_state_hash="3" * 16,
        market_replay_state_hash="4" * 16)
    targets = {
        "opsJournal": events, "opsJournalMeta": copy.deepcopy(meta),
        "opsJournalCompacted": [],
        "opsSequenceByAggregate": {
            f"mission:mw-{target_wal}": target_wal},
        "missions": [{"missionId": f"mission-{index}"}
                     for index in range(mission_count)],
        "missionWindows": [{"missionWindowId": f"mw-{target_wal}"}],
        "forecasts": [{"id": f"forecast-{target_wal}"}],
        "outcomes": compact["outcomes"], "incidents": [], "soak": {},
        "postmortems": [{"missionWindowId": f"mw-{target_wal}"}],
        "periodicReports": [{"reportId": f"report-{target_wal}"}],
        "challengerRuns": [{"runId": f"challenger-{target_wal}"}],
        "agentQueue": {"TEST": {"mode": "deep"}},
        "missionTickDurability": durability,
    }
    payload = recovery.build_payload(
        compact_readback=compact, targets=targets,
        generated_at=RECOVERY_AT, build_identity=BUILD,
        checkpoint_id=CHECKPOINT_ID,
        source_checkpoint_hash="a" * 64,
        checkpoint_verified_at=RECOVERY_AT,
        ledger_base_commit_sha=BASE_SHA,
        nonce_authority={
            "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
            "keyMaterialCounters": {
                recovery.nonce_material_domain(key):
                    int.from_bytes(b"\xc1" * 12, "big"),
            },
        })
    envelope = recovery.encrypt_payload(
        payload, key, key_identifier=key_id,
        nonce=nonce,
        generation_id="rrg-" + generation_digit * 32)
    return compact, envelope, targets


def _commit_metadata(sha, parents):
    return FakeResponse(200, {
        "sha": sha, "parents": [{"sha": parent} for parent in parents]})


def _responses(full, readback, recovery_object, *, ancestry=True):
    sidecar = (recovery_object if isinstance(recovery_object, dict) and
               recovery_object.get("schemaVersion") == recovery.SIDECAR_SCHEMA
               else recovery.build_sidecar(readback, recovery_object))
    values = [FakeResponse(200, {"sha": PINNED_SHA}),
              FakeResponse(200, full), FakeResponse(200, readback),
              FakeResponse(200, sidecar)]
    if ancestry:
        values.extend([
            _commit_metadata(PINNED_SHA, [BASE_SHA]),
            _commit_metadata(BASE_SHA, []),
        ])
    return values


def _required_checkpoint(checkpoint, key_id=CURRENT_ID,
                         checkpoint_id=CHECKPOINT_ID):
    value = copy.deepcopy(checkpoint)
    value["remoteRecoveryRequired"] = {
        "schemaVersion": recovery.SIDECAR_SCHEMA,
        "mode": "encrypted_required",
        "keyId": key_id,
        "checkpointId": checkpoint_id,
    }
    return value


def _verified_legacy_checkpoint(readback, targets):
    value = _full()
    value.update(copy.deepcopy(targets))
    manifest_hash = readback["integrityManifest"]["manifestHash"]
    value["remoteJournalCycle"] = {
        "remoteCommitSha": BASE_SHA,
        "receiptCommitSha": BASE_SHA,
        "committedAt": RECOVERY_AT,
        "readBackAt": RECOVERY_AT,
        "readBackVerified": True,
        "walReadBackVerified": True,
        "expectedHash": manifest_hash,
        "actualHash": manifest_hash,
        "remoteWalAppliedSequence": RECOVERY_WAL,
        "verifiedWalSequence": RECOVERY_WAL,
        "compactReceiptHash": readback["receiptHash"],
        "remoteDurabilityState": "verified",
        "receiptErrorClass": None,
        "errorClass": None,
        "walErrorClass": None,
    }
    return value


def _sealed_local_pair(*, key, key_id, readback, envelope, targets,
                       generation_digit):
    checkpoint = _full()
    checkpoint.update(copy.deepcopy(targets))
    checkpoint["missionTickDurability"]["remoteWalAppliedSequence"] = FULL_WAL
    manifest_hash = readback["integrityManifest"]["manifestHash"]
    checkpoint["remoteJournalCycle"] = {
        "remoteCommitSha": BASE_SHA, "receiptCommitSha": BASE_SHA,
        "readBackVerified": True, "walReadBackVerified": True,
        "remoteDurabilityState": "verified",
        "expectedHash": manifest_hash, "actualHash": manifest_hash,
        "compactReceiptHash": readback["receiptHash"],
        "remoteWalAppliedSequence": envelope["targetWalSequence"],
        "verifiedWalSequence": envelope["targetWalSequence"],
        "errorClass": None, "walErrorClass": None,
        "receiptErrorClass": None,
    }
    checkpoint = _required_checkpoint(checkpoint, key_id)
    sealed = storage.seal_checkpoint(checkpoint)
    payload = recovery.decrypt_envelope(
        envelope, key, key_identifier=key_id)
    payload["sourceCheckpointHash"] = storage._canonical_sha256(sealed)
    payload["payloadHash"] = recovery._hash({
        name: value for name, value in payload.items()
        if name != "payloadHash"})
    local_envelope = recovery.encrypt_payload(
        payload, key, key_identifier=key_id,
        nonce=bytes.fromhex(generation_digit * 24),
        generation_id="rrg-" + generation_digit * 32)
    return sealed, recovery.build_sidecar(readback, local_envelope)


def _urls(request_get):
    return [call.args[0] for call in request_get.call_args_list]


@contextlib.contextmanager
def _local_keyed_boot_probe():
    """Supply authoritative no-history evidence to local-only regressions."""
    pinned = {
        "base": ("https://raw.githubusercontent.com/mitsugue/argus/" +
                 PINNED_SHA + "/ledger"),
        "commitSha": PINNED_SHA, "owner": "mitsugue",
        "repository": "argus", "pathPrefix": "ledger",
    }
    with mock.patch.object(
            scanner, "_pinned_ledger_restore_base", return_value=pinned), \
            mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=True):
        yield


def test_new_disk_restores_exact_targets_and_seeds_wal_floor():
    readback, envelope, targets = _artifacts()
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        with mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, envelope)) as request_get:
            assert scanner._osint_restore_once() == "remote_journal_verified"
        stored = storage.load_checkpoint(paths["checkpoint"], require_seal=True)
        assert stored["missionTickDurability"]["walAppliedSequence"] == \
            RECOVERY_WAL
        marker = stored["remoteRecoveryRequired"]
        assert {name: marker[name] for name in (
            "schemaVersion", "mode", "keyId")} == {
                "schemaVersion": recovery.SIDECAR_SCHEMA,
                "mode": "encrypted_required", "keyId": CURRENT_ID}
        assert recovery.CHECKPOINT_ID_RE.fullmatch(marker["checkpointId"])
        installed_sidecar = scanner._read_local_recovery_sidecar()
        assert installed_sidecar["recovery"]["checkpointId"] == \
            marker["checkpointId"]
        # Compact proof hashes describe the newer producer checkpoint, while
        # these large bodies came from the older full object.  Restore must not
        # pair a compact-only hash with a body that was not recovered.
        assert stored["marketLedgerStateHash"] == _full()[
            "marketLedgerStateHash"]
        assert stored["chartIntelligenceStateHash"] == _full()[
            "chartIntelligenceStateHash"]
        assert scanner._MISSIONS == targets["missions"]
        assert len(scanner._MISSIONS) == 300
        for name, runtime in (
                ("missionWindows", scanner._MISSION_WINDOWS),
                ("forecasts", scanner._FORECAST_LEDGER),
                ("outcomes", scanner._OUTCOME_LEDGER),
                ("incidents", scanner._INCIDENTS),
                ("postmortems", scanner._POSTMORTEMS),
                ("periodicReports", scanner._PERIODIC_REPORTS),
                ("challengerRuns", scanner._CHALLENGER_RUNS),
                ("opsJournal", scanner._OPS_JOURNAL),
                ("opsJournalCompacted", scanner._OPS_JOURNAL_COMPACT)):
            assert runtime == targets[name]
        assert scanner._SOAK == targets["soak"]
        assert scanner._OPS_JOURNAL_META == targets["opsJournalMeta"]
        assert scanner._OPS_SEQ == targets["opsSequenceByAggregate"]
        assert scanner._POSTMORTEMS == targets["postmortems"]
        assert scanner._PERIODIC_REPORTS == targets["periodicReports"]
        assert scanner._CHALLENGER_RUNS == targets["challengerRuns"]
        assert scanner._OSINT_AGENT_QUEUE == targets["agentQueue"]
        wal = tick_durability.read_valid_wal(paths["wal"])
        assert wal["corruptCount"] == 0
        assert wal["maximumSequence"] == RECOVERY_WAL
        assert wal["records"][-1]["kind"] == "checkpoint_verified"
        assert scanner._REMOTE_CYCLE["verifiedWalSequence"] == RECOVERY_WAL
        assert scanner._REMOTE_CYCLE["remoteCommitSha"] == PINNED_SHA
        assert scanner._REMOTE_ACK["ackedKeys"] == [
            events["idempotencyKey"] for events in readback["opsJournal"]]
        scanner._MISSION_TICK_CONTEXT.update({
            "active": True, "ownerThread": scanner.threading.get_ident(),
            "jobId": "next", "walSequence": wal["maximumSequence"],
            "walEventCount": 0, "walAppendMs": 0, "lease": None,
        })
        next_record = scanner._append_tick_wal("transition", {"value": 1})
        assert next_record["sequence"] == RECOVERY_WAL + 1
        assert tick_durability.read_valid_wal(paths["wal"])[
            "maximumSequence"] == RECOVERY_WAL + 1
        assert pathlib.Path(paths["recovery"]).exists()
        scanner._OSINT_PERSIST_STATE.clear()
        scanner._OSINT_PERSIST_STATE.update({"restored": False})
        scanner._MISSIONS.clear()
        scanner._OPS_SEQ.clear()
        with _local_keyed_boot_probe():
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._MISSIONS == targets["missions"]
        assert scanner._OPS_SEQ == targets["opsSequenceByAggregate"]
        raw_prefix = ("https://raw.githubusercontent.com/mitsugue/argus/"
                      f"{PINNED_SHA}/ledger")
        assert _urls(request_get) == [
            "https://api.github.com/repos/mitsugue/argus/commits/ledger",
            f"{raw_prefix}/osint/memory.json",
            f"{raw_prefix}/osint/readback.json",
            f"{raw_prefix}/osint/recovery.json",
            ("https://api.github.com/repos/mitsugue/argus/git/commits/" +
             PINNED_SHA),
            ("https://api.github.com/repos/mitsugue/argus/git/commits/" +
             BASE_SHA),
        ]


def _install_local_pair(paths, root, sealed, sidecar):
    storage.atomic_write_json(
        paths["checkpoint"], sealed, temp_directory=root)
    storage.atomic_write_json(
        paths["recovery"], sidecar, temp_directory=root)


def _keyed_local_probe_responses(readback, envelope, *, full=None,
                                 ancestry=None):
    sidecar = (envelope if isinstance(envelope, dict) and envelope.get(
        "schemaVersion") == recovery.SIDECAR_SCHEMA else
        recovery.build_sidecar(readback, envelope))
    values = [
        FakeResponse(200, {"sha": PINNED_SHA}),
        FakeResponse(200, readback),
        FakeResponse(200, sidecar),
    ]
    values.extend(ancestry if ancestry is not None else [
        _commit_metadata(PINNED_SHA, [BASE_SHA]),
        _commit_metadata(BASE_SHA, []),
    ])
    if full is not None:
        values.append(FakeResponse(200, full))
    return values


def _deep_outer_sidecar_response(depth=10_000):
    response = FakeResponse(200)
    response._encoded = (
        b'{"schemaVersion":"' + recovery.SIDECAR_SCHEMA.encode("ascii") +
        b'","readback":{},"recovery":' +
        (b'{"nested":' * depth) + b'null' + (b'}' * depth) + b'}'
    )
    assert len(response._encoded) < scanner._DURABLE_RECOVERY_MAX_BYTES
    return response


def _keyed_local_legacy_probe_responses(readback, *, history=None,
                                        ancestry=None):
    """One immutable legacy readback plus proved recovery-path absence."""
    values = [
        FakeResponse(200, {"sha": PINNED_SHA}),
        FakeResponse(200, readback),
        FakeResponse(404),
        FakeResponse(200, [] if history is None else history),
    ]
    values.extend(ancestry if ancestry is not None else [
        _commit_metadata(PINNED_SHA, [BASE_SHA]),
        _commit_metadata(BASE_SHA, []),
    ])
    return values


def test_keyed_boot_remote_newer_than_local_uses_same_pinned_pair():
    local_wal = RECOVERY_WAL - 10
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=local_wal, mission_count=1, nonce=b"\xb1" * 12,
        generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback, remote_envelope, remote_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3)
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_probe_responses(
                    remote_readback, remote_envelope, full=_full())) as get:
            assert scanner._osint_restore_once() == \
                "remote_journal_verified"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "pinned_remote"
        assert scanner._MISSIONS == remote_targets["missions"]
        assert scanner._MISSION_BATCH_STATE["walAppliedSequence"] == \
            RECOVERY_WAL
        urls = _urls(get)
        assert sum(url.endswith("/osint/readback.json") for url in urls) == 1
        assert sum(url.endswith("/osint/recovery.json") for url in urls) == 1
        assert sum(url.endswith("/osint/memory.json") for url in urls) == 1


def test_deep_remote_outer_envelope_preserves_healthy_local_checkpoint():
    readback, envelope, targets = _artifacts(mission_count=2)
    sealed, sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, sealed, sidecar)
        checkpoint_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        responses = [
            FakeResponse(200, {"sha": PINNED_SHA}),
            FakeResponse(200, readback),
            _deep_outer_sidecar_response(),
            FakeResponse(500),
        ]
        with mock.patch.object(
                scanner.requests, "get", side_effect=responses):
            assert scanner._osint_restore_once() is None

        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_unreadable_or_oversized"
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "remote_recovery_unreadable_or_oversized"
        assert not scanner._DURABLE_STATE.get("localCheckpointError")
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
            checkpoint_before
        assert pathlib.Path(paths["recovery"]).is_file()
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_remote_ledger_http_failure_preserves_seal_valid_canonical():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        storage.write_checkpoint(
            paths["checkpoint"], remote_snapshot(FULL_WAL),
            temp_directory=root)
        before = pathlib.Path(paths["checkpoint"]).read_bytes()
        with mock.patch.object(
                scanner, "_pinned_ledger_restore_base",
                side_effect=recovery.RecoveryBundleError(
                    "ledger_ref_resolution_http_error")):
            assert scanner._osint_restore_once() is None
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert scanner._DURABLE_STATE["restoreDecision"] == {
            "RESTORE_STAGE": "REMOTE_NONCE_BOOT",
            "ERROR_CLASS": "ledger_ref_resolution_http_error",
            "LOCAL_VALIDITY": "VALID",
            "REMOTE_FAILURE_CLASS": "ledger_ref_resolution_http_error",
            "QUARANTINE_DECISION": "PRESERVE",
            "QUARANTINE_REASON": None,
        }
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._OSINT_PERSIST_STATE.get("restored") is not True


def test_remote_object_absent_preserves_marker_only_canonical_fail_closed():
    readback, _envelope, _targets = _artifacts(mission_count=1)
    marker_only = _required_checkpoint(remote_snapshot(FULL_WAL))
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        storage.write_checkpoint(
            paths["checkpoint"], marker_only, temp_directory=root)
        before = pathlib.Path(paths["checkpoint"]).read_bytes()
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(readback)):
            assert scanner._osint_restore_once() is None
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_nonce_authority_missing"
        assert scanner._DURABLE_STATE["restoreDecision"][
            "QUARANTINE_DECISION"] == "PRESERVE"
        assert scanner._DURABLE_STATE["restoreDecision"][
            "LOCAL_VALIDITY"] == "VALID"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_proven_corrupt_local_checkpoint_is_quarantined_with_exact_reason():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.object(scanner.requests, "get", return_value=
                              FakeResponse(503)):
        pathlib.Path(paths["checkpoint"]).write_text(
            '{"schemaVersion":"argus-durable-v3",', encoding="utf-8")
        assert scanner._osint_restore_once() is None
        assert not pathlib.Path(paths["checkpoint"]).exists()
        quarantine = pathlib.Path(
            scanner._DURABLE_STATE["quarantinedCheckpoint"])
        assert quarantine.is_file()
        assert scanner._DURABLE_STATE["restoreDecision"] == {
            "RESTORE_STAGE": "LOCAL_CHECKPOINT_LOAD",
            "ERROR_CLASS": "JSONDecodeError",
            "LOCAL_VALIDITY": "INVALID",
            "REMOTE_FAILURE_CLASS": None,
            "QUARANTINE_DECISION": "QUARANTINED",
            "QUARANTINE_REASON": "local_checkpoint_json_invalid",
        }
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_repeated_memory_snapshot_get_does_not_remove_valid_local_state():
    readback, _envelope, _targets = _artifacts(mission_count=1)
    marker_only = _required_checkpoint(remote_snapshot(FULL_WAL))
    responses = (
        _keyed_local_legacy_probe_responses(readback)[:4] +
        _keyed_local_legacy_probe_responses(readback)[:4])
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=responses):
        storage.write_checkpoint(
            paths["checkpoint"], marker_only, temp_directory=root)
        before = pathlib.Path(paths["checkpoint"]).read_bytes()
        client = scanner.app.test_client()
        assert client.get(
            "/api/argus/osint/memory-snapshot").status_code == 200
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert client.get(
            "/api/argus/osint/memory-snapshot").status_code == 200
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_keyed_boot_local_newer_than_remote_stays_persistent_local():
    remote_wal = RECOVERY_WAL - 10
    remote_readback, remote_envelope, _remote_targets = _artifacts(
        target_wal=remote_wal, mission_count=1)
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3, nonce=b"\xb1" * 12,
        generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_probe_responses(
                    remote_readback, remote_envelope)) as get:
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == local_targets["missions"]
        assert scanner._MISSION_BATCH_STATE["walAppliedSequence"] == \
            RECOVERY_WAL
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_equal_exact_pair_prefers_coherent_local():
    readback, envelope, targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=2)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_probe_responses(readback, envelope)) as get:
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == targets["missions"]
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_legacy_head_newer_than_local_fails_without_full_fallback():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL - 10, mission_count=1,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3)
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)) as get:
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_pinned_legacy_newer_than_local"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._MISSIONS != local_targets["missions"]
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_local_newer_than_legacy_head_stays_local():
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=RECOVERY_WAL - 10, mission_count=1)
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)) as get:
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == local_targets["missions"]
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_equal_exact_legacy_readback_prefers_local():
    readback, envelope, targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=2)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(readback)):
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == targets["missions"]


def test_keyed_boot_equal_wal_different_legacy_receipt_fails_closed():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=1,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback = copy.deepcopy(local_readback)
    remote_readback["marketLedgerStateHash"] = "5" * 16
    remote_readback["receiptHash"] = journal._h({
        key: value for key, value in remote_readback.items()
        if key != "receiptHash"
    })
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)):
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_pinned_legacy_receipt_mismatch"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_keyed_boot_legacy_head_sibling_rejects_local_authority():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=2)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    sibling = "c" * 40
    ancestry = [
        _commit_metadata(PINNED_SHA, [sibling]),
        _commit_metadata(sibling, []),
    ]
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(
                    local_readback, ancestry=ancestry)):
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_local_authority_provenance_invalid"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_keyed_boot_legacy_readback_or_history_ambiguity_fails_before_local():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=1)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    malformed = copy.deepcopy(local_readback)
    malformed["receiptHash"] = "0" * 16
    cases = [
        ([FakeResponse(200, {"sha": PINNED_SHA}), FakeResponse(404),
          FakeResponse(404)],
         "recovery_nonce_remote_legacy_readback_missing"),
        ([FakeResponse(200, {"sha": PINNED_SHA}), FakeResponse(200, malformed),
          FakeResponse(404)],
         "recovery_nonce_remote_legacy_readback_invalid"),
        ([FakeResponse(200, {"sha": PINNED_SHA}),
          FakeResponse(200, local_readback), FakeResponse(404),
          FakeResponse(503)],
         "recovery_nonce_history_query_ambiguous"),
        ([FakeResponse(200, {"sha": PINNED_SHA}),
          FakeResponse(200, local_readback), FakeResponse(404),
          FakeResponse(200, {"sha": BASE_SHA})],
         "recovery_nonce_history_query_ambiguous"),
        ([FakeResponse(200, {"sha": PINNED_SHA}),
          FakeResponse(200, local_readback), FakeResponse(404),
          FakeResponse(200, [{"sha": BASE_SHA}])],
         "recovery_nonce_remote_history_exists"),
    ]
    for responses, expected in cases:
        with tempfile.TemporaryDirectory() as root, \
                scanner_storage(root) as paths, \
                mock.patch.dict(os.environ, _key_env(), clear=False):
            _install_local_pair(paths, root, local_sealed, local_sidecar)
            with mock.patch.object(
                    scanner.requests, "get", side_effect=responses):
                assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected
            assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
            assert scanner._MISSIONS != local_targets["missions"]


def test_keyed_boot_remote_tag_or_ancestry_ambiguity_precedes_local_authority():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL - 10, mission_count=1,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback, remote_envelope, _remote_targets = _artifacts()
    tampered = recovery.build_sidecar(remote_readback, remote_envelope)
    ciphertext = tampered["recovery"]["ciphertext"]
    replacement = "A" if ciphertext[0] != "A" else "B"
    tampered["recovery"]["ciphertext"] = replacement + ciphertext[1:]
    cases = [
        (_keyed_local_probe_responses(remote_readback, tampered, ancestry=[]),
         "recovery_ciphertext_hash_mismatch"),
        (_keyed_local_probe_responses(
            remote_readback, remote_envelope, ancestry=[
                _commit_metadata(PINNED_SHA, ["c" * 40]),
                _commit_metadata("c" * 40, []),
            ]), "recovery_ledger_commit_nonancestor"),
    ]
    for responses, expected in cases:
        with tempfile.TemporaryDirectory() as root, \
                scanner_storage(root) as paths, \
                mock.patch.dict(os.environ, _key_env(), clear=False):
            _install_local_pair(paths, root, local_sealed, local_sidecar)
            with mock.patch.object(
                    scanner.requests, "get", side_effect=responses) as get:
                assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected
            assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
            assert scanner._MISSIONS != local_targets["missions"]
            assert scanner._remote_recovery_nonce_authority_absent(
                include_lock=True)
            assert not any(
                url.endswith("/osint/memory.json") for url in _urls(get))


def test_previous_key_is_selected_exactly_and_wrong_current_never_falls_back():
    readback, previous_envelope, _ = _artifacts(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(previous=PREVIOUS_KEY),
                            clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, previous_envelope)):
        assert scanner._osint_restore_once() == "remote_journal_verified"

    readback, current_envelope, _ = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(
                current=b"\x33" * 32, previous=CURRENT_KEY), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, current_envelope)):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_authentication_failed"


def test_missing_pair_matrix_and_same_commit_pinning():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(200, {"sha": PINNED_SHA}),
                FakeResponse(200, _full()), FakeResponse(404),
                FakeResponse(404)]) as request_get:
            assert scanner._osint_restore_once() == "remote_journal_verified"
        urls = _urls(request_get)
        assert sum("api.github.com" in url for url in urls) == 1
        assert all(f"/{PINNED_SHA}/ledger/" in url
                   for url in urls if "raw.githubusercontent.com" in url)

    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(200, {"sha": PINNED_SHA}),
                FakeResponse(200, _full()), FakeResponse(404),
                FakeResponse(404)]):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_missing_for_readback"

    readback, _envelope, _targets = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(200, {"sha": PINNED_SHA}),
                FakeResponse(200, _full()), FakeResponse(200, readback),
                FakeResponse(404)]):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_missing_for_readback"


def test_present_encrypted_artifact_requires_readback_and_configured_key():
    readback, envelope, _ = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    cases = [
        ({}, [FakeResponse(404), FakeResponse(200, sidecar)],
         "recovery_key_not_configured"),
        (_key_env(), [FakeResponse(404), FakeResponse(200, sidecar)],
         "remote_recovery_pair_readback_absent"),
    ]
    for env, tail, expected in cases:
        with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(scanner.requests, "get", side_effect=[
                    FakeResponse(200, {"sha": PINNED_SHA}),
                    FakeResponse(200, _full()), *tail]):
            assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected


def test_sidecar_wrapper_and_pair_mismatch_fail_closed():
    readback, envelope, _ = _artifacts(mission_count=1)
    wrapper = recovery.build_sidecar(readback, envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, wrapper)):
        assert scanner._osint_restore_once() == "remote_journal_verified"

    bad_readback = copy.deepcopy(readback)
    bad_readback["receiptHash"] = "0" * 16
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), bad_readback, wrapper)):
        assert scanner._osint_restore_once() is None

    tampered = copy.deepcopy(envelope)
    tampered["bundleHash"] = "0" * 64
    tampered_sidecar = copy.deepcopy(wrapper)
    tampered_sidecar["recovery"] = tampered
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, tampered_sidecar)):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_bundle_hash_mismatch"


def test_bare_recovery_envelope_is_never_a_cold_restore_artifact():
    readback, envelope, _ = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(200, {"sha": PINNED_SHA}),
                FakeResponse(200, _full()), FakeResponse(200, readback),
                FakeResponse(200, envelope)]):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_sidecar_required"


def test_cold_restore_requires_bounded_linear_base_to_pinned_commit():
    readback, envelope, _ = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    cases = [
        ([
            _commit_metadata(PINNED_SHA, ["c" * 40]),
            _commit_metadata("c" * 40, []),
         ], "recovery_ledger_commit_nonancestor"),
        ([
            _commit_metadata(PINNED_SHA, [BASE_SHA, "c" * 40]),
         ], "recovery_ledger_commit_multiparent"),
    ]
    for ancestry, expected in cases:
        with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
                mock.patch.dict(os.environ, _key_env(), clear=False), \
                mock.patch.object(scanner.requests, "get", side_effect=[
                    FakeResponse(200, {"sha": PINNED_SHA}),
                    FakeResponse(200, _full()), FakeResponse(200, readback),
                    FakeResponse(200, sidecar), *ancestry]):
            assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected


def test_bounded_commit_path_accepts_equal_and_rejects_stale_replay():
    with mock.patch.object(
            scanner, "_bounded_ledger_commit_metadata",
            return_value={"sha": BASE_SHA, "parents": []}) as metadata:
        assert scanner._verify_authenticated_ledger_commit_path(
            BASE_SHA, BASE_SHA, owner="owner", repository="ledger") == {
                "status": "verified", "ledgerBaseCommitSha": BASE_SHA,
                "exactCommitSha": BASE_SHA, "distance": 0}
    metadata.assert_called_once_with("owner", "ledger", BASE_SHA)

    chain = {f"{index:040x}": f"{index - 1:040x}"
             for index in range(1, 34)}

    def commit_metadata(_owner, _repository, commit):
        parent = chain.get(commit)
        return {"sha": commit, "parents": [parent] if parent else []}

    with mock.patch.object(
            scanner, "_bounded_ledger_commit_metadata",
            side_effect=commit_metadata), \
            mock.patch.object(scanner, "_LEDGER_ANCESTRY_MAX_COMMITS", 2):
        try:
            scanner._verify_authenticated_ledger_commit_path(
                f"{1:040x}", f"{4:040x}", owner="owner",
                repository="ledger")
        except recovery.RecoveryBundleError as exc:
            assert exc.classification == "recovery_ledger_commit_stale_replay"
        else:
            raise AssertionError("stale ancestry replay accepted")


def test_stale_or_wal_regressing_remote_recovery_never_bootstraps():
    readback, envelope, _ = _artifacts(mission_count=1)
    stale_full = _full()
    stale_full["generatedAt"] = "2026-08-11T22:00:00Z"
    stale_full["asOf"] = stale_full["generatedAt"]
    cases = [
        (stale_full, "recovery_timestamp_regressed"),
        (_full(RECOVERY_WAL + 1), "recovery_target_behind_full"),
    ]
    for full, expected in cases:
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
                mock.patch.dict(os.environ, _key_env(), clear=False), \
                mock.patch.object(scanner.requests, "get", side_effect=_responses(
                    full, readback, envelope)):
            assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected
            assert not pathlib.Path(paths["checkpoint"]).exists()
            assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_local_keyed_checkpoint_requires_exact_sidecar_and_key():
    readback, envelope, targets = _artifacts(mission_count=1)
    checkpoint = _full()
    checkpoint.update(copy.deepcopy(targets))
    # Local producer's raw checkpoint keeps its prior remote WAL scalar.
    checkpoint["missionTickDurability"]["remoteWalAppliedSequence"] = FULL_WAL
    checkpoint = _required_checkpoint(checkpoint)
    sealed = storage.seal_checkpoint(checkpoint)
    checkpoint_hash = storage._canonical_sha256(sealed)
    payload = recovery.decrypt_envelope(
        envelope, CURRENT_KEY, key_identifier=CURRENT_ID)
    payload["sourceCheckpointHash"] = checkpoint_hash
    payload["payloadHash"] = recovery._hash({
        key: value for key, value in payload.items() if key != "payloadHash"})
    local_envelope = recovery.encrypt_payload(
        payload, CURRENT_KEY, key_identifier=CURRENT_ID,
        nonce=b"\x91" * 12,
        generation_id="rrg-" + "9" * 32)
    sidecar = recovery.build_sidecar(readback, local_envelope)

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(scanner.requests, "get", side_effect=[
                    FakeResponse(503)]):
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["localCheckpointError"] == \
            "RecoveryBundleError"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert pathlib.Path(paths["checkpoint"]).exists()

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_nonce_authority_missing"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        legacy = remote_snapshot(FULL_WAL)
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        with mock.patch.dict(os.environ, {}, clear=True):
            assert scanner._osint_restore_once() == "persistent_local"


def test_orphan_encrypted_sidecar_without_keys_blocks_legacy_fallback():
    readback, envelope, _targets = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, {}, clear=True), \
            mock.patch.object(scanner.requests, "get") as request_get:
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_key_not_configured"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        request_get.assert_not_called()


def test_local_keyed_checkpoint_validates_sidecar_before_authority():
    readback, envelope, targets = _artifacts(mission_count=1)
    checkpoint = _full()
    checkpoint.update(copy.deepcopy(targets))
    checkpoint["missionTickDurability"]["remoteWalAppliedSequence"] = FULL_WAL
    checkpoint = _required_checkpoint(checkpoint)
    sealed = storage.seal_checkpoint(checkpoint)
    payload = recovery.decrypt_envelope(
        envelope, CURRENT_KEY, key_identifier=CURRENT_ID)
    payload["sourceCheckpointHash"] = storage._canonical_sha256(sealed)
    payload["payloadHash"] = recovery._hash({
        key: value for key, value in payload.items() if key != "payloadHash"})
    local_envelope = recovery.encrypt_payload(
        payload, CURRENT_KEY, key_identifier=CURRENT_ID,
        nonce=b"\x81" * 12,
        generation_id="rrg-" + "8" * 32)
    sidecar = recovery.build_sidecar(readback, local_envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe():
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryLocal"][
            "status"] == "verified"
        assert scanner._MISSIONS == targets["missions"]
        assert scanner._OPS_SEQ == targets["opsSequenceByAggregate"]
        assert tick_durability.read_valid_wal(paths["wal"])[
            "maximumSequence"] == RECOVERY_WAL

    tampered = copy.deepcopy(sidecar)
    ciphertext = tampered["recovery"]["ciphertext"]
    replacement = "A" if ciphertext[0] != "A" else "B"
    tampered["recovery"]["ciphertext"] = replacement + ciphertext[1:]
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], tampered,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._MISSIONS != targets["missions"]


def test_configured_legacy_checkpoint_migrates_before_authority():
    readback, _envelope, targets = _artifacts(mission_count=2)
    legacy = _verified_legacy_checkpoint(readback, targets)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe():
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        assert not pathlib.Path(paths["recovery"]).exists()
        assert scanner._osint_restore_once() == "persistent_local"
        installed = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        marker = installed["remoteRecoveryRequired"]
        assert {name: marker[name] for name in (
            "schemaVersion", "mode", "keyId")} == {
                "schemaVersion": recovery.SIDECAR_SCHEMA,
                "mode": "encrypted_required", "keyId": CURRENT_ID}
        assert recovery.CHECKPOINT_ID_RE.fullmatch(marker["checkpointId"])
        sidecar = scanner._read_local_recovery_sidecar()
        assert sidecar["recovery"]["keyId"] == CURRENT_ID
        assert sidecar["recovery"]["checkpointId"] == marker["checkpointId"]
        assert recovery.validate_pair(
            sidecar["readback"], sidecar["recovery"], CURRENT_KEY,
            key_identifier=CURRENT_ID)["targets"]["missions"] == \
            targets["missions"]
        assert scanner._DURABLE_STATE["remoteRecoveryMigration"] == {
            "status": "verified", "keyId": CURRENT_ID,
            "targetWalSequence": RECOVERY_WAL}
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is not None


def test_configured_legacy_migration_failure_never_becomes_authority():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.write_checkpoint(
            paths["checkpoint"], remote_snapshot(FULL_WAL),
            temp_directory=root)
        prior = pathlib.Path(paths["checkpoint"]).read_bytes()
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_legacy_migration_failed"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._OSINT_PERSIST_STATE.get("restored") is not True
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == prior
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")


def test_legacy_migration_installs_sidecar_before_checkpoint_and_retries_crash():
    readback, _envelope, targets = _artifacts(mission_count=2)
    legacy = _verified_legacy_checkpoint(readback, targets)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        prior = pathlib.Path(paths["checkpoint"]).read_bytes()
        real_replace = os.replace
        observed = {"blocked": False}

        def interrupt_before_pointer(source, destination):
            if os.path.abspath(destination) == os.path.abspath(
                    paths["checkpoint"]) and str(source).endswith(
                        ".recovery-migration-checkpoint"):
                observed["blocked"] = True
                raise OSError("simulated_pointer_crash")
            return real_replace(source, destination)

        with mock.patch.object(
                scanner.os, "replace", side_effect=interrupt_before_pointer):
            assert scanner._osint_restore_once() is None
        assert observed["blocked"] is True
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == prior
        assert pathlib.Path(paths["recovery"]).is_file()
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")

        # The orphaned, authenticated sidecar supplies a nonce floor.  A
        # clean retry stages a fresh pair and atomically switches the
        # checkpoint without ever applying the old plaintext authority.
        assert scanner._osint_restore_once() == "persistent_local"
        installed = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        verified = scanner._verify_local_recovery_sidecar(
            installed, allow_legacy_migration=False)
        assert verified["remoteRecoveryProvenance"][
            "targetWalSequence"] == RECOVERY_WAL


def test_required_marker_is_exact_and_bound_to_sidecar_key_id():
    readback, envelope, targets = _artifacts(mission_count=1)
    sealed, sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="7")
    invalid = copy.deepcopy(sealed)
    invalid["remoteRecoveryRequired"]["unexpected"] = True
    invalid = storage.seal_checkpoint(invalid)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], invalid,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_required_marker_invalid"

    previous_readback, previous_envelope, previous_targets = _artifacts(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, mission_count=1)
    previous_sealed, previous_sidecar = _sealed_local_pair(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, readback=previous_readback,
        envelope=previous_envelope, targets=previous_targets,
        generation_digit="6")
    mismatch = copy.deepcopy(previous_sealed)
    mismatch["remoteRecoveryRequired"]["keyId"] = CURRENT_ID
    mismatch = storage.seal_checkpoint(mismatch)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(previous=PREVIOUS_KEY),
                            clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], mismatch,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], previous_sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_required_marker_key_mismatch"


def test_previous_key_local_sidecar_restores_for_rotation_compatibility():
    readback, envelope, targets = _artifacts(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, mission_count=1)
    sealed, sidecar = _sealed_local_pair(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="5")
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(previous=PREVIOUS_KEY),
                            clear=False), _local_keyed_boot_probe():
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryLocal"]["keyId"] == \
            PREVIOUS_ID
        assert scanner._MISSIONS == targets["missions"]


def test_remote_recovery_wrapper_cap_fails_closed_before_json_parse():
    readback, envelope, _targets = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner, "_DURABLE_RECOVERY_MAX_BYTES", 128), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, envelope)):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_unreadable_or_oversized"


def test_streamed_oversized_readback_cannot_bypass_decompressed_byte_cap():
    response = FakeResponse(200)
    response._encoded = b"[" + (
        b" " * journal.MAX_COMPACT_READBACK_BYTES)
    with mock.patch.object(scanner.requests, "get", return_value=response), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="remote_readback_unreadable_or_oversized"):
        scanner._fetch_pinned_recovery_object(
            "https://immutable.invalid/readback.json",
            scanner._DURABLE_READBACK_MAX_BYTES, "readback")


def test_local_sidecar_reader_rejects_symlink_and_growth_before_json_parse():
    readback, envelope, _ = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        real = pathlib.Path(root, "real-sidecar.json")
        real.write_text(recovery._canonical(sidecar).decode("utf-8"),
                        encoding="utf-8")
        pathlib.Path(paths["recovery"]).symlink_to(real)
        try:
            scanner._read_local_recovery_sidecar()
        except recovery.RecoveryBundleError as exc:
            assert exc.classification in (
                "recovery_local_sidecar_invalid",
                "recovery_local_sidecar_unreadable")
        else:
            raise AssertionError("sidecar symlink accepted")

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        pathlib.Path(paths["recovery"]).write_text(
            "{}", encoding="utf-8")
        original_read = scanner.os.read
        first = True

        def grow_then_read(descriptor, size):
            nonlocal first
            if first:
                first = False
                with open(paths["recovery"], "ab") as handle:
                    handle.write(b" " * (recovery.MAX_SIDECAR_BYTES + 1))
            return original_read(descriptor, size)

        with mock.patch.object(scanner.os, "read", side_effect=grow_then_read):
            try:
                scanner._read_local_recovery_sidecar()
            except recovery.RecoveryBundleError as exc:
                assert exc.classification == "recovery_local_sidecar_invalid"
            else:
                raise AssertionError("growing sidecar accepted")


def test_deep_local_sidecar_and_outer_tree_fail_in_recovery_domain():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        pathlib.Path(paths["recovery"]).write_bytes(
            _deep_outer_sidecar_response()._encoded)
        try:
            scanner._read_local_recovery_sidecar()
        except recovery.RecoveryBundleError as exc:
            assert exc.classification == "recovery_local_sidecar_unreadable"
        else:
            raise AssertionError("deep local sidecar accepted")

    nested = None
    for _ in range(recovery.MAX_DEPTH + 1):
        nested = {"nested": nested}
    try:
        recovery.validate_sidecar({
            "schemaVersion": recovery.SIDECAR_SCHEMA,
            "readback": {},
            "recovery": nested,
        })
    except recovery.RecoveryBundleError as exc:
        assert exc.classification == "recovery_outer_bounds_invalid"
    else:
        raise AssertionError("deep in-memory outer sidecar accepted")


def test_late_apply_failure_rolls_back_and_never_sets_restore_success():
    readback, envelope, _ = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, envelope)), \
            mock.patch.object(scanner, "_persist_durability_metadata",
                              side_effect=OSError("late")):
        scanner._MISSIONS[:] = [{"missionId": "pre-restore"}]
        scanner._OPS_SEQ.update({"mission:pre-restore": 73})
        scanner._OSINT_AGENT_QUEUE.update({"BEFORE": {"mode": "deep"}})
        before = copy.deepcopy(scanner._MISSIONS)
        before_sequence = copy.deepcopy(scanner._OPS_SEQ)
        before_queue = copy.deepcopy(scanner._OSINT_AGENT_QUEUE)
        assert scanner._osint_restore_once() is None
        assert scanner._MISSIONS == before
        assert scanner._OPS_SEQ == before_sequence
        assert scanner._OSINT_AGENT_QUEUE == before_queue
        assert not pathlib.Path(paths["wal"]).exists()
        assert scanner._DURABLE_STATE.get("remoteRecoveryWalFloor") is None
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._DURABLE_STATE.get("restoreSource") != \
            "remote_journal_verified"
        assert scanner._OSINT_PERSIST_STATE.get("restored") is not True


def test_wal_floor_readback_failure_removes_only_new_anchor():
    blob = {
        "missionTickDurability": {"walAppliedSequence": RECOVERY_WAL},
        "remoteRecoveryProvenance": {
            "targetWalSequence": RECOVERY_WAL,
            "compactReceiptHash": "1" * 16,
            "bundleHash": "2" * 64,
            "ledgerCommitSha": PINNED_SHA,
            "checkpointVerifiedAt": RECOVERY_AT,
            "buildIdentity": BUILD,
        },
    }
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        original = tick_durability.read_valid_wal
        calls = 0

        def corrupt_first_readback(path, *, after_sequence=0):
            nonlocal calls
            calls += 1
            value = original(path, after_sequence=after_sequence)
            if calls == 2:
                value["corruptCount"] = 1
            return value

        with mock.patch.object(
                scanner.argus_tick_durability, "read_valid_wal",
                side_effect=corrupt_first_readback):
            try:
                scanner._seed_remote_recovery_wal_floor(blob)
            except scanner._RemoteRecoveryRestoreError as exc:
                assert str(exc) == "recovery_wal_floor_readback_failed"
            else:
                raise AssertionError("corrupt WAL floor read-back accepted")
        assert not pathlib.Path(paths["wal"]).exists()
