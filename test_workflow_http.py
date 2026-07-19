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


if __name__ == "__main__":
    unittest.main()
