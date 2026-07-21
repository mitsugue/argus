#!/usr/bin/env python3
"""Start and poll one admin-gated foundation job without exposing secrets."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


TERMINAL = {"completed", "failed", "cancelled"}
SAFE_RESULT_KEYS = {
    "rowCount", "oldestDate", "newestDate", "tradingDateCount", "missingDates",
    "duplicateCount", "revisionCount", "failedRequestCount", "universeCounts",
    "coverage", "turningPointCount", "backtests", "stateHash", "methodVersion",
    "rawProviderRowsPersisted", "status", "benchmarkId", "datasetHash",
    "resultClassification", "twoXClaimAllowed", "totalCostJpy", "readBackVerified",
    "verificationStatus", "pendingCount", "errorClass", "marketLedgerReadBack",
    "expectedHash", "actualHash", "remoteCommitSha", "ack",
    "matrix", "recentConfirmedTradingDay", "directClientAllSuccessful",
    "officialClientAllSuccessful", "oldestRequiredDateAccessible", "rootCause",
    "correctedDateFormat", "preview", "modelsApi", "stable", "stableModel",
    "previewProviderDefect", "stableProviderPath", "selectedBaselineModel",
    "baselineSwapReason", "formalBaselineModel", "latestCounts", "latestRatios",
    "observationCount", "checkpointPending", "permanentFailures",
    "universeObservationCounts", "spotChecks", "spotCheckPassed",
    "plan", "planEntitlement", "entitlementStartDate", "entitlementEndDate",
    "entitlementObservedAt", "latestConfirmedTradingDate",
    "providerResponseClass", "contractScope", "apiVersion", "universeMethodology",
    "productionHistoryYears", "productionFiveYearStartDate",
    "productionFiveYearEndDate", "archiveBackfillStatus", "archiveScope",
    "coreRequired", "stage", "batchPolicy", "checkpointPersistence",
    "duplicateSafeResume", "executionMode", "workerConcurrency",
    "workerMemorySoftLimitMb", "workerPeakMemoryMb", "backendPeakMemoryMb",
    "backendPeakMemoryAtStartMb", "backendRestartCountDuringJob",
    "backendBootIdStable",
    "dryRun", "manifestValidation", "providerPreflight", "formalResult",
}


def _request(url: str, *, token: Optional[str] = None,
             payload: Optional[Dict[str, Any]] = None,
             timeout: int = 120) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode()
        method = "POST"
    if token:
        headers["X-ARGUS-ADMIN-TOKEN"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"transport_{type(exc).__name__}") from None
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("invalid_json") from None
    if not isinstance(body, dict):
        raise RuntimeError("invalid_json_shape")
    return body


def _safe(job: Dict[str, Any]) -> Dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    return {"jobId": job.get("jobId"), "jobType": job.get("jobType"),
            "status": job.get("status"), "progress": job.get("progress"),
            "errorClass": job.get("errorClass"),
            "result": {k: v for k, v in result.items() if k in SAFE_RESULT_KEYS}}


def run(base_url: str, token: str, job_type: str, parameters: Dict[str, Any],
        poll_seconds: int, max_wait_seconds: int, resume: bool = False) -> int:
    base = base_url.rstrip("/")
    started = _request(
        f"{base}/api/argus/admin/foundation-jobs", token=token,
        payload={"jobType": job_type, "confirm": True, "triggerSource": "manual",
                 "resume": bool(resume), "parameters": parameters})
    jobs = ((started.get("job") or {}) if isinstance(started.get("job"), dict)
            else {})
    job_id = str(jobs.get("jobId") or "")
    if started.get("ok") is not True or not job_id:
        raise RuntimeError("job_start_failed")
    print(json.dumps({"started": {"jobId": job_id, "jobType": job_type}},
                     separators=(",", ":")))
    deadline = time.monotonic() + max_wait_seconds
    latest: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = _request(
            f"{base}/api/argus/foundation-jobs?" +
            urllib.parse.urlencode({"jobId": job_id}), timeout=60)
        rows = status.get("jobs") or []
        if not rows:
            raise RuntimeError("job_status_missing")
        latest = rows[0]
        if latest.get("status") in TERMINAL:
            break
        time.sleep(max(1, poll_seconds))
    else:
        print(json.dumps({"status": "running", "jobId": job_id,
                          "reason": "poll_timeout"}, separators=(",", ":")))
        return 6
    print(json.dumps({"final": _safe(latest)}, separators=(",", ":")))
    return 0 if latest.get("status") == "completed" else 8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://argus-backend-3j2m.onrender.com")
    parser.add_argument("--job-type", required=True)
    parser.add_argument("--parameters-json", default="{}")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-wait-seconds", type=int, default=21000)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("ARGUS_ADMIN_TOKEN", "")
    if not token:
        print('{"status":"blocked","reason":"ARGUS_ADMIN_TOKEN_missing"}')
        return 2
    try:
        parameters = json.loads(args.parameters_json)
        if not isinstance(parameters, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        print('{"status":"failure","reason":"invalid_parameters_json"}')
        return 2
    try:
        return run(args.base_url, token, args.job_type.upper(), parameters,
                   args.poll_seconds, args.max_wait_seconds, args.resume)
    except RuntimeError as exc:
        print(json.dumps({"status": "failure", "reason": str(exc)},
                         separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
