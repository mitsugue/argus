"""Scanner wiring guards: instrumentation is additive and non-authoritative."""

import copy
import datetime as dt
import json
import threading
import types
from unittest import mock

import sys

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)

import scanner


def test_wal_append_contract_is_unchanged_and_measurement_is_best_effort():
    saved = copy.deepcopy(scanner._MISSION_TICK_CONTEXT)
    scanner._MISSION_TICK_CONTEXT.clear()
    scanner._MISSION_TICK_CONTEXT.update({
        "active": True, "walSequence": 10, "walEventCount": 0,
        "walAppendMs": 0, "jobId": "job", "missionWindowId": "window",
        "lease": None, "ownerThread": threading.get_ident(),
    })
    expected = {"sequence": 11, "kind": "batch_cursor", "payload": {"x": 1}}
    try:
        with mock.patch.object(
                scanner.argus_tick_durability, "append_wal",
                return_value=expected) as append, \
                mock.patch.object(
                    scanner._RECOVERY_MEASUREMENTS, "record_mutation",
                    side_effect=OSError("diagnostic failure")):
            result = scanner._append_tick_wal("batch_cursor", {"x": 1})
        append.assert_called_once()
        assert result == expected
        assert scanner._MISSION_TICK_CONTEXT["walSequence"] == 11
        assert scanner._MISSION_TICK_CONTEXT["walEventCount"] == 1
    finally:
        scanner._MISSION_TICK_CONTEXT.clear()
        scanner._MISSION_TICK_CONTEXT.update(saved)


def test_scanner_measurement_helper_swallows_all_diagnostic_failures():
    with mock.patch.object(
            scanner._RECOVERY_MEASUREMENTS, "record_mutation",
            side_effect=OSError("metrics unavailable")):
        assert scanner._record_recovery_mutation(
            "core.batch_cursor", plaintext_bytes_estimate=12) is False


def test_phase_a_does_not_enable_v2_stage1_or_change_restore_authority():
    assert scanner._CHECKPOINT_V2_STAGE1_ENABLED is False
    projection = scanner._formal_soak_public_projection()
    assert projection["checkpointMode"] == "legacy_only"
    assert scanner._CHECKPOINT_V2_STATUS["state"] == "disabled"


def test_public_diagnostic_separates_legacy_health_from_exact_recovery():
    with mock.patch.object(
            scanner.argus_remote_recovery, "configured_keys",
            return_value={"status": "not_configured"}), \
            mock.patch.object(
                scanner._RECOVERY_MEASUREMENTS, "public_summary",
                return_value={"status": "SHADOW", "coverage": "INCOMPLETE",
                              "hardRpoClaimPermitted": False}):
        document = scanner._data_quality_console()
    assert document["recoveryMeasurement"]["coverage"] == "INCOMPLETE"
    assert document["authoritativeStateRegistry"]["shadowOnly"] is True
    exact = document["exactColdRecovery"]
    assert exact["status"] == "not_proven"
    assert exact["legacyRemoteHealthIsExactColdRecoveryProof"] is False
    assert exact["hardRpoClaimPermitted"] is False


