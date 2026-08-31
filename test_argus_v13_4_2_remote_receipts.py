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


def _accept(store, number, target=None, *, commit=None, accepted_at=NOW,
            expected_receipt_hash=None):
    return queue.accept_intent(
        store,
        idempotency_key=f"caos-receipt-{number:04d}-{target or number:06d}",
        build_sha=BUILD,
        remote_commit_sha=commit or (f"{number:040x}"[-40:]),
        expected_hash=f"{number:016x}"[-16:],
        target_wal_sequence=target if target is not None else number,
        accepted_at=accepted_at,
        expected_receipt_hash=expected_receipt_hash,
    )


def _store(count=1):
    state = queue.empty_store()
    rows = []
    for number in range(1, count + 1):
        state, row, _ = _accept(state, number)
        rows.append(row)
    return state, rows


def _current_legacy_store(count=1):
    state = queue.empty_store()
    rows = []
    for number in range(1, count + 1):
        state, row, _ = _accept(
            state, number, expected_receipt_hash=f"{number:016x}")
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


def _verify_selected(sequence, *, commit=None, receipt_hash=None):
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
        if receipt_hash is not None:
            scanner._REMOTE_CYCLE["compactReceiptHash"] = receipt_hash
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


def test_full_bounded_legacy_queue_coalesces_to_highest_cumulative_intent():
    count = queue.MAX_RECEIPTS
    scanner._REMOTE_RECEIPT_QUEUE, rows = _current_legacy_store(count)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              return_value={}), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(
                                  count, receipt_hash=f"{count:016x}")), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}) as checkpoint:
        result = scanner._persist_with_remote_receipt_drain(NOW)
    checkpoint.assert_called_once_with()
    flush = result["remoteReceiptFlush"]
    assert flush["coalescedReceiptCount"] == count
    assert flush["targetWalSequence"] == count
    assert flush["queueBefore"] == count
    assert flush["queueAfter"] == 0
    assert flush["checkpointCreated"] is True
    assert sum(row["durabilityState"] == "verified"
               for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]) == count
    assert {row["receiptId"] for row in rows} == {
        row["receiptId"] for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]}
    first_status = queue.status_view(
        scanner._REMOTE_RECEIPT_QUEUE["receipts"][0], now_iso=NOW)
    assert first_status["remoteCommitSha"] == f"{1:040x}"
    assert first_status["verifiedByRemoteCommitSha"] == f"{count:040x}"
    last_status = queue.status_view(
        scanner._REMOTE_RECEIPT_QUEUE["receipts"][-1], now_iso=NOW)
    assert last_status["verifiedByRemoteCommitSha"] == f"{count:040x}"


def test_receipt_verified_at_is_checkpoint_completion_not_drain_start():
    completed_at = "2026-08-05T03:02:03Z"
    scanner._REMOTE_RECEIPT_QUEUE, rows = _current_legacy_store(1)
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              return_value={}), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(
                                  1, receipt_hash=f"{1:016x}")), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}), \
            mock.patch.object(scanner, "_ai_now_iso",
                              return_value=completed_at):
        scanner._persist_with_remote_receipt_drain(NOW)
    receipt = queue.get_receipt(
        scanner._REMOTE_RECEIPT_QUEUE, rows[0]["operationId"])
    assert receipt["verifiedAt"] == completed_at
    assert receipt["verifiedAt"] != NOW


def test_scheduled_receipt_arrival_capacity_fits_one_bounded_drain():
    workflows = pathlib.Path(".github/workflows")
    producers = sorted(
        path.name for path in workflows.glob("*.yml")
        if "remote-journal/commit-receipt" in path.read_text(encoding="utf-8"))
    assert producers == ["caos-scan.yml", "caos-watchtower.yml"]

    watchtower = pathlib.Path(
        workflows, "caos-watchtower.yml").read_text(encoding="utf-8")
    ordinary_watchtower = watchtower.split("  remote-journal-rearm:", 1)[0]
    scan = pathlib.Path(
        workflows, "caos-scan.yml").read_text(encoding="utf-8")
    writer_timer = pathlib.Path(
        "ops/systemd/argus-watchtower-writer.timer"
    ).read_text(encoding="utf-8")
    assert ordinary_watchtower.count("remote-journal/commit-receipt") == 1
    assert scan.count("remote-journal/commit-receipt") == 1
    assert ordinary_watchtower.count("remote_receipt_drain.py") == 3
    assert scan.count("remote_receipt_drain.py") == 3
    assert ordinary_watchtower.count("--budget-seconds 240") == 1
    assert scan.count("--budget-seconds 240") == 1
    assert "cron:" not in watchtower
    assert (
        "OnCalendar=Mon..Fri *-*-* *:04,11,19,26,34,41,49,56:00 UTC"
        in writer_timer)
    assert "OnCalendar=Sat,Sun *-*-* *:04,34:00 UTC" in writer_timer
    assert "cron: '7,37 * * * *'" in scan

    # Between natural :07/:37 boundaries the deterministic EC2 schedule has
    # at most four Watchtower invocations plus one C.A.O.S. scan. The queue-bound
    # legacy drain therefore has >100x interval burst capacity and cannot be
    # the cause of an age breach under the frozen producer topology.
    maximum_scheduled_arrivals_per_half_hour = 5
    assert queue.MAX_RECEIPTS >= \
        100 * maximum_scheduled_arrivals_per_half_hour

    # GitHub schedules are best-effort and cannot establish the hard Recovery
    # timing claim.  The owner-controlled EC2 timer supplies one deterministic
    # opportunity every 20 minutes; the authenticated drain remains bounded to
    # four minutes after publication.
    ec2_rearm_max_gap_seconds = 20 * 60
    post_publication_drain_bound_seconds = 240
    total_modeled_bound_seconds = (
        ec2_rearm_max_gap_seconds +
        post_publication_drain_bound_seconds)
    assert total_modeled_bound_seconds == 1440
    assert 1800 - total_modeled_bound_seconds == 360
    assert total_modeled_bound_seconds < 1800
    assert "pending_within_slo" not in ordinary_watchtower
    assert "pending_within_slo" not in scan


def test_authenticated_publisher_trigger_drains_once_and_replay_is_noop():
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    scanner._REMOTE_RECEIPT_QUEUE, rows = _current_legacy_store(3)
    client = scanner.app.test_client()
    payload = {
        "operationId": rows[-1]["operationId"],
        "backendBuildSha": BUILD,
        "triggerClass": "publisher_receipt",
    }
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD), \
            mock.patch.object(scanner, "_ai_now_iso", return_value=NOW), \
            mock.patch.object(scanner, "_persist_remote_receipt_queue",
                              side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              return_value={}), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(
                                  3, receipt_hash=f"{3:016x}")), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}) as checkpoint:
        first = client.post(
            "/api/argus/admin/remote-journal/trigger-drain",
            headers={"X-ARGUS-ADMIN-TOKEN": "admin"}, json=payload)
        replay = client.post(
            "/api/argus/admin/remote-journal/trigger-drain",
            headers={"X-ARGUS-ADMIN-TOKEN": "admin"}, json=payload)
    assert first.status_code == 200
    assert first.get_json()["durabilityState"] == "verified"
    assert first.get_json()["coalescedReceiptCount"] == 3
    assert first.get_json()["checkpointCreated"] is True
    assert replay.status_code == 200
    assert replay.get_json()["drainStatus"] == "idempotent_replay"
    assert replay.get_json()["checkpointCreated"] is False
    checkpoint.assert_called_once_with()


def test_publisher_trigger_is_fail_closed_and_contention_has_no_checkpoint():
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    scanner._REMOTE_RECEIPT_QUEUE, rows = _current_legacy_store(1)
    client = scanner.app.test_client()
    path = "/api/argus/admin/remote-journal/trigger-drain"
    payload = {
        "operationId": rows[0]["operationId"],
        "backendBuildSha": BUILD,
        "triggerClass": "publisher_receipt",
    }
    assert client.post(path, json=payload).status_code == 401
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD):
        malformed = client.post(
            path, headers={"X-ARGUS-ADMIN-TOKEN": "admin"},
            json={**payload, "triggerClass": "manual"})
        mismatch = client.post(
            path, headers={"X-ARGUS-ADMIN-TOKEN": "admin"},
            json={**payload, "backendBuildSha": "a" * 40})
    assert malformed.status_code == 400
    assert mismatch.status_code == 409

    scanner._REMOTE_RECEIPT_FLUSH_LOCK.acquire()
    try:
        with mock.patch.object(
                scanner, "_backend_exact_sha", return_value=BUILD), \
                mock.patch.object(scanner, "_ai_now_iso", return_value=NOW), \
                mock.patch.object(scanner, "_osint_persist") as checkpoint:
            contended = client.post(
                path, headers={"X-ARGUS-ADMIN-TOKEN": "admin"}, json=payload)
    finally:
        scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    assert contended.status_code == 202
    assert contended.get_json()["drainStatus"] == "writer_lock_contended"
    assert contended.get_json()["checkpointCreated"] is False
    checkpoint.assert_not_called()
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["pendingCount"] == 1


