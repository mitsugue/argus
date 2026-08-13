"""v13.4.2 asynchronous Remote Journal receipt acceptance and drain tests."""
from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import time
import types
from unittest import mock

import pytest

import argus_remote_journal as journal
import argus_remote_receipt_queue as queue
from scripts.remote_journal_publish_policy import receipt_request


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner


BUILD = "b" * 40
COMMIT = "c" * 40
HASH = "d" * 16
NOW = "2026-08-05T03:00:00Z"


def _accept(store, number, target=None, *, commit=None, accepted_at=NOW):
    return queue.accept_intent(
        store,
        idempotency_key=f"caos-receipt-{number:04d}-{target or number:06d}",
        build_sha=BUILD,
        remote_commit_sha=commit or (f"{number:040x}"[-40:]),
        expected_hash=f"{number:016x}"[-16:],
        target_wal_sequence=target if target is not None else number,
        accepted_at=accepted_at,
    )


def _store(count=1):
    state = queue.empty_store()
    rows = []
    for number in range(1, count + 1):
        state, row, _ = _accept(state, number)
        rows.append(row)
    return state, rows


def _persist_in_memory(store):
    scanner._REMOTE_RECEIPT_QUEUE = copy.deepcopy(store)
    return {"verified": True, "readBackVerified": True}


def _legacy_receipt_readback():
    snapshot = {
        "schemaVersion": journal.SCHEMA_V3,
        "generatedAt": NOW,
        "asOf": NOW,
        "buildIdentity": {"appVersion": "13.4.13", "buildSha": BUILD},
        "outcomes": [],
        "missionTickDurability": {
            "walAppliedSequence": 3296,
            "remoteWalAppliedSequence": 3296,
            "verifiedWalSequence": 3296,
        },
        "marketLedgerStateHash": "1" * 16,
        "chartIntelligenceStateHash": "2" * 16,
        "todayIntelligenceStateHash": "3" * 16,
        "marketReplayStateHash": "4" * 16,
        **journal.snapshot_journal_section(
            events=[], meta={}, now_iso=NOW),
    }
    return journal.compact_readback_snapshot(snapshot)


def _verify_selected(sequence, *, commit=None):
    def verify(now_iso=None, blob=None):
        scanner._REMOTE_CYCLE.update({
            "readBackVerified": True,
            "walReadBackVerified": True,
            "remoteDurabilityState": "verified",
            "verifiedWalSequence": sequence,
            "remoteWalAppliedSequence": sequence,
            "receiptCommitSha": commit or scanner._REMOTE_CYCLE.get(
                "remoteCommitSha"),
            "receiptErrorClass": None,
            "walErrorClass": None,
            "errorClass": None,
        })
        return {"verificationStatus": "verified"}
    return verify


@pytest.fixture(autouse=True)
def restore_scanner_receipt_state():
    saved = {
        "queue": copy.deepcopy(scanner._REMOTE_RECEIPT_QUEUE),
        "cycle": copy.deepcopy(scanner._REMOTE_CYCLE),
        "token": scanner._ARGUS_ADMIN_TOKEN,
    }
    # A prior assertion must never leave the single writer lock held.
    if scanner._REMOTE_RECEIPT_FLUSH_LOCK.locked():
        scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    scanner._REMOTE_RECEIPT_QUEUE = queue.empty_store()
    yield
    if scanner._REMOTE_RECEIPT_FLUSH_LOCK.locked():
        scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    scanner._REMOTE_RECEIPT_QUEUE = saved["queue"]
    scanner._REMOTE_CYCLE.clear()
    scanner._REMOTE_CYCLE.update(saved["cycle"])
    scanner._ARGUS_ADMIN_TOKEN = saved["token"]


