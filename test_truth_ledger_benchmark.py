import ast
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

from scripts import truth_ledger_benchmark as benchmark


ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "truth_ledger_benchmark.py"
SMOKE_DIGEST = "4fd4d93967203d7bca52c4de543f9d8f84b9b2c2f80f2aaecff57b9f432117ec"
BOUNDED_DIGEST = "666772a616074f2f26bad8c8c3f881cbaee4f629e1f5bb633936801b67c5d347"


@pytest.fixture(scope="module")
def smoke_report():
    return benchmark.run_benchmark(smoke=True)


def _exact_cgroup_snapshot(*, oom=11, oom_kill=7):
    return {
        "available": True,
        "memoryCurrentBytes": 128 * 1024 * 1024,
        "memoryPeakBytes": 256 * 1024 * 1024,
        "memoryMaxBytes": benchmark.EXACT_4_GIB_BYTES,
        "swapMaxBytes": 0,
        "events": {"oom": oom, "oomKill": oom_kill},
    }


def _write_exact_cgroup(root):
    root.mkdir()
    (root / "memory.current").write_text("134217728\n", encoding="ascii")
    (root / "memory.peak").write_text("268435456\n", encoding="ascii")
    (root / "memory.max").write_text("4294967296\n", encoding="ascii")
    (root / "memory.swap.max").write_text("0\n", encoding="ascii")
    (root / "memory.events").write_text(
        "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n", encoding="ascii")


def test_smoke_report_is_bounded_valid_and_repository_representative(smoke_report):
    assert smoke_report["schemaVersion"] == benchmark.REPORT_SCHEMA
    assert smoke_report["fixtureVersion"] == benchmark.FIXTURE_VERSION
    assert smoke_report["mode"] == "smoke"
    assert smoke_report["passed"] is True
    assert smoke_report["counts"] == {
        "requestCount": 10,
        "decisionObservationCount": 21,
        "targetObservationCount": 10,
        "selectionCount": 10,
        "selectedCount": 10,
        "predictionCount": 10,
        "outcomeCount": 10,
        "evaluationCount": 10,
        "aggregateCount": 4,
    }
    assert all(smoke_report["validation"].values())


def test_canonical_sizes_timings_resources_and_caps_are_reported(smoke_report):
    expected_size_keys = {
        "decisionObservations", "targetObservations", "selections",
        "decisionSnapshot", "predictions", "outcomes", "evaluations",
        "aggregates", "artifactEnvelope",
    }
    assert set(smoke_report["canonicalJsonBytes"]) == expected_size_keys
    assert all(isinstance(value, int) and value > 0
               for value in smoke_report["canonicalJsonBytes"].values())
    assert (smoke_report["canonicalJsonBytes"]["decisionSnapshot"]
            <= smoke_report["caps"]["marketTruth"]["maxSnapshotBytes"])

    expected_timing_keys = {
        "buildObservations", "selectTruth", "buildDecisionSnapshot",
        "buildPredictions", "evaluate", "aggregate", "total",
    }
    assert set(smoke_report["timingsNs"]) == expected_timing_keys
    assert all(isinstance(value, int) and value >= 0
               for value in smoke_report["timingsNs"].values())
    assert smoke_report["timingsNs"]["total"] >= max(
        value for key, value in smoke_report["timingsNs"].items()
        if key != "total")

    resources = smoke_report["resources"]
    assert isinstance(resources["tracemallocPeakBytes"], int)
    assert resources["tracemallocPeakBytes"] > 0
    for key in ("processPeakRssBeforeBytes", "processPeakRssAfterBytes"):
        assert resources[key] is None or (
            isinstance(resources[key], int) and resources[key] > 0)

    assert smoke_report["caps"] == {
        "benchmark": {
            "requestCount": 10,
            "smokeRequestCount": 10,
            "boundedRequestCount": 32,
        },
        "marketTruth": {
            "maxInputObservations": 8192,
            "maxAdapterObservations": 64,
            "maxAdapterErrors": 64,
            "maxCandidates": 8,
            "maxAlternates": 4,
            "maxSnapshotRequests": 64,
            "maxDerivedEvidence": 32,
            "maxEvidenceInputs": 32,
            "maxObservationBytes": 16384,
            "maxSnapshotBytes": 262144,
        },
        "predictionLedgerV2": {
            "maxEvidenceRefs": 24,
            "maxMetricsPerEvent": 64,
            "maxAggregateEvents": 10000,
            "maxEmbeddedBytes": 8192,
            "maxTargetLadderEntries": 12,
            "maxForecastDistributionClasses": 16,
        },
    }


