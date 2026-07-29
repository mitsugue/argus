import io
import json
import os
import socket
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from scripts import workflow_http as wh


class WorkflowHttpTests(unittest.TestCase):
    def test_success_and_business_error(self):
        self.assertEqual(wh.classify_response(200, json.dumps({"ok": True}))["outcome"], wh.SUCCESS)
        self.assertEqual(wh.classify_response(200, json.dumps({"error": "bad"}))["outcome"], wh.FAILURE)
        self.assertEqual(wh.classify_response(200, json.dumps({"ok": False}))["outcome"], wh.FAILURE)

    def test_http_failures_and_invalid_json(self):
        for code in (401, 403, 500):
            self.assertEqual(wh.classify_response(code, json.dumps({"error": "x"}))["outcome"], wh.FAILURE)
        self.assertEqual(wh.classify_response(200, "not-json")["reason"], "invalid_json")

    def test_expected_skip_and_degraded(self):
        r = wh.classify_response(429, json.dumps({"status": "budget_exceeded"}),
                                 expected_statuses=["budget_exceeded"])
        self.assertEqual(r["outcome"], wh.EXPECTED_SKIP)
        r = wh.classify_response(401, json.dumps({"status": "budget_exceeded"}),
                                 expected_statuses=["budget_exceeded"])
        self.assertEqual(r["outcome"], wh.FAILURE)
        r = wh.classify_response(200, json.dumps(
            {"ok": False, "reason": "private_store_not_configured"}),
            expected_values=["private_store_not_configured"])
        self.assertEqual(r["outcome"], wh.EXPECTED_SKIP)
        self.assertEqual(wh.classify_response(200, json.dumps({"status": "partial"}))["outcome"], wh.DEGRADED)
        self.assertEqual(wh.classify_response(
            200, json.dumps({"ok": True, "status": "deterministic_mode",
                             "reason": "deterministic_mode"}))["outcome"],
            wh.EXPECTED_SKIP)

    def test_timeout_is_failure_and_secret_not_logged(self):
        with mock.patch.object(wh, "request_json", side_effect=socket.timeout()), \
                mock.patch.dict(os.environ, {"TEST_ADMIN_TOKEN": "do-not-print-me"}):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = wh.main(["--name", "timeout", "--url", "https://example.invalid",
                              "--header-env", "X-ARGUS-ADMIN-TOKEN=TEST_ADMIN_TOKEN"])
        self.assertEqual(rc, 1)
        self.assertNotIn("do-not-print-me", out.getvalue() + err.getvalue())

    def test_http_error_body_is_classified(self):
        with mock.patch.object(wh, "request_json",
                               return_value=(401, json.dumps({"error": "unauthorized"}))):
            self.assertEqual(wh.main(["--name", "denied", "--url",
                                      "https://example.invalid"]), 1)

    def test_transient_timeout_retries_then_succeeds(self):
        with mock.patch.object(
                wh, "request_json",
                side_effect=[
                    socket.timeout(),
                    (200, json.dumps({"ok": True, "updated": 0})),
                ]) as request_mock, mock.patch.object(wh.time, "sleep") as sleep:
            rc = wh.main([
                "--name", "retry", "--url", "https://example.invalid",
                "--attempts", "3", "--retry-delay", "0",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(request_mock.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_persistent_business_failure_is_not_retried(self):
        with mock.patch.object(
                wh, "request_json",
                return_value=(200, json.dumps({"ok": False, "error": "bad"}))
                ) as request_mock:
            rc = wh.main([
                "--name", "business", "--url", "https://example.invalid",
                "--attempts", "3", "--retry-delay", "0",
            ])
        self.assertEqual(rc, 1)
        self.assertEqual(request_mock.call_count, 1)

    def test_response_secrets_and_arbitrary_body_are_not_logged(self):
        body = {"ok": True, "token": "secret-value", "prompt": "private-body"}
        with mock.patch.object(wh, "request_json",
                               return_value=(200, json.dumps(body))):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(wh.main(["--name", "safe", "--url",
                                          "https://example.invalid"]), 0)
        self.assertNotIn("secret-value", out.getvalue() + err.getvalue())
        self.assertNotIn("private-body", out.getvalue() + err.getvalue())

    def test_identity_contract_preserves_safe_build_and_ready_fields(self):
        body = {
            "status": "ok",
            "buildSha": "6a4ac01",
            "ready": True,
            "token": "must-not-leak",
            "privateState": {"owner": "must-not-leak"},
        }
        with mock.patch.object(wh, "request_json",
                               return_value=(200, json.dumps(body))):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(wh.main(["--name", "identity", "--url",
                                          "https://example.invalid"]), 0)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["buildSha"], "6a4ac01")
        self.assertIs(summary["ready"], True)
        self.assertNotIn("token", summary)
        self.assertNotIn("privateState", summary)
        self.assertNotIn("must-not-leak", out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
