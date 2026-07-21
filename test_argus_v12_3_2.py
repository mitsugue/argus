"""ARGUS v12.3.2 — EC2 primary scheduler and source-independent Soak."""
import importlib.util
import io
import json
import os
import pathlib
import unittest
from unittest import mock

import argus_runtime as runtime
import argus_scheduler as scheduler


ROOT = pathlib.Path(__file__).parent


class SchedulerAuthorityTests(unittest.TestCase):
    def test_source_priority_and_legacy_normalization(self):
        self.assertEqual(scheduler.normalize_trigger_source("schedule"),
                         "github_schedule")
        self.assertEqual(scheduler.scheduler_source_priority("ec2_systemd"), 1)
        self.assertEqual(scheduler.scheduler_source_priority("github_schedule"), 2)
        self.assertEqual(scheduler.scheduler_source_priority("manual"), 3)
        self.assertIsNone(scheduler.normalize_trigger_source("unknown"))

    def test_first_valid_lease_wins_across_sources(self):
        rows = []
        ec2 = scheduler.mission_window(
            observed_at="2026-07-20T00:07:02Z",
            trigger_source="ec2_systemd",
            scheduled_for="2026-07-20T00:07:00Z")
        record, run = scheduler.begin_mission_window(
            rows, window=ec2, build_sha="abc1234",
            runtime_version="12.3.2", started_at="2026-07-20T00:07:02Z")
        self.assertTrue(run)
        self.assertEqual(record["leaseOwner"], "ec2_systemd")
        self.assertEqual(record["leaseExpiresAt"], "2026-07-20T00:17:02Z")
        scheduler.finish_mission_window(
            record, completed_at="2026-07-20T00:07:05Z", status="completed")
        github = scheduler.mission_window(
            observed_at="2026-07-20T00:08:00Z",
            trigger_source="github_schedule",
            scheduled_for="2026-07-20T00:07:00Z")
        duplicate, run_again = scheduler.begin_mission_window(
            rows, window=github, build_sha="abc1234",
            runtime_version="12.3.2", started_at="2026-07-20T00:08:00Z")
        self.assertFalse(run_again)
        self.assertEqual(len(rows), 1)
        self.assertEqual(duplicate["leaseOwner"], "ec2_systemd")
        self.assertEqual(duplicate["duplicateSuppressed"], 1)
        self.assertEqual(duplicate["lastDuplicateSource"], "github_schedule")
        self.assertEqual(duplicate["finalStatus"], "completed")

    def test_window_record_contains_required_operational_fields(self):
        window = scheduler.mission_window(
            observed_at="2026-07-20T00:07:02Z",
            trigger_source="ec2_systemd")
        record, _ = scheduler.begin_mission_window(
            [], window=window, build_sha="abc1234",
            runtime_version="12.3.2", started_at="2026-07-20T00:07:02Z")
        for key in ("missionWindowId", "triggerSource", "scheduledFor",
                    "receivedAt", "delaySeconds", "leaseOwner",
                    "leaseExpiresAt", "duplicateSuppressed", "finalStatus",
                    "buildSha", "runtimeVersion"):
            self.assertIn(key, record)


class SoakSourceIndependenceTests(unittest.TestCase):
    def _heartbeat(self, *, source, expected, observed, delay=2):
        return runtime.soak_heartbeat(
            soak_id="soak-final", build_sha="abc1234",
            runtime_version="12.3.2", expected_at=expected,
            observed_at=observed, source=source, health_status="ok",
            ready_status="ready", restore_outcome="restored",
            durable_integrity="ok", journal_status="verified",
            read_back_verified=True, scheduler_delay_seconds=delay,
            evidence_type="scheduled_mission", now_iso=observed)

    def test_fresh_ec2_keeps_running_when_github_is_missing(self):
        first = self._heartbeat(
            source="ec2_systemd", expected="2026-07-20T00:07:00Z",
            observed="2026-07-20T00:07:02Z")
        second = self._heartbeat(
            source="ec2_systemd", expected="2026-07-20T00:37:00Z",
            observed="2026-07-20T00:37:02Z")
        soak = {"soakId": "soak-final", "buildSha": "abc1234",
                "startedAt": "2026-07-20T00:07:02Z", "heartbeats": []}
        self.assertTrue(runtime.append_soak_heartbeat(soak, first))
        self.assertTrue(runtime.append_soak_heartbeat(soak, second))
        state = runtime.build_soak_state(
            soak=soak, now_iso="2026-07-20T00:38:00Z",
            current_build_sha="abc1234")
        self.assertEqual(state["state"], "running")
        self.assertEqual(state["warningSource"], "github_schedule")
        self.assertEqual(state["referenceHeartbeatSource"], "ec2_systemd")
        self.assertIsNone(state["failureClass"])

    def test_failure_classes_are_explicit(self):
        good = self._heartbeat(
            source="ec2_systemd", expected="2026-07-20T00:07:00Z",
            observed="2026-07-20T00:07:02Z")
        cases = (
            ({**good, "buildSha": "other"}, "build_mismatch"),
            ({**good, "healthStatus": "failed"}, "application_failure"),
            ({**good, "durableIntegrity": "corrupt"},
             "durable_integrity_failure"),
            ({**good, "journalStatus": "hash_mismatch"}, "journal_failure"),
        )
        for heartbeat, expected in cases:
            soak = {"soakId": "soak-final",
                    "buildSha": heartbeat["buildSha"],
                    "startedAt": "2026-07-20T00:07:02Z",
                    "heartbeats": [heartbeat]}
            state = runtime.build_soak_state(
                soak=soak, now_iso="2026-07-20T00:08:00Z",
                current_build_sha="abc1234")
            self.assertEqual(state["failureClass"], expected)


