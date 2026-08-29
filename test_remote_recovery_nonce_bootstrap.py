"""Cross-host AES-GCM nonce-floor bootstrap regressions."""
from __future__ import annotations

import base64
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import types
from unittest import mock

import pytest

import argus_persistent_storage as storage
import argus_remote_journal as journal
import argus_remote_recovery as recovery


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner
from test_argus_persistent_mission_storage import remote_snapshot


CURRENT_ID = "bootstrap-current-v1"
PREVIOUS_ID = "bootstrap-previous-v1"
CURRENT_KEY = bytes(range(32))
PREVIOUS_KEY = bytes(reversed(range(32)))


def _encoded_key(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _key_env(*, previous=False):
    value = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": CURRENT_ID,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(CURRENT_KEY),
    }
    if previous:
        value.update({
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": PREVIOUS_ID,
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY": _encoded_key(PREVIOUS_KEY),
        })
    return value


def _paths(root):
    return storage.configured_paths({
        "ARGUS_PERSISTENT_ROOT": str(root),
        "ARGUS_REMOTE_RECOVERY_FILE": str(Path(root) / "recovery.json"),
        "ARGUS_REMOTE_RECOVERY_NONCE_STATE_FILE": str(
            Path(root) / "nonce-state.json"),
        "ARGUS_CHECKPOINT_TEMP_DIR": str(root),
    }, production=False)


def _install_paths(root):
    configured = _paths(root)
    scanner._DURABILITY_PATHS = configured
    scanner._OSINT_PERSIST_FILE = configured["checkpoint"]
    scanner._REMOTE_RECOVERY_FILE = configured["recovery"]
    return configured


def _write_state(path, counters):
    value = {
        "schemaVersion": scanner._REMOTE_RECOVERY_NONCE_STATE_LEGACY_SCHEMA,
        "keyMaterialCounters": dict(counters),
    }
    storage.atomic_write_json(
        str(path), value, temp_directory=str(path.parent),
        maximum_bytes=scanner._REMOTE_RECOVERY_NONCE_STATE_MAX_BYTES)


def _event(sequence):
    body = {
        "eventId": f"bootstrap-event-{sequence}",
        "eventType": "mission_completed",
        "aggregateType": "mission",
        "aggregateId": "bootstrap",
        "sequence": sequence,
        "occurredAt": "2026-08-13T01:02:03Z",
        "idempotencyKey": f"mission:bootstrap:{sequence}",
        "privacyClassification": "public_safe",
        "payload": {"missionType": "ordinary"},
    }
    body["integrityHash"] = scanner.argus_remote_journal._h(body)
    return body


def _envelope(key, key_id, counter):
    return _envelope_with_authority(
        key, key_id, counter,
        {recovery.nonce_material_domain(key): counter})


