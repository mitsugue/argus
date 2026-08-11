import json
import sys
import types
from pathlib import Path

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = type("OpenQuoteContext", (), {})
_moomoo.OpenSecTradeContext = type("OpenSecTradeContext", (), {})
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)

import argus_portfolio_sync
import argus_remote_journal
import scanner
from scripts import memory_snapshot_resource_probe as resource_probe


NOW = "2026-08-11T21:30:00Z"
COMPACT_KEYS = {
    "receiptSchemaVersion", "schemaVersion", "generatedAt", "asOf",
    "buildIdentity", "opsJournal", "integrityManifest", "outcomes",
    "missionTickDurability", "marketLedgerStateHash",
    "chartIntelligenceStateHash", "todayIntelligenceStateHash",
    "marketReplayStateHash", "receiptHash",
}


def _restored(monkeypatch):
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW)


def test_direct_compact_endpoint_is_exact_full_projection(monkeypatch):
    _restored(monkeypatch)
    with scanner.app.test_client() as client:
        full_response = client.get("/api/argus/osint/memory-snapshot")
        compact_response = client.get("/api/argus/osint/remote-readback")

    assert full_response.status_code == 200
    assert compact_response.status_code == 200
    full = full_response.get_json()
    compact = compact_response.get_json()
    expected = argus_remote_journal.compact_readback_snapshot(full)
    assert compact == expected
    assert set(compact) == COMPACT_KEYS
    assert argus_remote_journal.verify_compact_readback_snapshot(compact)
    assert len(compact_response.data) < len(full_response.data)


def test_compact_endpoint_never_materializes_full_only_stores(monkeypatch):
    _restored(monkeypatch)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("full_only_materialization")

    monkeypatch.setattr(
        scanner.argus_verified_snapshot, "normalize_store", forbidden)
    monkeypatch.setattr(
        scanner.argus_asset_chart_cache, "normalize_store", forbidden)
    monkeypatch.setattr(
        scanner.argus_research_benchmark, "normalize_state", forbidden)
    monkeypatch.setattr(
        scanner.argus_research_benchmark_v2, "normalize_state", forbidden)
    monkeypatch.setattr(
        scanner.argus_foundation_jobs, "normalize_state", forbidden)

    with scanner.app.test_client() as client:
        response = client.get("/api/argus/osint/remote-readback")
    assert response.status_code == 200
    compact = response.get_json()
    assert set(compact) == COMPACT_KEYS
    assert argus_remote_journal.verify_compact_readback_snapshot(compact)


def test_compact_endpoint_preserves_public_privacy_contract(monkeypatch):
    _restored(monkeypatch)
    with scanner.app.test_client() as client:
        compact = client.get("/api/argus/osint/remote-readback").get_json()
    assert not argus_portfolio_sync.contains_sensitive(compact)
    body = json.dumps(compact, ensure_ascii=False)
    for forbidden in (
            "passphrase", "credential", "apiKey", "quantity", "avgCost",
            "acquisitionPrice", "OPENAI_API_KEY", "ARGUS_ADMIN_TOKEN"):
        assert forbidden not in body


def test_watchtower_is_compact_first_and_full_only_on_publish():
    text = Path(".github/workflows/caos-watchtower.yml").read_text(
        encoding="utf-8")
    fetch_step = text.split("- name: Fetch public-safe status snapshot", 1)[1]
    fetch_step = fetch_step.split("- name: Checkout (main)", 1)[0]
    assert "/api/argus/osint/remote-readback" in fetch_step
    assert "/api/argus/osint/memory-snapshot" not in fetch_step
    assert fetch_step.index("data-quality-before.json") < \
        fetch_step.index("/api/argus/osint/remote-readback") < \
        fetch_step.index("data-quality.json", fetch_step.index(
            "/api/argus/osint/remote-readback"))

    commit_step = text.split(
        "- name: Commit snapshot and enqueue bounded Remote Journal receipt",
        1,
    )[1]
    decision = commit_step.index("DECISION_ACTION=")
    publish = commit_step.index(
        'if [ "$DECISION_ACTION" = "publish" ]; then')
    full_fetch = commit_step.index("/api/argus/osint/memory-snapshot")
    rebuild = commit_step.index("osint-publish-readback.json")
    prepare = commit_step.index("prepare \\")
    assert decision < publish < full_fetch < rebuild < prepare
    assert '--source-readback "$RUNNER_TEMP/osint-source-readback.json"' \
        in commit_step[:publish]
    assert '--source-readback "$RUNNER_TEMP/osint-publish-readback.json"' \
        in commit_step[publish:]
    assert "compact_process_boot_changed" in commit_step
    assert "publish_process_boot_changed" in commit_step
    assert "publish_identity_changed" in commit_step
    assert "watchtower-remote-journal-accept-receipt" in commit_step


