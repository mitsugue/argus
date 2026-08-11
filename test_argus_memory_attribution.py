import inspect
import json
import pathlib
import threading
import tracemalloc

import argus_memory_attribution as memory
import scanner


def _sample(rss, *, fd=4, threads=1):
    unknown_status = {value: memory.UNKNOWN for value in memory._STATUS_FIELDS.values()}
    unknown_status.update({"vmRssBytes": rss, "fdCount": fd,
                           "threads": threads, "rssPeakBytes": rss})
    return {
        "capturedAt": "2026-08-10T00:00:00Z",
        "process": unknown_status,
        "smapsRollup": {value: memory.UNKNOWN
                         for value in memory._SMAPS_FIELDS.values()},
        "cgroup": {"memoryCurrentBytes": rss,
                   "memoryPeakBytes": rss,
                   "memoryMaxBytes": 4 * 1024 ** 3,
                   "stat": {key: memory.UNKNOWN
                            for key in memory._CGROUP_STAT_FIELDS}},
        "allocatorMetrics": "UNAVAILABLE",
        "logicalObjects": memory.logical_metrics({}),
    }


def _rich_sample(rss, arena, live, free):
    sample = _sample(rss)
    sample["process"].update({"rssAnonBytes": rss - 4096,
                              "rssFileBytes": 4096})
    sample["smapsRollup"]["pssBytes"] = rss - 2048
    sample["allocatorMetrics"] = {
        "status": "AVAILABLE", "arenaBytes": arena, "freeChunkCount": 10,
        "mmapBytes": 0, "allocatedBytes": live, "freeBytes": free,
        "topReleasableBytes": 4096,
    }
    sample["cgroup"]["stat"]["anon"] = rss
    return sample


def _complete_legacy(recorder, index):
    key = f"legacy-{index}"
    base = 100_000_000 + index * 1024
    recorder.begin(key, {
        "missionWindowId": f"mw-legacy-{index}",
        "triggerSource": "ec2_systemd",
        "scheduledAt": "2026-08-10T00:00:00Z",
        "actualAt": "2026-08-10T00:00:01Z",
        "checkpointWriteNumber": index + 1,
        "stage1EffectiveState": "disabled",
        "v2GenerationAttempted": False,
        "legacyCheckpointAttempted": True,
    }, initial_sample=_sample(base))
    for offset, phase in enumerate(("T1", "T2", "T3", "T4", "T5"), 1):
        recorder.capture(key, phase, sample=_sample(base + offset * 1024))
    recorder.mark_not_applicable(
        key, ("T6", "T7", "T8", "T9", "T10"),
        reason="checkpoint_v2_disabled")
    recorder.capture(key, "T11", sample=_sample(base + 7 * 1024))
    recorder.capture(key, "T12", sample=_sample(base + 8 * 1024))
    return recorder.complete(key)


def _complete_stage1(recorder, index):
    key = f"stage1-{index}"
    base = 120_000_000 + index * 2048
    recorder.begin(key, {
        "missionWindowId": f"mw-stage1-{index}",
        "triggerSource": "github_schedule",
        "scheduledAt": "2026-08-10T00:00:00Z",
        "actualAt": "2026-08-10T00:00:01Z",
        "checkpointWriteNumber": index + 1,
        "stage1EffectiveState": "enabled",
        "v2GenerationAttempted": True,
        "legacyCheckpointAttempted": True,
    }, initial_sample=_sample(base))
    for offset, phase in enumerate(memory.PHASES[1:], 1):
        recorder.capture(
            key, phase, sample=_sample(base + offset * 2048),
            metadata=({"generationId": f"generation-{index}"}
                      if phase in ("T9", "T10") else None))
    return recorder.complete(key)


def test_linux_collectors_are_scalar_fail_open_and_never_trim_allocator():
    snapshot = memory.memory_snapshot({"missionBookkeepingEntries": 2})
    assert set(snapshot) == {
        "capturedAt", "process", "smapsRollup", "cgroup",
        "allocatorMetrics", "logicalObjects"}
    assert snapshot["logicalObjects"]["missionBookkeepingEntries"] == 2
    assert isinstance(snapshot["process"]["fdCount"], (int, str))
    source = inspect.getsource(memory)
    assert ".malloc_trim(" not in source
    assert "libc.malloc_trim" not in source
    allocator = snapshot["allocatorMetrics"]
    assert allocator == "UNAVAILABLE" or set(allocator) == {
        "status", "arenaBytes", "freeChunkCount", "mmapBytes",
        "allocatedBytes", "freeBytes", "topReleasableBytes"}


