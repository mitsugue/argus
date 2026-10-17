"""Static gates for the Round 2A canonical Prediction Ledger workflow cutover."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "prediction-ledger.yml"
CLOSEPIN_WORKFLOW = ROOT / ".github" / "workflows" / "closepin-pin.yml"
EVENT_WORKFLOW = ROOT / ".github" / "workflows" / "event-ledger.yml"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_writer_is_single_serialized_job_without_overwrite_mode():
    source = _source()
    assert source.count("concurrency:") == 1
    assert "group: ledger-branch-writer" in source
    assert "cancel-in-progress: false" in source
    assert "force" not in source.lower()
    assert "needs: gate" not in source
    assert "use mode=" not in source


def test_runtime_is_staged_from_exact_triggering_sha_before_ledger_checkout():
    source = _source()
    stage = source.index("Stage exact triggering-commit canonical ledger runtime")
    switch = source.index("Switch to ledger branch")
    run = source.index("Append canonical Prediction Ledger v2 records")
    assert stage < switch < run
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in source
    assert "scripts/run_prediction_ledger.py" in source
    assert "argus_decision_ledger.py" in source
    assert "argus_market_data_truth.py" in source
    assert "argus_market_clock.py" in source
    assert "argus_calibration.py" in source
    assert 'printf \'%s\\n\' "$GITHUB_SHA" > "$RUNTIME/SOURCE_SHA"' in source
    assert 'sha256sum -c "$RUNTIME/SHA256SUMS"' in source
    assert "raw.githubusercontent.com" not in source
    assert "ref: main" not in source


def test_slow_ai_observation_cannot_block_the_canonical_ledger():
    source = _source()
    ai = source[source.index("Trigger AI judgment run without blocking the canonical ledger"):
                source.index("Switch to ledger branch")]
    assert "--timeout 420" in ai
    assert "|| AI_RC=$?" in ai
    assert 'if [ "$AI_RC" -ne 0 ]; then' in ai
    assert "canonical ledger processing continued independently" in ai


def test_canonical_runner_receives_only_bounded_snapshot_contract():
    source = _source()
    canonical = source[source.index("Append canonical Prediction Ledger v2 records"):
                       source.index("# scout-ledger-v1")]
    assert 'snapshot.get("canonicalPredictionLedger")' in canonical
    assert 'canonical.get("schemaVersion") != "argus-prediction-ledger-v2"' in canonical
    assert 'canonical.get("mode") != "forward_live"' in canonical
    assert 'python3 "$RUNNER_TEMP/run_prediction_ledger.py"' in canonical
    assert "--snapshot snap.json" in canonical
    assert "--ledger-root ledger/prediction/v2" in canonical
    assert "--expected-mode forward_live" in canonical
    assert '--run-id "$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"' in canonical
    assert '--runner-build-sha "$GITHUB_SHA"' in canonical
    for forbidden in (
            "/api/argus/japan-watchlist", "/api/argus/us-watchlist",
            "/api/argus/class-quotes", "/api/argus/sensor-quotes",
            "/api/argus/crypto-watchlist", "now_price", "cls_price",
            "sens_now", "ledger-v3"):
        assert forbidden not in canonical


def test_legacy_prediction_files_are_read_only_compatibility_artifacts():
    source = _source()
    for forbidden in (
            "mkdir -p ledger/days", "mkdir -p ledger/scores",
            "open('ledger/days", 'open("ledger/days',
            "open('ledger/scores", 'open("ledger/scores',
            "open('ledger/summary.json", 'open("ledger/summary.json',
            "git add ledger/days", "git add ledger/scores",
            "ledger/days/*.json", "glob.glob('ledger/days"):
        assert forbidden not in source
    assert "Historical ledger/days, ledger/scores and" in source
    assert "ledger/summary.json are read-only compatibility artifacts" in source
    assert "git status --porcelain -- ledger/days ledger/scores ledger/summary.json" in source


def test_v4_latest_price_scorers_and_main_downloads_are_absent():
    source = _source()
    for forbidden in (
            "Calibration v4 dry-run", "argus_ledger_v4.py",
            "argus_v4_dryrun.py", "raw.githubusercontent.com",
            "Record today's predictions + score the past",
            "last run of the day wins", "score_rows(", "now_price ="):
        assert forbidden not in source


def test_scout_remains_explicit_shadow_derived_only():
    source = _source()
    derived = source[source.index("# scout-ledger-v1"):
                     source.index("Commit to ledger branch")]
    assert derived.count("SHADOW DERIVED") == 1
    assert derived.count("'authority': 'SHADOW_DERIVED'") >= 2
    assert derived.count("'canonicalPredictionLedger': False") >= 2
    assert derived.count("'calibrationEligible': False") >= 2
    assert "'mode': 'forward_live'" not in derived
    assert "'calibrationEligible': True" not in derived
    assert "entry-scout (calibration)" not in derived


def test_retired_pin_has_no_schedule_acquisition_score_or_notification():
    source = CLOSEPIN_WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" not in source
    assert "curl " not in source and "requests." not in source
    assert "contents: write" not in source and "ntfy.sh" not in source
    assert "ledger/closepin" not in _source()
    bridge = (ROOT / "bridge" / "trigger_closepin.sh").read_text()
    assert "curl " not in bridge and "source " not in bridge
    assert "exit 0" in bridge


def test_event_ledger_plain_push_shares_the_writer_queue():
    source = EVENT_WORKFLOW.read_text(encoding="utf-8")
    assert source.count("concurrency:") == 1
    assert "group: ledger-branch-writer" in source
    assert "cancel-in-progress: false" in source
    assert "git push origin HEAD:ledger" in source


def test_result_lookup_runs_after_canonical_commit_with_exact_staged_runtime():
    source = _source()
    publish = source.index('Publish bounded event prediction result lookup')
    assert source.index('Commit to ledger branch') < publish
    assert 'id: canonical_commit' in source
    assert "steps.canonical_commit.outcome == 'success'" in source[publish:]
    step = source[publish:source.index('# The ledger is ARGUS', publish)]
    assert 'sha256sum -c "$RUNTIME/SHA256SUMS"' in step
    assert 'SOURCE_COMMIT=$(git rev-parse HEAD)' in step
    assert '--source-commit "$SOURCE_COMMIT"' in step
    assert 'git add ledger/event-prediction-results/v1/recent.json' in step
    assert '/api/' not in step and 'curl ' not in step
    assert 'scripts/export_event_prediction_results.py' in source[:source.index('Switch to ledger branch')]


def test_ai_failure_and_timeout_have_an_independent_canonical_job_budget():
    source = _source()
    ai_job = source[source.index('  ai-judgment:'):source.index('  record-and-score:')]
    writer = source[source.index('  record-and-score:'):]
    assert 'timeout-minutes: 9' in ai_job
    assert 'needs: ai-judgment' in writer
    assert "if: ${{ !cancelled() && github.event.inputs.mode != 'ai-only' }}" in writer
    assert 'timeout-minutes: 15' in writer
    assert 'continue-on-error' not in source
    assert "needs.ai-judgment.result != 'success'" in writer


def test_canonical_push_precedes_every_auxiliary_persistence_failure():
    source = _source()
    capture = source.index('Append canonical Prediction Ledger v2 records')
    commit = source.index('Commit canonical ledger before auxiliary persistence')
    vault = source.index('Persist backup vault')
    assert capture < commit < vault
    step = source[commit:vault]
    assert 'git add ledger/prediction/v2/' in step
    assert 'git push origin HEAD:ledger' in step
    assert 'id: canonical_commit' in step
    assert 'snap.pending.json' in source[capture:commit]
    assert 'mv snap.pending.json snap.json' in source[capture:commit]


def test_backup_failure_stays_red_but_does_not_skip_independent_saves():
    source = _source()
    following = source.split('id: backup_vault', 1)[1].split('Publish bounded event prediction result lookup', 1)[0]
    for block in following.split('      - name: ')[1:]:
        if block.startswith(('Persist ', 'Commit to ledger branch', 'Layer 2B', 'Decision Value')):
            condition = next(line for line in block.splitlines() if line.strip().startswith('if:'))
            assert '!cancelled()' in condition
            assert "steps.canonical_commit.outcome == 'success'" in condition
    assert 'continue-on-error' not in source
    stage = source.split('Switch to ledger branch')[0]
    assert 'persist_backup_vault.py' in stage
    assert '"$RUNNER_TEMP/workflow_http.py" \\' in stage


def test_notification_distinguishes_saved_canonical_ledger(tmp_path):
    import os
    import subprocess
    import textwrap
    stub = tmp_path / 'curl'
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$NOTIFY_TEST_ARGS"\n')
    stub.chmod(0o755)
    source = _source().split('      - name: Notify on failure', 1)[1]
    script = textwrap.dedent(source.split('        run: |\n', 1)[1]).replace('${{ github.run_id }}', '123')
    for outcome, title, body in (
        ('success', 'ARGUS auxiliary save FAILED', '予測台帳の記録・採点は保存済み'),
        ('failure', 'ARGUS ledger FAILED', '保存できませんでした')):
        args = tmp_path / 'args'
        result = subprocess.run(['bash', '-e', '-c', script], env={**os.environ,
            'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
            'NTFY_TOPIC': 'synthetic-test', 'CANONICAL_OUTCOME': outcome,
            'NOTIFY_TEST_ARGS': str(args)}, capture_output=True, text=True)
        assert result.returncode == 0
        sent = args.read_text()
        assert title in sent and body in sent
        assert '/actions/runs/123' in sent
