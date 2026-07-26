from pathlib import Path

from scripts.deploy_scope import classify


WORKFLOW = Path(".github/workflows/caos-scan.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


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
    receipt_pos = text.index("remote-journal-commit-receipt")
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
