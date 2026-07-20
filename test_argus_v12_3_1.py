"""ARGUS v12.3.1 — scheduled mission / Build Soak reliability guards."""
import os
import pathlib
import json
import sys
import types
import unittest
from unittest import mock

import argus_decision_ledger as dl
import argus_runtime as runtime
import argus_scheduler as scheduler

# moomoo importはユーザーHOMEへログを書くため、このunit processだけ外部adapterをstub。
_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *a, **k: None
_moomoo.OpenSecTradeContext = lambda *a, **k: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


ROOT = pathlib.Path(__file__).parent


class MissionWindowTests(unittest.TestCase):
    def test_version_12_3_1_is_consistent(self):
        package = json.loads((ROOT / "web/package.json").read_text())
        lock = json.loads((ROOT / "web/package-lock.json").read_text())
        guide = (ROOT / "web/src/routes/Guide.tsx").read_text()
        self.assertEqual(package["version"], "12.3.1")
        self.assertEqual(lock["version"], package["version"])
        self.assertEqual(lock["packages"][""]["version"], package["version"])
        self.assertIn("['v12.3.1'", guide)

    def test_30_minute_window_boundaries_and_timezone_independence(self):
        before = scheduler.mission_window(observed_at="2026-07-20T00:06:59Z")
        at = scheduler.mission_window(observed_at="2026-07-20T00:07:00Z")
        jst = scheduler.mission_window(observed_at="2026-07-20T09:07:00+09:00")
        self.assertEqual(before["scheduledFor"], "2026-07-19T23:37:00Z")
        self.assertEqual(at["scheduledFor"], "2026-07-20T00:07:00Z")
        self.assertEqual(at["missionWindowId"], jst["missionWindowId"])

    def test_delay_classes_are_distinct(self):
        cases = [(300, "on_time"), (301, "delayed"),
                 (1801, "severely_delayed"), (5401, "missed")]
        for seconds, expected in cases:
            self.assertEqual(scheduler.scheduler_delay_class(seconds), expected)

    def test_schedule_manual_source_and_explicit_delayed_window(self):
        scheduled = scheduler.mission_window(
            observed_at="2026-07-20T01:10:00Z", trigger_source="schedule",
            scheduled_for="2026-07-20T00:07:00Z")
        manual = scheduler.mission_window(
            observed_at="2026-07-20T01:10:00Z", trigger_source="manual",
            scheduled_for="2026-07-20T00:07:00Z")
        self.assertEqual(scheduled["delayClassification"], "severely_delayed")
        self.assertEqual(manual["triggerSource"], "manual")
        self.assertEqual(scheduled["missionWindowId"], manual["missionWindowId"])

    def test_missing_windows_raise_effective_delay_from_run_history(self):
        prior = [{"missionWindowId": "mw-2026-07-20T00:07:00Z",
                  "scheduledFor": "2026-07-20T00:07:00Z",
                  "triggerSource": "schedule", "status": "completed"}]
        current = scheduler.mission_window(
            observed_at="2026-07-20T01:26:00Z", trigger_source="schedule")
        effective = scheduler.apply_window_history(current, prior)
        self.assertEqual(effective["scheduledFor"], "2026-07-20T01:07:00Z")
        self.assertEqual(effective["missedWindowCount"], 1)
        self.assertEqual(effective["delaySeconds"], 49 * 60)
        self.assertEqual(effective["delayClassification"], "severely_delayed")

    def test_duplicate_suppressed_and_failed_window_retryable(self):
        rows = []
        win = scheduler.mission_window(observed_at="2026-07-20T00:08:00Z")
        rec, run = scheduler.begin_mission_window(
            rows, window=win, build_sha="abc1234",
            started_at="2026-07-20T00:08:00Z")
        self.assertTrue(run)
        scheduler.finish_mission_window(
            rec, completed_at="2026-07-20T00:08:05Z", status="completed")
        same, run2 = scheduler.begin_mission_window(
            rows, window=win, build_sha="abc1234",
            started_at="2026-07-20T00:09:00Z")
        self.assertFalse(run2)
        self.assertEqual(same["duplicateSuppressed"], 1)
        self.assertEqual(len(rows), 1)
        same["status"] = "failed"
        _, retry = scheduler.begin_mission_window(
            rows, window=win, build_sha="abc1234",
            started_at="2026-07-20T00:20:00Z")
        self.assertTrue(retry)
        self.assertEqual(rows[0]["retryCount"], 1)

    def test_catch_up_is_bounded_and_does_not_relabel_old_windows(self):
        windows = scheduler.bounded_catchup_windows(
            last_scheduled_for="2026-07-20T00:07:00Z",
            current_scheduled_for="2026-07-20T03:07:00Z")
        self.assertEqual(len(windows), scheduler.MISSION_CATCHUP_LIMIT)
        self.assertEqual(windows[0], "mw-2026-07-20T00:37:00Z")

    def test_workflow_schedule_concurrency_and_dispatch_contract(self):
        src = (ROOT / ".github/workflows/caos-scan.yml").read_text()
        self.assertIn("cron: '7,37 * * * *'", src)
        self.assertIn("workflow_dispatch", src)
        self.assertIn("group: caos-scan-scheduled-missions", src)
        self.assertIn("cancel-in-progress: false", src)
        self.assertIn("timeout-minutes: 10", src)
        self.assertIn('"triggerSource":os.environ["TRIGGER_SOURCE"]', src)
        self.assertNotIn('curl -s --max-time 60 "$BE/healthz" > /dev/null || true', src)