def _envelope_with_authority(key, key_id, counter, counters):
    generated_at = "2026-08-13T01:02:03Z"
    target_wal = 4701
    event = _event(1)
    meta = {
        "totalObserved": 1,
        scanner.argus_remote_journal.OPS_SEQUENCE_HIGH_WATER_FIELD: 1,
    }
    section = scanner.argus_remote_journal.snapshot_journal_section(
        events=[event], meta=meta, compacted=[], now_iso=generated_at)
    durability = {
        "walAppliedSequence": target_wal,
        "remoteWalAppliedSequence": target_wal,
        "verifiedWalSequence": target_wal,
    }
    compact = scanner.argus_remote_journal.build_compact_readback_snapshot(
        schema_version=scanner.argus_remote_journal.SCHEMA_V3,
        generated_at=generated_at, as_of=generated_at,
        build_identity={"appVersion": "13.4.13", "buildSha": "b" * 40},
        ops_journal=section["opsJournal"],
        integrity_manifest=section["integrityManifest"], outcomes=[],
        mission_tick_durability=durability,
        market_ledger_state_hash="1" * 16,
        chart_intelligence_state_hash="2" * 16,
        today_intelligence_state_hash="3" * 16,
        market_replay_state_hash="4" * 16)
    targets = {
        "opsJournal": copy.deepcopy(section["opsJournal"]),
        "opsJournalMeta": meta,
        "opsJournalCompacted": [],
        "opsSequenceByAggregate": {"mission:bootstrap": 1},
        "missions": [], "missionWindows": [], "forecasts": [],
        "outcomes": [], "incidents": [], "soak": {},
        "postmortems": [], "periodicReports": [], "challengerRuns": [],
        "agentQueue": {}, "missionTickDurability": durability,
    }
    payload = recovery.build_payload(
        compact_readback=compact, targets=targets,
        generated_at=generated_at,
        build_identity={"appVersion": "13.4.13", "buildSha": "b" * 40},
        source_checkpoint_hash="c" * 64,
        checkpoint_id="rcp-" + "d" * 32,
        checkpoint_verified_at=generated_at,
        ledger_base_commit_sha="e" * 40,
        nonce_authority={
            "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
            "keyMaterialCounters": dict(counters),
        })
    return compact, recovery.encrypt_payload(
        payload, key, key_identifier=key_id,
        nonce=counter.to_bytes(12, "big"),
        generation_id="rrg-" + "f" * 32)


@pytest.fixture
def bootstrap_runtime(tmp_path):
    saved_paths = scanner._DURABILITY_PATHS
    saved_checkpoint = scanner._OSINT_PERSIST_FILE
    saved_recovery = scanner._REMOTE_RECOVERY_FILE
    configured = _install_paths(tmp_path)
    try:
        yield configured
    finally:
        scanner._DURABILITY_PATHS = saved_paths
        scanner._OSINT_PERSIST_FILE = saved_checkpoint
        scanner._REMOTE_RECOVERY_FILE = saved_recovery


def _authenticated_floor(key, key_id, counter):
    compact, envelope = _envelope(key, key_id, counter)
    recovery.validate_pair(
        compact, envelope, key, key_identifier=key_id)
    return scanner._authenticated_remote_recovery_nonce_floor(
        envelope, {"keyId": key_id, "key": key})


def _pinned():
    return {
        "base": "https://raw.githubusercontent.com/owner/repository/" +
                "a" * 40 + "/ledger",
        "commitSha": "a" * 40,
        "owner": "owner", "repository": "repository",
        "pathPrefix": "ledger",
    }


def _install_sidecar(root, key, key_id, counter):
    compact, envelope = _envelope(key, key_id, counter)
    sidecar = recovery.build_sidecar(compact, envelope)
    storage.atomic_write_json(
        str(Path(root) / "recovery.json"), sidecar,
        temp_directory=str(root), maximum_bytes=recovery.MAX_SIDECAR_BYTES)
    return sidecar


def _write_clean_legacy_checkpoint(root, *, marker=False):
    value = remote_snapshot(4701)
    if marker:
        value["remoteRecoveryRequired"] = {
            "schemaVersion": recovery.SIDECAR_SCHEMA,
            "mode": "encrypted_required", "keyId": CURRENT_ID,
            "checkpointId": "rcp-" + "1" * 32,
        }
    storage.write_checkpoint(
        scanner._DURABILITY_PATHS["checkpoint"], value,
        temp_directory=str(root))
    return storage.load_checkpoint(
        scanner._DURABILITY_PATHS["checkpoint"], require_seal=True)