def test_caos_scan_full_boot_restore_publisher_is_unchanged():
    text = Path(".github/workflows/caos-scan.yml").read_text(
        encoding="utf-8")
    assert "/api/argus/osint/memory-snapshot" in text
    assert "prepare_remote_journal_publish.py" in text
    assert "ledger/osint/memory.json" in text


def test_resource_probe_uses_one_fixture_construction_per_worker():
    source = Path("scripts/memory_snapshot_resource_probe.py").read_text(
        encoding="utf-8")
    assert source.count(
        "fixture._verified_store(verified_bars_per_record)") == 1
    assert source.count(
        "fixture._asset_store(asset_bars_per_record)") == 1
    assert "two-fresh-long-lived-workers-one-mode-each" in source
    assert '"--worker-mode", mode' in source
    assert "cycles == MINIMUM_CYCLES" in source


def test_resource_comparison_requires_material_rss_arena_and_time_reduction():
    compact = {
        "processPeakRssBytes": 200 * resource_probe.MIB,
        "bodyLiveMaximums": {"arenaBytes": 180 * resource_probe.MIB},
        "durationMs": {"p50": 10.0},
        "responseBytes": {"maximum": 4_096},
    }
    full = {
        "processPeakRssBytes": 220 * resource_probe.MIB,
        "bodyLiveMaximums": {"arenaBytes": 210 * resource_probe.MIB},
        "durationMs": {"p50": 25.0},
        "responseBytes": {"minimum": 130 * resource_probe.MIB},
    }
    comparison = resource_probe._comparison_metrics(compact, full)
    assert comparison["processPeakRssReductionBytes"] == 20 * \
        resource_probe.MIB
    assert comparison["arenaMaximumReductionBytes"] == 30 * \
        resource_probe.MIB
    assert comparison["durationP50ReductionMs"] == 15.0
    assert comparison["responseByteReductionBytes"] == \
        130 * resource_probe.MIB - 4_096
    assert comparison["minimumProductionFullResponseBytes"] == \
        120 * resource_probe.MIB
    assert comparison["maximumProductionFullResponseBytes"] == \
        140 * resource_probe.MIB


def test_resource_comparison_fails_closed_for_missing_linux_metrics():
    compact = {
        "processPeakRssBytes": resource_probe.memory.UNKNOWN,
        "bodyLiveMaximums": {"arenaBytes": resource_probe.memory.UNKNOWN},
        "durationMs": {"p50": 10.0},
        "responseBytes": {"maximum": 4_096},
    }
    full = {
        "processPeakRssBytes": 220 * resource_probe.MIB,
        "bodyLiveMaximums": {"arenaBytes": 210 * resource_probe.MIB},
        "durationMs": {"p50": 25.0},
        "responseBytes": {"minimum": 130 * resource_probe.MIB},
    }
    comparison = resource_probe._comparison_metrics(compact, full)
    assert comparison["processPeakRssReductionBytes"] == \
        resource_probe.memory.UNKNOWN
    assert comparison["arenaMaximumReductionBytes"] == \
        resource_probe.memory.UNKNOWN

    sample = {key: 1 for key in resource_probe.METRIC_KEYS}
    sample.update({"processPeakRssBytes": 1, "cgroupMaxBytes": 1})
    incomplete = dict(sample)
    incomplete["pssBytes"] = resource_probe.memory.UNKNOWN
    rows = [{
        "before": sample,
        "bodyLive": incomplete,
        "afterRelease": sample,
    }]
    assert resource_probe._telemetry_complete(rows, sample, sample) is False


def test_resource_probe_source_has_no_memory_control_or_payload_artifact():
    source = Path("scripts/memory_snapshot_resource_probe.py").read_text(
        encoding="utf-8")
    for forbidden in (
            "gc" + ".collect(", "malloc" + "_trim(", "os." + "exec",
            "os." + "kill"):
        assert forbidden not in source
    assert 'row.pop("body")' in source
    assert "json.loads(body)" not in source
    assert "server_jsonify_observer" in source
    encoded_size_source = source.split("def _encoded_size", 1)[1].split(
        "def _proof_prefix", 1)[0]
    assert "JSONEncoder" in encoded_size_source
    assert ".iterencode(value)" in encoded_size_source
    assert "json.dumps" not in encoded_size_source
    assert '"receiptHashes": receipt_hashes' in source
    assert '"responseBytes": len(body)' in source


def test_production_section_cardinality_contract_is_fixed():
    assert resource_probe.SECTION_TARGET_COUNTS == {
        "marketLedger": {
            "observations": 45_148, "derivedMetrics": 815,
            "turningPoints": 4_622, "backtests": 34, "imports": 219,
            "rolledBackImports": 0,
        },
        "chartIntelligence": {
            "snapshots": 295, "zones": 1_916,
            "turningPoints": 12_021, "reactionAnomalies": 0,
            "relationshipBreaks": 1, "invalidations": 1_183,
        },
        "todayIntelligence": {
            "snapshots": 332, "shortSellingHistory": 1_234,
            "failedRallyOutcomes": 652,
        },
        "marketReplay": {"contexts": 24, "contextHistory": 369},
    }
    assert resource_probe.DEFAULT_VERIFIED_BARS_PER_RECORD == 9_140
    assert resource_probe.DEFAULT_ASSET_BARS_PER_RECORD == 5_024


def test_proof_padding_is_exact_unique_and_bounded():
    container = {"rows": [{"id": index} for index in range(8)]}
    target = resource_probe._encoded_size(container) + 8 * 256
    resource_probe._pad_rows_to_exact_size(
        container, container["rows"], target, "unit")
    fillers = [row["resourceProofFiller"] for row in container["rows"]]
    assert resource_probe._encoded_size(container) == target
    assert len(set(fillers)) == len(fillers)
    assert all(len(value.encode("utf-8")) <=
               resource_probe.MAX_FILLER_BYTES_PER_ROW for value in fillers)


def test_synthetic_journal_and_outcomes_are_exact_and_verified():
    journal = resource_probe._journal_fixture()
    outcomes = resource_probe._outcome_fixture()
    section = argus_remote_journal.snapshot_journal_section(
        events=journal, meta={"totalObserved": len(journal)},
        compacted=[], now_iso=resource_probe.FIXED_NOW)
    assert len(journal) == resource_probe.EXPECTED_JOURNAL_COUNT
    assert len(outcomes) == resource_probe.EXPECTED_OUTCOME_COUNT
    assert resource_probe._encoded_size(journal) == \
        resource_probe.SECTION_TARGET_BYTES["opsJournal"]
    assert resource_probe._encoded_size(outcomes) == \
        resource_probe.SECTION_TARGET_BYTES["outcomes"]
    assert section["integrityManifest"]["eventCount"] == \
        resource_probe.EXPECTED_JOURNAL_COUNT
    assert section["integrityManifest"]["rejectedCount"] == 0
    assert len(section["integrityManifest"][
        "highestSequenceByAggregate"]) == \
        resource_probe.EXPECTED_JOURNAL_AGGREGATE_COUNT
    assert all(row["privacyClassification"] == "public_safe"
               for row in journal + outcomes)


def test_fixture_section_gate_accepts_only_expected_scalars():
    sections = {
        key: {
            "encodedBytes": target,
            "counts": dict(resource_probe.SECTION_TARGET_COUNTS.get(
                key, {})),
        }
        for key, target in resource_probe.SECTION_TARGET_BYTES.items()
    }
    sections["opsJournal"]["counts"] = {
        "events": resource_probe.EXPECTED_JOURNAL_COUNT}
    sections["integrityManifest"] = {
        "encodedBytes": 62_000,
        "counts": {
            "eventIds": resource_probe.EXPECTED_JOURNAL_COUNT,
            "idempotencyKeys": resource_probe.EXPECTED_JOURNAL_COUNT,
            "highestSequenceByAggregate":
                resource_probe.EXPECTED_JOURNAL_AGGREGATE_COUNT,
        },
    }
    sections["outcomes"]["counts"] = {
        "outcomes": resource_probe.EXPECTED_OUTCOME_COUNT}
    assert resource_probe._fixture_sections_verified({
        "sections": sections}) is True
    sections["marketLedger"]["counts"]["observations"] -= 1
    assert resource_probe._fixture_sections_verified({
        "sections": sections}) is False