class SoakHeartbeatTests(unittest.TestCase):
    def _heartbeat(self, **overrides):
        args = dict(
            soak_id="soak-abc", build_sha="abc1234", runtime_version="12.3.1",
            expected_at="2026-07-20T00:07:00Z",
            observed_at="2026-07-20T00:08:00Z", source="github_actions_schedule",
            health_status="ok", ready_status="ready", restore_outcome="restored",
            durable_integrity="ok", journal_status="verified",
            read_back_verified=True, scheduler_delay_seconds=60,
            evidence_type="scheduled_mission", now_iso="2026-07-20T00:08:00Z")
        args.update(overrides)
        return runtime.soak_heartbeat(**args)

    def _state(self, heartbeat, now="2026-07-20T01:00:00Z", started=None,
               required_hours=72):
        soak = {"soakId": "soak-abc", "buildSha": "abc1234",
                "startedAt": started or "2026-07-20T00:08:00Z",
                "heartbeats": []}
        self.assertTrue(runtime.append_soak_heartbeat(soak, heartbeat))
        return runtime.build_soak_state(
            soak=soak, now_iso=now, current_build_sha="abc1234",
            required_hours=required_hours)

    def test_first_heartbeat_running_and_duplicate_rejected(self):
        hb = self._heartbeat()
        soak = {"soakId": "soak-abc", "buildSha": "abc1234",
                "startedAt": hb["observedAt"], "heartbeats": []}
        self.assertTrue(runtime.append_soak_heartbeat(soak, hb))
        self.assertFalse(runtime.append_soak_heartbeat(soak, hb))
        state = runtime.build_soak_state(
            soak=soak, now_iso="2026-07-20T00:09:00Z",
            current_build_sha="abc1234")
        self.assertEqual(state["state"], "running")
        self.assertEqual(state["heartbeatCount"], 1)

    def test_scheduler_delay_is_not_interruption_with_alternative_evidence(self):
        state = self._state(self._heartbeat(scheduler_delay_seconds=1200))
        self.assertEqual(state["state"], "scheduler_delayed")

    def test_verification_gap_and_critical_failures(self):
        self.assertEqual(self._state(self._heartbeat(
            read_back_verified=False))["state"], "verification_gap")
        self.assertEqual(self._state(self._heartbeat(
            health_status="failed"))["state"], "interrupted")
        self.assertEqual(self._state(self._heartbeat(
            durable_integrity="corrupt_ignored"))["state"], "interrupted")
        self.assertEqual(self._state(self._heartbeat(
            journal_status="hash_mismatch"))["state"], "interrupted")
        self.assertEqual(self._state(self._heartbeat(), now="2026-07-20T04:00:00Z")
                         ["state"], "interrupted")

    def test_build_mismatch_completed_and_retrospective_label(self):
        mismatch = self._heartbeat(build_sha="other")
        soak = {"soakId": "soak-abc", "buildSha": "other",
                "startedAt": "2026-07-20T00:08:00Z", "heartbeats": []}
        self.assertTrue(runtime.append_soak_heartbeat(soak, mismatch))
        state = runtime.build_soak_state(
            soak=soak, now_iso="2026-07-20T00:09:00Z",
            current_build_sha="abc1234")
        self.assertEqual(state["state"], "interrupted")
        completed = self._state(
            self._heartbeat(expected_at="2026-07-20T01:07:00Z",
                            observed_at="2026-07-20T01:08:00Z",
                            now_iso="2026-07-20T01:08:00Z"),
            now="2026-07-20T01:09:00Z",
            started="2026-07-20T00:08:00Z", required_hours=1)
        self.assertEqual(completed["state"], "completed")
        retro = self._heartbeat(retrospective=True)
        self.assertTrue(retro["retrospectiveEvidence"])

    def test_future_heartbeat_is_rejected(self):
        self.assertIsNone(self._heartbeat(
            observed_at="2026-07-20T00:09:00Z",
            now_iso="2026-07-20T00:08:00Z"))
        self.assertIsNone(self._heartbeat(
            expected_at="2026-07-20T00:09:00Z"))

    def test_new_build_does_not_inherit_old_soak(self):
        decision = runtime.soak_restore_decision(
            persisted={"soakId": "old", "buildSha": "oldsha",
                       "startedAt": "2026-07-19T00:00:00Z"},
            current_build_sha="newsha", boot_iso="2026-07-20T00:00:00Z")
        self.assertEqual(decision["action"], "new_soak")

    def test_past_unverified_interruption_cannot_be_rewritten(self):
        hb = self._heartbeat()
        soak = {"soakId": "soak-abc", "buildSha": "abc1234",
                "startedAt": hb["observedAt"], "heartbeats": [hb],
                "interruptions": [{"verified": False, "gapMinutes": 79.8}]}
        state = runtime.build_soak_state(
            soak=soak, now_iso="2026-07-20T00:09:00Z",
            current_build_sha="abc1234")
        self.assertEqual(state["state"], "interrupted")


