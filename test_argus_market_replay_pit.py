import copy
import hashlib
import json
import unittest
from datetime import date, timedelta
from unittest import mock

import argus_market_replay as replay


def bars(count=100):
    start = date(2026, 1, 1)
    result = []
    for index in range(count):
        day = start + timedelta(days=index)
        close = 100 + index * 0.1
        result.append({
            "date": day.isoformat(), "open": close - 0.2,
            "high": close + 1, "low": close - 1, "close": close,
            "volume": 1000 + index, "availableFrom": day.isoformat(),
            "source": "jquants", "sourceId": f"fixture:{day.isoformat()}",
            "datasetId": "fixture-daily-v1", "revision": 0,
        })
    return result


CUTOFF = "2026-03-22T23:59:59.999999Z"


class ReplayPointInTimeTests(unittest.TestCase):
    def test_hostile_future_bar_and_future_revision_never_enter_dataset(self):
        source = bars()
        baseline = replay.build_context(
            source, symbol="1321", market="JP", horizon=5, now_iso=CUTOFF)
        hostile = copy.deepcopy(source)
        future_revision = copy.deepcopy(hostile[50])
        future_revision.update({
            "open": 9998, "high": 10001, "low": 9997, "close": 9999,
            "revision": 1, "knownAt": "2026-03-23T00:00:00Z",
        })
        hostile.append(future_revision)
        result = replay.build_context(
            hostile, symbol="1321", market="JP", horizon=5, now_iso=CUTOFF)
        self.assertEqual(baseline["datasetHash"], result["datasetHash"])
        self.assertEqual(baseline["historyCoverage"], result["historyCoverage"])
        proof = result["computation"]["noFutureLeakageProof"]["filterProof"]
        self.assertGreater(proof["excludedFutureCount"], 0)
        self.assertFalse(proof["futureRowsAdmitted"])
        self.assertTrue(result["computation"]["noFutureLeakage"])
        self.assertTrue(result["eventStudy"]["noFutureLeakage"])

    def test_highest_visible_revision_is_selected_and_bound_to_dataset(self):
        source = bars(70)
        original = replay.build_context(
            source, symbol="1321", market="JP", horizon=5, now_iso=CUTOFF)
        revised = copy.deepcopy(source)
        correction = copy.deepcopy(revised[50])
        correction.update({
            "close": correction["close"] + 2,
            "high": correction["high"] + 2,
            "revision": 2,
            "knownAt": "2026-03-01T10:00:00Z",
            "sourceId": "fixture:revision:2",
        })
        revised.append(correction)
        result = replay.build_context(
            revised, symbol="1321", market="JP", horizon=5, now_iso=CUTOFF)
        proof = result["computation"]["noFutureLeakageProof"]
        self.assertNotEqual(original["datasetHash"], result["datasetHash"])
        self.assertEqual(result["datasetHash"], proof["normalizedDatasetHash"])
        self.assertEqual("highest_visible_revision_per_period",
                         proof["revisionSelection"])
        self.assertEqual(1, proof["filterProof"]["supersededRevisionCount"])
        self.assertEqual(result["historyCoverage"]["count"],
                         proof["normalizedRowCount"])

    def test_dataset_hash_binds_revision_knowledge_time_and_dataset_identity(self):
        base = bars(2)
        changed_revision = copy.deepcopy(base)
        changed_revision[-1]["revision"] = 1
        changed_known = copy.deepcopy(base)
        changed_known[-1]["knownAt"] = "2026-01-02T23:59:59Z"
        changed_dataset = copy.deepcopy(base)
        changed_dataset[-1]["datasetId"] = "fixture-daily-v2"
        self.assertNotEqual(replay.dataset_hash(base),
                            replay.dataset_hash(changed_revision))
        self.assertNotEqual(replay.dataset_hash(base),
                            replay.dataset_hash(changed_known))
        self.assertNotEqual(replay.dataset_hash(base),
                            replay.dataset_hash(changed_dataset))
        context_rows = bars(70)
        context = replay.build_context(
            context_rows, symbol="1321", market="JP", horizon=5,
            now_iso=CUTOFF)
        self.assertEqual(replay.dataset_hash(context_rows),
                         context["datasetHash"])

    def test_no_future_leakage_flag_requires_successful_proof_verification(self):
        with mock.patch(
                "argus_market_replay.argus_market_data_truth.verify_point_in_time_proof",
                return_value=(False, "hostile_test_failure")):
            result = replay.build_context(
                bars(70), symbol="1321", market="JP", horizon=5, now_iso=CUTOFF)
        self.assertFalse(result["computation"]["noFutureLeakage"])
        self.assertFalse(result["eventStudy"]["noFutureLeakage"])
        self.assertFalse(result["calibrationCurve"]["noFutureLeakage"])
        self.assertFalse(result["computation"]["noFutureLeakageProof"]["verified"])

    def test_current_latest_ledger_scalar_is_never_backdated(self):
        ledger = {"table": [{
            "seriesId": "fixture.latest.only", "latestValue": 999,
            "history": [],
        }]}
        result = replay.build_context(
            bars(70), symbol="1321", market="JP", horizon=5,
            ledger=ledger, now_iso=CUTOFF)
        self.assertEqual([], result["extremes"]["series"])
        self.assertFalse(result["extremes"]["latestValueFallbackUsed"])
        self.assertTrue(result["extremes"]["publicationTimeIntegrity"])

    def test_conflicting_same_revision_fails_closed(self):
        source = bars(70)
        conflict = copy.deepcopy(source[20])
        conflict["close"] += 1
        conflict["high"] += 1
        source.append(conflict)
        with self.assertRaisesRegex(ValueError, "conflicting_row_revision"):
            replay.build_context(
                source, symbol="1321", market="JP", horizon=5, now_iso=CUTOFF)

    def test_unbound_or_future_auxiliary_inputs_are_excluded(self):
        chart = {
            "indicators": {"bars": [{"close": 100}]},
            "zones": [{"id": "future-zone", "center": 110, "upper": 111,
                       "lower": 109, "status": "active"}],
            "eventMarkers": [{"id": "future-result", "labelJa": "future"}],
        }
        calibration = {"horizons": {"5": {"modelBrier": 0.01}}}
        unbound = replay.build_context(
            bars(70), symbol="1321", market="JP", horizon=5,
            chart_report=chart, calibration=calibration, now_iso=CUTOFF)
        self.assertEqual([], unbound["changeConditions"])
        self.assertIsNone(unbound["probabilityQuality"]["modelBrier"])
        proofs = unbound["computation"]["noFutureLeakageProof"][
            "auxiliaryInputs"]
        self.assertEqual(["EXCLUDED_UNBOUND", "EXCLUDED_UNBOUND"],
                         [row["status"] for row in proofs])
        self.assertTrue(unbound["computation"]["noFutureLeakage"])

        future = "2026-03-23T00:00:00Z"
        future_result = replay.build_context(
            bars(70), symbol="1321", market="JP", horizon=5,
            chart_report=replay.seal_auxiliary_input(
                chart, kind="chart_report", known_at=future),
            calibration=replay.seal_auxiliary_input(
                calibration, kind="calibration", known_at=future),
            now_iso=CUTOFF)
        future_proofs = future_result["computation"][
            "noFutureLeakageProof"]["auxiliaryInputs"]
        self.assertEqual(["EXCLUDED_FUTURE", "EXCLUDED_FUTURE"],
                         [row["status"] for row in future_proofs])
        self.assertEqual([], future_result["changeConditions"])
        self.assertIsNone(future_result["probabilityQuality"]["modelBrier"])

    def test_sealed_auxiliary_inputs_are_admitted_only_at_their_cutoff(self):
        chart = {
            "indicators": {"bars": [{"close": 100}]},
            "zones": [{"id": "known-zone", "center": 110, "upper": 111,
                       "lower": 109, "status": "active"}],
            "eventMarkers": [],
        }
        calibration = {
            "historyStart": "2026-01-01", "historyEnd": "2026-03-20",
            "horizons": {"5": {"modelBrier": 0.22,
                                  "calibrationDatasetHash": "fixture"}},
        }
        bound_chart = replay.seal_auxiliary_input(
            chart, kind="chart_report", known_at=CUTOFF)
        bound_calibration = replay.seal_auxiliary_input(
            calibration, kind="calibration", known_at=CUTOFF)
        result = replay.build_context(
            bars(70), symbol="1321", market="JP", horizon=5,
            chart_report=bound_chart, calibration=bound_calibration,
            now_iso=CUTOFF)
        self.assertEqual("upside_close_break",
                         result["changeConditions"][0]["triggerType"])
        self.assertEqual(0.22, result["probabilityQuality"]["modelBrier"])
        self.assertEqual(["ADMITTED", "ADMITTED"], [
            row["status"] for row in result["computation"]
            ["noFutureLeakageProof"]["auxiliaryInputs"]])
        self.assertTrue(result["computation"]["noFutureLeakage"])

        tampered = copy.deepcopy(bound_chart)
        tampered["zones"][0]["upper"] = 999
        rejected = replay.build_context(
            bars(70), symbol="1321", market="JP", horizon=5,
            chart_report=tampered, now_iso=CUTOFF)
        self.assertEqual([], rejected["changeConditions"])
        self.assertEqual("EXCLUDED_INTEGRITY_FAILURE",
                         rejected["computation"]["noFutureLeakageProof"]
                         ["auxiliaryInputs"][0]["status"])

    def test_nested_future_chart_bar_cannot_be_sealed_or_forged_into_replay(self):
        future_chart = {
            "indicators": {"bars": [{
                "date": "2026-03-23", "open": 100, "high": 120,
                "low": 99, "close": 119,
            }]},
            "zones": [{"id": "future-zone", "center": 110,
                       "upper": 111, "lower": 109, "status": "active"}],
            "eventMarkers": [],
        }
        with self.assertRaisesRegex(
                ValueError, "auxiliary_nested_time_invalid"):
            replay.seal_auxiliary_input(
                future_chart, kind="chart_report", known_at=CUTOFF)

        valid_chart = copy.deepcopy(future_chart)
        valid_chart["indicators"]["bars"][0]["date"] = "2026-03-22"
        forged = replay.seal_auxiliary_input(
            valid_chart, kind="chart_report", known_at=CUTOFF)
        forged["indicators"]["bars"][0]["date"] = "2026-03-23"
        body = copy.deepcopy(forged)
        receipt = body.pop("_pointInTimeReceipt")
        receipt["contentHash"] = hashlib.sha256(json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest()
        forged["_pointInTimeReceipt"] = receipt

        result = replay.build_context(
            bars(70), symbol="1321", market="JP", horizon=5,
            chart_report=forged, now_iso=CUTOFF)
        proof = result["computation"]["noFutureLeakageProof"]
        self.assertEqual("EXCLUDED_TEMPORAL_FAILURE",
                         proof["auxiliaryInputs"][0]["status"])
        self.assertIn("indicators.bars.0.date",
                      proof["auxiliaryInputs"][0]["temporalProof"]
                      ["futureTimestampPaths"])
        self.assertEqual([], result["changeConditions"])
        self.assertTrue(proof["auxiliaryTemporalIntegrity"])
        self.assertTrue(result["computation"]["noFutureLeakage"])

    def test_nested_future_after_legacy_64_path_boundary_is_rejected(self):
        chart = {
            "indicators": {"bars": [
                {"date": "2026-03-20", "open": 100, "high": 101,
                 "low": 99, "close": 100}
                for _ in range(70)
            ] + [{"date": "2026-03-23", "open": 100, "high": 101,
                  "low": 99, "close": 100}]},
            "zones": [], "eventMarkers": [],
        }
        with self.assertRaisesRegex(
                ValueError, "auxiliary_nested_time_invalid"):
            replay.seal_auxiliary_input(
                chart, kind="chart_report", known_at=CUTOFF)

    def test_auxiliary_temporal_path_overflow_fails_closed(self):
        chart = {
            "indicators": {"bars": [
                {"date": "2026-03-20", "open": 100, "high": 101,
                 "low": 99, "close": 100}
                for _ in range(
                    replay.MAX_AUXILIARY_TEMPORAL_PATHS + 1)
            ]},
            "zones": [], "eventMarkers": [],
        }
        proof = replay._auxiliary_temporal_proof(
            chart, kind="chart_report",
            cutoff=replay._auxiliary_time(CUTOFF))
        self.assertTrue(proof["temporalPathOverflow"])
        self.assertFalse(proof["verified"])
        with self.assertRaisesRegex(
                ValueError, "auxiliary_nested_time_invalid"):
            replay.seal_auxiliary_input(
                chart, kind="chart_report", known_at=CUTOFF)

    def test_real_260_bar_auxiliary_timestamp_shape_remains_admissible(self):
        chart = {
            "indicators": {"bars": [
                {"date": "2026-03-20", "availableFrom": "2026-03-20",
                 "knownAt": "2026-03-20T23:00:00Z",
                 "observedAt": "2026-03-20T20:00:00Z",
                 "open": 100, "high": 101, "low": 99, "close": 100}
                for _ in range(260)
            ]},
            "zones": [], "eventMarkers": [],
        }
        sealed = replay.seal_auxiliary_input(
            chart, kind="chart_report", known_at=CUTOFF)
        self.assertEqual(
            replay.AUXILIARY_INPUT_SCHEMA,
            sealed["_pointInTimeReceipt"]["schemaVersion"])


if __name__ == "__main__":
    unittest.main()