def test_cgroup_v2_parser_marks_optional_fields_unknown(tmp_path):
    (tmp_path / "memory.current").write_text("123\n", encoding="utf-8")
    (tmp_path / "memory.peak").write_text("456\n", encoding="utf-8")
    (tmp_path / "memory.max").write_text("max\n", encoding="utf-8")
    (tmp_path / "memory.stat").write_text(
        "anon 10\nfile 20\nslab 30\n", encoding="utf-8")
    result = memory.cgroup_metrics(str(tmp_path))
    assert result["memoryCurrentBytes"] == 123
    assert result["memoryPeakBytes"] == 456
    assert result["memoryMaxBytes"] == "max"
    assert result["stat"]["anon"] == 10
    assert result["stat"]["file"] == 20
    assert result["stat"]["sock"] == memory.UNKNOWN


def test_history_is_bounded_after_100_missions_and_scalar_only():
    recorder = memory.MemoryAttributionRecorder(16)
    for index in range(100):
        _complete_legacy(recorder, index)
    view = recorder.view()
    assert view["historyLimit"] == 16
    assert view["historyCount"] == 16
    assert view["completedCount"] == 100
    assert view["droppedCount"] == 84
    assert view["historySerializedBytes"] < 2 * 1024 * 1024
    assert view["records"][0]["metadata"]["missionWindowId"] == "mw-legacy-84"
    encoded = json.dumps(view, sort_keys=True)
    for forbidden in ("portfolioData", "symbolUniverse", "newsContent",
                      "checkpointPayload", "ARGUS_ADMIN_TOKEN"):
        assert forbidden not in encoded


def test_source_subphases_capture_real_boundaries_and_scalar_deltas():
    recorder = memory.MemoryAttributionRecorder(16)
    recorder.begin(
        "source-1", {"missionWindowId": "mw-source"},
        initial_sample=_rich_sample(1000, 800, 300, 500))
    for index, phase in enumerate(memory.SOURCE_PHASES):
        recorder.capture_source_phase(
            "source-1", phase,
            sample=_rich_sample(1000 + index * 100,
                                800 + index * 80,
                                300 + index,
                                500 + index * 79),
            metadata={"operation": f"source_boundary_{index}",
                      "topLevelKeys": index})
    for phase in memory.PHASES[1:]:
        recorder.capture("source-1", phase, sample=_sample(2000))
    record = recorder.complete("source-1")
    source = record["sourceConstruction"]
    assert source["phaseOrder"] == list(memory.SOURCE_PHASES)
    assert source["phases"]["S0"]["deltaFromPrevious"]["rssBytes"] \
        == memory.NOT_APPLICABLE
    assert source["phases"]["S1"]["deltaFromPrevious"] == {
        "rssBytes": 100, "rssAnonBytes": 100, "rssFileBytes": 0,
        "pssBytes": 100, "arenaBytes": 80, "allocatedBytes": 1,
        "freeBytes": 79, "topReleasableBytes": 0,
        "cgroupCurrentBytes": 100, "cgroupAnonBytes": 100,
    }
    assert source["phases"]["S8"]["metadata"]["topLevelKeys"] == \
        len(memory.SOURCE_PHASES) - 1


def test_prelude_and_mission_path_are_fixed_bounded_scalar_projections():
    recorder = memory.MemoryAttributionRecorder(16)
    prelude = {
        phase: _rich_sample(1000 + index * 10, 800 + index * 5,
                            300, 500 + index * 5)
        for index, phase in enumerate(memory.PRELUDE_PHASES)
    }
    recorder.begin(
        "path-1", {"missionWindowId": "mw-path"},
        initial_sample=_rich_sample(1100, 850, 300, 550),
        prelude_samples=prelude)
    for index, phase in enumerate(memory.MISSION_PATH_PHASES[1:], 1):
        recorder.capture_mission_path_phase(
            "path-1", phase,
            sample=_rich_sample(1100 + index * 10, 850 + index * 5,
                                300, 550 + index * 5),
            metadata={"operation": f"fixed_{index}"})
    for phase in memory.PHASES[1:]:
        recorder.capture("path-1", phase, sample=_sample(2000))
    record = recorder.complete("path-1")
    assert record["preludeAttribution"]["phaseOrder"] == list(
        memory.PRELUDE_PHASES)
    assert record["preludeAttribution"]["phases"]["P1"]["metadata"][
        "operation"] == "auth_storage_body_lease_constructed"
    assert record["missionPathAttribution"]["phaseOrder"] == list(
        memory.MISSION_PATH_PHASES)
    encoded = json.dumps(record, sort_keys=True)
    assert "sampleProjection" in encoded
    assert "checkpointPayload" not in encoded
    assert record["sourceConstruction"]["phaseOrder"] == []