def test_post_accepts_and_returns_before_full_checkpoint():
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    started = time.monotonic()
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD), \
            mock.patch.object(scanner, "_persist_remote_receipt_queue",
                              side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_osint_persist") as checkpoint:
        response = scanner.app.test_client().post(
            "/api/argus/admin/remote-journal/commit-receipt",
            headers={"X-ARGUS-ADMIN-TOKEN": "admin",
                     "Idempotency-Key": "caos-receipt-fast-0001"},
            json={"remoteCommitSha": COMMIT, "expectedHash": HASH,
                  "expectedReceiptHash": "e" * 16,
                  "artifactMode": "legacy_full",
                  "backendBuildSha": BUILD, "targetWalSequence": 3296})
    elapsed = time.monotonic() - started
    assert response.status_code == 202
    assert response.get_json()["durabilityState"] == "pending"
    assert response.get_json()["accepted"] is True
    assert elapsed < 1.0
    checkpoint.assert_not_called()


def test_real_legacy_receipt_policy_matches_hardened_endpoint():
    readback = _legacy_receipt_readback()
    request = receipt_request(
        readback,
        remote_commit_sha=COMMIT,
        backend_build_sha=BUILD,
        expected_hash=readback["integrityManifest"]["manifestHash"],
        expected_receipt_hash=readback["receiptHash"],
        artifact_mode="legacy_full",
        idempotency_prefix="caos-scan",
    )
    assert request["payload"]["artifactMode"] == "legacy_full"
    assert request["payload"]["expectedReceiptHash"] == \
        readback["receiptHash"]
    assert request["payload"]["targetWalSequence"] == 3296

    scanner._ARGUS_ADMIN_TOKEN = "admin"
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD), \
            mock.patch.object(scanner, "_persist_remote_receipt_queue",
                              side_effect=_persist_in_memory):
        response = scanner.app.test_client().post(
            "/api/argus/admin/remote-journal/commit-receipt",
            headers={
                "X-ARGUS-ADMIN-TOKEN": "admin",
                "Idempotency-Key": request["idempotencyKey"],
            },
            json=request["payload"],
        )
    assert response.status_code == 202
    assert response.get_json()["accepted"] is True


def test_post_auth_schema_sha_sequence_and_idempotency_are_fail_closed():
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    client = scanner.app.test_client()
    assert client.post(
        "/api/argus/admin/remote-journal/commit-receipt").status_code == 401
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD), \
            mock.patch.object(scanner, "_persist_remote_receipt_queue",
                              side_effect=_persist_in_memory):
        invalid = client.post(
            "/api/argus/admin/remote-journal/commit-receipt",
            headers={"X-ARGUS-ADMIN-TOKEN": "admin"},
            json={"remoteCommitSha": COMMIT, "expectedHash": HASH,
                  "backendBuildSha": BUILD, "targetWalSequence": 1})
        mismatch = client.post(
            "/api/argus/admin/remote-journal/commit-receipt",
            headers={"X-ARGUS-ADMIN-TOKEN": "admin",
                     "Idempotency-Key": "caos-receipt-build-0001"},
            json={"remoteCommitSha": COMMIT, "expectedHash": HASH,
                  "expectedReceiptHash": "e" * 16,
                  "artifactMode": "legacy_full",
                  "backendBuildSha": "a" * 40, "targetWalSequence": 1})
    assert invalid.status_code == 400
    assert mismatch.status_code == 409


def test_duplicate_idempotency_key_and_same_target_sequence_are_auditable():
    state, first, replay = _accept(queue.empty_store(), 1, 42)
    state, same, replay = queue.accept_intent(
        state, idempotency_key=first["idempotencyKey"], build_sha=BUILD,
        remote_commit_sha=first["remoteCommitSha"],
        expected_hash=first["expectedHash"], target_wal_sequence=42,
        accepted_at="2026-08-05T03:01:00Z")
    assert replay is True
    assert same["acceptedAt"] == NOW
    state, second, replay = _accept(state, 2, 42)
    assert replay is False
    assert second["receiptId"] != first["receiptId"]
    assert len(state["receipts"]) == 2
    with pytest.raises(queue.ReceiptQueueError, match="idempotency_key_conflict"):
        queue.accept_intent(
            state, idempotency_key=first["idempotencyKey"], build_sha=BUILD,
            remote_commit_sha="e" * 40, expected_hash=first["expectedHash"],
            target_wal_sequence=42, accepted_at=NOW)