def _observed_sized_legacy_readback(target_bytes=1_065_021):
    """Create an exact-size legacy proof with retained outcome evidence."""
    generated_at = "2026-08-13T01:02:03Z"
    target_wal = 4701
    event = _event(1)
    meta = {
        "totalObserved": 1,
        journal.OPS_SEQUENCE_HIGH_WATER_FIELD: 1,
    }
    section = journal.snapshot_journal_section(
        events=[event], meta=meta, compacted=[], now_iso=generated_at)
    durability = {
        "walAppliedSequence": target_wal,
        "remoteWalAppliedSequence": target_wal,
        "verifiedWalSequence": target_wal,
    }
    outcome = {
        "id": "outcome-first-activation",
        "forecastId": "forecast-first-activation",
        "status": "unresolved",
        "resolutionState": "retry_pending",
        "transitionHistory": [{
            "from": "unresolved_missing_price", "to": "retry_pending",
            "at": generated_at, "reason": "missing_price",
        }],
        "retainedEvidenceA": "",
        "retainedEvidenceB": "",
    }

    def build():
        sealed = dict(outcome)
        sealed["integrityHash"] = journal._h(sealed)
        return journal.build_compact_readback_snapshot(
            schema_version=journal.SCHEMA_V3,
            generated_at=generated_at, as_of=generated_at,
            build_identity={"appVersion": "13.5.36", "buildSha": "b" * 40},
            ops_journal=section["opsJournal"],
            integrity_manifest=section["integrityManifest"],
            outcomes=[sealed], mission_tick_durability=durability,
            market_ledger_state_hash="1" * 16,
            chart_intelligence_state_hash="2" * 16,
            today_intelligence_state_hash="3" * 16,
            market_replay_state_hash="4" * 16)

    baseline = build()
    remaining = target_bytes - journal.compact_readback_serialized_size(
        baseline)
    assert remaining >= 0
    outcome["retainedEvidenceA"] = "x" * min(remaining, 900_000)
    remaining -= len(outcome["retainedEvidenceA"])
    outcome["retainedEvidenceB"] = "x" * remaining
    exact = build()
    assert journal.compact_readback_serialized_size(exact) == target_bytes
    return exact, meta, durability


def _seed_worker(root, start, result, remote_counter):
    try:
        os.environ.clear()
        os.environ.update(_key_env())
        _install_paths(root)
        floor = _authenticated_floor(
            CURRENT_KEY, CURRENT_ID, remote_counter)
        start.wait()
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            floor, recovery.configured_keys())
        nonce = scanner._next_remote_recovery_nonce(
            CURRENT_ID, authenticated_remote_floor=floor)
        result.put(("ok", int.from_bytes(nonce, "big")))
    except Exception as exc:  # pragma: no cover - surfaced by parent assertion
        result.put(("error", type(exc).__name__, str(exc)))


def test_same_current_remote_floor_reserves_n_plus_one_and_stays_private(
        bootstrap_runtime):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        floor = _authenticated_floor(CURRENT_KEY, CURRENT_ID, 91)
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            floor, recovery.configured_keys())
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            CURRENT_ID, authenticated_remote_floor=floor), "big") == 92

    state_path = Path(bootstrap_runtime["recoveryNonceState"])
    encoded = state_path.read_text(encoding="utf-8")
    assert CURRENT_ID not in encoded
    assert _encoded_key(CURRENT_KEY) not in encoded
    durable_json = json.dumps(scanner._DURABLE_STATE)
    assert CURRENT_ID not in durable_json
    assert "keyMaterialCounters" not in durable_json
    assert "recoveryNonceCounter" not in durable_json
    with pytest.raises(TypeError):
        json.dumps(floor)