def test_mark_not_applicable_distinguishes_unknown_for_all_phase_containers():
    recorder = memory.MemoryAttributionRecorder(16)
    recorder.begin(
        "skip-1", {"missionWindowId": "mw-skip"},
        initial_sample=_rich_sample(1000, 800, 300, 500))
    recorder.capture_prelude_phase(
        "skip-1", "P0", sample=_rich_sample(1000, 800, 300, 500))
    recorder.mark_not_applicable(
        "skip-1", ("T0", "T1", "P0", "P1", "M0", "M1", "S0"),
        reason="duplicate_or_exception_path")
    recorder.mark_not_applicable(
        "skip-1", ("T1", "P1", "M1", "S0"),
        reason="must_not_duplicate_phase_order")
    record = recorder.complete("skip-1")

    assert record["phases"]["T0"]["status"] == "CAPTURED"
    assert record["preludeAttribution"]["phases"]["P0"]["status"] == \
        "CAPTURED"
    assert record["missionPathAttribution"]["phases"]["M0"]["status"] == \
        "CAPTURED"
    for container, phase, sample_field in (
            (record, "T1", "sample"),
            (record["preludeAttribution"], "P1", "sampleProjection"),
            (record["missionPathAttribution"], "M1", "sampleProjection"),
            (record["sourceConstruction"], "S0", "sample")):
        row = container["phases"][phase]
        assert row["status"] == memory.NOT_APPLICABLE
        assert row[sample_field] is None
        assert row["metadata"]["reason"] == "duplicate_or_exception_path"
        assert container["phaseOrder"].count(phase) == 1
    assert record["phases"]["T2"]["status"] == memory.UNKNOWN
    assert record["preludeAttribution"]["phases"]["P2"]["status"] == \
        memory.UNKNOWN
    assert record["missionPathAttribution"]["phases"]["M2"]["status"] == \
        memory.UNKNOWN
    assert record["sourceConstruction"]["phases"]["S1"]["status"] == \
        memory.UNKNOWN
    assert all(
        value == memory.NOT_APPLICABLE
        for value in record["sourceConstruction"]["phases"]["S0"]
        ["deltaFromPrevious"].values())


def test_operation_ring_is_bounded_after_250_events_and_privacy_safe():
    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=1024)
    for index in range(250):
        start = _rich_sample(10_000 + index, 8_000, 3_000, 5_000)
        end = _rich_sample(12_000 + index, 10_000, 3_010, 6_990)
        token = recorder.begin(
            kind="HTTP",
            name=("GET /api/argus/events/"
                  "123e4567-e89b-12d3-a456-426614174000?symbol=SECRET"),
            known=False, sample=start,
            metadata={"requestBody": {"must": "not survive"}})
        recorder.complete(token, sample=end, metadata={"statusCode": 200})
    view = recorder.view()
    assert view["historyLimit"] == 32
    assert view["historyCount"] == 32
    assert view["observedCount"] == 250
    assert view["qualifiedCount"] == 250
    assert view["droppedCount"] == 218
    assert view["historySerializedBytes"] < 512 * 1024
    encoded = json.dumps(view, sort_keys=True)
    assert "SECRET" not in encoded
    assert "123e4567" not in encoded
    assert "<id>" in encoded
    assert "requestBody" not in encoded
    assert "must" not in encoded

    quiet = memory.OperationAttributionRecorder(32, threshold_bytes=1024)
    token = quiet.begin(kind="HTTP", name="GET /healthz", sample=_sample(10))
    assert quiet.complete(token, sample=_sample(11)) is None
    assert quiet.view()["historyCount"] == 0


def test_heavy_hitters_survive_tail_overwrite_and_subthreshold_repetition():
    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=64 * 1024 * 1024)
    mib = 1024 * 1024
    token = recorder.begin(
        kind="internal", name="source.asset_chart_reports.normalize",
        sample=_rich_sample(10 * mib, 8 * mib, 3 * mib, 5 * mib))
    recorder.complete(
        token, sample=_rich_sample(19 * mib, 17 * mib, 4 * mib, 13 * mib))
    for index in range(5000):
        token = recorder.begin(
            kind="HTTP", name=f"GET /noise/{index}",
            sample=_rich_sample(1000, 1000, 500, 500))
        recorder.complete(
            token, sample=_rich_sample(2024, 2024, 600, 1424))
    for _ in range(100):
        token = recorder.begin(
            kind="scheduler", name="small_repeated_allocator",
            sample=_rich_sample(1000, 1000, 500, 500))
        recorder.complete(
            token, sample=_rich_sample(103400, 103400, 600, 102800))
    view = recorder.view()
    assert view["historyCount"] == 0
    assert view["observedCount"] == 5101
    for rows in view["heavyHitters"].values():
        assert len(rows) <= 16
    arena_names = {
        row["operationName"]
        for row in view["heavyHitters"]["cumulativePositiveArenaBytes"]}
    assert "internal:source.asset_chart_reports.normalize" in arena_names
    assert "scheduler:small_repeated_allocator" in arena_names
    assert all(row.get("errorUpperBoundBytes", 0) >= 0
               for row in view["heavyHitters"][
                   "cumulativePositiveArenaBytes"])


