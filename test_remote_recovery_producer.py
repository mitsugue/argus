"""Configured-key acceptance for the real checkpoint recovery producer."""
from __future__ import annotations

import base64
import contextlib
import copy
import json
import os
import pathlib
import tempfile
import types
from unittest import mock

import pytest

import argus_persistent_storage as storage
import argus_remote_journal as journal
import argus_remote_recovery as recovery
import argus_state_journal
import argus_tick_durability as durability


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner
from test_argus_persistent_mission_storage import scanner_storage


BUILD_SHA = "a" * 40
LEDGER_BASE = "b" * 40
CURRENT_ID = "producer-current-v1"
PREVIOUS_ID = "producer-previous-v1"
CURRENT_KEY = bytes(range(32))
PREVIOUS_KEY = bytes(reversed(range(32)))
AT = "2026-08-13T01:02:03Z"
KEY_VARIABLES = (
    "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID",
    "ARGUS_REMOTE_RECOVERY_CURRENT_KEY",
    "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID",
    "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY",
)


def _encoded_key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@contextlib.contextmanager
def _key_environment(*, configured: bool, previous: bool = False):
    with mock.patch.dict(os.environ, {}, clear=False):
        for name in KEY_VARIABLES:
            os.environ.pop(name, None)
        os.environ["RENDER_GIT_COMMIT"] = BUILD_SHA
        if configured:
            os.environ.update({
                "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": CURRENT_ID,
                "ARGUS_REMOTE_RECOVERY_CURRENT_KEY":
                    _encoded_key(CURRENT_KEY),
            })
            if previous:
                os.environ.update({
                    "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": PREVIOUS_ID,
                    "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY":
                        _encoded_key(PREVIOUS_KEY),
                })
        yield


def _reset_recovery_targets() -> None:
    for target in (
            scanner._OPS_JOURNAL, scanner._OPS_JOURNAL_COMPACT,
            scanner._MISSIONS, scanner._MISSION_WINDOWS,
            scanner._FORECAST_LEDGER, scanner._OUTCOME_LEDGER,
            scanner._INCIDENTS, scanner._POSTMORTEMS,
            scanner._PERIODIC_REPORTS, scanner._CHALLENGER_RUNS):
        target.clear()
    scanner._OPS_JOURNAL_META.clear()
    scanner._OPS_SEQ.clear()
    scanner._OSINT_AGENT_QUEUE.clear()
    scanner._SOAK.clear()
    scanner._MISSION_BATCH_STATE.clear()
    scanner._MISSION_BATCH_STATE.update({
        "schemaVersion": "argus-mission-batch-v1",
        "cursor": 0,
        "remainingCount": 0,
        "lastJobId": "producer-test",
        "lastResult": "completed",
        "lastCompletedAt": AT,
        "walAppliedSequence": 0,
    })
    event = argus_state_journal.event(
        event_type="mission_completed", aggregate_type="mission",
        aggregate_id="producer-test", sequence=1, occurred_at=AT,
        payload={"missionType": "ordinary"})
    assert event is not None
    scanner._OPS_JOURNAL.append(event)
    scanner._OPS_SEQ["mission:producer-test"] = 1
    scanner._OPS_JOURNAL_META.update({"totalObserved": 1})
    scanner._MISSIONS.append({"missionId": "producer-test"})
    outcome = {"id": "producer-outcome", "status": "resolved"}
    outcome["integrityHash"] = journal._h(outcome)
    scanner._OUTCOME_LEDGER.append(outcome)
    scanner._OSINT_AGENT_QUEUE["PROBE"] = {"mode": "deep"}


def _append_verified_cycle(paths, sequence: int = 1) -> None:
    durability.append_wal(
        paths["wal"], sequence=sequence, kind="journal_transition",
        job_id="producer-test",
        payload={"transitionId": f"producer-{sequence}"},
        occurred_at=AT)
    compact_receipt_hash = f"{sequence:016x}"
    scanner._REMOTE_CYCLE.update({
        "remoteCommitSha": LEDGER_BASE,
        "receiptCommitSha": LEDGER_BASE,
        "committedAt": AT,
        "readBackAt": AT,
        "readBackVerified": True,
        "walReadBackVerified": True,
        "expectedHash": "c" * 16,
        "actualHash": "c" * 16,
        "remoteWalAppliedSequence": sequence,
        "verifiedWalSequence": sequence,
        "compactReceiptHash": compact_receipt_hash,
        "errorClass": None,
        "walErrorClass": None,
        "remoteDurabilityState": "verified",
        "receiptCreatedAt": AT,
        "receiptVerifiedAt": AT,
        "receiptAgeSeconds": 0,
        "receiptAttempts": 1,
        "receiptErrorClass": None,
    })
    write = scanner._persist_remote_wal_receipt(saved_at=AT)
    assert write["readBackVerified"] is True