def test_overlay_seeds_only_after_exact_pair_authentication_and_hands_off(
        bootstrap_runtime):
    compact, envelope = _envelope(CURRENT_KEY, CURRENT_ID, 63)
    sidecar = recovery.build_sidecar(compact, envelope)
    handoff = []
    with mock.patch.dict(os.environ, _key_env(), clear=True), \
            mock.patch.object(
                scanner, "_fetch_pinned_recovery_object",
                side_effect=[
                    {"status": "present", "value": compact},
                    {"status": "present", "value": sidecar},
                ]), \
            mock.patch.object(
                scanner, "_verify_authenticated_ledger_commit_path",
                return_value={"status": "verified", "distance": 0}):
        merged = scanner._overlay_remote_recovery(
            remote_snapshot(4600), "https://pinned.invalid/ledger",
            "a" * 40, ledger_owner="owner", ledger_repository="repository",
            nonce_floor_handoff=handoff)
    assert len(handoff) == 1
    state = scanner._read_remote_recovery_nonce_state(
        bootstrap_runtime["recoveryNonceState"], missing_ok=False)
    assert state["keyMaterialCounters"] == {
        scanner._remote_recovery_nonce_domain(CURRENT_KEY): 63}
    serialized = json.dumps(merged, sort_keys=True)
    assert _encoded_key(CURRENT_KEY) not in serialized
    assert "keyMaterialCounters" not in serialized
    assert '"nonce"' not in serialized
    assert "_remote_counter" not in serialized


def test_overlay_authentication_failure_never_seeds_remote_floor(
        bootstrap_runtime):
    compact, envelope = _envelope(CURRENT_KEY, CURRENT_ID, 63)
    sidecar = recovery.build_sidecar(compact, envelope)
    wrong_env = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": CURRENT_ID,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(PREVIOUS_KEY),
    }
    with mock.patch.dict(os.environ, wrong_env, clear=True), \
            mock.patch.object(
                scanner, "_fetch_pinned_recovery_object",
                side_effect=[
                    {"status": "present", "value": compact},
                    {"status": "present", "value": sidecar},
                ]), \
            mock.patch.object(
                scanner, "_verify_authenticated_ledger_commit_path",
                return_value={"status": "verified", "distance": 0}), \
            pytest.raises(scanner._RemoteRecoveryRestoreError,
                          match="recovery_authentication_failed"):
        scanner._overlay_remote_recovery(
            remote_snapshot(4600), "https://pinned.invalid/ledger",
            "a" * 40, ledger_owner="owner", ledger_repository="repository",
            nonce_floor_handoff=[])
    assert not Path(bootstrap_runtime["recoveryNonceState"]).exists()


def test_previous_remote_floor_is_retained_while_current_starts_at_one(
        bootstrap_runtime):
    with mock.patch.dict(os.environ, _key_env(previous=True), clear=True):
        floor = _authenticated_floor(PREVIOUS_KEY, PREVIOUS_ID, 77)
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            floor, recovery.configured_keys())
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            CURRENT_ID, authenticated_remote_floor=floor), "big") == 1
        state = scanner._read_remote_recovery_nonce_state(
            bootstrap_runtime["recoveryNonceState"], missing_ok=False)
    assert state["keyMaterialCounters"] == {
        scanner._remote_recovery_nonce_domain(PREVIOUS_KEY): 77,
        scanner._remote_recovery_nonce_domain(CURRENT_KEY): 1,
    }


@pytest.mark.parametrize("mutation", ["delete", "rollback"])
def test_seeded_floor_state_loss_repairs_from_history_before_nonce_return(
        bootstrap_runtime, mutation):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        floor = _authenticated_floor(CURRENT_KEY, CURRENT_ID, 54)
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            floor, recovery.configured_keys())
        state_path = Path(bootstrap_runtime["recoveryNonceState"])
        if mutation == "delete":
            state_path.unlink()
        else:
            _write_state(state_path, {
                scanner._remote_recovery_nonce_domain(CURRENT_KEY): 53})
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            CURRENT_ID, authenticated_remote_floor=floor), "big") == 55