def test_fixture_adapter_is_registered_but_cannot_grant_truth_authority(smoke_report):
    seam = smoke_report["providerSeams"]["nonAuthoritativeFixtureCandidate"]
    assert seam == {
        "adapterRegistered": True,
        "registrationGrantsAuthority": False,
        "authorityGrantedByRepositoryPolicy": False,
        "selectedCount": 0,
        "rejectedNonAuthoritativeCandidateCount": 1,
    }


def test_smoke_digest_and_canonical_sizes_are_reproducible(smoke_report):
    repeated = benchmark.run_benchmark(smoke=True)
    assert smoke_report["deterministicDigest"] == SMOKE_DIGEST
    assert repeated["deterministicDigest"] == SMOKE_DIGEST
    assert repeated["canonicalJsonBytes"] == smoke_report["canonicalJsonBytes"]


def test_full_bounded_fixture_stays_within_contract_caps():
    report = benchmark.run_benchmark()
    assert report["passed"] is True
    assert report["mode"] == "bounded"
    assert report["counts"] == {
        "requestCount": 32,
        "decisionObservationCount": 64,
        "targetObservationCount": 32,
        "selectionCount": 32,
        "selectedCount": 32,
        "predictionCount": 32,
        "outcomeCount": 32,
        "evaluationCount": 32,
        "aggregateCount": 4,
    }
    assert report["deterministicDigest"] == BOUNDED_DIGEST
    assert (report["canonicalJsonBytes"]["decisionSnapshot"]
            <= report["caps"]["marketTruth"]["maxSnapshotBytes"])


def test_exact_4gib_cgroup_contract_passes_only_without_swap_or_oom():
    before = _exact_cgroup_snapshot()
    after = _exact_cgroup_snapshot()
    contract = benchmark.cgroup_contract(before, after, required=True)
    assert contract == {
        "required": True,
        "enforcementStatus": "PASS",
        "passed": True,
        "observedExactContract": True,
        "requiredMemoryMaxBytes": 4294967296,
        "requiredSwapMaxBytes": 0,
        "memoryMaxBytes": 4294967296,
        "swapMaxBytes": 0,
        "memoryCurrentBytes": 134217728,
        "memoryPeakBytes": 268435456,
        "oomDelta": 0,
        "oomKillDelta": 0,
        "failureReasons": [],
    }

    bad = dict(after)
    bad["swapMaxBytes"] = 1024
    bad["events"] = {"oom": 12, "oomKill": 8}
    failed = benchmark.cgroup_contract(before, bad, required=True)
    assert failed["enforcementStatus"] == "FAIL"
    assert failed["passed"] is False
    assert set(failed["failureReasons"]) == {
        "swap_max_not_zero", "oom_changed", "oom_kill_changed",
    }


def test_local_missing_cgroup_is_explicitly_skipped_but_never_claimed_exact():
    unavailable = {
        "available": False,
        "memoryCurrentBytes": None,
        "memoryPeakBytes": None,
        "memoryMaxBytes": None,
        "swapMaxBytes": None,
        "events": {"oom": None, "oomKill": None},
    }
    contract = benchmark.cgroup_contract(
        unavailable, unavailable, required=False)
    assert contract["enforcementStatus"] == "SKIPPED_LOCAL"
    assert contract["passed"] is True
    assert contract["observedExactContract"] is False
    assert contract["failureReasons"]

    required = benchmark.cgroup_contract(
        unavailable, unavailable, required=True)
    assert required["enforcementStatus"] == "FAIL"
    assert required["passed"] is False


def test_required_cgroup_flag_enforces_exact_fixture_during_benchmark(tmp_path):
    cgroup_root = tmp_path / "cgroup"
    _write_exact_cgroup(cgroup_root)
    report = benchmark.run_benchmark(
        smoke=True, require_exact_4g=True, cgroup_root=cgroup_root)
    assert report["passed"] is True
    assert report["resources"]["cgroup"]["enforcementStatus"] == "PASS"
    assert report["resources"]["cgroup"]["observedExactContract"] is True