def _load_sidecar(path: str):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _activate_clean_legacy_nonce_authority(paths):
    """Run the production genesis proof before producer-only unit calls."""
    storage.write_checkpoint(
        paths["checkpoint"], {"schemaVersion": "argus-durable-v3"},
        temp_directory=paths["tempDirectory"])
    checkpoint = storage.load_checkpoint(
        paths["checkpoint"], require_seal=True)
    pinned = {
        "base": "https://raw.githubusercontent.com/owner/repository/" +
                "a" * 40 + "/ledger",
        "commitSha": "a" * 40, "owner": "owner",
        "repository": "repository", "pathPrefix": "ledger",
    }
    with mock.patch.object(
            scanner, "_probe_pinned_remote_recovery_nonce_floor",
            return_value=None), mock.patch.object(
            scanner, "_pinned_recovery_path_never_existed",
            return_value=True):
        result = scanner._prepare_keyed_local_recovery_nonce_boot(
            checkpoint, recovery.configured_keys(), pinned)
    assert result["status"] == "activated_genesis"


def test_configured_producer_binds_exact_verified_checkpoint_and_current_key():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True, previous=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths)
        _activate_clean_legacy_nonce_authority(paths)
        real_atomic_write = storage.atomic_write_json
        with mock.patch.object(
                recovery, "encrypt_payload",
                wraps=recovery.encrypt_payload) as encrypt_spy, \
                mock.patch.object(
                    storage, "atomic_write_json",
                    wraps=real_atomic_write) as write_spy, \
                mock.patch.object(
                    storage.os, "fsync", wraps=storage.os.fsync) as fsync_spy:
            checkpoint_result = scanner._osint_persist()

        assert checkpoint_result["verified"] is True
        assert checkpoint_result["postVerify"]["status"] == "verified"
        assert checkpoint_result["walCompaction"]["compactedThrough"] == 1
        assert encrypt_spy.call_count == 1
        assert encrypt_spy.call_args.args[1] == CURRENT_KEY
        assert encrypt_spy.call_args.kwargs["key_identifier"] == CURRENT_ID
        assert fsync_spy.call_count > 0
        sidecar_writes = [
            call for call in write_spy.call_args_list
            if call.args and os.path.abspath(call.args[0]) ==
            os.path.abspath(paths["recovery"])
        ]
        assert len(sidecar_writes) == 1
        assert callable(sidecar_writes[0].kwargs["validator"])

        checkpoint = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        marker = checkpoint["remoteRecoveryRequired"]
        assert marker == {
            "schemaVersion": recovery.SIDECAR_SCHEMA,
            "mode": "encrypted_required",
            "keyId": CURRENT_ID,
            "checkpointId": marker["checkpointId"],
        }
        assert recovery.CHECKPOINT_ID_RE.fullmatch(marker["checkpointId"])

        sidecar = recovery.validate_sidecar(_load_sidecar(paths["recovery"]))
        payload = recovery.validate_pair(
            sidecar["readback"], sidecar["recovery"], CURRENT_KEY,
            key_identifier=CURRENT_ID)
        assert sidecar["recovery"]["keyId"] == CURRENT_ID
        assert payload["checkpointId"] == marker["checkpointId"]
        assert payload["sourceCheckpointHash"] == \
            checkpoint_result["snapshotHash"]
        assert payload["ledgerBaseCommitSha"] == LEDGER_BASE
        assert payload["compactReadback"] == sidecar["readback"]
        assert set(payload["targets"]) == set(recovery.TARGET_KEYS)
        assert payload["targets"]["missions"] == \
            checkpoint["missions"]
        assert payload["targets"]["opsSequenceByAggregate"] == \
            checkpoint["opsSequenceByAggregate"]
        ciphertext = recovery._b64_decode(
            sidecar["recovery"]["ciphertext"], "test_invalid")
        assert len(ciphertext) == recovery.PADDED_PLAINTEXT_BYTES + 16
        public_sidecar = json.dumps(sidecar, sort_keys=True)
        assert "nonceAuthority" not in public_sidecar
        assert "keyMaterialCounters" not in public_sidecar
        for domain in payload["nonceAuthority"]["keyMaterialCounters"]:
            assert domain not in public_sidecar

        keys = recovery.configured_keys()
        assert recovery.decrypt_configured(
            sidecar["recovery"], keys) == payload
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_key_id_mismatch"):
            recovery.decrypt_envelope(
                sidecar["recovery"], PREVIOUS_KEY,
                key_identifier=PREVIOUS_ID)

        # Rotation compatibility is decrypt-only: an old previous-key
        # envelope remains readable, while the real producer call above used
        # current key material exactly once.
        prior_payload = copy.deepcopy(payload)
        prior_payload["nonceAuthority"]["keyMaterialCounters"][
            recovery.nonce_material_domain(PREVIOUS_KEY)] = \
                int.from_bytes(b"\x99" * 12, "big")
        prior_payload["payloadHash"] = recovery._hash({
            name: value for name, value in prior_payload.items()
            if name != "payloadHash"})
        prior = recovery.encrypt_payload(
            prior_payload, PREVIOUS_KEY, key_identifier=PREVIOUS_ID,
            nonce=b"\x99" * 12)
        assert recovery.decrypt_configured(prior, keys) == prior_payload


