from pathlib import Path

from scripts import normalized_hash_resource_probe as probe


def _rows(values):
    return [
        {"cycle": index, "after": dict(value)}
        for index, value in enumerate(values, start=1)
    ]


def test_steady_state_summary_uses_cycles_after_warmup_and_worker_baseline():
    baseline = {
        "processRssBytes": 100,
        "rssAnonBytes": 90,
        "pssBytes": 95,
        "arenaBytes": 80,
        "uordblksBytes": 50,
        "fordblksBytes": 30,
    }
    samples = _rows([
        {key: baseline[key] + offset for key in probe.STEADY_STATE_METRICS}
        for offset in (30, 10, 20, 40)
    ])

    summary = probe._steady_state_summary(baseline, samples)

    assert summary["sampleDefinition"] == \
        "cycles_3_plus_after_nearest_rank_p50"
    assert summary["sampleCount"] == 4
    assert summary["afterP50Bytes"]["processRssBytes"] == 120
    assert summary["growthFromBaselineBytes"] == {
        key: 20 for key in probe.STEADY_STATE_METRICS
    }


def test_material_rss_signal_is_independent_of_process_lifetime_high_water():
    threshold = probe.MINIMUM_MATERIAL_RSS_REDUCTION_BYTES
    fallback_growth = 16 * probe.MIB
    candidate_growth = 64 * 1024
    failed_high_water_reduction = 712_704

    steady_reduction = probe._reduction(
        fallback_growth, candidate_growth)

    assert failed_high_water_reduction < threshold
    assert steady_reduction == 16 * probe.MIB - 64 * 1024
    assert steady_reduction >= threshold


def test_paired_steady_state_reduction_uses_fixed_logical_cycles():
    fallback = {
        "baseline": {"processRssBytes": 100},
        "cycles": _rows([
            {"processRssBytes": 1_000},
            {"processRssBytes": 2_000},
            {"processRssBytes": 116},
            {"processRssBytes": 118},
            {"processRssBytes": 114},
        ]),
    }
    candidate = {
        "baseline": {"processRssBytes": 100},
        "cycles": _rows([
            {"processRssBytes": 5_000},
            {"processRssBytes": 6_000},
            {"processRssBytes": 101},
            {"processRssBytes": 102},
            {"processRssBytes": 103},
        ]),
    }

    assert probe._paired_steady_state_reduction(
        fallback, candidate, "processRssBytes") == 15


def test_missing_steady_state_metric_fails_closed():
    summary = probe._steady_state_summary({}, _rows([{} for _ in range(30)]))
    assert summary["afterP50Bytes"]["processRssBytes"] == \
        probe.memory.UNKNOWN
    assert summary["growthFromBaselineBytes"]["processRssBytes"] == \
        probe.memory.UNKNOWN
    assert probe._reduction(probe.memory.UNKNOWN, 0) == \
        probe.memory.UNKNOWN

    fallback = {"baseline": {"processRssBytes": 1}, "cycles": _rows([
        {"processRssBytes": 1} for _ in range(32)])}
    candidate = {"baseline": {"processRssBytes": 1}, "cycles": _rows([
        {"processRssBytes": 1} for _ in range(32)])}
    candidate["cycles"][5]["cycle"] = 99
    assert probe._paired_steady_state_reduction(
        fallback, candidate, "processRssBytes") == probe.memory.UNKNOWN


def test_paired_allocation_peak_summary_requires_every_fixed_cycle():
    fallback = {"allocationTrace": {"cycles": [
        {"cycle": cycle, "peakIncrementBytes": 10 * probe.MIB + cycle}
        for cycle in range(1, 33)
    ]}}
    candidate = {"allocationTrace": {"cycles": [
        {"cycle": cycle, "peakIncrementBytes": 2 * probe.MIB + cycle}
        for cycle in range(1, 33)
    ]}}

    summary = probe._paired_allocation_peak_reduction_summary(
        fallback, candidate)

    assert summary == {
        "sampleDefinition":
            "paired_cycles_3_plus_peak_increment_reduction",
        "sampleCount": 30,
        "minimum": 8 * probe.MIB,
        "p50": 8 * probe.MIB,
        "p95": 8 * probe.MIB,
        "maximum": 8 * probe.MIB,
        "span": 0,
    }

    candidate["allocationTrace"]["cycles"][5]["cycle"] = 99
    failed = probe._paired_allocation_peak_reduction_summary(
        fallback, candidate)
    assert failed["sampleCount"] == 0
    assert failed["minimum"] == probe.memory.UNKNOWN
    assert failed["p50"] == probe.memory.UNKNOWN