def test_actual_public_data_quality_route_redacts_all_recovery_identifiers():
    now = dt.datetime(2026, 8, 13, 12, 0, 0, tzinfo=dt.timezone.utc)
    registry = scanner.argus_recovery_registry
    store = scanner.argus_recovery_metrics.RecoveryMeasurementStore(
        None, clock=lambda: now)
    private = [
        row for row in registry.mutations()
        if not registry.mutation_allows_public_telemetry(row)]
    denied_states = [
        row for row in registry.states()
        if not registry.state_allows_public_telemetry(row)]
    denied_checkpoint_keys = sorted({
        key for row in denied_states for key in row.checkpointKeys})
    for row in private:
        store.record_mutation(
            row.mutationClass, plaintext_bytes_estimate=10,
            observed_at=now)
    section_sizes = {
        key: index + 1
        for index, key in enumerate(denied_checkpoint_keys)}
    store.record_checkpoint(
        checkpoint_bytes=sum(section_sizes.values()) + 100,
        section_sizes=section_sizes,
        source_assembly_ms=1, section_accounting_ms=2, seal_ms=3,
        atomic_write_readback_ms=4, local_wal_bytes=5,
        local_wal_record_count=6, local_wal_high_water=7,
        legacy_remote_ack_sequence=0, legacy_remote_ack_at=None,
        legacy_predictions={"configured": True, "exists": False,
                            "bytes": 0, "recordCount": 0,
                            "complete": True}, observed_at=now)

    periodic_reports = [{"report": "PRIVATE_REPORT_SENTINEL"}]
    challenger_runs = [{
        "state": "SECURITY_STATE_SENTINEL",
        "ownerDecision": "OWNER_DECISION_SENTINEL",
    }]
    postmortems = [{"body": "PRIVATE_POSTMORTEM_SENTINEL"}]
    with mock.patch.object(scanner, "_RECOVERY_MEASUREMENTS", store), \
            mock.patch.object(
                scanner, "_PERIODIC_REPORTS", periodic_reports), \
            mock.patch.object(
                scanner, "_CHALLENGER_RUNS", challenger_runs), \
            mock.patch.object(scanner, "_POSTMORTEMS", postmortems), \
            mock.patch.object(
                scanner.argus_remote_recovery, "configured_keys",
                return_value={"status": "not_configured"}), \
            scanner.app.test_request_context("/api/argus/data-quality"):
        document = scanner.api_argus_data_quality().get_json()

    encoded = json.dumps(document, sort_keys=True)
    for row in private:
        assert row.mutationClass not in encoded
        for target in row.targetStateIds:
            assert target not in encoded
    for row in denied_states:
        assert row.stateId not in encoded
    for section in denied_checkpoint_keys:
        assert f'"{section}"' not in encoded
    for sentinel in ("PRIVATE_REPORT_SENTINEL", "SECURITY_STATE_SENTINEL",
                     "OWNER_DECISION_SENTINEL",
                     "PRIVATE_POSTMORTEM_SENTINEL"):
        assert sentinel not in encoded
    agent_ops = document["agentOps"]
    for field in ("periodicReports", "challengerRuns", "postmortems",
                  "ownerDecision"):
        assert field not in agent_ops
    assert all(value is not source for value in agent_ops.values()
               for source in (periodic_reports, challenger_runs, postmortems))
    assert "validationErrors" not in document["authoritativeStateRegistry"]
    assert document["authoritativeStateRegistry"]["validationErrorCount"] == 0
    assert document["recoveryMeasurement"]["mutationDistributions"][
        "private.redacted"]["mutationCount"] == len(private)
    assert "legacyPredictionsJsonl" not in document["recoveryMeasurement"][
        "latestCheckpointMeasurement"]


def test_public_recovery_projection_failure_uses_fixed_conservative_fallback():
    with mock.patch.object(
            scanner._RECOVERY_MEASUREMENTS, "public_summary",
            side_effect=RuntimeError("OWNER_PRIVATE_SENTINEL")), \
            mock.patch.object(
                scanner.argus_recovery_registry, "registry_summary",
                side_effect=RuntimeError("TERM_OVERLAY_SENTINEL")):
        document = scanner._data_quality_console()
    encoded = json.dumps(document, sort_keys=True)
    assert "OWNER_PRIVATE_SENTINEL" not in encoded
    assert "TERM_OVERLAY_SENTINEL" not in encoded
    assert document["recoveryMeasurement"]["status"] == "SHADOW"
    assert document["recoveryMeasurement"]["coverage"] == "INCOMPLETE"
    assert document["recoveryMeasurement"]["hardRpoClaimPermitted"] is False
    assert document["authoritativeStateRegistry"][
        "validationStatus"] == "unavailable"


def test_other_public_health_routes_do_not_serialize_recovery_measurements():
    with scanner.app.test_request_context("/api/argus/data-quality/status"):
        status = scanner.api_argus_data_quality_status().get_json()
    with scanner.app.test_request_context("/healthz"):
        health = scanner.healthz().get_json()
    with scanner.app.test_request_context("/readyz"):
        ready_response = scanner.readyz()
        ready = (ready_response[0] if isinstance(ready_response, tuple)
                 else ready_response).get_json()
    for document in (status, health, ready):
        encoded = json.dumps(document, sort_keys=True)
        assert "recoveryMeasurement" not in document
        assert "ai.result_and_cost" not in encoded
        assert "termOverlay" not in encoded