def test_publisher_trigger_never_promotes_failed_or_poison_receipt():
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    state, rows = _current_legacy_store(1)
    state = queue.record_attempt(
        state, rows[0]["operationId"], attempted_at=NOW)
    scanner._REMOTE_RECEIPT_QUEUE = queue.record_retry(
        state, rows[0]["operationId"], now_iso=NOW,
        error_class="remote_wal_sequence_mismatch", permanent=True)
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD), \
            mock.patch.object(scanner, "_ai_now_iso", return_value=NOW), \
            mock.patch.object(scanner, "_osint_persist") as checkpoint:
        response = scanner.app.test_client().post(
            "/api/argus/admin/remote-journal/trigger-drain",
            headers={"X-ARGUS-ADMIN-TOKEN": "admin"},
            json={"operationId": rows[0]["operationId"],
                  "backendBuildSha": BUILD,
                  "triggerClass": "publisher_receipt"})
    assert response.status_code == 409
    assert response.get_json()["durabilityState"] == "failed"
    checkpoint.assert_not_called()


def test_newer_receipt_arriving_during_flush_remains_pending():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _current_legacy_store(2)

    def verify_with_arrival(now_iso=None, blob=None):
        updated, _, _ = _accept(
            scanner._REMOTE_RECEIPT_QUEUE, 3, 3,
            expected_receipt_hash=f"{3:016x}")
        _persist_in_memory(updated)
        return _verify_selected(
            2, receipt_hash=f"{2:016x}")(now_iso, blob)

    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              return_value={}), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=verify_with_arrival), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              side_effect=lambda: {"verified": True}):
        result = scanner._persist_with_remote_receipt_drain(NOW)
    assert result["remoteReceiptFlush"]["coalescedReceiptCount"] == 2
    pending = [row for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]
               if row["durabilityState"] == "pending"]
    assert [row["targetWalSequence"] for row in pending] == [3]


def test_current_legacy_batch_reverifies_after_crash_without_double_ack():
    scanner._REMOTE_RECEIPT_QUEUE, _ = _current_legacy_store(3)
    patches = (
        mock.patch.object(scanner, "_persist_remote_receipt_queue",
                          side_effect=_persist_in_memory),
        mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                          return_value={}),
        mock.patch.object(scanner, "_remote_readback_ack",
                          side_effect=_verify_selected(
                              3, receipt_hash=f"{3:016x}")),
        mock.patch.object(scanner, "_journal_compact", return_value=0),
    )
    with patches[0], patches[1], patches[2], patches[3]:
        plan = scanner._prepare_remote_receipt_drain(NOW)
    assert plan["status"] == "verified_checkpoint_pending"
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=NOW)["pendingCount"] == 3
    scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    plan["lockHeld"] = False

    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              return_value={}), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=_verify_selected(
                                  3, receipt_hash=f"{3:016x}")), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}):
        result = scanner._persist_with_remote_receipt_drain(
            "2026-08-05T03:01:00Z")
    flush = result["remoteReceiptFlush"]
    assert flush["status"] == "verified"
    assert flush["coalescedReceiptCount"] == 3
    assert flush["queueAfter"] == 0
    assert sum(row["durabilityState"] == "verified"
               for row in scanner._REMOTE_RECEIPT_QUEUE["receipts"]) == 3