def test_admitted_heavy_hitter_updates_supplements_on_nonpositive_score():
    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=0, heavy_hitter_limit=4)
    first = recorder.begin(
        kind="internal", name="admitted_key",
        sample=_rich_sample(100, 100, 40, 60))
    recorder.complete(first, sample=_rich_sample(200, 200, 90, 110))
    second = recorder.begin(
        kind="internal", name="admitted_key",
        sample=_rich_sample(200, 200, 90, 110))
    recorder.complete(second, sample=_rich_sample(150, 150, 70, 80))
    view = recorder.view()
    cumulative = view["heavyHitters"]["cumulativePositiveArenaBytes"][0]
    maximum = view["heavyHitters"]["maximumSingleArenaDeltaBytes"][0]
    assert cumulative["estimatedBytes"] == 100
    assert maximum["maximumBytes"] == 100
    assert cumulative["eventCountSinceAdmission"] == 2
    assert maximum["eventCountSinceAdmission"] == 2
    assert cumulative["signedAllocatedBytesSinceAdmission"] == 30
    assert cumulative["sameThreadCountSinceAdmission"] == 2


def test_operation_concurrency_classification_is_conservative():
    recorder = memory.OperationAttributionRecorder(32, threshold_bytes=0)
    first = recorder.begin(
        kind="internal", name="first", sample=_rich_sample(100, 100, 40, 60))
    second = recorder.begin(
        kind="internal", name="second", sample=_rich_sample(100, 100, 40, 60))
    second_row = recorder.complete(
        second, sample=_rich_sample(120, 120, 50, 70))
    first_row = recorder.complete(
        first, sample=_rich_sample(130, 130, 60, 70))
    solo = recorder.begin(
        kind="internal", name="solo", sample=_rich_sample(130, 130, 60, 70))
    solo_row = recorder.complete(
        solo, sample=_rich_sample(140, 140, 70, 70))
    invalid_row = recorder.complete(
        solo, sample=_rich_sample(140, 140, 70, 70))
    assert first_row["concurrencyClass"] == "OVERLAPPED"
    assert second_row["concurrencyClass"] == "OVERLAPPED"
    assert solo_row["concurrencyClass"] == "EXCLUSIVE"
    assert invalid_row["concurrencyClass"] == "UNKNOWN"
    assert first_row["completionThreadClass"] == "SAME_THREAD"
    assert first_row["sameThreadCompletion"] is True
    assert invalid_row["completionThreadClass"] == "UNKNOWN"
    view = recorder.view()
    assert view["activeCount"] == 0
    assert view["maximumActiveCount"] == 2
    assert view["concurrencyScope"] == "instrumented_operations_only"


def test_cross_thread_completion_is_scalar_and_active_tracking_is_bounded():
    recorder = memory.OperationAttributionRecorder(
        64, threshold_bytes=0, active_operation_limit=4)
    tokens = [
        recorder.begin(
            kind="background", name=f"bounded-{index}",
            sample=_rich_sample(100, 100, 40, 60))
        for index in range(9)
    ]
    pressured = recorder.view()
    assert pressured["activeCount"] == 9
    assert pressured["activeTrackedCount"] == 4
    assert pressured["activeTrackingLimit"] == 4
    assert pressured["activeTrackingOverflowActiveCount"] == 5
    assert pressured["activeTrackingOverflowCount"] == 5

    completed = {}

    def finish_on_worker():
        completed["row"] = recorder.complete(
            tokens[0], sample=_rich_sample(120, 120, 50, 70))

    worker = threading.Thread(target=finish_on_worker)
    worker.start()
    worker.join()
    assert completed["row"]["completionThreadClass"] == "CROSS_THREAD"
    assert completed["row"]["sameThreadCompletion"] is False
    assert completed["row"]["crossThreadCompletion"] is True
    for token in tokens[1:]:
        recorder.complete(token, sample=_rich_sample(120, 120, 50, 70))
    released = recorder.view()
    assert released["activeCount"] == 0
    assert released["activeTrackedCount"] == 0
    assert released["activeTrackingOverflowActiveCount"] == 0
    assert released["maximumActiveCount"] == 9
    assert sum(
        row["completionThreadClass"] == "CROSS_THREAD"
        for row in released["records"]) == 1


