#!/usr/bin/env python3
"""GET-only verification for production release-manifest publication."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import time
import urllib.error
import urllib.request
from typing import Any


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _get(url: str, timeout: int) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "argus-production-release-verifier/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), json.loads(
                response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return 0, None


def evaluate(
    *,
    health_status: int,
    health: Any,
    ready_status: int,
    ready: Any,
    expected_sha: str,
    expected_version: str,
) -> tuple[bool, str]:
    expected_sha = str(expected_sha or "").lower()
    if not FULL_SHA_RE.fullmatch(expected_sha):
        return False, "expected_full_sha_required"
    if health_status != 200 or not isinstance(health, dict):
        return False, "health_unavailable"
    if health.get("status") != "ok":
        return False, "health_not_ok"
    observed = str(health.get("buildSha") or "").lower()
    if not observed or not expected_sha.startswith(observed):
        return False, "health_sha_mismatch"
    version = str(
        health.get("backendVersion") or health.get("appVersion") or "")
    if version != str(expected_version):
        return False, "health_version_mismatch"
    if ready_status != 200 or not isinstance(ready, dict):
        return False, "ready_unavailable"
    if ready.get("ready") is not True:
        return False, "ready_not_true"
    ready_sha = str(ready.get("buildSha") or "").lower()
    if ready_sha and not expected_sha.startswith(ready_sha):
        return False, "ready_sha_mismatch"
    return True, "verified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--request-timeout-seconds", type=int, default=30)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    attempts = 0
    reason = "not_started"
    health: Any = None
    ready: Any = None
    while time.monotonic() - started <= max(1, args.timeout_seconds):
        attempts += 1
        health_status, health = _get(
            args.base_url.rstrip("/") + "/healthz",
            max(1, args.request_timeout_seconds),
        )
        ready_status, ready = _get(
            args.base_url.rstrip("/") + "/readyz",
            max(1, args.request_timeout_seconds),
        )
        accepted, reason = evaluate(
            health_status=health_status,
            health=health,
            ready_status=ready_status,
            ready=ready,
            expected_sha=args.expected_sha,
            expected_version=args.expected_version,
        )
        if accepted:
            checked_at = dt.datetime.now(
                tz=dt.timezone.utc).replace(microsecond=0).isoformat().replace(
                    "+00:00", "Z")
            evidence = {
                "status": "verified",
                "checkedAt": checked_at,
                "attempts": attempts,
                "buildSha": args.expected_sha.lower(),
                "version": args.expected_version,
                "verifiedHealth": True,
                "verifiedReady": True,
                "health": {
                    "status": health.get("status"),
                    "buildSha": health.get("buildSha"),
                    "backendVersion": health.get("backendVersion"),
                },
                "ready": {
                    "ready": ready.get("ready"),
                    "buildSha": ready.get("buildSha"),
                },
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(evidence, sort_keys=True, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )
            print(json.dumps(evidence, sort_keys=True))
            return 0
        time.sleep(max(1, min(args.poll_seconds, 60)))
    failure = {
        "status": "failed",
        "reason": reason,
        "attempts": attempts,
        "buildSha": str(args.expected_sha).lower(),
        "version": args.expected_version,
        "verifiedHealth": False,
        "verifiedReady": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(failure, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(failure, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
