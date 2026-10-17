"""Deterministic reproduction of the Watchtower Remote Journal liveness gap."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import types
from unittest import mock

import pytest

import argus_remote_journal as journal
import argus_remote_receipt_queue as queue
import argus_state_journal
from scripts.deploy_scope import classify
from scripts.prepare_remote_journal_publish import prepare
from scripts.remote_journal_publish_policy import (
    PublishPolicyError,
    publication_decision,
    receipt_request,
    remote_progress,
    runtime_remote_pending_count,
)


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


BUILD = "b" * 40
REMOTE_COMMIT = "c" * 40
LOCAL_WAL = 4512
REMOTE_WAL = 4492
M3_AT = "2026-08-11T13:07:09Z"
M4_AT = "2026-08-11T13:37:15Z"


def _event(number: int, occurred_at: str):
    return argus_state_journal.event(
        event_type="mission_completed",
        aggregate_type="mission",
        aggregate_id=f"mw-{number}",
        sequence=number,
        occurred_at=occurred_at,
        payload={"missionType": "ordinary"},
    )


def _readback(*, events, generated_at, wal_sequence):
    full = {
        "schemaVersion": journal.SCHEMA_V3,
        "generatedAt": generated_at,
        "asOf": generated_at,
        "buildIdentity": {"appVersion": "13.4.13", "buildSha": BUILD},
        "outcomes": [],
        "missionTickDurability": {
            "walAppliedSequence": wal_sequence,
            "remoteWalAppliedSequence": wal_sequence,
            "verifiedWalSequence": min(wal_sequence, REMOTE_WAL),
        },
        "marketLedgerStateHash": "1" * 16,
        "chartIntelligenceStateHash": "2" * 16,
        "todayIntelligenceStateHash": "3" * 16,
        "marketReplayStateHash": "4" * 16,
        **journal.snapshot_journal_section(
            events=events, meta={}, now_iso=generated_at),
    }
    return full, journal.compact_readback_snapshot(full)


def _stuck_proofs():
    remote_events = [_event(1, "2026-08-11T12:37:21Z")]
    local_events = remote_events + [
        _event(number, f"2026-08-11T13:{number:02d}:08Z")
        for number in range(2, 18)
    ]
    _, existing = _readback(
        events=remote_events,
        generated_at="2026-08-11T12:37:21Z",
        wal_sequence=REMOTE_WAL)
    _, source = _readback(
        events=local_events,
        generated_at="2026-08-11T13:18:24Z",
        wal_sequence=LOCAL_WAL)
    return source, existing


def _runtime_truth(*, local=17, pending=1, committed=16, failed=0):
    return {
        "schemaVersion": "argus-operational-diagnostics-v1",
        "durability": {
            "integrityStatus": "ok",
            "journalCorruptCount": 0,
            "missionWalCorruptCount": 0,
        },
        "remoteJournal": {
            "localCommittedCount": local,
            "pendingCount": pending,
            "committedCount": committed,
            "failedCount": failed,
        },
    }


def _persist_queue_in_memory(store):
    scanner._REMOTE_RECEIPT_QUEUE = copy.deepcopy(store)
    return {"verified": True, "readBackVerified": True}


def _verify_remote_4512(now_iso=None, blob=None):
    scanner._REMOTE_CYCLE.update({
        "readBackVerified": True,
        "walReadBackVerified": True,
        "remoteDurabilityState": "verified",
        "verifiedWalSequence": LOCAL_WAL,
        "remoteWalAppliedSequence": LOCAL_WAL,
        "receiptCommitSha": REMOTE_COMMIT,
        "receiptErrorClass": None,
        "walErrorClass": None,
        "errorClass": None,
    })
    return {"verificationStatus": "verified"}


@pytest.fixture(autouse=True)
def restore_receipt_state():
    saved_queue = copy.deepcopy(scanner._REMOTE_RECEIPT_QUEUE)
    saved_cycle = copy.deepcopy(scanner._REMOTE_CYCLE)
    if scanner._REMOTE_RECEIPT_FLUSH_LOCK.locked():
        scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    scanner._REMOTE_RECEIPT_QUEUE = queue.empty_store()
    scanner._REMOTE_CYCLE.clear()
    scanner._REMOTE_CYCLE.update({
        "verifiedWalSequence": REMOTE_WAL,
        "remoteWalAppliedSequence": REMOTE_WAL,
        "readBackVerified": True,
        "walReadBackVerified": True,
        "remoteDurabilityState": "verified",
    })
    yield
    if scanner._REMOTE_RECEIPT_FLUSH_LOCK.locked():
        scanner._REMOTE_RECEIPT_FLUSH_LOCK.release()
    scanner._REMOTE_RECEIPT_QUEUE = saved_queue
    scanner._REMOTE_CYCLE.clear()
    scanner._REMOTE_CYCLE.update(saved_cycle)


def test_verified_proof_delta_overrides_delayed_slot_without_stale_projection():
    source, existing = _stuck_proofs()
    # The compact proof excludes runtime projections such as
    # remoteJournalCycle.pendingCount.  Signed event identity and exact WAL are
    # the only liveness inputs.
    assert "remoteJournalCycle" not in source
    progress = remote_progress(source, existing)
    assert progress == {
        "remoteProofMissing": False,
        "eventSetChanged": True,
        "walAdvanced": True,
        "sourceEventCount": 17,
        "remoteEventCount": 1,
        "sourceWalTarget": LOCAL_WAL,
        "remoteWalTarget": REMOTE_WAL,
        "forwardProgress": True,
    }

    ordinary = publication_decision(
        source, existing, event_name="schedule", utc_minute=7)
    delayed = publication_decision(
        source, existing, event_name="schedule", utc_minute=18)
    manual = publication_decision(
        source, existing, event_name="workflow_dispatch", utc_minute=34)
    bounded = publication_decision(
        existing, existing, event_name="schedule", utc_minute=18)

    assert ordinary["publish"] is True
    assert ordinary["reason"] == "ordinary_hourly_slot"
    assert delayed["publish"] is True
    assert delayed["reason"] == "natural_remote_backlog"
    assert manual["publish"] is True
    assert manual["reason"] == "manual"
    assert bounded["publish"] is False
    assert bounded["reason"] == "bounded_churn_skip"


def test_malformed_or_regressing_proof_fails_closed():
    source, existing = _stuck_proofs()
    tampered = copy.deepcopy(source)
    tampered["missionTickDurability"]["remoteWalAppliedSequence"] = 999
    with pytest.raises(
            PublishPolicyError,
            match="source_compact_readback_not_verifiable"):
        remote_progress(tampered, existing)

    _, older = _readback(
        events=[], generated_at="2026-08-11T14:00:00Z",
        wal_sequence=REMOTE_WAL - 1)
    with pytest.raises(PublishPolicyError, match="source_wal_regressed"):
        remote_progress(older, existing)

    broken_remote = copy.deepcopy(existing)
    broken_remote["receiptHash"] = "0" * 16
    with pytest.raises(
            PublishPolicyError,
            match="ledger_compact_readback_not_verifiable"):
        remote_progress(source, broken_remote)


def test_missing_remote_proof_is_forward_progress_and_output_is_private():
    source, _ = _stuck_proofs()
    progress = remote_progress(source, None)
    assert progress["remoteProofMissing"] is True
    assert progress["forwardProgress"] is True
    assert progress["remoteWalTarget"] == 0
    decision = publication_decision(
        source, None, event_name="schedule", utc_minute=18)
    encoded = json.dumps(decision, sort_keys=True)
    assert decision["reason"] == "natural_remote_backlog"
    assert "idempotencyKey" not in encoded
    assert "aggregateId" not in encoded
    assert "mw-" not in encoded


def test_lost_receipt_uses_runtime_truth_without_rewriting_ledger():
    _, ledger = _stuck_proofs()
    decision = publication_decision(
        ledger, ledger, event_name="schedule", utc_minute=18,
        runtime_data_quality=_runtime_truth())
    assert decision["forwardProgress"] is False
    assert decision["eventSetChanged"] is False
    assert decision["walAdvanced"] is False
    assert decision["action"] == "receipt_only"
    assert decision["publish"] is False
    assert decision["receiptOnly"] is True
    assert decision["reason"] == "natural_receipt_recovery"
    assert decision["runtimeRemotePendingCount"] == 1

    # Receipt-only reuses the already verified ledger proof and exact ledger
    # commit; it does not create a second ledger snapshot or commit.
    request = receipt_request(
        ledger, remote_commit_sha=REMOTE_COMMIT,
        backend_build_sha=BUILD,
        expected_hash=ledger["integrityManifest"]["manifestHash"])
    assert request["payload"]["targetWalSequence"] == REMOTE_WAL

    no_gap = publication_decision(
        ledger, ledger, event_name="schedule", utc_minute=18,
        runtime_data_quality=_runtime_truth(local=16, pending=0, committed=16))
    assert no_gap["action"] == "skip"
    assert no_gap["receiptOnly"] is False


@pytest.mark.parametrize("runtime, message", [
    ({"schemaVersion": "wrong", "remoteJournal": {}},
     "runtime_data_quality_invalid"),
    ({"schemaVersion": "argus-operational-diagnostics-v1"},
     "runtime_remote_journal_truth_missing"),
    (_runtime_truth(local=17, pending=True, committed=16),
     "runtime_remote_journal_truth_invalid"),
    (_runtime_truth(local=17, pending=1, committed=15),
     "runtime_remote_journal_truth_inconsistent"),
    (_runtime_truth(failed=True),
     "runtime_remote_journal_truth_invalid"),
    ({**_runtime_truth(), "durability": {
        "integrityStatus": "failed", "journalCorruptCount": 1,
        "missionWalCorruptCount": 0, "checkpoint": {}}},
     "runtime_durable_integrity_invalid"),
])
def test_runtime_truth_is_optional_but_malformed_values_fail_closed(
        runtime, message):
    _, ledger = _stuck_proofs()
    assert runtime_remote_pending_count(None) is None
    with pytest.raises(PublishPolicyError, match=message):
        publication_decision(
            ledger, ledger, event_name="schedule", utc_minute=18,
            runtime_data_quality=runtime)


def test_cumulative_remote_failures_never_latch_natural_progress_off():
    source, ledger = _stuck_proofs()
    historical_failure = _runtime_truth(failed=1)

    publish = publication_decision(
        source, ledger, event_name="schedule", utc_minute=18,
        runtime_data_quality=historical_failure)
    assert publish["action"] == "publish"
    assert publish["reason"] == "natural_remote_backlog"
    assert publish["runtimeRemoteFailureCount"] == 1

    receipt_only = publication_decision(
        ledger, ledger, event_name="schedule", utc_minute=18,
        runtime_data_quality=historical_failure)
    assert receipt_only["action"] == "receipt_only"
    assert receipt_only["reason"] == "natural_receipt_recovery"
    assert receipt_only["runtimeRemoteFailureCount"] == 1
    assert runtime_remote_pending_count(historical_failure) == 1


def test_rearm_wal_bool_fails_closed_without_changing_ordinary_schedule():
    _, ledger = _stuck_proofs()
    malformed = _runtime_truth(local=16, pending=0, committed=16)
    malformed["durability"]["checkpoint"] = {
        "verified": True, "readBackVerified": True,
        "includedWalSequence": LOCAL_WAL,
    }
    malformed["remoteJournal"].update({
        "readBackVerified": True, "walReadBackVerified": True,
        "state": "verified",
        "remoteWalAppliedSequence": True,
        "verifiedWalSequence": REMOTE_WAL,
        "errorPresent": False,
    })
    ordinary = publication_decision(
        ledger, ledger, event_name="schedule", utc_minute=18,
        runtime_data_quality=malformed)
    assert ordinary["action"] == "skip"
    with pytest.raises(PublishPolicyError, match="runtime_wal_sequence_invalid"):
        publication_decision(
            ledger, ledger, event_name="workflow_dispatch", utc_minute=18,
            runtime_data_quality=malformed, natural_rearm=True)


def test_receipt_request_requires_exact_identity_hash_and_wal():
    source, _ = _stuck_proofs()
    expected_hash = source["integrityManifest"]["manifestHash"]
    request = receipt_request(
        source,
        remote_commit_sha=REMOTE_COMMIT,
        backend_build_sha=BUILD,
        expected_hash=expected_hash)
    assert request["idempotencyKey"] == (
        f"caos-watchtower-{REMOTE_COMMIT}-{LOCAL_WAL}")
    assert request["payload"] == {
        "remoteCommitSha": REMOTE_COMMIT,
        "expectedHash": expected_hash,
        "backendBuildSha": BUILD,
        "targetWalSequence": LOCAL_WAL,
    }
    with pytest.raises(PublishPolicyError, match="backend_build_sha_invalid"):
        receipt_request(
            source, remote_commit_sha=REMOTE_COMMIT,
            backend_build_sha=BUILD[:7], expected_hash=expected_hash)
    with pytest.raises(
            PublishPolicyError, match="compact_readback_hash_mismatch"):
        receipt_request(
            source, remote_commit_sha=REMOTE_COMMIT,
            backend_build_sha=BUILD, expected_hash="0" * 16)


def test_same_signed_event_manifest_with_new_wal_is_published(tmp_path):
    # Normal snapshots refresh integrityManifest.generatedAt and manifestHash,
    # but the progress identity ignores those clock-only fields and still
    # detects the independently bound WAL boundary.
    event = _event(1, "2026-08-11T12:37:21Z")
    old_full, old_readback = _readback(
        events=[event], generated_at="2026-08-11T12:37:21Z",
        wal_sequence=REMOTE_WAL)
    source_full = copy.deepcopy(old_full)
    source_full["generatedAt"] = "2026-08-11T12:37:22Z"
    source_full["asOf"] = "2026-08-11T12:37:22Z"
    source_full.update(journal.snapshot_journal_section(
        events=[event], meta={}, now_iso="2026-08-11T12:37:22Z"))
    source_full["missionTickDurability"] = {
        "walAppliedSequence": LOCAL_WAL,
        "remoteWalAppliedSequence": LOCAL_WAL,
        "verifiedWalSequence": REMOTE_WAL,
    }
    source_readback = journal.compact_readback_snapshot(source_full)
    assert (
        source_readback["integrityManifest"]["manifestHash"] ==
        old_readback["integrityManifest"]["manifestHash"]) is False
    assert source_readback["receiptHash"] != old_readback["receiptHash"]
    progress = remote_progress(source_readback, old_readback)
    assert progress["eventSetChanged"] is False
    assert progress["walAdvanced"] is True
    assert progress["forwardProgress"] is True

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, separators=(",", ":")),
                        encoding="utf-8")

    runner_full = tmp_path / "runner" / "memory.json"
    runner_readback = tmp_path / "runner" / "readback.json"
    ledger_full = tmp_path / "ledger" / "osint" / "memory.json"
    ledger_readback = tmp_path / "ledger" / "osint" / "readback.json"
    write(runner_full, source_full)
    write(runner_readback, source_readback)
    write(ledger_full, old_full)
    write(ledger_readback, old_readback)

    result = prepare(
        source_full=runner_full,
        source_readback=runner_readback,
        ledger_full=ledger_full,
        ledger_readback=ledger_readback)
    assert result["status"] == "prepared"
    assert result["readbackPublished"] is True
    committed = json.loads(ledger_readback.read_text(encoding="utf-8"))
    assert committed["missionTickDurability"][
        "walAppliedSequence"] == LOCAL_WAL


def test_exact_stuck_state_and_candidate_natural_recovery_without_manual_flush():
    source, existing = _stuck_proofs()

    # Pre-fix: a runner that starts at :18 is discarded solely by wall clock.
    assert (18 < 15) is False
    assert queue.summary(scanner._REMOTE_RECEIPT_QUEUE,
                         now_iso=M3_AT)["pendingCount"] == 0

    # M3 and M4 are ordinary natural adapters, but an empty receipt queue
    # selects zero work.  Unrelated natural opportunities cannot advance 4492.
    with mock.patch.object(
            scanner, "_osint_persist",
            side_effect=lambda: {"verified": True}):
        m3 = scanner._persist_with_remote_receipt_drain(M3_AT)
        m4 = scanner._persist_with_remote_receipt_drain(M4_AT)
    assert m3["remoteReceiptFlush"]["status"] == "noop"
    assert m4["remoteReceiptFlush"]["status"] == "noop"
    assert m3["remoteReceiptFlush"]["queueBefore"] == 0
    assert m4["remoteReceiptFlush"]["queueBefore"] == 0
    assert scanner._REMOTE_CYCLE["verifiedWalSequence"] == REMOTE_WAL

    # Candidate: the same delayed natural Watchtower run detects exact proof
    # progress, publishes, and fsyncs one idempotent asynchronous intent.
    decision = publication_decision(
        source, existing, event_name="schedule", utc_minute=18)
    assert decision["publish"] is True
    expected_hash = source["integrityManifest"]["manifestHash"]
    request = receipt_request(
        source,
        remote_commit_sha=REMOTE_COMMIT,
        backend_build_sha=BUILD,
        expected_hash=expected_hash)
    payload = request["payload"]
    accepted, first, replayed = queue.accept_intent(
        scanner._REMOTE_RECEIPT_QUEUE,
        idempotency_key=request["idempotencyKey"],
        build_sha=payload["backendBuildSha"],
        remote_commit_sha=payload["remoteCommitSha"],
        expected_hash=payload["expectedHash"],
        target_wal_sequence=payload["targetWalSequence"],
        accepted_at="2026-08-11T13:18:25Z")
    assert replayed is False
    accepted, duplicate, replayed = queue.accept_intent(
        accepted,
        idempotency_key=request["idempotencyKey"],
        build_sha=payload["backendBuildSha"],
        remote_commit_sha=payload["remoteCommitSha"],
        expected_hash=payload["expectedHash"],
        target_wal_sequence=payload["targetWalSequence"],
        accepted_at="2026-08-11T13:18:26Z")
    assert replayed is True
    assert duplicate["operationId"] == first["operationId"]
    assert len(accepted["receipts"]) == 1
    scanner._REMOTE_RECEIPT_QUEUE = accepted

    # The next ordinary natural adapter verifies the immutable read-back,
    # creates its already-required checkpoint, and acknowledges exactly once.
    with mock.patch.object(
            scanner, "_persist_remote_receipt_queue",
            side_effect=_persist_queue_in_memory), mock.patch.object(
            scanner, "_remote_readback_ack",
            side_effect=_verify_remote_4512), mock.patch.object(
            scanner, "_journal_compact", return_value=0), mock.patch.object(
            scanner, "_osint_persist",
            side_effect=lambda: {"verified": True}) as checkpoint:
        natural = scanner._persist_with_remote_receipt_drain(
            "2026-08-11T14:07:09Z")

    flush = natural["remoteReceiptFlush"]
    assert flush["status"] == "verified"
    assert flush["targetWalSequence"] == LOCAL_WAL
    assert flush["verifiedWalSequence"] == LOCAL_WAL
    assert flush["coalescedReceiptCount"] == 1
    assert flush["queueBefore"] == 1
    assert flush["queueAfter"] == 0
    assert checkpoint.call_count == 1
    assert scanner._REMOTE_CYCLE["verifiedWalSequence"] == LOCAL_WAL
    assert queue.summary(
        scanner._REMOTE_RECEIPT_QUEUE,
        now_iso="2026-08-11T14:07:09Z")["pendingCount"] == 0


def test_watchtower_wires_verified_publish_and_receipt_only_paths():
    text = Path(".github/workflows/caos-watchtower.yml").read_text(
        encoding="utf-8")
    step = text.split(
        "- name: Commit snapshot and enqueue bounded Remote Journal receipt",
        1)[1]
    checkout = step.index("git checkout -B ledger")
    for copied in (
            "remote_journal_publish_policy.py",
            "prepare_remote_journal_publish.py",
            "workflow_http.py",
            "argus_remote_journal.py"):
        assert step.index(f'cp scripts/{copied}' if copied !=
                          "argus_remote_journal.py" else
                          'cp argus_remote_journal.py') < checkout
    assert "/api/argus/admin/diagnostics/operational" in text
    assert 'X-ARGUS-ADMIN-TOKEN: $ARGUS_ADMIN_TOKEN' in text
    assert '--runtime-data-quality "$RUNNER_TEMP/data-quality.json"' in step
    assert 'DECISION_ACTION" = "receipt_only"' in step
    assert "exact proof ready" in step
    assert "verify-ledger-base-ancestor" in step
    assert '--recovery-ledger-base "$RECOVERY_LEDGER_BASE"' in step
    assert '--cas-ledger-head "$LEDGER_CAS_BASE"' in step
    assert '--force-with-lease=refs/heads/ledger:"$LEDGER_CAS_BASE"' in step
    assert "git pull --rebase" not in step
    receipt_only = step.split(
        'elif [ "$DECISION_ACTION" = "receipt_only" ]; then', 1)[1]
    assert receipt_only.index("inspect-pair") < receipt_only.index(
        "prepare-pair") < receipt_only.index("origin HEAD:ledger")
    assert 'PAIR_NEEDS_COMMIT=false' in receipt_only
    assert 'PAIR_NEEDS_COMMIT" = "true"' in receipt_only
    assert "--expected-receipt-hash" in step
    remote_head = step.index('[ "$REMOTE_HEAD" = "$REMOTE_COMMIT_SHA" ]')
    exact_receipt = step.index("--expected-receipt-hash", remote_head)
    post = step.index("watchtower-remote-journal-accept-receipt")
    assert remote_head < exact_receipt < post
    assert "--timeout 15" in step[post:]
    assert "for DELAY in" not in step
    assert "while true" not in step
    assert 'echo "$ARGUS_ADMIN_TOKEN"' not in text
    assert "GITHUB_SHA" not in step
    assert 'd.get("remoteCommitSha")==os.environ["REMOTE_COMMIT_SHA"]' in step
    assert 'd.get("targetWalSequence")' in step


def test_caos_scan_retires_legacy_writer_when_recovery_is_configured():
    text = Path(".github/workflows/caos-scan.yml").read_text(
        encoding="utf-8")
    durability = text.split("\n  durability-flush:\n", 1)[1].split(
        "\n  result:\n", 1)[0]
    probe = durability.index(
        "/api/argus/admin/remote-journal/recovery-sidecar")
    configured = durability.index(
        'remoteArtifactMode=encrypted_recovery_v1', probe)
    retired = durability.index(
        "expected_skip_encrypted_recovery_owned_by_watchtower", configured)
    checkout = durability.index('git checkout -B ledger')
    assert probe < configured < retired < checkout
    assert durability.count("validate-sidecar") == 2
    assert durability.count("prepare_remote_journal_publish.py") >= 4
    not_configured = durability.index("'not_configured'", probe)
    full_snapshot = durability.index(
        "/api/argus/osint/memory-snapshot", not_configured)
    assert not_configured < full_snapshot < checkout
    assert '--max-filesize 268435456' in durability[
        not_configured:full_snapshot]
    flush = durability.split(
        "- name: Commit verified snapshot and post receipt", 1)[1]
    assert "recheck_remote_artifact_mode" in flush
    assert flush.count("CURRENT_MODE=$(recheck_remote_artifact_mode)") == 2
    assert flush.index("CURRENT_MODE=$(recheck_remote_artifact_mode)") < \
        flush.index('git checkout -B ledger')
    second_recheck = flush.rindex(
        "CURRENT_MODE=$(recheck_remote_artifact_mode)")
    assert second_recheck < flush.index("git push origin HEAD:ledger")
    assert "legacy push suppressed" in flush[second_recheck:]
    assert "prepare-pair" not in durability
    assert "ledger/osint/recovery.json" not in durability


def test_watchtower_fetches_full_snapshot_only_for_not_configured_mode():
    text = Path(".github/workflows/caos-watchtower.yml").read_text(
        encoding="utf-8")
    patrol = text.split("\n  patrol:\n", 1)[1].split(
        "\n  remote-journal-rearm:\n", 1)[0]
    probe = patrol.index(
        "/api/argus/admin/remote-journal/recovery-sidecar")
    configured = patrol.index(
        "encrypted_recovery_v1", probe)
    not_configured = patrol.index("'not_configured'", probe)
    full_snapshot = patrol.index(
        "/api/argus/osint/memory-snapshot", not_configured)
    checkout = patrol.index("ref: main", full_snapshot)
    assert probe < configured < not_configured < full_snapshot < checkout
    assert '--max-filesize 268435456' in patrol[
        not_configured:full_snapshot]
    missing_token = patrol.index(
        'ARGUS_ADMIN_TOKEN missing; remote artifact mode is indeterminate')
    default_legacy = patrol.index(
        "printf '%s' legacy_full", not_configured)
    assert missing_token < probe < not_configured < default_legacy < \
        full_snapshot
    assert "printf '%s' legacy_full" not in patrol[:not_configured]
    assert patrol.count("validate-sidecar") == 1


def test_watchtower_remote_journal_step_is_valid_bash():
    text = Path(".github/workflows/caos-watchtower.yml").read_text(
        encoding="utf-8")
    step = text.split(
        "- name: Commit snapshot and enqueue bounded Remote Journal receipt",
        1)[1]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    script = script.replace("${{ github.event_name }}", "schedule")
    script = script.replace("${{ inputs.remoteJournalRearm }}", "false")
    checked = subprocess.run(
        ["bash", "-n"], input=script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr


def test_liveness_fix_is_workflow_only_and_preserves_production_scope():
    assert classify([
        ".github/workflows/caos-watchtower.yml",
        "scripts/prepare_remote_journal_publish.py",
        "scripts/remote_journal_publish_policy.py",
        "test_remote_journal_liveness.py",
        "test_remote_journal_publish.py",
    ]) == {
        "frontendDeploy": False,
        "backendDeploy": False,
        "newBackendSoak": False,
        "preserveBackendSoak": True,
        "checkpointStage1": False,
    }
