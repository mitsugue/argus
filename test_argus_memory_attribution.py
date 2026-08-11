import inspect
import json
import pathlib
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
    for index, phase in enumerate(memory.SOURCE_PHASES[1:], 1):
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
    assert source["phases"]["S8"]["metadata"]["topLevelKeys"] == 8


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
    positions = [source.index(f'"{phase}"') for phase in memory.SOURCE_PHASES[1:]]
    assert positions == sorted(positions)
    for operation in (
            "wal_cursor_read", "reference_sections_assembled",
            "control_states_normalized", "market_ledger_normalize_hash",
            "chart_state_normalize_hash", "decision_states_normalize_hash",
            "public_stores_normalize_hash", "persistent_source_ready"):
        assert operation in source
    assert "hash_with_transient_normalize" in source


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