def test_concurrent_bootstrap_reservations_are_unique_and_above_remote_floor(
        bootstrap_runtime, tmp_path):
    context = multiprocessing.get_context("fork")
    start = context.Event()
    result = context.Queue()
    workers = [context.Process(
        target=_seed_worker,
        args=(str(tmp_path), start, result, 200)) for _ in range(8)]
    for worker in workers:
        worker.start()
    start.set()
    observed = [result.get(timeout=30) for _ in workers]
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0
    assert all(row[0] == "ok" for row in observed), observed
    assert sorted(row[1] for row in observed) == list(range(201, 209))
    state = scanner._read_remote_recovery_nonce_state(
        bootstrap_runtime["recoveryNonceState"], missing_ok=False)
    assert state["keyMaterialCounters"][
        scanner._remote_recovery_nonce_domain(CURRENT_KEY)] == 208


def test_unauthenticated_or_unavailable_material_cannot_seed(
        bootstrap_runtime):
    compact, envelope = _envelope(CURRENT_KEY, CURRENT_ID, 12)
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_authentication_failed"):
        recovery.validate_pair(
            compact, envelope, PREVIOUS_KEY, key_identifier=CURRENT_ID)

    floor = scanner._authenticated_remote_recovery_nonce_floor(
        envelope, {"keyId": CURRENT_ID, "key": CURRENT_KEY})
    with mock.patch.dict(os.environ, {
            "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": PREVIOUS_ID,
            "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(PREVIOUS_KEY),
    }, clear=True):
        with pytest.raises(recovery.RecoveryBundleError,
                           match="recovery_nonce_bootstrap_key_unavailable"):
            scanner._seed_authenticated_remote_recovery_nonce_floor(
                floor, recovery.configured_keys())


def test_true_clean_legacy_activation_is_single_use_and_starts_at_one(
        bootstrap_runtime, tmp_path):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        checkpoint = _write_clean_legacy_checkpoint(tmp_path)
        assert scanner._remote_recovery_nonce_authority_absent(
            include_lock=True)
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=True):
            result = scanner._prepare_keyed_local_recovery_nonce_boot(
                checkpoint, recovery.configured_keys(), _pinned())
        assert result["status"] == "activated_genesis"
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            CURRENT_ID), "big") == 1


def test_first_activation_migrates_1065021_byte_legacy_readback_exactly(
        bootstrap_runtime, tmp_path):
    compact, meta, durability = _observed_sized_legacy_readback()
    assert journal.verify_strict_compact_readback_snapshot(compact)
    checkpoint = _write_clean_legacy_checkpoint(tmp_path)
    pinned = _pinned()
    with mock.patch.dict(os.environ, _key_env(), clear=True), \
            mock.patch.object(
                scanner, "_fetch_pinned_recovery_object", side_effect=[
                    {"status": "present", "value": compact},
                    {"status": "absent", "value": None},
                ]), \
            mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=True):
        handoff = []
        boot = scanner._prepare_keyed_local_recovery_nonce_boot(
            checkpoint, recovery.configured_keys(), pinned,
            evidence_handoff=handoff)
        assert boot["status"] == "activated_genesis"
        assert len(handoff) == 1
        nonce = scanner._next_remote_recovery_nonce(CURRENT_ID)
        counter = int.from_bytes(nonce, "big")
        targets = {
            "opsJournal": copy.deepcopy(compact["opsJournal"]),
            "opsJournalMeta": copy.deepcopy(meta),
            "opsJournalCompacted": [],
            "opsSequenceByAggregate": {"mission:bootstrap": 1},
            "missions": [], "missionWindows": [], "forecasts": [],
            "outcomes": copy.deepcopy(compact["outcomes"]),
            "incidents": [], "soak": {}, "postmortems": [],
            "periodicReports": [], "challengerRuns": [], "agentQueue": {},
            "missionTickDurability": copy.deepcopy(durability),
        }
        payload = recovery.build_payload(
            compact_readback=compact, targets=targets,
            generated_at=compact["generatedAt"],
            build_identity=compact["buildIdentity"],
            source_checkpoint_hash=storage._canonical_sha256(checkpoint),
            checkpoint_id="rcp-" + "7" * 32,
            checkpoint_verified_at=compact["generatedAt"],
            ledger_base_commit_sha=pinned["commitSha"],
            nonce_authority={
                "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
                "keyMaterialCounters": {
                    recovery.nonce_material_domain(CURRENT_KEY): counter,
                },
            })
        envelope = recovery.encrypt_payload(
            payload, CURRENT_KEY, key_identifier=CURRENT_ID, nonce=nonce,
            generation_id="rrg-" + "8" * 32)
        sidecar = recovery.build_sidecar(compact, envelope)
        restored = recovery.validate_pair(
            sidecar["readback"], sidecar["recovery"], CURRENT_KEY,
            key_identifier=CURRENT_ID)

    assert sidecar["readback"] == compact
    assert restored["compactReadback"] == compact
    assert restored["targets"]["outcomes"] == compact["outcomes"]
    assert recovery.configured_keys({"ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID":
                                     CURRENT_ID,
                                     "ARGUS_REMOTE_RECOVERY_CURRENT_KEY":
                                     _encoded_key(CURRENT_KEY)})[
                                         "previous"] is None
    assert scanner._CHECKPOINT_V2_STAGE1_ENABLED is False


