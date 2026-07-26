"""Mission tick batching/durability regression tests (no provider/API calls)."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import argus_scheduler
import argus_tick_durability as durability
from scripts import workflow_http


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


class WalCheckpointTests(unittest.TestCase):
    def test_one_hundred_transitions_are_small_wal_appends(self):
        with tempfile.TemporaryDirectory() as directory:
            wal = os.path.join(directory, "mission.wal")
            for sequence in range(1, 101):
                durability.append_wal(
                    wal, sequence=sequence, kind="mission_transition",
                    payload={"transitionState": {
                        "mission": {"missionId": f"m-{sequence}",
                                    "status": "completed"}}},
                    job_id="job-100")
            state = durability.read_valid_wal(wal)
            self.assertEqual(len(state["records"]), 100)
            self.assertEqual(state["maximumSequence"], 100)
            self.assertLess(state["bytes"], 100_000)

    def test_checkpoint_is_one_verified_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            wal = os.path.join(directory, "mission.wal")
            snapshot = os.path.join(directory, "state.json")
            durability.append_wal(
                wal, sequence=1, kind="mission_transition",
                payload={"transitionState": {"mission": {
                    "missionId": "m-1", "status": "completed"}}},
                job_id="job-1")
            result = durability.verified_checkpoint(
                snapshot, {"schemaVersion": "argus-durable-v3", "value": 1},
                job_id="job-1", wal_path=wal, included_sequence=1)
            self.assertTrue(result["verified"])
            self.assertEqual(json.loads(pathlib.Path(snapshot).read_text())["value"], 1)
            state = durability.read_valid_wal(wal)
            self.assertEqual([row["kind"] for row in state["records"]],
                             ["checkpoint_verified"])
            self.assertEqual(result["walCompaction"]["compactedThrough"], 1)

    def test_wal_is_not_compacted_when_checkpoint_readback_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            wal = os.path.join(directory, "mission.wal")
            snapshot = os.path.join(directory, "state.json")
            pathlib.Path(snapshot).write_text('{"verified":"old"}')
            durability.append_wal(
                wal, sequence=1, kind="journal_transition",
                payload={"journalEvent": {"idempotencyKey": "one"}},
                job_id="job-1")
            original = pathlib.Path(wal).read_bytes()
            with mock.patch.object(durability.json, "loads",
                                   side_effect=json.JSONDecodeError(
                                       "bad", "x", 0)):
                with self.assertRaises(json.JSONDecodeError):
                    durability.verified_checkpoint(
                        snapshot, {"verified": "new"}, job_id="job-1",
                        wal_path=wal, included_sequence=1)
            self.assertEqual(pathlib.Path(snapshot).read_text(),
                             '{"verified":"old"}')
            self.assertEqual(pathlib.Path(wal).read_bytes(), original)

    def test_corrupt_wal_tail_is_ignored_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            wal = os.path.join(directory, "mission.wal")
            durability.append_wal(
                wal, sequence=1, kind="mission_transition",
                payload={"transitionState": {}}, job_id="job")
            with open(wal, "ab") as handle:
                handle.write(b"{malformed\n")
            state = durability.read_valid_wal(wal)
            self.assertEqual(len(state["records"]), 1)
            self.assertEqual(state["corruptCount"], 1)

    def test_snapshot_plus_wal_replays_committed_transition(self):
        saved_missions = list(scanner._MISSIONS)
        saved_batch = dict(scanner._MISSION_BATCH_STATE)
        try:
            scanner._MISSIONS[:] = []
            scanner._MISSION_BATCH_STATE.update({"cursor": 0,
                                                 "walAppliedSequence": 0})
            record = {
                "sequence": 1,
                "kind": "mission_transition",
                "payload": {"transitionState": {
                    "mission": {"missionId": "m-replay",
                                "status": "completed"},
                    "batch": {"cursor": 1, "walAppliedSequence": 1}}},
            }
            scanner._apply_mission_wal_record(record)
            self.assertEqual(scanner._MISSIONS[0]["missionId"], "m-replay")
            self.assertEqual(scanner._MISSION_BATCH_STATE["cursor"], 1)
            scanner._apply_mission_wal_record(record)
            self.assertEqual(len(scanner._MISSIONS), 1)
        finally:
            scanner._MISSIONS[:] = saved_missions
            scanner._MISSION_BATCH_STATE.clear()
            scanner._MISSION_BATCH_STATE.update(saved_batch)

    def test_scanner_journal_does_not_full_serialize_per_event(self):
        saved_context = dict(scanner._MISSION_TICK_CONTEXT)
        saved_wal = scanner._MISSION_WAL_FILE
        saved_journal = list(scanner._OPS_JOURNAL)
        saved_meta = dict(scanner._OPS_JOURNAL_META)
        saved_seq = dict(scanner._OPS_SEQ)
        with tempfile.TemporaryDirectory() as directory:
            try:
                scanner._MISSION_WAL_FILE = os.path.join(directory, "tick.wal")
                scanner._MISSION_TICK_CONTEXT.update({
                    "active": True, "jobId": "job-100", "lease": None,
                    "walSequence": 0, "walEventCount": 0, "walAppendMs": 0,
                    "ownerThread": threading.get_ident()})
                scanner._OPS_JOURNAL[:] = []
                scanner._OPS_JOURNAL_META["totalObserved"] = 0
                scanner._OPS_SEQ.clear()
                with mock.patch.object(scanner, "_osint_persist") as persist:
                    for number in range(100):
                        scanner._journal(
                            "incident_opened", "incident", f"inc-{number}",
                            {"component": "test"})
                persist.assert_not_called()
                state = durability.read_valid_wal(scanner._MISSION_WAL_FILE)
                self.assertEqual(len(state["records"]), 100)
                self.assertEqual(scanner._MISSION_TICK_CONTEXT[
                    "walEventCount"], 100)
            finally:
                scanner._MISSION_WAL_FILE = saved_wal
                scanner._MISSION_TICK_CONTEXT.clear()
                scanner._MISSION_TICK_CONTEXT.update(saved_context)
                scanner._OPS_JOURNAL[:] = saved_journal
                scanner._OPS_JOURNAL_META.clear()
                scanner._OPS_JOURNAL_META.update(saved_meta)
                scanner._OPS_SEQ.clear()
                scanner._OPS_SEQ.update(saved_seq)

    def test_active_tick_fails_closed_when_wal_append_fails(self):
        saved_context = dict(scanner._MISSION_TICK_CONTEXT)
        saved_journal = list(scanner._OPS_JOURNAL)
        saved_seq = dict(scanner._OPS_SEQ)
        saved_meta = dict(scanner._OPS_JOURNAL_META)
        try:
            scanner._MISSION_TICK_CONTEXT.update({
                "active": True, "ownerThread": threading.get_ident(),
                "jobId": "fail-closed", "lease": None, "walSequence": 0})
            with mock.patch.object(
                    scanner.argus_tick_durability, "append_wal",
                    side_effect=OSError("disk_full")):
                with self.assertRaises(OSError):
                    scanner._journal(
                        "incident_opened", "incident", "inc-disk",
                        {"component": "test"})
        finally:
            scanner._MISSION_TICK_CONTEXT.clear()
            scanner._MISSION_TICK_CONTEXT.update(saved_context)
            scanner._OPS_JOURNAL[:] = saved_journal
            scanner._OPS_SEQ.clear()
            scanner._OPS_SEQ.update(saved_seq)
            scanner._OPS_JOURNAL_META.clear()
            scanner._OPS_JOURNAL_META.update(saved_meta)


class SingleFlightTests(unittest.TestCase):
    def test_five_contenders_allow_exactly_one_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "lease")
            barrier = threading.Barrier(5)
            release = threading.Event()
            results = []

            def contender(number: int) -> None:
                lease = durability.TickLease(
                    path, build_sha="abc", owner=f"worker-{number}")
                barrier.wait()
                acquired = lease.acquire()
                results.append(acquired)
                if acquired:
                    release.wait(1)
                    lease.release()

            threads = [threading.Thread(target=contender, args=(number,))
                       for number in range(5)]
            for thread in threads:
                thread.start()
            while len(results) < 5:
                threading.Event().wait(0.01)
            release.set()
            for thread in threads:
                thread.join()
            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), 4)

    def test_active_lease_cannot_be_stolen_and_metadata_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "lease")
            first = durability.TickLease(
                path, build_sha="abc1234", owner="ec2_systemd")
            second = durability.TickLease(
                path, build_sha="abc1234", owner="github_schedule")
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            self.assertEqual(second.metadata["jobId"], first.job_id)
            for key in ("acquiredAt", "expiresAt", "heartbeatAt", "buildSha"):
                self.assertIn(key, second.metadata)
            first.release()

    def test_released_or_expired_metadata_does_not_deadlock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "lease")
            pathlib.Path(path).write_text(json.dumps({
                "jobId": "crashed", "expiresAt": "2000-01-01T00:00:00Z"}))
            recovered = durability.TickLease(
                path, build_sha="new", owner="recovery")
            self.assertTrue(recovered.acquire())
            recovered.release()
            restarted = durability.TickLease(
                path, build_sha="new", owner="restart")
            self.assertTrue(restarted.acquire())
            restarted.release()


class BatchingAndActionsTests(unittest.TestCase):
    def test_pure_event_and_time_guards(self):
        self.assertFalse(argus_scheduler.batch_limit_reached(
            processed=2, max_events=3, elapsed_seconds=4, max_seconds=5))
        self.assertTrue(argus_scheduler.batch_limit_reached(
            processed=3, max_events=3, elapsed_seconds=1, max_seconds=5))
        self.assertTrue(argus_scheduler.batch_limit_reached(
            processed=1, max_events=3, elapsed_seconds=5, max_seconds=5))

    def test_partial_is_degraded_busy_is_expected_and_error_is_failure(self):
        partial = workflow_http.classify_response(
            200, json.dumps({"ok": True, "status": "degraded",
                             "result": "partial", "hasMore": True}))
        busy = workflow_http.classify_response(
            200, json.dumps({"ok": True, "status": "expected_skip",
                             "result": "busy"}))
        failure = workflow_http.classify_response(
            500, json.dumps({"ok": False, "status": "failed"}))
        self.assertEqual(partial["outcome"], workflow_http.DEGRADED)
        self.assertEqual(busy["outcome"], workflow_http.EXPECTED_SKIP)
        self.assertEqual(failure["outcome"], workflow_http.FAILURE)

    def test_workflow_and_ec2_callers_are_bounded_and_non_parallel(self):
        workflow = pathlib.Path(
            ".github/workflows/caos-scan.yml").read_text()
        invoker = pathlib.Path("scripts/argus_mission_tick.py").read_text()
        self.assertIn("for BATCH in 1 2 3", workflow)
        self.assertIn('LAST_RESULT" = "partial"', workflow)
        self.assertIn("ARGUS_TICK_MAX_BATCHES", invoker)
        self.assertNotIn("ThreadPoolExecutor", workflow + invoker)

    def test_official_event_tracking_persists_once_after_its_loop(self):
        source = pathlib.Path("scanner.py").read_text()
        block = source.split("def _official_events_track():", 1)[1].split(
            "@app.route(\"/api/argus/official-events\")", 1)[0]
        self.assertEqual(block.count("_official_events_persist()"), 1)
        self.assertNotIn("_osint_persist()", block)

    def test_endpoint_resumes_without_duplicate_or_skipped_missions(self):
        saved = {
            "missions": list(scanner._MISSIONS),
            "windows": list(scanner._MISSION_WINDOWS),
            "forecasts": list(scanner._FORECAST_LEDGER),
            "outcomes": list(scanner._OUTCOME_LEDGER),
            "batch": dict(scanner._MISSION_BATCH_STATE),
            "token": scanner._ARGUS_ADMIN_TOKEN,
            "wal": scanner._MISSION_WAL_FILE,
            "lease": scanner._MISSION_LEASE_FILE,
            "persistState": dict(scanner._OSINT_PERSIST_STATE),
            "startup": dict(scanner._STARTUP),
        }
        with tempfile.TemporaryDirectory() as directory:
            try:
                scanner._MISSIONS[:] = []
                scanner._MISSION_WINDOWS[:] = []
                scanner._FORECAST_LEDGER[:] = []
                scanner._OUTCOME_LEDGER[:] = []
                scanner._MISSION_BATCH_STATE.update({
                    "cursor": 0, "remainingCount": 0,
                    "walAppliedSequence": 0})
                scanner._OSINT_PERSIST_STATE["restored"] = True
                scanner._STARTUP.update({"state": "ready",
                                         "restoreOutcome": "test_mode"})
                scanner._ARGUS_ADMIN_TOKEN = "test-admin"
                scanner._MISSION_WAL_FILE = os.path.join(directory, "wal")
                scanner._MISSION_LEASE_FILE = os.path.join(directory, "lease")
                now = scanner._ai_now_iso()
                for number in range(7):
                    mission = argus_scheduler.mission(
                        mission_type="daily_learning", market="ALL",
                        session_date=now[:10], scheduled_for=now,
                        symbol=f"T{number}")
                    assert mission is not None
                    scanner._MISSIONS.append(mission)
                checkpoint = {
                    "verified": True, "snapshotBytes": 1234,
                    "serializationMs": 2, "includedWalSequence": 1,
                    "walCompaction": {"bytes": 120, "receiptSequence": 2},
                }
                calendar = {
                    "JP": {"isTradingDay": True},
                    "US": {"isTradingDay": True},
                }
                report = {"reportId": "r", "status": "ok"}
                publication = {"status": "verified"}
                client = scanner.app.test_client()
                headers = {"X-ARGUS-ADMIN-TOKEN": "test-admin"}
                payload = {"triggerSource": "manual", "runId": "bounded-test"}
                common = (
                    mock.patch.dict(os.environ, {
                        "ARGUS_MISSION_BATCH_MAX_EVENTS": "3",
                        "ARGUS_OUTCOME_BATCH_MAX_EVENTS": "3"}, clear=False),
                    mock.patch.object(
                        scanner.argus_scheduler, "generate_daily_missions",
                        return_value=[]),
                    mock.patch.object(
                        scanner.argus_scheduler, "generate_periodic_missions",
                        return_value=[]),
                    mock.patch.object(
                        scanner.argus_scheduler, "detect_missed",
                        return_value=[]),
                    mock.patch.object(
                        scanner, "_market_calendar_states",
                        return_value=calendar),
                    mock.patch.object(
                        scanner, "_market_ledger_tick",
                        return_value={"changed": False}),
                    mock.patch.object(
                        scanner, "_precompute_verified_market_view",
                        return_value=(report, publication)),
                    mock.patch.object(scanner, "_osint_persist",
                                      return_value=checkpoint),
                )
                with common[0], common[1], common[2], common[3], common[4], \
                        common[5], common[6], common[7]:
                    responses = [
                        client.post("/api/argus/admin/missions/tick",
                                    headers=headers, json=payload)
                        for _ in range(3)]
                bodies = [response.get_json() for response in responses]
                self.assertEqual([body["processedMissionCount"]
                                  for body in bodies], [3, 3, 1])
                self.assertEqual([body["result"] for body in bodies],
                                 ["partial", "partial", "caught_up"])
                self.assertEqual(bodies[-1]["cursorAfter"], 7, bodies)
                self.assertEqual(len({
                    mission["missionId"] for mission in scanner._MISSIONS
                    if mission["status"] == "complete"}), 7)
            finally:
                scanner._MISSIONS[:] = saved["missions"]
                scanner._MISSION_WINDOWS[:] = saved["windows"]
                scanner._FORECAST_LEDGER[:] = saved["forecasts"]
                scanner._OUTCOME_LEDGER[:] = saved["outcomes"]
                scanner._MISSION_BATCH_STATE.clear()
                scanner._MISSION_BATCH_STATE.update(saved["batch"])
                scanner._ARGUS_ADMIN_TOKEN = saved["token"]
                scanner._MISSION_WAL_FILE = saved["wal"]
                scanner._MISSION_LEASE_FILE = saved["lease"]
                scanner._OSINT_PERSIST_STATE.clear()
                scanner._OSINT_PERSIST_STATE.update(saved["persistState"])
                scanner._STARTUP.clear()
                scanner._STARTUP.update(saved["startup"])


class RegressionContractTests(unittest.TestCase):
    def test_schema_is_additive_and_soak_history_is_not_rewritten(self):
        source = pathlib.Path("scanner.py").read_text()
        self.assertIn('"schemaVersion": "argus-durable-v3"', source)
        self.assertIn('"missionTickDurability": dict(_MISSION_BATCH_STATE)',
                      source)
        self.assertIn("interruptions = list(_SOAK.get", source)

    def test_public_get_and_ai_contract_remain_unchanged(self):
        workflow = pathlib.Path(
            ".github/workflows/caos-scan.yml").read_text()
        self.assertIn('"automaticAiExecutions"', pathlib.Path(
            "scanner.py").read_text())
        self.assertNotIn("/api/argus/admin/missions/tick\", methods=[\"GET\"]",
                         pathlib.Path("scanner.py").read_text())
        self.assertNotIn("ThreadPoolExecutor", workflow)

    def test_remote_pending_diagnostics_do_not_clear_stale_receipt(self):
        saved_journal = list(scanner._OPS_JOURNAL)
        saved_ack = dict(scanner._REMOTE_ACK)
        saved_cycle = dict(scanner._REMOTE_CYCLE)
        saved_meta = dict(scanner._OPS_JOURNAL_META)
        try:
            scanner._OPS_JOURNAL[:] = [{
                "idempotencyKey": "pending-1",
                "occurredAt": "2026-07-25T00:00:00Z"}]
            scanner._REMOTE_ACK["ackedKeys"] = []
            scanner._REMOTE_CYCLE.update({
                "readBackVerified": False,
                "errorClass": "commit_receipt_stale",
                "acknowledgedCount": 7})
            scanner._OPS_JOURNAL_META["totalObserved"] = 8
            value = scanner._remote_journal_diagnostics(
                "2026-07-25T01:00:00Z")
            self.assertEqual(value["pendingCount"], 1)
            self.assertEqual(value["oldestPendingAgeSeconds"], 3600)
            self.assertEqual(value["localSequencePosition"], 8)
            self.assertEqual(value["remoteSequencePosition"], 7)
            self.assertFalse(value["readBackVerified"])
            self.assertEqual(scanner._REMOTE_CYCLE["errorClass"],
                             "commit_receipt_stale")
        finally:
            scanner._OPS_JOURNAL[:] = saved_journal
            scanner._REMOTE_ACK.clear()
            scanner._REMOTE_ACK.update(saved_ack)
            scanner._REMOTE_CYCLE.clear()
            scanner._REMOTE_CYCLE.update(saved_cycle)
            scanner._OPS_JOURNAL_META.clear()
            scanner._OPS_JOURNAL_META.update(saved_meta)


if __name__ == "__main__":
    unittest.main()