def test_accepted_intent_survives_restart_and_status_is_public_safe():
    state, receipt, _ = _accept(queue.empty_store(), 1, 3296)
    with tempfile.TemporaryDirectory() as root:
        path = pathlib.Path(root, "queue.json")
        scanner.argus_persistent_storage.atomic_write_json(
            str(path), state, temp_directory=root,
            validator=queue.verify_store)
        restored = json.loads(path.read_text(encoding="utf-8"))
    assert queue.verify_store(restored)
    status = queue.status_view(restored["receipts"][0], now_iso=NOW)
    assert status["operationId"] == receipt["operationId"]
    assert status["durabilityState"] == "pending"
    assert "idempotencyKey" not in status
    assert "expectedHash" not in status
    assert status["remoteCommitSha"] == receipt["remoteCommitSha"]


def test_33_distinct_commits_ack_oldest_exact_intent_without_regression():
    scanner._REMOTE_RECEIPT_QUEUE, rows = _store(33)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(1)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}) as checkpoint:
        result = scanner._persist_with_remote_receipt_drain(NOW)
    checkpoint.assert_called_once_with()
    flush = result["remoteReceiptFlush"]
    assert flush["coalescedReceiptCount"] == 1
    assert flush["targetWalSequence"] == 1
    assert flush["queueBefore"] == 33
    assert flush["queueAfter"] == 32
    assert flush["checkpointCreated"] is True
    assert sum(row["durabilityState"] == "verified"
               for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]) == 1
    assert {row["receiptId"] for row in rows} == {
        row["receiptId"] for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]}
    first_status = queue.status_view(
        scanner._REMOTE_RECEIPT_QUEUE["receipts"][0], now_iso=NOW)
    assert first_status["remoteCommitSha"] == f"{1:040x}"
    assert first_status["verifiedByRemoteCommitSha"] == f"{1:040x}"
    last_status = queue.status_view(
        scanner._REMOTE_RECEIPT_QUEUE["receipts"][-1], now_iso=NOW)
    assert last_status["verifiedByRemoteCommitSha"] is None


def test_newer_receipt_arriving_during_flush_remains_pending():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(2)

    def verify_with_arrival(now_iso=None, blob=None):
        updated, _, _ = _accept(scanner._REMOTE_RECEIPT_QUEUE, 3, 3)
        _persist_in_memory(updated)
        return _verify_selected(1)(now_iso, blob)

    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=verify_with_arrival), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              side_effect=lambda: {"verified": True}):
        result = scanner._persist_with_remote_receipt_drain(NOW)
    assert result["remoteReceiptFlush"]["coalescedReceiptCount"] == 1
    pending = [row for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]
               if row["durabilityState"] == "pending"]
    assert [row["targetWalSequence"] for row in pending] == [2, 3]


@pytest.mark.parametrize("error_class", ["timeout", "http_500", "http_403",
                                           "http_429"])
def test_transient_timeout_5xx_auth_and_rate_limit_are_classified(error_class):
    scanner._REMOTE_RECEIPT_QUEUE, rows = _store(1)

    def failure(now_iso=None, blob=None):
        scanner._REMOTE_CYCLE.update({
            "readBackVerified": False, "walReadBackVerified": False,
            "receiptErrorClass": error_class,
            "remoteDurabilityState": "transient_failure"})
        return None

    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=failure):
        plan = scanner._prepare_remote_receipt_drain(NOW)
        scanner._complete_remote_receipt_drain(
            plan, {"verified": True}, NOW)
    receipt = queue.get_receipt(
        scanner._REMOTE_RECEIPT_QUEUE, rows[0]["operationId"])
    assert receipt["durabilityState"] == "pending"
    assert receipt["lastErrorClass"] == error_class
    assert receipt["attempts"] == 1
    assert receipt["nextAttemptAt"] > NOW