def test_operation_snapshot_exceptions_release_registered_and_overflow_slots():
    class ExplodingCopy(dict):
        def __deepcopy__(self, memo):
            raise RuntimeError("synthetic snapshot failure")

    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=0, active_operation_limit=2)
    try:
        recorder.begin(
            kind="internal", name="begin_failure",
            sample=ExplodingCopy(_rich_sample(100, 100, 40, 60)))
        assert False, "begin must propagate the synthetic copy failure"
    except RuntimeError:
        pass
    assert recorder.view()["activeCount"] == 0

    first = recorder.begin(
        kind="internal", name="first",
        sample=_rich_sample(100, 100, 40, 60))
    second = recorder.begin(
        kind="internal", name="second",
        sample=_rich_sample(100, 100, 40, 60))
    try:
        recorder.begin(
            kind="internal", name="overflow_begin_failure",
            sample=ExplodingCopy(_rich_sample(100, 100, 40, 60)))
        assert False, "overflow begin must propagate the synthetic copy failure"
    except RuntimeError:
        pass
    after_overflow_failure = recorder.view()
    assert after_overflow_failure["activeTrackedCount"] == 2
    assert after_overflow_failure["activeTrackingOverflowActiveCount"] == 0

    overflow = recorder.begin(
        kind="internal", name="overflow_complete_failure",
        sample=_rich_sample(100, 100, 40, 60))
    assert recorder.view()["activeTrackingOverflowActiveCount"] == 1
    try:
        recorder.complete(
            overflow,
            sample=ExplodingCopy(_rich_sample(120, 120, 50, 70)))
        assert False, "overflow complete must release after snapshot failure"
    except RuntimeError:
        pass
    after_overflow_complete_failure = recorder.view()
    assert after_overflow_complete_failure["activeTrackedCount"] == 2
    assert after_overflow_complete_failure[
        "activeTrackingOverflowActiveCount"] == 0

    try:
        recorder.complete(
            first,
            sample=ExplodingCopy(_rich_sample(120, 120, 50, 70)))
        assert False, "complete must propagate the synthetic copy failure"
    except RuntimeError:
        pass
    after_complete_failure = recorder.view()
    assert after_complete_failure["activeCount"] == 1
    assert after_complete_failure["activeTrackedCount"] == 1
    recorder.complete(second, sample=_rich_sample(120, 120, 50, 70))
    assert recorder.view()["activeCount"] == 0


def test_intermission_summary_subtracts_only_exclusive_contributors():
    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=0, intermission_limit=16)
    recorder.open_intermission(
        record_id="m0", mission_window_id="mw-0",
        sample=_rich_sample(1000, 800, 300, 500))
    token = recorder.begin(
        kind="background", name="exclusive_work",
        sample=_rich_sample(1000, 800, 300, 500))
    recorder.complete(
        token, sample=_rich_sample(1100, 850, 320, 530))
    result = recorder.close_intermission(
        next_record_id="m1", next_mission_window_id="mw-1",
        sample=_rich_sample(1300, 1000, 400, 600))
    assert result["boundaryDeltas"]["rssBytes"] == 300
    assert result["exclusiveSignedRssBytes"] == 100
    assert result["unexplainedResidual"]["rssBytes"] == 200
    assert result["kindCounts"]["background"] == 1
    assert result["kindAggregates"]["background"]["count"] == 1
    assert result["kindAggregates"]["background"][
        "maxRssDeltaBytes"] == 100
    assert result["kindAggregates"]["background"][
        "completionThreadCounts"]["SAME_THREAD"] == 1
    assert set(result["kindAggregates"]) == set(memory._OPERATION_KINDS)
    assert result["concurrencyCounts"]["EXCLUSIVE"] == 1
    for index in range(20):
        recorder.open_intermission(
            record_id=f"m-{index}", mission_window_id=f"mw-{index}",
            sample=_rich_sample(1000, 800, 300, 500))
        recorder.close_intermission(
            next_record_id=f"n-{index}",
            next_mission_window_id=f"nw-{index}",
            sample=_rich_sample(1001, 801, 301, 500))
    history = recorder.view()["intermissionHistory"]
    assert history["historyCount"] == 16
    assert history["droppedCount"] == 5