class OutcomeAndJournalIntegrationTests(unittest.TestCase):
    def test_outcome_retry_stable_id_and_missing_never_zero(self):
        fc = {"id": "fc-one", "symbol": "TEST", "issuedAt": "2026-07-18T00:00:00Z",
              "forecastHorizon": "next_session", "origin": "forward_live"}
        first = dl.outcome_record(
            forecast=fc, outcome_as_of="2026-07-19T00:00:00Z",
            start_price=None, end_price=None, now_iso="2026-07-19T00:00:00Z")
        first = dl.schedule_outcome_retry(
            first, now_iso="2026-07-19T00:00:00Z", retry_interval_seconds=1800)
        pending = dl.retry_outcome_record(
            existing=first, forecast=fc, outcome_as_of="2026-07-19T00:31:00Z",
            start_price=None, end_price=None, now_iso="2026-07-19T00:31:00Z",
            retry_interval_seconds=1800)
        resolved = dl.retry_outcome_record(
            existing=pending, forecast=fc, outcome_as_of="2026-07-19T01:02:00Z",
            start_price=100, end_price=101, now_iso="2026-07-19T01:02:00Z",
            retry_interval_seconds=1800)
        self.assertEqual(first["id"], pending["id"])
        self.assertEqual(pending["id"], resolved["id"])
        self.assertEqual(pending["resolutionState"], "retry_pending")
        self.assertEqual(resolved["status"], "resolved")
        self.assertNotEqual(pending.get("absoluteReturnPct"), 0)
        self.assertEqual(len({first["id"], pending["id"], resolved["id"]}), 1)

    def test_commit_receipt_is_pending_until_verified_readback(self):
        old_token = scanner._ARGUS_ADMIN_TOKEN
        old_cycle = dict(scanner._REMOTE_CYCLE)
        try:
            scanner._ARGUS_ADMIN_TOKEN = "test-admin"
            client = scanner.app.test_client()
            response = client.post(
                "/api/argus/admin/remote-journal/commit-receipt",
                headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"},
                json={"remoteCommitSha": "a" * 40, "expectedHash": "b" * 16})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "pending")
            self.assertFalse(response.get_json()["readBackVerified"])
            self.assertEqual(scanner._REMOTE_CYCLE["expectedHash"], "b" * 16)
        finally:
            scanner._ARGUS_ADMIN_TOKEN = old_token
            scanner._REMOTE_CYCLE.clear(); scanner._REMOTE_CYCLE.update(old_cycle)

    def test_tick_window_prevents_duplicate_outcome_retry_and_ai_calls(self):
        old_token = scanner._ARGUS_ADMIN_TOKEN
        old_startup = dict(scanner._STARTUP)
        old_disabled = scanner._REMOTE_ACK.get("disabled")
        saved = {"missions": list(scanner._MISSIONS),
                 "windows": list(scanner._MISSION_WINDOWS),
                 "forecasts": list(scanner._FORECAST_LEDGER),
                 "outcomes": list(scanner._OUTCOME_LEDGER),
                 "soak": dict(scanner._SOAK),
                 "journal": list(scanner._OPS_JOURNAL),
                 "opsSeq": dict(scanner._OPS_SEQ),
                 "journalMeta": dict(scanner._OPS_JOURNAL_META),
                 "remoteCycle": dict(scanner._REMOTE_CYCLE),
                 "incidents": list(scanner._INCIDENTS),
                 "agentQueue": dict(scanner._OSINT_AGENT_QUEUE),
                 "durable": dict(scanner._DURABLE_STATE)}
        old_sha = os.environ.get("RENDER_GIT_COMMIT")
        try:
            scanner._ARGUS_ADMIN_TOKEN = "test-admin"
            scanner._STARTUP.update({"state": "ready", "restoreOutcome": "test_mode",
                                     "restoreCompletedAt": scanner._ai_now_iso()})
            scanner._REMOTE_ACK["disabled"] = True
            scanner._MISSIONS.clear(); scanner._MISSION_WINDOWS.clear()
            scanner._FORECAST_LEDGER.clear(); scanner._OUTCOME_LEDGER.clear()
            scanner._SOAK.update({"soakId": None, "buildSha": None,
                                  "startedAt": None, "heartbeats": [],
                                  "interruptions": [], "previousSoak": None})
            os.environ["RENDER_GIT_COMMIT"] = "abc1234" + "0" * 33
            fc = {"id": "fc-route", "symbol": "TEST",
                  "issuedAt": "2026-01-01T00:00:00Z",
                  "forecastHorizon": "next_session", "origin": "forward_live"}
            scanner._FORECAST_LEDGER.append(fc)
            client = scanner.app.test_client()
            headers = {"X-ARGUS-ADMIN-TOKEN": "test-admin"}
            payload = {"triggerSource": "schedule",
                       "expectedBuildSha": os.environ["RENDER_GIT_COMMIT"]}
            with mock.patch.object(scanner, "_price_history_cached", return_value=[
                    {"date": "2026-01-01", "close": 100},
                    {"date": "2026-01-02", "close": 101}], create=True), \
                    mock.patch.object(scanner, "_execute_ai_judgment") as ai:
                first = client.post("/api/argus/admin/missions/tick",
                                    headers=headers, json=payload)
                second = client.post("/api/argus/admin/missions/tick",
                                     headers=headers, json=payload)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.get_json()["status"], "completed")
            self.assertEqual(second.get_json()["status"], "expected_skip")
            self.assertEqual(len(scanner._OUTCOME_LEDGER), 1)
            self.assertEqual(scanner._OUTCOME_LEDGER[0]["status"], "resolved")
            ai.assert_not_called()
        finally:
            scanner._ARGUS_ADMIN_TOKEN = old_token
            scanner._STARTUP.clear(); scanner._STARTUP.update(old_startup)
            if old_disabled is None:
                scanner._REMOTE_ACK.pop("disabled", None)
            else:
                scanner._REMOTE_ACK["disabled"] = old_disabled
            scanner._MISSIONS[:] = saved["missions"]
            scanner._MISSION_WINDOWS[:] = saved["windows"]
            scanner._FORECAST_LEDGER[:] = saved["forecasts"]
            scanner._OUTCOME_LEDGER[:] = saved["outcomes"]
            scanner._SOAK.clear(); scanner._SOAK.update(saved["soak"])
            scanner._OPS_JOURNAL[:] = saved["journal"]
            scanner._OPS_SEQ.clear(); scanner._OPS_SEQ.update(saved["opsSeq"])
            scanner._OPS_JOURNAL_META.clear(); scanner._OPS_JOURNAL_META.update(saved["journalMeta"])
            scanner._REMOTE_CYCLE.clear(); scanner._REMOTE_CYCLE.update(saved["remoteCycle"])
            scanner._INCIDENTS[:] = saved["incidents"]
            scanner._OSINT_AGENT_QUEUE.clear(); scanner._OSINT_AGENT_QUEUE.update(saved["agentQueue"])
            scanner._DURABLE_STATE.clear(); scanner._DURABLE_STATE.update(saved["durable"])
            if old_sha is None:
                os.environ.pop("RENDER_GIT_COMMIT", None)
            else:
                os.environ["RENDER_GIT_COMMIT"] = old_sha


if __name__ == "__main__":
    unittest.main()