@pytest.mark.parametrize(
    "failure_point",
    ("encrypt", "sidecar", "write", "pair", "installed_readback"),
)
def test_configured_producer_failure_prevents_wal_compaction_and_preserves_wal(
        failure_point):
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths)
        _activate_clean_legacy_nonce_authority(paths)
        wal_before = pathlib.Path(paths["wal"]).read_bytes()
        real_atomic_write = storage.atomic_write_json

        def fail_recovery_write(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(paths["recovery"]):
                raise storage.PersistentStorageError(
                    "injected_recovery_write_failure")
            return real_atomic_write(path, *args, **kwargs)

        stack = contextlib.ExitStack()
        with stack:
            compact_spy = stack.enter_context(mock.patch.object(
                durability, "compact_verified_wal",
                wraps=durability.compact_verified_wal))
            if failure_point == "encrypt":
                stack.enter_context(mock.patch.object(
                    recovery, "encrypt_payload",
                    side_effect=recovery.RecoveryBundleError(
                        "injected_encrypt_failure")))
            elif failure_point == "sidecar":
                stack.enter_context(mock.patch.object(
                    recovery, "build_sidecar",
                    side_effect=recovery.RecoveryBundleError(
                        "injected_sidecar_failure")))
            elif failure_point == "write":
                stack.enter_context(mock.patch.object(
                    storage, "atomic_write_json",
                    side_effect=fail_recovery_write))
            elif failure_point == "pair":
                stack.enter_context(mock.patch.object(
                    recovery, "validate_pair",
                    side_effect=recovery.RecoveryBundleError(
                        "injected_pair_failure")))
            else:
                stack.enter_context(mock.patch.object(
                    scanner, "_read_local_recovery_sidecar",
                    side_effect=ValueError(
                        "injected_installed_readback_failure")))

            with pytest.raises(
                    scanner._RemoteRecoveryCheckpointError,
                    match="^remote_recovery_sidecar_failed$"):
                scanner._osint_persist()

        assert compact_spy.call_count == 0
        assert pathlib.Path(paths["wal"]).read_bytes() == wal_before
        assert scanner._DURABLE_STATE["remoteRecoverySidecar"][
            "status"] == "failed"
        assert scanner._DURABLE_STATE["integrityStatus"] == "write_failed"
        assert not any(
            row.get("kind") == "checkpoint_verified"
            for row in durability.read_valid_wal(paths["wal"])["records"])


def test_unconfigured_producer_preserves_legacy_checkpoint_and_compaction():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=False), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths)
        checkpoint_result = scanner._osint_persist()

        assert checkpoint_result["verified"] is True
        assert checkpoint_result["postVerify"] == {"status": "not_configured"}
        assert checkpoint_result["walCompaction"]["compactedThrough"] == 1
        checkpoint = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        assert "remoteRecoveryRequired" not in checkpoint
        assert not pathlib.Path(paths["recovery"]).exists()
        assert not pathlib.Path(paths["recoveryNonceState"]).exists()