def test_marker_with_total_local_loss_never_becomes_genesis(
        bootstrap_runtime, tmp_path):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        checkpoint = _write_clean_legacy_checkpoint(tmp_path, marker=True)
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=True), pytest.raises(
                    recovery.RecoveryBundleError,
                    match="recovery_nonce_authority_missing"):
            scanner._prepare_keyed_local_recovery_nonce_boot(
                checkpoint, recovery.configured_keys(), _pinned())
        assert scanner._remote_recovery_nonce_authority_absent(
            include_lock=True)


def test_historical_recovery_path_blocks_genesis_without_nonce_files(
        bootstrap_runtime, tmp_path):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        checkpoint = _write_clean_legacy_checkpoint(tmp_path)
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=False), pytest.raises(
                    recovery.RecoveryBundleError,
                    match="recovery_nonce_remote_history_exists"):
            scanner._prepare_keyed_local_recovery_nonce_boot(
                checkpoint, recovery.configured_keys(), _pinned())
        assert scanner._remote_recovery_nonce_authority_absent(
            include_lock=True)


def test_self_consistent_volume_rollback_seeds_remote_m_then_reserves_m_plus_1(
        bootstrap_runtime, tmp_path):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        _install_sidecar(tmp_path, CURRENT_KEY, CURRENT_ID, 31)
        local_floor = scanner._authenticated_installed_recovery_nonce_floor(
            recovery.configured_keys())
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            local_floor, recovery.configured_keys())

        # The local disk is internally consistent at N, while the immutable
        # ledger has already accepted M for the same key material.
        remote_floor = _authenticated_floor(CURRENT_KEY, CURRENT_ID, 79)
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=remote_floor):
            result = scanner._prepare_keyed_local_recovery_nonce_boot(
                {}, recovery.configured_keys(), _pinned())
        assert result["status"] == "seeded"
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            CURRENT_ID, authenticated_remote_floor=remote_floor),
            "big") == 80


def test_local_ahead_of_remote_seed_does_not_append_authority(
        bootstrap_runtime, tmp_path):
    with mock.patch.dict(os.environ, _key_env(), clear=True):
        _install_sidecar(tmp_path, CURRENT_KEY, CURRENT_ID, 91)
        local_floor = scanner._authenticated_installed_recovery_nonce_floor(
            recovery.configured_keys())
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            local_floor, recovery.configured_keys())
        before = scanner._read_remote_recovery_nonce_history(
            bootstrap_runtime["recoveryNonceHistory"], missing_ok=False)
        remote_floor = _authenticated_floor(CURRENT_KEY, CURRENT_ID, 54)
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=remote_floor):
            scanner._prepare_keyed_local_recovery_nonce_boot(
                {}, recovery.configured_keys(), _pinned())
        after = scanner._read_remote_recovery_nonce_history(
            bootstrap_runtime["recoveryNonceHistory"], missing_ok=False)
        assert after == before
        assert remote_floor._seeded_counter == 91