def test_intermission_reports_boundary_spanning_without_false_attribution():
    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=0, intermission_limit=4)
    prior_completed = recorder.begin(
        kind="scheduler", name="prior_completed",
        sample=_rich_sample(900, 700, 250, 450))
    prior_still_active = recorder.begin(
        kind="journal", name="prior_still_active",
        sample=_rich_sample(900, 700, 250, 450))
    recorder.open_intermission(
        record_id="m0", mission_window_id="mw-0",
        sample=_rich_sample(1000, 800, 300, 500))
    recorder.complete(
        prior_completed, sample=_rich_sample(1050, 825, 310, 515))
    contained = recorder.begin(
        kind="background", name="contained",
        sample=_rich_sample(1050, 825, 310, 515))
    recorder.complete(
        contained, sample=_rich_sample(1100, 850, 320, 530))
    started_during = recorder.begin(
        kind="HTTP", name="still_running",
        sample=_rich_sample(1100, 850, 320, 530))
    result = recorder.close_intermission(
        next_record_id="m1", next_mission_window_id="mw-1",
        sample=_rich_sample(1200, 900, 350, 550))

    assert result["inFlightAtOpen"] == 2
    assert result["observedCompletionCount"] == 2
    assert result["operationCount"] == 2
    assert result["completedOperationCount"] == 1
    assert result["boundarySpanningCompletedCount"] == 1
    assert result["boundarySpanningKindCounts"]["scheduler"] == 1
    assert result["startedBeforeIntervalStillActiveAtClose"] == 1
    assert result["startedDuringIntervalStillActiveAtClose"] == 1
    assert result["untrackedStillActiveAtClose"] == 0
    assert result["boundarySpanningInFlightCount"] == 2
    assert result["boundarySpanningCount"] == 3
    assert result["kindCounts"]["scheduler"] == 0
    assert result["kindCounts"]["background"] == 1
    assert result["kindAggregates"]["background"]["count"] == 1
    assert result["untrackedBoundaryClassification"] == memory.NOT_APPLICABLE
    recorder.complete(
        prior_still_active, sample=_rich_sample(1200, 900, 350, 550))
    recorder.complete(
        started_during, sample=_rich_sample(1200, 900, 350, 550))
    assert recorder.view()["activeCount"] == 0


def test_10000_operations_remain_bounded_private_and_scalar_only():
    recorder = memory.OperationAttributionRecorder(
        32, threshold_bytes=8 * 1024 * 1024,
        active_operation_limit=8)
    before_fd = memory.process_metrics()["fdCount"]
    before_threads = threading.active_count()
    anchors = [
        recorder.begin(
            kind="background", name=f"anchor-{index}",
            sample=_rich_sample(1000, 1000, 500, 500))
        for index in range(17)
    ]
    pressure = recorder.view()
    assert pressure["activeCount"] == 17
    assert pressure["activeTrackedCount"] == 8
    assert pressure["activeTrackingOverflowActiveCount"] == 9
    for index in range(10_000):
        token = recorder.begin(
            kind="HTTP",
            name=(f"GET /asset/{index}/"
                  "123e4567-e89b-12d3-a456-426614174000?symbol=SECRET"),
            sample=_rich_sample(1000, 1000, 500, 500),
            metadata={"requestBody": "SECRET"})
        recorder.complete(
            token, sample=_rich_sample(2024, 2024, 600, 1424),
            metadata={"statusCode": 200})
    for token in anchors:
        recorder.complete(
            token, sample=_rich_sample(1000, 1000, 500, 500))
    view = recorder.view()
    encoded = json.dumps(view, sort_keys=True)
    assert view["observedCount"] == 10_017
    assert view["historyCount"] == 0
    assert view["activeCount"] == 0
    assert view["activeTrackedCount"] == 0
    assert view["activeTrackingOverflowActiveCount"] == 0
    assert view["activeTrackingOverflowCount"] == 10_009
    assert view["maximumActiveCount"] == 18
    assert view["knownOperationCount"] <= 64
    assert all(len(rows) <= 16 for rows in view["heavyHitters"].values())
    assert view["serializedBytes"] < 2 * 1024 * 1024
    assert "SECRET" not in encoded
    assert "123e4567" not in encoded
    assert "_attributionStartedThreadId" not in encoded
    assert memory.process_metrics()["fdCount"] == before_fd
    assert threading.active_count() == before_threads


def test_32_cycle_legacy_and_stage1_phase_and_overhead_contracts():
    tracemalloc.start()
    try:
        before_current, _ = tracemalloc.get_traced_memory()
        legacy = memory.MemoryAttributionRecorder(16)
        stage1 = memory.MemoryAttributionRecorder(16)
        for index in range(32):
            _complete_legacy(legacy, index)
            _complete_stage1(stage1, index)
        after_current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert after_current - before_current < 8 * 1024 * 1024
    assert peak - before_current < 16 * 1024 * 1024
    assert legacy.view()["completedCount"] == 32
    assert stage1.view()["completedCount"] == 32
    legacy_last = legacy.view()["records"][-1]
    stage1_last = stage1.view()["records"][-1]
    assert legacy_last["phaseOrder"] == list(memory.PHASES)
    assert all(legacy_last["phases"][phase]["status"] == memory.NOT_APPLICABLE
               for phase in ("T6", "T7", "T8", "T9", "T10"))
    assert legacy_last["differentials"]["V2DeltaRSS"] == memory.NOT_APPLICABLE
    assert stage1_last["phaseOrder"] == list(memory.PHASES)
    assert all(stage1_last["phases"][phase]["status"] == "CAPTURED"
               for phase in memory.PHASES)
    assert isinstance(stage1_last["differentials"]["V2DeltaRSS"], int)
    assert isinstance(stage1_last["differentials"]["interMissionDeltaRSS"], int)