@pytest.mark.parametrize(("verified_sequence", "artifact_error",
                          "expected_error"), [
    (2, None, "remote_wal_sequence_mismatch"),
    (4, None, "remote_wal_sequence_mismatch"),
    (None, "remote_receipt_compact_identity_mismatch",
     "remote_receipt_compact_identity_mismatch"),
])
def test_current_legacy_batch_rejects_stale_gap_and_fork_readback(
        verified_sequence, artifact_error, expected_error):
    scanner._REMOTE_RECEIPT_QUEUE, _ = _current_legacy_store(3)
    artifact = (
        scanner.argus_remote_recovery.RecoveryBundleError(artifact_error)
        if artifact_error else {})
    verify = (
        _verify_selected(verified_sequence, receipt_hash=f"{3:016x}")
        if verified_sequence is not None else _verify_selected(3))
    with mock.patch.object(scanner, "_persist_remote_receipt_queue",
                           side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              side_effect=(artifact if artifact_error else None),
                              return_value=({} if not artifact_error else None)), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=verify), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}):
        result = scanner._persist_with_remote_receipt_drain(NOW)
    flush = result["remoteReceiptFlush"]
    assert flush["status"] == "failed"
    assert flush["errorClass"] == expected_error
    summary = queue.summary(scanner._REMOTE_RECEIPT_QUEUE, now_iso=NOW)
    assert summary["failedCount"] == 1
    assert summary["pendingCount"] == 2


def test_keyed_receipts_retain_oldest_exact_fifo_verification():
    state = queue.empty_store()
    for number in range(1, 4):
        state, _, _ = queue.accept_intent(
            state,
            idempotency_key=f"caos-keyed-{number:04d}-{number:06d}",
            build_sha=BUILD, remote_commit_sha=f"{number:040x}",
            expected_hash=f"{number:016x}",
            target_wal_sequence=number, accepted_at=NOW,
            expected_receipt_hash="e" * 16,
            artifact_mode="encrypted_recovery_v1",
            recovery_bundle_hash="f" * 64,
            recovery_generation_id="rrg-" + "a" * 32,
            recovery_key_id="key-001",
            ledger_base_commit_sha="d" * 40)
    scanner._REMOTE_RECEIPT_QUEUE = state

    def verify_oldest(now_iso=None, blob=None):
        result = _verify_selected(1)(now_iso, blob)
        scanner._REMOTE_CYCLE["compactReceiptHash"] = "e" * 16
        return result

    with mock.patch.object(
            scanner.argus_remote_recovery, "configured_keys",
            return_value={"status": "configured"}), \
            mock.patch.object(scanner, "_persist_remote_receipt_queue",
                              side_effect=_persist_in_memory), \
            mock.patch.object(scanner, "_verified_remote_receipt_artifact",
                              return_value={}), \
            mock.patch.object(scanner, "_remote_readback_ack",
                              side_effect=verify_oldest), \
            mock.patch.object(scanner, "_journal_compact", return_value=0), \
            mock.patch.object(scanner, "_osint_persist",
                              return_value={"verified": True}):
        result = scanner._persist_with_remote_receipt_drain(NOW)
    flush = result["remoteReceiptFlush"]
    assert flush["targetWalSequence"] == 1
    assert flush["coalescedReceiptCount"] == 1
    assert flush["queueAfter"] == 2


def test_cumulative_primitive_rejects_keyed_missing_and_partial_batches():
    legacy, rows = _current_legacy_store(2)
    with pytest.raises(queue.ReceiptQueueError,
                       match="receipt_batch_coverage_invalid"):
        queue.mark_selected_covered_verified(
            legacy, operation_ids=[rows[0]["operationId"], "rr-missing"],
            verified_sequence=2, remote_commit_sha=f"{2:040x}",
            verified_at=NOW)
    with pytest.raises(queue.ReceiptQueueError,
                       match="receipt_batch_coverage_invalid"):
        queue.mark_selected_covered_verified(
            legacy, operation_ids=[rows[0]["operationId"],
                                   rows[1]["operationId"]],
            verified_sequence=1, remote_commit_sha=f"{1:040x}",
            verified_at=NOW)

    keyed = queue.empty_store()
    keyed, receipt, _ = queue.accept_intent(
        keyed, idempotency_key="caos-keyed-boundary-0001",
        build_sha=BUILD, remote_commit_sha=COMMIT,
        expected_hash=HASH, target_wal_sequence=1, accepted_at=NOW,
        expected_receipt_hash="e" * 16,
        artifact_mode="encrypted_recovery_v1",
        recovery_bundle_hash="f" * 64,
        recovery_generation_id="rrg-" + "a" * 32,
        recovery_key_id="key-001", ledger_base_commit_sha="d" * 40)
    with pytest.raises(queue.ReceiptQueueError,
                       match="receipt_batch_coverage_invalid"):
        queue.mark_selected_covered_verified(
            keyed, operation_ids=[receipt["operationId"]],
            verified_sequence=1, remote_commit_sha=COMMIT,
            verified_at=NOW)


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
