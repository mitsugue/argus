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
    return {
        "businessStatus": data.get("status"),
        "reason": data.get("reason"),
        "missionWindowId": window.get("missionWindowId"),
        "triggerSource": window.get("triggerSource"),
        "duplicateSuppressed": window.get("duplicateSuppressed"),
        "finalStatus": window.get("finalStatus") or window.get("status"),
        "delaySeconds": window.get("delaySeconds"),
        "outcomeEvaluated": outcome.get("evaluated"),
        "outcomeResolved": outcome.get("resolved"),
        "outcomeCount": outcome.get("outcomeCount"),
        "soakId": soak.get("soakId"),
        "soakState": soak.get("state"),
        "heartbeatCount": soak.get("heartbeatCount"),
        "readBackVerified": remote.get("readBackVerified"),
        "remoteCommitSha": remote.get("remoteCommitSha"),
    }


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
    scheduled_for, window_id = _window(dt.datetime.now(tz=UTC))
    payload: dict[str, object] = {
        "triggerSource": "ec2_systemd",
        "scheduledFor": scheduled_for,
        "missionWindowId": window_id,
    }
    expected_sha = os.environ.get("ARGUS_EXPECTED_BUILD_SHA", "").strip()
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
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status_code = int(response.status)
                body = json.loads(response.read().decode("utf-8"))
            safe = _safe_response(body)
            business_status = safe.get("businessStatus")
            if status_code != 200 or business_status not in (
                "completed", "expected_skip", "degraded"
            ):
                _emit(
                    status="failure", errorClass="business_failure",
                    httpStatus=status_code, attempt=attempt,
                    elapsedMs=round((time.monotonic() - started) * 1000),
                    **safe,
                )
                return 1
            _emit(
                status=("success" if business_status != "degraded" else "degraded"),
                httpStatus=status_code, attempt=attempt,
                elapsedMs=round((time.monotonic() - started) * 1000),
                **safe,
            )
            return 0 if business_status != "degraded" else 2
        except urllib.error.HTTPError as exc:
            retryable = int(exc.code) >= 500
            if not retryable or attempt >= attempts:
                _emit(status="failure", errorClass="http_error",
                      httpStatus=int(exc.code), attempt=attempt)
                return 1
        except (urllib.error.URLError, TimeoutError, socket.timeout,
                json.JSONDecodeError, UnicodeDecodeError) as exc:
            if attempt >= attempts:
                _emit(status="failure", errorClass=type(exc).__name__,
                      attempt=attempt)
                return 1
        time.sleep(5)
    return 1


if __name__ == "__main__":
    sys.exit(main())