def test_rotation_rollback_latest_pair_restores_every_carried_material_floor(
        bootstrap_runtime):
    """Old key nonce 50 cannot become 11 after disk/config rollback to 10."""
    old_key, new_key = CURRENT_KEY, PREVIOUS_KEY
    old_id, new_id = CURRENT_ID, PREVIOUS_ID
    counters = {
        recovery.nonce_material_domain(old_key): 50,
        recovery.nonce_material_domain(new_key): 100,
    }
    compact, envelope = _envelope_with_authority(
        new_key, new_id, 100, counters)
    sidecar = recovery.build_sidecar(compact, envelope)
    rollback_env = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": old_id,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(old_key),
        "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": new_id,
        "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY": _encoded_key(new_key),
    }
    with mock.patch.dict(os.environ, rollback_env, clear=True):
        # Self-consistent rolled-back local authority and sidecar both say 10.
        _install_sidecar(
            Path(bootstrap_runtime["recovery"]).parent,
            old_key, old_id, 10)
        local = _authenticated_floor(old_key, old_id, 10)
        scanner._seed_authenticated_remote_recovery_nonce_floor(
            local, recovery.configured_keys())
        readback_result = {"status": "present", "value": compact}
        recovery_result = {"status": "present", "value": sidecar}
        with mock.patch.object(
                scanner, "_fetch_pinned_recovery_object",
                side_effect=[readback_result, recovery_result]), \
                mock.patch.object(
                    scanner, "_verify_authenticated_ledger_commit_path",
                    return_value={"status": "verified", "distance": 0}):
            boot = scanner._prepare_keyed_local_recovery_nonce_boot(
                {}, recovery.configured_keys(), _pinned())
        assert boot["status"] == "seeded"
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            old_id), "big") == 51
        state = scanner._read_remote_recovery_nonce_state(
            bootstrap_runtime["recoveryNonceState"], missing_ok=False)
    assert state["keyMaterialCounters"][
        recovery.nonce_material_domain(new_key)] == 100


def test_rotation_carry_forward_survives_key_id_rename(bootstrap_runtime):
    renamed_id = "bootstrap-current-renamed-v2"
    counters = {recovery.nonce_material_domain(CURRENT_KEY): 50}
    compact, envelope = _envelope_with_authority(
        CURRENT_KEY, CURRENT_ID, 50, counters)
    renamed_env = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": renamed_id,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(CURRENT_KEY),
        "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": CURRENT_ID,
        "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY": _encoded_key(CURRENT_KEY),
    }
    sidecar = recovery.build_sidecar(compact, envelope)
    # Identical bytes never create an arbitrary ID fallback: the old ID must
    # be explicitly retained in previous for this transition window.
    with mock.patch.dict(os.environ, {
            "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": renamed_id,
            "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(CURRENT_KEY),
    }, clear=True), pytest.raises(
            recovery.RecoveryBundleError,
            match="recovery_key_id_unavailable"):
        scanner._recovery_key_for_envelope(
            envelope, recovery.configured_keys())
    with mock.patch.dict(os.environ, renamed_env, clear=True), \
            mock.patch.object(
                scanner, "_fetch_pinned_recovery_object", side_effect=[
                    {"status": "present", "value": compact},
                    {"status": "present", "value": sidecar},
                ]), \
            mock.patch.object(
                scanner, "_verify_authenticated_ledger_commit_path",
                return_value={"status": "verified", "distance": 0}):
        keys = recovery.configured_keys()
        assert keys["current"]["keyId"] == renamed_id
        assert keys["previous"]["keyId"] == CURRENT_ID
        authority = scanner._probe_pinned_remote_recovery_nonce_floor(
            keys, _pinned())
        scanner._seed_authenticated_remote_recovery_nonce_authority(
            authority, keys)
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            renamed_id, authenticated_remote_floor=authority), "big") == 51