def test_smoke_cli_emits_one_canonical_json_report():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--smoke"],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout.count("\n") == 1
    report = json.loads(completed.stdout)
    assert report["passed"] is True
    assert report["deterministicDigest"] == SMOKE_DIGEST
    assert completed.stdout.strip() == json.dumps(
        report, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"))


def test_script_imports_only_stdlib_and_canonical_contract_modules():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_project_modules = {
        "argus_decision_ledger", "argus_market_data_truth",
    }
    allowed_stdlib_modules = {
        "__future__", "argparse", "datetime", "hashlib", "json", "pathlib",
        "resource", "sys", "time", "tracemalloc", "typing",
    }
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    non_stdlib = imported_roots - allowed_stdlib_modules
    assert non_stdlib == allowed_project_modules
    assert "scanner" not in imported_roots
    assert "tachibana" not in source.lower()


def test_script_calls_canonical_market_truth_and_ledger_v2_apis_directly():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    calls = {
        (node.func.value.id, node.func.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"market_truth", "decision_ledger"}
    }
    assert {
        ("market_truth", "AdapterSpec"),
        ("market_truth", "ProviderAdapterRegistry"),
        ("market_truth", "build_observation"),
        ("market_truth", "validate_observation"),
        ("market_truth", "select_truth"),
        ("market_truth", "build_decision_snapshot"),
        ("market_truth", "verify_decision_snapshot"),
        ("market_truth", "repository_provider_priority"),
        ("decision_ledger", "point_in_time_truth_ref"),
        ("decision_ledger", "session_maturity_contract"),
        ("decision_ledger", "forecast_distribution"),
        ("decision_ledger", "prediction_record_v2"),
        ("decision_ledger", "evaluation_metric"),
        ("decision_ledger", "outcome_resolution_event"),
        ("decision_ledger", "evaluation_event_record"),
        ("decision_ledger", "aggregate_evaluation_events"),
    }.issubset(calls)


def test_exact_head_truth_ledger_ci_gate_preserves_exact_4gib_contract():
    workflow_path = ROOT / ".github" / "workflows" / "memory-attribution.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    for path in (
        "argus_market_clock.py",
        "argus_market_data_truth.py",
        "argus_decision_ledger.py",
        "scripts/truth_ledger_benchmark.py",
        "test_argus_market_data_truth.py",
        "test_argus_prediction_ledger_v2.py",
        "test_truth_ledger_benchmark.py",
    ):
        assert workflow.count(f'- "{path}"') == 2

    job = workflow.split("\n  linux-4gib-truth-ledger:\n", 1)[1]
    assert job.count("actions/checkout@v5") == 1
    exact_head = "${{ github.event.pull_request.head.sha || github.sha }}"
    assert f"ref: {exact_head}" in job
    assert f"expected_head='{exact_head}'" in job
    assert 'test "$(git rev-parse HEAD)" = "$expected_head"' in job
    assert "ROUND2_HEAD_SHA=%s" in job
    assert "--memory 4g --memory-swap 4g --pids-limit 128" in job
    assert 'memory.max)" = "4294967296"' in job
    assert 'memory.swap.max)" = "0"' in job
    assert "pip install --quiet pytest" in job
    assert "test_argus_market_data_truth.py" in job
    assert "test_argus_prediction_ledger_v2.py" in job
    assert "test_truth_ledger_benchmark.py" in job
    assert "scripts/truth_ledger_benchmark.py" in job
    assert "--require-exact-4g" in job
    assert "--smoke" not in job
    assert BOUNDED_DIGEST in job
    assert 'cgroup["memoryMaxBytes"] == 4294967296' in job
    assert 'cgroup["swapMaxBytes"] == 0' in job
    assert 'cgroup["memoryPeakBytes"] < cgroup["memoryMaxBytes"]' in job
    assert 'cgroup["oomDelta"] == 0' in job
    assert 'cgroup["oomKillDelta"] == 0' in job
    assert '"headSha": os.environ["ROUND2_HEAD_SHA"]' in job
    assert f"round2-truth-ledger-proof-{exact_head}" in job
    assert "artifacts/truth-ledger-benchmark.json" in job
    assert "artifacts/round2-truth-ledger-ci-proof.json" in job
    assert "scanner.py" not in job
    assert job.count("if: always()") == 2

    container_step = job.split(
        "- name: Truth and ledger proof in exact 4 GiB cgroup", 1)[1].split(
        "- name: Exact-head truth and ledger terminal gate", 1)[0]
    container_script = textwrap.dedent(
        container_step.split("        run: |\n", 1)[1])
    checked = subprocess.run(
        ["bash", "-n"], input=container_script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr

    terminal_step = job.split(
        "- name: Exact-head truth and ledger terminal gate", 1)[1].split(
        "- name: Publish exact-head Round 2 truth and ledger proof", 1)[0]
    terminal_script = textwrap.dedent(
        terminal_step.split("        run: |\n", 1)[1])
    checked = subprocess.run(
        ["bash", "-n"], input=terminal_script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr
