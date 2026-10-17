#!/usr/bin/env python3
"""Run the approved one-shot research benchmark without exposing credentials.

This operator tool performs a no-provider dry-run first, enforces the explicit
JPY ceiling, submits the execute request exactly once, and then polls only the
public status endpoint.  It never prints response bodies or request headers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


TERMINAL = {"achieved", "not_achieved", "provider_blocked", "provider_failed",
            "input_budget_exceeded", "invalid_evaluator_json", "invalid",
            "interrupted"}


def _request_json(url: str, *, token: Optional[str] = None,
                  payload: Optional[Dict[str, Any]] = None,
                  timeout: int = 120) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if payload is not None:
        method = "POST"
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if token:
        headers["X-ARGUS-ADMIN-TOKEN"] = token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"transport {type(exc).__name__}") from None
    if not 200 <= status < 300:
        raise RuntimeError(f"HTTP {status}")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("invalid JSON") from None
    if not isinstance(body, dict):
        raise RuntimeError("invalid JSON shape")
    return body


def _safe_status(body: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("status", "mode", "benchmarkId", "datasetHash", "benchmarkDate",
            "researchEpoch", "geminiModel", "argusModel", "refereeModel",
            "pricingVersion", "argusVersion", "calibrationCaseCount", "holdoutCaseCount",
            "geminiScore", "argusScore", "medianRatio", "geometricMeanRatio",
            "twoXClaimAllowed", "totalApiCostJpy", "resultClassification")
    return {key: body.get(key) for key in keys if key in body}


def run(base_url: str, *, token: str, ceiling_jpy: float,
        poll_seconds: int, max_wait_seconds: int) -> int:
    base = base_url.rstrip("/")
    policy = _request_json(f"{base}/api/argus/cost-policy", timeout=60)
    if policy.get("mode") != "DETERMINISTIC":
        print('{"status":"blocked","reason":"normal_mode_not_deterministic"}')
        return 2

    dry = _request_json(
        f"{base}/api/argus/admin/research-benchmark/dry-run", token=token,
        payload={"triggerSource": "manual"})
    dry_summary = {"status": dry.get("status"),
                   "providersConfigured": dry.get("providersConfigured"),
                   "estimatedCostJpy": dry.get("estimatedCostJpy"),
                   "effectiveBudgetJpy": dry.get("effectiveBudgetJpy"),
                   "caseCount": dry.get("caseCount"),
                   "maximumCalls": dry.get("maximumCalls")}
    print(json.dumps({"dryRun": dry_summary}, separators=(",", ":")))
    try:
        estimated = float(dry.get("estimatedCostJpy"))
    except (TypeError, ValueError):
        estimated = float("inf")
    dry_hash = str(dry.get("dryRunHash") or "")
    if (dry.get("status") != "ready" or dry.get("ok") is not True
            or dry.get("providersConfigured") is not True
            or estimated > ceiling_jpy or len(dry_hash) != 64):
        print('{"status":"blocked","reason":"dry_run_gate"}')
        return 3

    # Deliberately no retry: the backend also persists executionCount=1 at begin.
    started = _request_json(
        f"{base}/api/argus/admin/research-benchmark/execute", token=token,
        payload={"triggerSource": "manual", "confirm": True,
                 "dryRunHash": dry_hash}, timeout=120)
    if started.get("ok") is not True or started.get("status") != "running":
        print(json.dumps({"execute": _safe_status(started)}, separators=(",", ":")))
        return 4
    print(json.dumps({"execute": _safe_status(started)}, separators=(",", ":")))

    deadline = time.monotonic() + max_wait_seconds
    latest: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _request_json(f"{base}/api/argus/research-benchmark", timeout=60)
        status = str(latest.get("status") or "")
        if status in TERMINAL:
            break
        if status != "running":
            print(json.dumps({"final": _safe_status(latest)}, separators=(",", ":")))
            return 5
        time.sleep(poll_seconds)
    else:
        print('{"status":"running","reason":"poll_timeout"}')
        return 6

    final_policy = _request_json(f"{base}/api/argus/cost-policy", timeout=60)
    print(json.dumps({"final": _safe_status(latest)}, separators=(",", ":")))
    if final_policy.get("mode") != "DETERMINISTIC":
        print('{"status":"failure","reason":"deterministic_restore_failed"}')
        return 7
    return 0 if latest.get("status") in ("achieved", "not_achieved") else 8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://argus-backend-3j2m.onrender.com")
    parser.add_argument("--ceiling-jpy", type=float, default=800.0)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--max-wait-seconds", type=int, default=3000)
    args = parser.parse_args()
    token = os.environ.get("ARGUS_ADMIN_TOKEN", "")
    if not token:
        print('{"status":"blocked","reason":"ARGUS_ADMIN_TOKEN_missing"}')
        return 2
    try:
        return run(args.base_url, token=token, ceiling_jpy=args.ceiling_jpy,
                   poll_seconds=max(1, args.poll_seconds),
                   max_wait_seconds=max(1, args.max_wait_seconds))
    except RuntimeError as exc:
        print(json.dumps({"status": "failure", "reason": str(exc)},
                         separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
