#!/usr/bin/env python3
"""Invoke the ARGUS mission tick from EC2 systemd without exposing secrets."""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request


UTC = dt.timezone.utc
OFFSET_MINUTE = 7
INTERVAL_SECONDS = 30 * 60
IDENTITY_DECISION_FILE = "/run/argus-build-identity/decision.json"


def _window(now: dt.datetime) -> tuple[str, str]:
    now = now.astimezone(UTC).replace(microsecond=0)
    offset = OFFSET_MINUTE * 60
    slot = int((now.timestamp() - offset) // INTERVAL_SECONDS)
    scheduled = dt.datetime.fromtimestamp(
        slot * INTERVAL_SECONDS + offset, tz=UTC)
    scheduled_for = scheduled.isoformat().replace("+00:00", "Z")
    return scheduled_for, f"mw-{scheduled_for}"


def _emit(**fields: object) -> None:
    fields.setdefault("component", "argus-mission-tick")
    print(json.dumps(fields, ensure_ascii=False, sort_keys=True), flush=True)


def _safe_response(body: object) -> dict[str, object]:
    data = body if isinstance(body, dict) else {}
    window = data.get("missionWindow")
    window = window if isinstance(window, dict) else {}
    soak = data.get("soak")
    soak = soak if isinstance(soak, dict) else {}
    outcome = data.get("outcomeRetry")
    outcome = outcome if isinstance(outcome, dict) else {}
    remote = data.get("remoteJournal")
    remote = remote if isinstance(remote, dict) else {}
    cost = data.get("costPolicy")
    cost = cost if isinstance(cost, dict) else {}
    return {
        "businessStatus": data.get("status"),
        "result": data.get("result"),
        "reason": data.get("reason"),
        "jobId": data.get("jobId"),
        "processedCount": data.get("processedCount"),
        "remainingCount": data.get("remainingCount"),
        "hasMore": data.get("hasMore"),
        "cursorBefore": data.get("cursorBefore"),
        "cursorAfter": data.get("cursorAfter"),
        "checkpointCreated": data.get("checkpointCreated"),
        "missionWindowId": window.get("missionWindowId"),
        "triggerSource": window.get("triggerSource"),
        "duplicateSuppressed": window.get("duplicateSuppressed"),
        "finalStatus": window.get("finalStatus") or window.get("status"),
        "delaySeconds": window.get("delaySeconds"),
        "outcomeEvaluated": outcome.get("evaluated"),
        "outcomeResolved": outcome.get("resolved"),
        "outcomeCount": outcome.get("outcomeCount"),
        "outcomeDuplicateCount": outcome.get("duplicateCount"),
        "soakId": soak.get("soakId"),
        "soakState": soak.get("state"),
        "heartbeatCount": soak.get("heartbeatCount"),
        "readBackVerified": remote.get("readBackVerified"),
        "remoteCommitSha": remote.get("remoteCommitSha"),
        "remoteErrorClass": remote.get("errorClass"),
        "automaticAiEnabled": cost.get("automaticAiEnabled"),
        "automaticAiExecutions": cost.get("automaticAiExecutions"),
    }


def _identity_decision() -> dict[str, object]:
    path = os.environ.get(
        "ARGUS_BUILD_IDENTITY_DECISION_FILE", IDENTITY_DECISION_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        # Backward-compatible bootstrap for a not-yet-upgraded unit.  A static
        # pin is never preferred once the independent preflight is installed.
        expected = os.environ.get("ARGUS_EXPECTED_BUILD_SHA", "").strip()
        return ({"status": "verified", "identitySource": "static_bootstrap",
                 "expectedBuildSha": expected} if expected else
                {"status": "failure", "errorClass":
                 "build_identity_decision_missing"})


def main() -> int:
    base = os.environ.get(
        "ARGUS_BACKEND_URL", "https://argus-backend-3j2m.onrender.com"
    ).rstrip("/")
    token = os.environ.get("ARGUS_ADMIN_TOKEN", "")
    if not token:
        _emit(status="failure", errorClass="missing_admin_token")
        return 78
    timeout = min(180, max(10, int(os.environ.get(
        "ARGUS_TICK_TIMEOUT_SECONDS", "180"))))
    attempts = min(2, max(1, int(os.environ.get(
        "ARGUS_TICK_MAX_ATTEMPTS", "2"))))
    max_batches = min(6, max(1, int(os.environ.get(
        "ARGUS_TICK_MAX_BATCHES", "3"))))
    total_budget = min(270, max(30, int(os.environ.get(
        "ARGUS_TICK_TOTAL_BUDGET_SECONDS", "240"))))
    deadline = time.monotonic() + total_budget
    identity = _identity_decision()
    identity_status = str(identity.get("status") or "failure")
    identity_log = {
        "identitySource": identity.get("identitySource"),
        "errorClass": identity.get("errorClass"),
        "expectedBuildSha": (str(identity.get("expectedBuildSha"))[:7]
                              if identity.get("expectedBuildSha") else None),
        "actualBuildSha": (str(identity.get("actualBuildSha"))[:7]
                            if identity.get("actualBuildSha") else None),
        "buildMismatch": identity.get("buildMismatch"),
        "transitionElapsedSeconds": identity.get(
            "transitionElapsedSeconds"),
    }
    if identity_status == "expected_skip":
        _emit(status="expected_skip", **identity_log)
        return 0
    if identity_status != "verified":
        _emit(status="failure", **identity_log)
        return 1

    scheduled_for, window_id = _window(dt.datetime.now(tz=UTC))
    requested_source = os.environ.get(
        "ARGUS_TRIGGER_SOURCE", "ec2_systemd").strip().lower()
    diagnostic = requested_source in ("diagnostic", "manual")
    payload: dict[str, object] = {
        "triggerSource": ("manual" if diagnostic else "ec2_systemd"),
        "scheduledFor": scheduled_for,
        "missionWindowId": window_id,
    }
    if diagnostic:
        payload.pop("missionWindowId", None)
        payload["runId"] = "diagnostic-" + str(time.time_ns())
    expected_sha = str(identity.get("expectedBuildSha") or "").strip()
    if expected_sha:
        payload["expectedBuildSha"] = expected_sha
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/argus/admin/missions/tick",
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ARGUS-ADMIN-TOKEN": token,
            "User-Agent": "argus-ec2-systemd/1",
        },
    )
    last_safe: dict[str, object] = {}
    for batch in range(1, max_batches + 1):
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            remaining_budget = int(deadline - started)
            if remaining_budget <= 0:
                _emit(status="degraded",
                      errorClass="bounded_total_budget_exhausted",
                      batch=batch, **last_safe)
                return 2
            try:
                with urllib.request.urlopen(
                        request,
                        timeout=max(1, min(timeout, remaining_budget))) as response:
                    status_code = int(response.status)
                    body = json.loads(response.read().decode("utf-8"))
                safe = _safe_response(body)
                last_safe = safe
                business_status = safe.get("businessStatus")
                result = safe.get("result")
                if status_code != 200 or business_status not in (
                    "completed", "expected_skip", "degraded"
                ):
                    _emit(
                        status="failure", errorClass="business_failure",
                        httpStatus=status_code, attempt=attempt, batch=batch,
                        elapsedMs=round((time.monotonic() - started) * 1000),
                        **safe,
                    )
                    return 1
                if result == "busy":
                    _emit(
                        status="expected_skip", httpStatus=status_code,
                        attempt=attempt, batch=batch,
                        elapsedMs=round((time.monotonic() - started) * 1000),
                        invocation=("diagnostic" if diagnostic else "natural"),
                        **identity_log, **safe)
                    return 0
                if result == "partial":
                    _emit(
                        status="partial", httpStatus=status_code,
                        attempt=attempt, batch=batch,
                        elapsedMs=round((time.monotonic() - started) * 1000),
                        invocation=("diagnostic" if diagnostic else "natural"),
                        **identity_log, **safe)
                    break
                _emit(
                    status="success", httpStatus=status_code,
                    attempt=attempt, batch=batch,
                    elapsedMs=round((time.monotonic() - started) * 1000),
                    invocation=("diagnostic" if diagnostic else "natural"),
                    **identity_log, **safe,
                )
                return 0
            except urllib.error.HTTPError as exc:
                retryable = int(exc.code) >= 500
                if not retryable or attempt >= attempts:
                    _emit(status="failure", errorClass="http_error",
                          httpStatus=int(exc.code), attempt=attempt, batch=batch)
                    return 1
            except (urllib.error.URLError, TimeoutError, socket.timeout,
                    json.JSONDecodeError, UnicodeDecodeError) as exc:
                if attempt >= attempts:
                    _emit(status="failure", errorClass=type(exc).__name__,
                          attempt=attempt, batch=batch)
                    return 1
            time.sleep(max(0, min(5, deadline - time.monotonic())))
        if last_safe.get("result") != "partial":
            return 1
    _emit(status="degraded", errorClass="bounded_batches_exhausted",
          batch=max_batches, **last_safe)
    return 2


if __name__ == "__main__":
    sys.exit(main())