class SystemdContractTests(unittest.TestCase):
    def test_timer_contract(self):
        timer = (ROOT / "ops/systemd/argus-mission-tick.timer").read_text()
        self.assertIn("OnCalendar=*-*-* *:07,37:00 UTC", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("AccuracySec=1s", timer)
        self.assertIn("RandomizedDelaySec=0", timer)

    def test_service_reuses_secret_file_without_command_line_secret(self):
        service = (ROOT / "ops/systemd/argus-mission-tick.service").read_text()
        self.assertIn("EnvironmentFile=/etc/argus-bridge.env", service)
        self.assertNotIn("ARGUS_ADMIN_TOKEN=", service)
        self.assertNotIn("--token", service)
        self.assertIn("NoNewPrivileges=true", service)
        env = (ROOT / "ops/systemd/argus-mission-tick.env.example").read_text()
        self.assertIn("ARGUS_TICK_TIMEOUT_SECONDS=180", env)

    def test_invoker_emits_stable_utc_window_and_no_secret(self):
        path = ROOT / "scripts/argus_mission_tick.py"
        spec = importlib.util.spec_from_file_location("mission_tick", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        scheduled, window_id = module._window(
            module.dt.datetime(2026, 7, 20, 0, 36, 59,
                               tzinfo=module.UTC))
        self.assertEqual(scheduled, "2026-07-20T00:07:00Z")
        self.assertEqual(window_id, "mw-2026-07-20T00:07:00Z")
        source = path.read_text()
        self.assertIn('"triggerSource": "ec2_systemd"', source)
        self.assertIn('"ARGUS_TICK_TIMEOUT_SECONDS", "180"', source)
        self.assertNotIn('print(token', source)

    def test_invoker_success_log_is_structured_and_secret_free(self):
        path = ROOT / "scripts/argus_mission_tick.py"
        spec = importlib.util.spec_from_file_location("mission_tick_run", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "status": "completed",
                    "missionWindow": {
                        "missionWindowId": "mw-2026-07-20T00:07:00Z",
                        "triggerSource": "ec2_systemd",
                        "finalStatus": "completed",
                    },
                    "outcomeRetry": {"evaluated": 1, "resolved": 0,
                                     "outcomeCount": 10},
                    "soak": {"soakId": "soak-abc", "state": "running",
                             "heartbeatCount": 2},
                    "remoteJournal": {"readBackVerified": True},
                }).encode()

        output = io.StringIO()
        env = {"ARGUS_ADMIN_TOKEN": "super-secret-test-value",
               "ARGUS_TICK_MAX_ATTEMPTS": "1"}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(module.urllib.request, "urlopen",
                                  return_value=Response()), \
                mock.patch("sys.stdout", output):
            self.assertEqual(module.main(), 0)
        record = json.loads(output.getvalue())
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["triggerSource"], "ec2_systemd")
        self.assertTrue(record["readBackVerified"])
        self.assertNotIn("super-secret-test-value", output.getvalue())

    def test_version_contract(self):
        package = json.loads((ROOT / "web/package.json").read_text())
        lock = json.loads((ROOT / "web/package-lock.json").read_text())
        self.assertGreaterEqual(tuple(int(x) for x in package["version"].split(".")),
                                (12, 3, 2))
        self.assertEqual(lock["version"], package["version"])
        self.assertEqual(lock["packages"][""]["version"], package["version"])


if __name__ == "__main__":
    unittest.main()
