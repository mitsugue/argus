"""Scanner wiring guards: instrumentation is additive and non-authoritative."""

import copy
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
                scanner._RECOVERY_MEASUREMENTS, "summary",
                return_value={"status": "SHADOW", "coverage": "INCOMPLETE",
                              "hardRpoClaimPermitted": False}):
        document = scanner._data_quality_console()
    assert document["recoveryMeasurement"]["coverage"] == "INCOMPLETE"
    assert document["authoritativeStateRegistry"]["shadowOnly"] is True
    exact = document["exactColdRecovery"]
    assert exact["status"] == "not_proven"
    assert exact["legacyRemoteHealthIsExactColdRecoveryProof"] is False
    assert exact["hardRpoClaimPermitted"] is False