def test_delayed_readback_retries_and_later_verifies():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    calls = {"count": 0}

    def delayed(now_iso=None, blob=None):
        calls["count"] += 1
        if calls["count"] == 1:
            scanner._REMOTE_CYCLE.update({
                "readBackVerified": False, "walReadBackVerified": False,
                "receiptErrorClass": "exact_commit_not_available"})
            return None
        return _verify_selected(1)(now_iso, blob)

    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=delayed), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              side_effect=lambda: {"verified": True}):
        first = scanner._persist_with_remote_receipt_drain(NOW)
        second = scanner._persist_with_remote_receipt_drain(
            "2026-08-05T03:01:00Z")
    assert first["remoteReceiptFlush"]["status"] == "pending_retry"
    assert second["remoteReceiptFlush"]["status"] == "verified"


def test_poison_receipt_isolated_without_blocking_newer_valid_receipt():
    scanner._REMOTE_RECEIPT_QUEUE, rows = _store(1)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(2)), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}):
        poisoned = scanner._persist_with_remote_receipt_drain(NOW)
    assert poisoned["remoteReceiptFlush"]["status"] == "failed"
    failed = queue.get_receipt(
        scanner._REMOTE_RECEIPT_QUEUE, rows[0]["operationId"])
    assert failed["poison"] is True
    updated, _, _ = _accept(scanner._REMOTE_RECEIPT_QUEUE, 2, 2)
    scanner._REMOTE_RECEIPT_QUEUE = updated
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(2)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}):
        recovered = scanner._persist_with_remote_receipt_drain(
            "2026-08-05T03:01:00Z")
    assert recovered["remoteReceiptFlush"]["status"] == "verified"
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["verifiedCount"] == 1


def test_writer_lock_contention_is_bounded_and_does_not_drop_queue():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    scanner._REMOTE_RECEIPT_FLUSH_LOCK.acquire()
    try:
        plan = scanner._prepare_remote_receipt_drain(NOW)
    finally:
        scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    assert plan["status"] == "writer_lock_contended"
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["pendingCount"] == 1


def test_checkpoint_failure_keeps_receipt_pending_for_retry():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(1)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": False}):
        result = scanner._persist_with_remote_receipt_drain(NOW)
    assert result["remoteReceiptFlush"]["status"] == "pending_retry"
    assert result["remoteReceiptFlush"]["errorClass"] == \
        "checkpoint_persist_failed"
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["pendingCount"] == 1


def test_v2_validation_failure_does_not_overrule_healthy_legacy_checkpoint():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    checkpoint = {"verified": True,
                  "checkpointV2": {"verified": False,
                                   "errorClass": "v2_validation_failed"}}
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(1)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value=checkpoint):
        result = scanner._persist_with_remote_receipt_drain(NOW)
    assert result["remoteReceiptFlush"]["status"] == "verified"
    assert checkpoint["checkpointV2"]["verified"] is False


def test_kill_after_intent_fsync_and_restart_restore_loses_nothing():
    state, receipt, _ = _accept(queue.empty_store(), 1, 3296)
    with tempfile.TemporaryDirectory() as root:
        queue_file = pathlib.Path(root, "queue.json")
        scanner.argus_persistent_storage.atomic_write_json(
            str(queue_file), state, temp_directory=root,
            validator=queue.verify_store)
        scanner._REMOTE_RECEIPT_QUEUE = queue.empty_store()
        with mock.patch.object(scanner, "_REMOTE_RECEIPT_QUEUE_FILE",
                               str(queue_file)):
            restored = scanner._restore_remote_receipt_queue()
    assert restored["status"] == "restored"
    assert queue.get_receipt(scanner._REMOTE_RECEIPT_QUEUE,
                             receipt["operationId"]) is not None


