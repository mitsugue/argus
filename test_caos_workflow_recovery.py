import re
from pathlib import Path

from scripts.deploy_scope import classify


WORKFLOW = Path(".github/workflows/caos-scan.yml")
WATCHTOWER_WORKFLOW = Path(".github/workflows/caos-watchtower.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _circular_minute_gaps(minutes: list[int]) -> list[int]:
    ordered = sorted(minutes)
    return [
        *[right - left for left, right in zip(ordered, ordered[1:])],
        60 - ordered[-1] + ordered[0],
    ]


def test_watchtower_schedule_reregistration_preserves_exact_contract():
    text = WATCHTOWER_WORKFLOW.read_text(encoding="utf-8")
    crons = re.findall(r"^\s+- cron: '([^']+)'", text, flags=re.MULTILINE)
    assert crons == [
        "4-59/15 * * * 1-5",
        "11-59/15 * * * 1-5",
        "4 * * * 0,6",
        "34 * * * 0,6",
    ]

    weekday = sorted([*range(4, 60, 15), *range(11, 60, 15)])
    weekend = [4, 34]
    assert weekday == [4, 11, 19, 26, 34, 41, 49, 56]
    assert len(weekday) == len(set(weekday))
    assert len(weekend) == len(set(weekend))
    assert _circular_minute_gaps(weekday) == [7, 8, 7, 8, 7, 8, 7, 8]
    assert max(_circular_minute_gaps(weekday)) * 60 == 480
    assert _circular_minute_gaps(weekend) == [30, 30]
    assert max(_circular_minute_gaps(weekend)) * 60 == 1800

    dispatch = text.split("  workflow_dispatch:", 1)[1].split(
        "\n\n# GitHub concurrency", 1
    )[0]
    assert "remoteJournalRearm:" in dispatch
    assert "required: false" in dispatch
    assert "default: false" in dispatch
    assert "type: boolean" in dispatch

    patrol = text.split("  patrol:", 1)[1].split(
        "\n  remote-journal-rearm:", 1
    )[0]
    assert (
        "if: github.event_name != 'workflow_dispatch' || "
        "inputs.remoteJournalRearm != true"
    ) in patrol
    rearm_header = text.split("  remote-journal-rearm:", 1)[1].split(
        "    runs-on:", 1
    )[0]
    assert (
        "if: github.event_name == 'workflow_dispatch' && "
        "inputs.remoteJournalRearm == true"
    ) in rearm_header
    assert "github.event_name == 'schedule'" not in rearm_header


def test_workflow_only_release_scope_is_backend_false():
    scope = classify([
        ".github/workflows/caos-scan.yml",
        "scripts/resolve_backend_identity.py",
        "scripts/prepare_remote_journal_publish.py",
        "test_backend_identity_resolver.py",
        "test_caos_workflow_recovery.py",
        "test_remote_journal_publish.py",
    ])
    assert scope == {
        "frontendDeploy": False,
        "backendDeploy": False,
        "newBackendSoak": False,
        "preserveBackendSoak": True,
        "checkpointStage1": False,
    }


def test_github_sha_is_not_sent_as_expected_backend_identity():
    text = _text()
    assert '"expectedBuildSha":os.environ["GITHUB_SHA"]' not in text
    assert "EXPECTED_BACKEND_SHA" in text
    assert "resolve_backend_identity.py" in text


def test_workflow_has_independent_control_plane_jobs():
    text = _text()
    for job in (
        "backend-identity:",
        "mission-backup:",
        "caos-collection:",
        "durability-flush:",
        "result:",
    ):
        assert job in text
    assert "if: always() && !cancelled() && github.event_name == 'schedule'" in text
    assert "needs: [backend-identity, mission-backup, caos-collection]" in text


def test_partial_or_hard_mission_failure_does_not_suppress_flush():
    text = _text()
    durability = text.split("  durability-flush:", 1)[1].split(
        "\n  result:", 1
    )[0]
    assert "needs.mission-backup.result == 'success'" not in durability
    assert "durability runs independently" in text
    assert 'if [ "$LAST_RESULT" = "partial" ]' in text
    assert "exit 2" in text


def test_durability_failure_is_visible_and_non_green():
    text = _text()
    flush = text.split("- name: Commit verified snapshot and post receipt", 1)[1]
    assert "continue-on-error" not in flush
    assert '[ "${{ needs.durability-flush.result }}" = "success" ] || exit 1' in text


def test_cancelled_or_manual_workflow_performs_no_operational_write():
    text = _text()
    assert "if: always() && !cancelled() && github.event_name == 'schedule'" in text
    assert "github.event_name == 'schedule'" in text.split(
        "  mission-backup:", 1
    )[1].split("  caos-collection:", 1)[0]
    assert "expected_skip_manual_diagnostic" in text


def test_stale_writer_guard_and_verified_receipt_order_remain():
    text = _text()
    select_pos = text.index("prepare_remote_journal_publish.py")
    remote_verify_pos = text.index(
        '[ "$REMOTE_HEAD" = "$REMOTE_COMMIT_SHA" ]'
    )
    receipt_pos = text.index("remote-journal-accept-receipt")
    assert select_pos < remote_verify_pos < receipt_pos
    assert "verify-committed --readback ledger/osint/readback.json" in text
    assert "expected_skip_stale_snapshot" in text


def test_oversized_full_snapshot_uses_compact_readback_without_github_blob():
    text = _text()
    flush = text.split("- name: Commit verified snapshot and post receipt", 1)[1]
    copy_helper_pos = text.index(
        'cp scripts/prepare_remote_journal_publish.py'
    )
    copy_module_pos = text.index(
        'cp argus_remote_journal.py "$RUNNER_TEMP/argus_remote_journal.py"'
    )
    checkout_pos = text.index("git checkout -B ledger")
    assert copy_helper_pos < checkout_pos
    assert copy_module_pos < checkout_pos
    assert "fullSnapshotRetained" in flush
    assert "ledger/osint/readback.json" in flush
    assert 'cp "$RUNNER_TEMP/osint-memory.json" ledger/osint/memory.json' not in flush
    assert (
        "json.load(open('ledger/osint/memory.json'))"
        "['integrityManifest']['manifestHash']"
    ) not in flush


def test_no_secret_value_is_logged_or_artifacted():
    text = _text()
    assert 'echo "$ARGUS_ADMIN_TOKEN"' not in text
    assert "Authorization:" not in text
    assert "upload-artifact" not in text


def test_work_is_bounded():
    text = _text()
    assert "for BATCH in 1 2 3" in text
    assert "for ROUND in 1 2 3 4" in text
    assert "while true" not in text


def test_mission_backup_transport_budget_covers_verified_checkpoint():
    text = _text()
    mission = text.split("  mission-backup:", 1)[1].split(
        "\n  caos-collection:", 1
    )[0]
    assert "--name missions-tick" in mission
    assert "--method POST --timeout 240" in mission
    assert "--method POST --timeout 90" not in mission


def test_async_receipt_contract_is_fast_idempotent_and_exact():
    text = _text()
    flush = text.split("- name: Commit verified snapshot and post receipt", 1)[1]
    assert "--name remote-journal-accept-receipt" in flush
    assert "--timeout 15" in flush
    assert "Idempotency-Key=RECEIPT_IDEMPOTENCY_KEY" in flush
    assert 'remote_journal_publish_policy.py" receipt' in flush
    assert '--expected-receipt-hash "$NEW_RECEIPT_HASH"' in flush
    assert "--artifact-mode legacy_full" in flush
    assert "--idempotency-prefix caos-scan" in flush
    assert 'json.load(sys.stdin)["payload"]["targetWalSequence"]' in flush
    assert 'json.load(sys.stdin)["payload"]' in flush
    assert 'json.dumps({"remoteCommitSha"' not in flush
    assert "--timeout 60" not in flush.split(
        "remote-journal-accept-receipt", 1)[1].split(")", 1)[0]


def test_receipt_drain_is_bounded_and_pending_can_never_be_green():
    text = _text()
    flush = text.split("- name: Commit verified snapshot and post receipt", 1)[1]
    assert 'cp scripts/remote_receipt_drain.py' in text
    assert '"$RUNNER_TEMP/remote_receipt_drain.py"' in flush
    assert "--budget-seconds 240" in flush
    assert "--operation-id \"$OPERATION_ID\"" in flush
    assert "--target-wal-sequence \"$TARGET_WAL_SEQUENCE\"" in flush
    assert 'assert d.get("status")=="verified"' in flush
    assert 'DURABILITY_RESULT="pending_within_slo"' not in flush
    assert "overallResult=pending_within_slo" not in text
    assert '[ "$VERIFIED_SEQUENCE" = "$TARGET_WAL_SEQUENCE" ]' in flush
    assert '[ "$VERIFIED_SEQUENCE" -ge "$TARGET_WAL_SEQUENCE" ]' in flush
    assert 'd.get("verifiedByRemoteCommitSha") or ""' in flush
    assert '[ "$VERIFIED_COMMIT" = "$REMOTE_COMMIT_SHA" ]' in flush
    assert "overallResult=verified" in text


def test_identity_and_durability_recheck_use_safe_http_summary_contract():
    text = _text()
    identity = text.split("- name: Read live backend identity", 1)[1].split(
        "- name: Resolve authoritative deployed backend", 1
    )[0]
    durability = text.split(
        "- name: Independently recheck health, ready, and backend identity", 1
    )[1].split("- name: Fetch validated durable snapshots", 1)[0]
    for block in (identity, durability):
        assert "scripts/workflow_http.py" in block
        assert '.get("buildSha") or ""' in block
        assert '.get("ready") is True' in block
    assert "buildSha" in __import__(
        "scripts.workflow_http", fromlist=["_SAFE_OUTPUT_KEYS"]
    )._SAFE_OUTPUT_KEYS
    assert "ready" in __import__(
        "scripts.workflow_http", fromlist=["_SAFE_OUTPUT_KEYS"]
    )._SAFE_OUTPUT_KEYS