def test_supervisor_separates_os_rss_and_asset_allocation_gates(monkeypatch):
    environment = {
        "pythonImplementation": "CPython",
        "pythonVersion": "3.12.0",
        "pythonBuild": "3.12.0 test",
        "libcName": "glibc",
        "libcVersion": "2.36",
        "system": "Linux",
        "machine": "x86_64",
        "kernelRelease": "test-kernel",
        "runnerImageOs": "ubuntu24",
        "runnerImageVersion": "test-version",
        "containerImage": "python@sha256:test",
        "sourceHeadSha": "a" * 40,
        "executionSha": "b" * 40,
    }
    monkeypatch.setattr(
        probe, "_environment_fingerprint", lambda: dict(environment))
    pid_by_key = {
        ("resource", "verified", "fallback"): 101,
        ("resource", "verified", "normalized"): 102,
        ("resource", "asset", "fallback"): 103,
        ("resource", "asset", "normalized"): 104,
        ("allocation_peak", "asset", "fallback"): 105,
        ("allocation_peak", "asset", "normalized"): 106,
    }

    def worker(
            store_kind, mode, cycles, bars_per_record,
            measurement_profile="resource"):
        # Verified retains a stable 4 MiB OS signal.  Asset deliberately has
        # only a 64 KiB retained signal, mirroring the allocator-noise case.
        growth = (
            4 * probe.MIB if store_kind == "verified" and mode == "fallback"
            else 64 * 1024 if store_kind == "asset" and mode == "fallback"
            else 0)
        baseline = {
            metric: 10 * probe.MIB for metric in probe.STEADY_STATE_METRICS
        }
        baseline.update({
            "processPeakRssBytes": 100 * probe.MIB,
            "topReleasableBytes": 0,
            "cgroupCurrentBytes": 10 * probe.MIB,
            "cgroupPeakBytes": 20 * probe.MIB,
            "cgroupMaxBytes": probe.memory.UNKNOWN,
        })
        after = dict(baseline)
        for metric in probe.STEADY_STATE_METRICS:
            after[metric] = baseline[metric] + growth
        rows = [
            {"cycle": index, "after": dict(after)}
            for index in range(1, cycles + 1)
        ]
        memory = {
            "baseline": baseline,
            "final": dict(after),
            "steadyState": probe._steady_state_summary(baseline, rows[2:]),
            "cycles": rows,
            "oomDelta": probe.memory.UNKNOWN,
            "oomKillDelta": probe.memory.UNKNOWN,
        }
        if measurement_profile == "allocation_peak":
            peak = 8 * probe.MIB if mode == "fallback" else 1 * probe.MIB
            return {
                "storeKind": store_kind,
                "pathMode": mode,
                "measurementProfile": "python_allocation_peak",
                "freshProcess": True,
                "processId": pid_by_key[
                    (measurement_profile, store_kind, mode)],
                "environment": environment,
                "returnCode": 0,
                "abnormalExit": False,
                "passed": True,
                "digest": "digest-asset",
                "storeShape": {"barsPerRecord": bars_per_record},
                "wholeStateRepresentationsPerCall": (
                    2 if mode == "fallback" else 1),
                "normalizeCallsDuringCycles": (
                    cycles if mode == "fallback" else 0),
                "durationMs": {
                    "p50": 4.0 if mode == "fallback" else 1.0},
                "allocationTrace": {"cycles": [
                    {"cycle": cycle, "peakIncrementBytes": peak}
                    for cycle in range(1, cycles + 1)
                ], "peakIncrementBytes": {"p50": peak}},
                "memory": memory,
                "runtimeActions": {
                    "allocatorTrimInvoked": False,
                    "forcedCollectionInvoked": False,
                    "restartInvoked": False,
                },
                "checks": {
                    "productionCalibratedCanonicalInput": True,
                    "allocationTraceStartedFresh": True,
                    "allocationTraceStopped": True,
                    "logicalPeakBelow3GiB": True,
                },
            }
        return {
            "storeKind": store_kind,
            "pathMode": mode,
            "freshProcess": True,
            "processId": pid_by_key[
                (measurement_profile, store_kind, mode)],
            "measurementProfile": "os_resource_uninstrumented",
            "environment": environment,
            "returnCode": 0,
            "abnormalExit": False,
            "passed": True,
            "digest": f"digest-{store_kind}",
            "storeShape": {"barsPerRecord": bars_per_record},
            "wholeStateRepresentationsPerCall": (
                2 if mode == "fallback" else 1),
            "normalizeCallsDuringCycles": (
                cycles if mode == "fallback" else 0),
            "durationMs": {"p50": 2.0 if mode == "fallback" else 1.0},
            "memory": memory,
            "runtimeActions": {
                "allocatorTrimInvoked": False,
                "forcedCollectionInvoked": False,
                "restartInvoked": False,
            },
            "checks": {
                "productionCalibratedCanonicalInput": True,
                "allocationTracerNotLoaded": True,
                "plateauBelow128MiB": True,
                "logicalPeakBelow3GiB": True,
            },
        }

    monkeypatch.setattr(probe, "_run_worker", worker)
    report = probe.run(cycles=32)

    assert report["passed"] is True
    assert report["schemaVersion"] == \
        "argus-normalized-hash-resource-proof-v3"
    assert report["workerCount"] == 6
    assert report["resourceWorkerCount"] == 4
    assert report["allocationWorkerCount"] == 2
    assert report["checks"]["sixFreshProcesses"] is True
    assert report["checks"]["fourUninstrumentedResourceProcesses"] is True
    assert report["checks"]["twoFreshAssetAllocationProcesses"] is True
    assert report["checks"][
        "verifiedSteadyStateRssMateriallyReduced"] is True
    assert report["checks"][
        "verifiedSteadyStatePssMateriallyReduced"] is True
    assert report["checks"][
        "verifiedSteadyStateRssAnonMateriallyReduced"] is True
    assert report["checks"][
        "assetAllocationPeakMinimumMateriallyReduced"] is True
    assert report["checks"][
        "assetAllocationPeakP50MateriallyReduced"] is True
    assert report["checks"]["environmentFingerprintComplete"] is True
    assert report["diagnostics"][
        "assetPostCallSteadyStateReductionBytes"][
            "processRssBytes"] == 64 * 1024
    assert report["diagnostics"][
        "assetAllocationPeakReductionBytes"]["minimum"] == 7 * probe.MIB
    assert report["diagnostics"][
        "processPeakRssMateriallyReduced"] is False


def test_normalized_probe_keeps_one_mib_and_pins_execution_image():
    assert probe.MINIMUM_MATERIAL_RSS_REDUCTION_BYTES == probe.MIB
    assert probe.MINIMUM_MATERIAL_ALLOCATION_REDUCTION_BYTES == probe.MIB
    workflow = Path(".github/workflows/memory-attribution.yml").read_text(
        encoding="utf-8")
    source = Path("scripts/normalized_hash_resource_probe.py").read_text(
        encoding="utf-8")
    assert "verifiedSteadyStateRssMateriallyReduced" in source
    assert "assetAllocationPeakMinimumMateriallyReduced" in source
    assert "assetAllocationPeakP50MateriallyReduced" in source
    assert "processPeakRssRole" in source
    assert "\nimport tracemalloc" not in source
    assert "    import tracemalloc as allocation_tracer" in source
    assert "python:3.12-slim@sha256:" in workflow
    assert "ARGUS_PROBE_RUNNER_IMAGE_VERSION" in workflow
    assert "ARGUS_PROBE_HEAD_SHA" in workflow
    assert "ARGUS_PROBE_EXECUTION_SHA" in workflow
    assert "test_argus_normalized_hash_resource_probe.py" in workflow
