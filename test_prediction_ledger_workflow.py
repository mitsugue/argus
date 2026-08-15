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


def test_canonical_runner_receives_only_bounded_snapshot_contract():
    source = _source()
    canonical = source[source.index("Append canonical Prediction Ledger v2 records"):
                       source.index("# closepin-v1")]
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


def test_closepin_and_scout_are_explicit_shadow_derived_only():
    source = _source()
    derived = source[source.index("# closepin-v1"):
                     source.index("Commit to ledger branch")]
    assert derived.count("SHADOW DERIVED") == 2
    assert derived.count("'authority': 'SHADOW_DERIVED'") >= 4
    assert derived.count("'canonicalPredictionLedger': False") >= 4
    assert derived.count("'calibrationEligible': False") >= 4
    assert "'mode': 'forward_live'" not in derived
    assert "'calibrationEligible': True" not in derived
    assert "entry-scout (calibration)" not in derived


def test_closepin_pin_writer_is_serialized_and_shadow_classified():
    source = CLOSEPIN_WORKFLOW.read_text(encoding="utf-8")
    assert source.count("concurrency:") == 1
    assert "group: ledger-branch-writer" in source
    assert "cancel-in-progress: false" in source
    assert '"mode": "shadow"' in source
    assert '"authority": "SHADOW_DERIVED"' in source
    assert '"canonicalPredictionLedger": False' in source
    assert '"calibrationEligible": False' in source


def test_event_ledger_plain_push_shares_the_writer_queue():
    source = EVENT_WORKFLOW.read_text(encoding="utf-8")
    assert source.count("concurrency:") == 1
    assert "group: ledger-branch-writer" in source
    assert "cancel-in-progress: false" in source
    assert "git push origin HEAD:ledger" in source