def test_kill_after_remote_verification_before_local_ack_reconciles_once():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(1)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0):
        plan = scanner._prepare_remote_receipt_drain(NOW)
    # Simulated SIGKILL: the queue is still pending, while immutable read-back
    # was already proven.  A later process re-verifies rather than fabricating.
    assert plan["status"] == "verified_checkpoint_pending"
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["pendingCount"] == 1
    scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    plan["lockHeld"] = False
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(1)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}) as checkpoint:
        result = scanner._persist_with_remote_receipt_drain(
            "2026-08-05T03:01:00Z")
    checkpoint.assert_called_once_with()
    assert result["remoteReceiptFlush"]["status"] == "verified"


def test_v1341_migration_preserves_times_proof_and_lower_bound():
    legacy = {
        "schemaVersion": "argus-remote-receipt-v2",
        "remoteCommitSha": COMMIT,
        "expectedHash": HASH,
        "committedAt": NOW,
        "remoteWalAppliedSequence": 0,
        "verifiedWalSequence": 3270,
        "readBackVerified": True,
        "walReadBackVerified": False,
    }
    migrated = queue.migrate_legacy_receipt(
        legacy, backend_build_sha=BUILD,
        idempotency_key="migration-v1341-proof-0001")
    receipt = migrated["receipts"][0]
    assert receipt["acceptedAt"] == NOW
    assert receipt["targetWalSequence"] == 3270
    assert receipt["migrationLowerBound"] is True
    assert receipt["durabilityState"] == "pending"
    again = queue.normalize_store(migrated)
    assert again == migrated


def test_pending_slo_and_exact_status_endpoint_contract():
    state, receipt, _ = _accept(queue.empty_store(), 1, 3296)
    within = queue.status_view(
        receipt, now_iso="2026-08-05T03:29:59Z")
    beyond = queue.status_view(
        receipt, now_iso="2026-08-05T03:30:01Z")
    assert within["ageSeconds"] == 1799
    assert beyond["ageSeconds"] == 1801
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    scanner._REMOTE_RECEIPT_QUEUE = state
    response = scanner.app.test_client().get(
        "/api/argus/admin/remote-journal/receipts/" +
        receipt["operationId"],
        headers={"X-ARGUS-ADMIN-TOKEN": "admin"})
    body = response.get_json()
    assert response.status_code == 200
    for key in ("operationId", "receiptId", "acceptedAt",
                "targetWalSequence", "durabilityState", "remoteCommitSha",
                "readBackVerified", "verifiedAt", "attempts",
                "lastErrorClass", "ageSeconds"):
        assert key in body
    assert "expectedHash" not in body
    assert "idempotencyKey" not in body


def test_exact_wal_sequence_mismatch_is_poison_and_never_acknowledged():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(2)), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}) as checkpoint:
        result = scanner._persist_with_remote_receipt_drain(NOW)
    checkpoint.assert_called_once_with()
    assert result["remoteReceiptFlush"]["status"] == "failed"
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["failedCount"] == 1


def test_invalid_queue_never_silently_resets_or_loses_records():
    state, _, _ = _accept(queue.empty_store(), 1, 1)
    tampered = copy.deepcopy(state)
    tampered["receipts"][0]["targetWalSequence"] = 999
    with pytest.raises(queue.ReceiptQueueError,
                       match="receipt_queue_integrity_invalid"):
        _accept(tampered, 2, 2)
    assert len(tampered["receipts"]) == 1


def test_no_duplicate_checkpoint_storm_one_normal_checkpoint_per_lifecycle():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _store(1)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(1)), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              side_effect=lambda: {"verified": True}) as checkpoint:
        first = scanner._persist_with_remote_receipt_drain(NOW)
        second = scanner._persist_with_remote_receipt_drain(
            "2026-08-05T03:30:00Z")
    assert checkpoint.call_count == 2
    assert first["remoteReceiptFlush"]["checkpointCreated"] is True
    assert second["remoteReceiptFlush"]["status"] == "noop"
    assert second["remoteReceiptFlush"]["checkpointCreated"] is False