def test_nonce_authority_map_tamper_and_bounds_fail_closed():
    counters = {recovery.nonce_material_domain(CURRENT_KEY): 41}
    compact, envelope = _envelope_with_authority(
        CURRENT_KEY, CURRENT_ID, 41, counters)
    # Any ciphertext mutation fails tag/hash validation before a map can seed.
    tampered = copy.deepcopy(envelope)
    ciphertext = recovery._b64_decode(
        tampered["ciphertext"], "test_ciphertext_invalid")
    tampered["ciphertext"] = recovery._b64_encode(
        bytes([ciphertext[0] ^ 1]) + ciphertext[1:])
    with pytest.raises(recovery.RecoveryBundleError):
        recovery.validate_pair(
            compact, tampered, CURRENT_KEY, key_identifier=CURRENT_ID)
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_nonce_authority_invalid"):
        recovery.validate_nonce_authority({
            "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
            "keyMaterialCounters": {
                f"{index:064x}": index + 1
                for index in range(
                    recovery.MAX_NONCE_AUTHORITY_DOMAINS + 1)
            },
        })
    _compact, payload_envelope = _envelope_with_authority(
        CURRENT_KEY, CURRENT_ID, 40, counters)
    payload = recovery.decrypt_envelope(
        payload_envelope, CURRENT_KEY, key_identifier=CURRENT_ID)
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_nonce_authority_binding_invalid"):
        recovery.encrypt_payload(
            payload, CURRENT_KEY, key_identifier=CURRENT_ID,
            nonce=(42).to_bytes(12, "big"))


@pytest.mark.parametrize("failure", [
    "network", "wrong_tag", "nonancestor",
])
def test_remote_probe_ambiguity_fails_before_nonce_authority(
        bootstrap_runtime, failure):
    compact, envelope = _envelope(CURRENT_KEY, CURRENT_ID, 41)
    sidecar = recovery.build_sidecar(compact, envelope)
    if failure == "wrong_tag":
        sidecar = copy.deepcopy(sidecar)
        ciphertext = sidecar["recovery"]["ciphertext"]
        replacement = "A" if ciphertext[0] != "A" else "B"
        sidecar["recovery"]["ciphertext"] = replacement + ciphertext[1:]
    results = (
        [{"status": "transport_error", "value": None},
         {"status": "transport_error", "value": None}]
        if failure == "network" else
        [{"status": "present", "value": compact},
         {"status": "present", "value": sidecar}])
    ancestry = (recovery.RecoveryBundleError(
        "recovery_ledger_commit_nonancestor")
        if failure == "nonancestor" else
        {"status": "verified", "distance": 0})
    with mock.patch.dict(os.environ, _key_env(), clear=True), \
            mock.patch.object(
                scanner, "_fetch_pinned_recovery_object",
                side_effect=results), mock.patch.object(
                scanner, "_verify_authenticated_ledger_commit_path",
                side_effect=ancestry), pytest.raises(
                    recovery.RecoveryBundleError):
        scanner._probe_pinned_remote_recovery_nonce_floor(
            recovery.configured_keys(), _pinned())
    assert scanner._remote_recovery_nonce_authority_absent(
        include_lock=True)


def test_path_history_query_ambiguity_is_fail_closed(bootstrap_runtime):
    response = types.SimpleNamespace(
        status_code=503, close=lambda: None,
        iter_content=lambda chunk_size: iter(()))
    with mock.patch.object(scanner.requests, "get", return_value=response), \
            pytest.raises(recovery.RecoveryBundleError,
                          match="recovery_nonce_history_query_ambiguous"):
        scanner._pinned_recovery_path_never_existed(_pinned())
    assert scanner._remote_recovery_nonce_authority_absent(
        include_lock=True)
