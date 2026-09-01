import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import argus_remote_journal as journal
from scripts.deploy_scope import classify


WORKFLOW = Path(".github/workflows/caos-scan.yml")
WATCHTOWER_WORKFLOW = Path(".github/workflows/caos-watchtower.yml")
WATCHTOWER_TIMER = Path("ops/systemd/argus-watchtower-writer.timer")
WATCHTOWER_SERVICE = Path("ops/systemd/argus-watchtower-writer.service")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _circular_minute_gaps(minutes: list[int]) -> list[int]:
    ordered = sorted(minutes)
    return [
        *[right - left for left, right in zip(ordered, ordered[1:])],
        60 - ordered[-1] + ordered[0],
    ]


def _watchtower_job(text: str, name: str, next_name=None) -> str:
    job = text.split(f"\n  {name}:\n", 1)[1]
    if next_name is not None:
        job = job.split(f"\n  {next_name}:\n", 1)[0]
    return job


def _workflow_step_run(job: str, name: str) -> str:
    step = job.split(f"      - name: {name}\n", 1)[1]
    boundaries = [
        position for marker in ("\n      - name: ", "\n      - uses: ")
        if (position := step.find(marker)) >= 0
    ]
    if boundaries:
        step = step[:min(boundaries)]
    run = step.split("        run: |\n", 1)[1]
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in run.splitlines()
    ).rstrip()


_READBACK_BOUND_SETUP = """READBACK_MAX_BYTES=$(python3 -c \\
  'import argus_remote_journal as j; print(j.MAX_COMPACT_READBACK_BYTES)')
case "$READBACK_MAX_BYTES" in
  ''|*[!0-9]*)
    echo "invalid canonical compact readback bound"
    exit 1
    ;;
esac
[ "$READBACK_MAX_BYTES" -gt 0 ] || {
  echo "invalid canonical compact readback bound"
  exit 1
}"""

_HISTORICAL_PROTECTED_MAIN = "2d6a12800cf732085031b21612b537455fb06e6f"


def _readback_curl(step: str) -> str:
    match = re.search(
        r'curl --fail --silent --show-error --max-time 60 \\\n'
        r'\s+--max-filesize "\$READBACK_MAX_BYTES" \\\n'
        r'\s+"\$BE/api/argus/osint/remote-readback" \\\n'
        r'\s+-o "\$RUNNER_TEMP/osint-readback\.json"',
        step,
    )
    assert match is not None
    return match.group(0)


def test_watchtower_uses_one_deterministic_systemd_scheduler_contract():
    text = WATCHTOWER_WORKFLOW.read_text(encoding="utf-8")
    timer = WATCHTOWER_TIMER.read_text(encoding="utf-8")
    service = WATCHTOWER_SERVICE.read_text(encoding="utf-8")
    crons = re.findall(r"^\s+- cron: '([^']+)'", text, flags=re.MULTILINE)
    assert crons == []
    assert "\n  schedule:" not in text

    weekday = [4, 11, 19, 26, 34, 41, 49, 56]
    weekend = [4, 34]
    assert len(weekday) == len(set(weekday))
    assert len(weekend) == len(set(weekend))
    assert _circular_minute_gaps(weekday) == [7, 8, 7, 8, 7, 8, 7, 8]
    assert max(_circular_minute_gaps(weekday)) * 60 == 480
    assert _circular_minute_gaps(weekend) == [30, 30]
    assert max(_circular_minute_gaps(weekend)) * 60 == 1800
    assert (
        "OnCalendar=Mon..Fri *-*-* *:04,11,19,26,34,41,49,56:00 UTC"
        in timer)
    assert "OnCalendar=Sat,Sun *-*-* *:04,34:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "AccuracySec=1us" in timer
    assert "RandomizedDelaySec=0" in timer
    assert "Unit=argus-watchtower-writer.service" in timer
    assert "Type=oneshot" in service
    assert "User=argus-rearm" in service
    assert "Group=argus-rearm" in service
    assert "StateDirectory=argus-watchtower-writer" in service
    assert "/opt/argus-watchtower-writer/" in service
    assert "/opt/argus/" not in service

    dispatch = text.split("  workflow_dispatch:", 1)[1].split(
        "\n\n# GitHub concurrency", 1
    )[0]
    assert "remoteJournalRearm:" in dispatch
    assert "required: false" in dispatch
    assert "default: false" in dispatch
    assert "type: boolean" in dispatch
    assert "dispatchMode:" in dispatch
    assert "default: owner_manual" in dispatch
    assert "- ec2_systemd_writer" in dispatch
    assert "writerScheduledFor:" in dispatch
    assert "writerDispatchId:" in dispatch
    assert "run-name:" in text
    assert "Watchtower EC2 {0}" in text
    assert text.count("Validate exact Watchtower dispatch identity") == 2
    assert "--scheduled-writer" in text
    assert "source=ec2_systemd_writer" in text
    assert "--writer-scheduled-for '${{ inputs." not in text
    assert "--writer-dispatch-id '${{ inputs." not in text
    assert 'scheduledFor=${{ inputs.' not in text
    assert text.count("WATCHTOWER_SCHEDULED_FOR: ${{ inputs.") == 3
    assert text.count("WATCHTOWER_DISPATCH_ID: ${{ inputs.") == 3

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


def test_watchtower_writer_and_rearm_concurrency_remain_disjoint():
    text = WATCHTOWER_WORKFLOW.read_text(encoding="utf-8")
    assert "'caos-watchtower-remote-journal-rearm'" in text
    assert "|| 'caos-watchtower'" in text
    assert "cancel-in-progress: false" in text
    assert "queue: max" not in text


def test_watchtower_direct_publish_prechecks_bind_repo_import_path():
    text = WATCHTOWER_WORKFLOW.read_text(encoding="utf-8")
    patrol = text.split("  patrol:", 1)[1].split(
        "\n  remote-journal-rearm:", 1
    )[0]
    rearm = text.split("  remote-journal-rearm:", 1)[1]
    direct = (
        'PYTHONPATH="$GITHUB_WORKSPACE" python3 '
        "scripts/prepare_remote_journal_publish.py"
    )

    assert patrol.count(direct) == 1
    assert rearm.count(direct) == 1
    assert "python3 scripts/prepare_remote_journal_publish.py" not in \
        text.replace(direct, "")


def test_watchtower_publish_helper_import_topologies_are_executable(tmp_path):
    root = Path(__file__).resolve().parent
    direct_env = os.environ.copy()
    direct_env["PYTHONPATH"] = str(root)
    direct = subprocess.run(
        [sys.executable, "scripts/prepare_remote_journal_publish.py", "--help"],
        cwd=root, env=direct_env, check=False, capture_output=True, text=True,
    )
    assert direct.returncode == 0, direct.stderr

    runner = tmp_path / "runner-temp"
    runner.mkdir()
    shutil.copyfile(
        root / "scripts" / "prepare_remote_journal_publish.py",
        runner / "prepare_remote_journal_publish.py",
    )
    shutil.copyfile(
        root / "argus_remote_journal.py", runner / "argus_remote_journal.py"
    )
    copied_env = os.environ.copy()
    copied_env.pop("PYTHONPATH", None)
    copied = subprocess.run(
        [sys.executable, str(runner / "prepare_remote_journal_publish.py"),
         "--help"],
        cwd=tmp_path, env=copied_env, check=False, capture_output=True, text=True,
    )
    assert copied.returncode == 0, copied.stderr


def test_protected_main_readback_bound_does_not_cross_shell_step_boundary(
    tmp_path,
):
    assert re.fullmatch(r"[0-9a-f]{40}", _HISTORICAL_PROTECTED_MAIN)
    env = os.environ.copy()
    env.pop("READBACK_MAX_BYTES", None)
    producer = subprocess.run(
        ["bash", "-c", _READBACK_BOUND_SETUP], env=env, check=False,
        capture_output=True, text=True,
    )
    assert producer.returncode == 0, producer.stderr

    env["RUNNER_TEMP"] = str(tmp_path)
    historical_consumer = r'''set -e
curl() {
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--max-filesize" ]; then
      [ -n "$2" ] || return 2
      return 0
    fi
    shift
  done
  return 92
}
BE="https://argus-backend-3j2m.onrender.com"
curl --fail --silent --show-error --max-time 60 \
  --max-filesize "$READBACK_MAX_BYTES" \
  "$BE/api/argus/osint/remote-readback" \
  -o "$RUNNER_TEMP/osint-readback.json"
'''
    consumer = subprocess.run(
        ["bash", "-c", historical_consumer], env=env, check=False,
        capture_output=True, text=True,
    )
    assert consumer.returncode == 2
    assert not (tmp_path / "osint-readback.json").exists()


def test_watchtower_readback_bound_is_owned_and_executable_in_each_curl_step(
    tmp_path,
):
    root = Path(__file__).resolve().parent
    text = WATCHTOWER_WORKFLOW.read_text(encoding="utf-8")
    patrol = _watchtower_job(text, "patrol", "remote-journal-rearm")
    rearm = _watchtower_job(text, "remote-journal-rearm")
    refresh = _workflow_step_run(
        patrol, "Watchtower refresh + visible translation (admin; token never logged)"
    )
    snapshot = _workflow_step_run(patrol, "Fetch public-safe status snapshot")
    rearm_fetch = _workflow_step_run(
        rearm, "Fetch one bounded verified recovery pair"
    )

    assert "READBACK_MAX_BYTES" not in refresh
    for step in (snapshot, rearm_fetch):
        assert step.count(_READBACK_BOUND_SETUP) == 1
        assert step.count('--max-filesize "$READBACK_MAX_BYTES"') == 1

        runner_temp = tmp_path / str(len(list(tmp_path.iterdir())))
        runner_temp.mkdir()
        env = os.environ.copy()
        env.pop("READBACK_MAX_BYTES", None)
        env["RUNNER_TEMP"] = str(runner_temp)
        env["GITHUB_WORKSPACE"] = str(root)
        script = f"""set -euo pipefail
{_READBACK_BOUND_SETUP}
curl() {{
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--max-filesize" ]; then
      [ "$#" -ge 2 ] || return 90
      printf '%s' "$2" > "$RUNNER_TEMP/observed-max-filesize"
      shift 2
      continue
    fi
    if [ "$1" = "-o" ]; then
      [ "$#" -ge 2 ] || return 91
      : > "$2"
      shift 2
      continue
    fi
    shift
  done
}}
BE="https://argus-backend-3j2m.onrender.com"
{_readback_curl(step)}
"""
        completed = subprocess.run(
            ["bash", "-c", script], cwd=root, env=env, check=False,
            capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert (runner_temp / "observed-max-filesize").read_text() == str(
            journal.MAX_COMPACT_READBACK_BYTES
        )


def test_watchtower_readback_bound_validation_fails_closed(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"${FAKE_READBACK_MAX_BYTES-}\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    for invalid in ("", "0", "-1", "abc", "1 2"):
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
        env["FAKE_READBACK_MAX_BYTES"] = invalid
        completed = subprocess.run(
            ["bash", "-c", f"set -euo pipefail\n{_READBACK_BOUND_SETUP}\n"],
            env=env, check=False, capture_output=True, text=True,
        )
        assert completed.returncode != 0, invalid
        assert "invalid canonical compact readback bound" in completed.stdout


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