def test_scanner_phase_hooks_are_in_production_order_and_disabled_is_na():
    source = inspect.getsource(scanner._osint_persist_locked)
    positions = [source.index(f'"{phase}"')
                 for phase in ("T1", "T2", "T3", "T4", "T5")]
    assert positions == sorted(positions)
    isolated = inspect.getsource(
        scanner.argus_checkpoint_v2_isolated.launch_isolated_generation)
    positions = [isolated.index(f'"{phase}"')
                 for phase in ("T6", "T7", "T8", "T9", "T10")]
    assert positions == sorted(positions)

    old_recorder = scanner._MEMORY_ATTRIBUTION
    old_enabled = scanner._CHECKPOINT_V2_STAGE1_ENABLED
    old_record = scanner._MISSION_TICK_CONTEXT.get("memoryAttributionRecordId")
    try:
        scanner._MEMORY_ATTRIBUTION = memory.MemoryAttributionRecorder(16)
        scanner._CHECKPOINT_V2_STAGE1_ENABLED = False
        scanner._MISSION_TICK_CONTEXT["memoryAttributionRecordId"] = "disabled"
        scanner._MEMORY_ATTRIBUTION.begin(
            "disabled", {"stage1EffectiveState": "disabled"},
            initial_sample=_sample(10))
        scanner._checkpoint_v2_dual_write({})
        scanner._memory_attribution_capture("T11")
        scanner._memory_attribution_capture("T12")
        record = scanner._MEMORY_ATTRIBUTION.complete("disabled")
        assert all(record["phases"][phase]["status"] == memory.NOT_APPLICABLE
                   for phase in ("T6", "T7", "T8", "T9", "T10"))
    finally:
        scanner._MEMORY_ATTRIBUTION = old_recorder
        scanner._CHECKPOINT_V2_STAGE1_ENABLED = old_enabled
        scanner._MISSION_TICK_CONTEXT["memoryAttributionRecordId"] = old_record


def test_scanner_source_hooks_match_actual_construction_order():
    source = inspect.getsource(scanner._osint_persist_locked)
    coarse = ("S0", "S1", "S2", "S3", "S4", "S5", "S6",
              "S7V0", "S7V1", "S7V7", "S7A0", "S7A1", "S7A7",
              "S7", "S8")
    positions = [source.index(f'"{phase}"') for phase in coarse]
    assert positions == sorted(positions)
    for operation in (
            "wal_cursor_read", "reference_sections_assembled",
            "control_states_normalized", "market_ledger_normalize_hash",
            "chart_state_normalize_hash", "decision_states_normalize_hash",
            "public_stores_normalize_hash", "persistent_source_ready"):
        assert operation in source
    assert "hash_with_transient_normalize" in source
    observer = inspect.getsource(scanner._memory_state_hash_observer)
    for event in (
            "hash_enter", "internal_normalize_complete", "stable_tree_ready",
            "hash_projection_ready", "canonical_string_ready",
            "utf8_bytes_ready", "hash_complete"):
        assert event in observer


def test_scanner_mission_path_hooks_cover_the_previous_s0_s1_interval():
    mission = inspect.getsource(scanner._api_argus_admin_missions_tick_impl)
    positions = [mission.index(f'"M{index}"') for index in range(1, 18)]
    assert positions == sorted(positions)
    adapter = inspect.getsource(scanner._persist_with_remote_receipt_drain)
    assert [adapter.index(f'"M{index}"') for index in range(18, 21)] == \
        sorted(adapter.index(f'"M{index}"') for index in range(18, 21))
    persist = inspect.getsource(scanner._osint_persist)
    locked = inspect.getsource(scanner._osint_persist_locked)
    assert '"M21"' in persist
    assert locked.index('"M22"') < locked.index('"S0"') < \
        locked.index("read_valid_wal") < locked.index('"S1"') < \
        locked.index('"M23"')
    for phase, slot in (("M6", "jp_primary"), ("M7", "jp_secondary"),
                        ("M8", "us_primary"), ("M9", "us_secondary")):
        assert f'("{phase}", "{slot}"' in mission
    view_capture = mission[
        mission.index("_memory_attribution_path_capture(\n"
                      "                _view_phase"):
        mission.index("_view_phase_index = len(_view_phase_specs)")]
    assert "_view_slot" in view_capture
    assert "_market_symbol" not in view_capture


def test_http_attribution_uses_route_template_and_never_symbol_value():
    middleware = inspect.getsource(scanner._memory_attribution_request_begin)
    assert "request.url_rule.rule" in middleware
    assert 'name=f"{request.method} {rule}"' in middleware
    assert "request.path" not in middleware
    normalized = memory.normalize_operation_name(
        "HTTP", "GET /api/chart/<symbol>?symbol=SPY")
    assert normalized == "HTTP:GET /api/chart/<id>"
    assert "SPY" not in normalized


def test_scalar_logical_counts_and_s7_observer_never_summarize_receipts(
        monkeypatch):
    calls = {"summary": 0}

    def forbidden_summary(*args, **kwargs):
        calls["summary"] += 1
        raise AssertionError("diagnostic scalar path must not deep-copy receipts")

    old_recorder = scanner._MEMORY_ATTRIBUTION
    old_record_id = scanner._MISSION_TICK_CONTEXT.get(
        "memoryAttributionRecordId")
    try:
        monkeypatch.setattr(
            scanner.argus_remote_receipt_queue, "summary", forbidden_summary)
        monkeypatch.setattr(
            scanner, "_REMOTE_RECEIPT_QUEUE", {"receipts": [{}, {}, {}]})
        scanner._MEMORY_ATTRIBUTION = memory.MemoryAttributionRecorder(4)
        scanner._MEMORY_ATTRIBUTION.begin(
            "scalar-only", {"missionWindowId": "mw-scalar"},
            initial_sample=_rich_sample(1000, 800, 300, 500))
        scanner._MISSION_TICK_CONTEXT[
            "memoryAttributionRecordId"] = "scalar-only"
        logical = scanner._memory_attribution_logical_counts()
        scanner._memory_state_hash_observer("asset")(
            "hash_enter", {"entryCount": 3})
        record = scanner._MEMORY_ATTRIBUTION.complete("scalar-only")
        assert logical["remoteJournalQueueCount"] == 3
        assert record["sourceConstruction"]["phaseOrder"] == ["S7A2"]
        assert calls["summary"] == 0
    finally:
        scanner._MEMORY_ATTRIBUTION = old_recorder
        scanner._MISSION_TICK_CONTEXT[
            "memoryAttributionRecordId"] = old_record_id


def test_admin_memory_attribution_endpoint_is_private_and_ready_is_aggregate_only(
        monkeypatch):
    old_recorder = scanner._MEMORY_ATTRIBUTION
    old_operations = scanner._MEMORY_OPERATIONS
    old_gate = dict(scanner._AI_GATE_STATE)
    try:
        scanner._MEMORY_ATTRIBUTION = memory.MemoryAttributionRecorder(16)
        scanner._MEMORY_OPERATIONS = memory.OperationAttributionRecorder(
            32, threshold_bytes=0)
        monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-admin")
        with scanner.app.test_client() as client:
            denied = client.get("/api/argus/admin/memory-attribution")
            allowed = client.get(
                "/api/argus/admin/memory-attribution",
                headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"})
            ready = client.get("/readyz")
        assert denied.status_code == 401
        assert allowed.status_code == 200
        assert allowed.get_json()["schemaVersion"] == memory.SCHEMA_VERSION
        assert allowed.get_json()["operationAttribution"]["historyLimit"] == 32
        assert allowed.get_json()["operationAttribution"]["schemaVersion"] == \
            memory.OPERATION_SCHEMA_VERSION
        assert allowed.get_json()["operationAttribution"]["heavyHitterLimit"] \
            == 16
        encoded = json.dumps(allowed.get_json(), sort_keys=True)
        assert "X-ARGUS-ADMIN-TOKEN" not in encoded
        assert "test-admin" not in encoded
        assert "memoryAttribution" not in (ready.get_json() or {})
    finally:
        scanner._MEMORY_ATTRIBUTION = old_recorder
        scanner._MEMORY_OPERATIONS = old_operations
        scanner._AI_GATE_STATE.clear()
        scanner._AI_GATE_STATE.update(old_gate)


def test_diagnostic_does_not_enter_checkpoint_or_wal_contracts():
    persist_source = pathlib.Path("scanner.py").read_text(encoding="utf-8")
    checkpoint_literal = persist_source[
        persist_source.index("        blob = {"):
        persist_source.index("job_id = str(_MISSION_TICK_CONTEXT")]
    assert '"memoryAttribution"' not in checkpoint_literal
    assert '"operationAttribution"' not in checkpoint_literal
    assert "memory-attribution" not in pathlib.Path(
        "argus_tick_durability.py").read_text(encoding="utf-8")
