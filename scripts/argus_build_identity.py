#!/usr/bin/env python3
"""Resolve the trusted production build before an EC2 mission tick.

The trusted side is GitHub's main ref.  The backend health response is only the
observed side of the comparison and can never promote itself to trusted state.
No authentication material is read or emitted by this helper.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional, Tuple


UTC = dt.timezone.utc
DEFAULT_REF_URL = "https://api.github.com/repos/mitsugue/argus/commits/main"
DEFAULT_BACKEND_URL = "https://argus-backend-3j2m.onrender.com"
DEFAULT_STATE_FILE = "/var/lib/argus-build-identity/state.json"
DEFAULT_DECISION_FILE = "/run/argus-build-identity/decision.json"
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _iso(now: dt.datetime) -> str:
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _epoch(value: object) -> Optional[float]:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return None


def _valid_sha(value: object) -> str:
    value = str(value or "").strip().lower()
    return value if SHA_RE.fullmatch(value) else ""


def _matches(trusted: str, observed: str) -> bool:
    trusted = _valid_sha(trusted)
    observed = _valid_sha(observed)
    return bool(trusted and observed and (
        trusted.startswith(observed) or observed.startswith(trusted)))


def resolve_identity(*, trusted_sha: str, backend_sha: str,
                     state: dict[str, Any], now_iso: str,
                     grace_seconds: int, upstream_error: str | None = None,
                     static_sha: str = "") -> Tuple[dict[str, Any], dict[str, Any]]:
    """Pure deployment-transition state machine used by the service and tests."""
    state = dict(state) if isinstance(state, dict) else {}
    backend_sha = _valid_sha(backend_sha)
    trusted_sha = _valid_sha(trusted_sha)
    if not backend_sha:
        return ({"status": "failure", "errorClass": "backend_build_unavailable",
                 "identitySource": "backend_health",
                 "expectedBuildSha": trusted_sha or None,
                 "actualBuildSha": None}, state)

    if upstream_error:
        last_verified = _valid_sha(state.get("lastVerifiedSha"))
        fallback = last_verified or _valid_sha(static_sha)
        source = ("last_verified_fallback" if last_verified
                  else "static_bootstrap_fallback")
        if fallback and _matches(fallback, backend_sha):
            return ({"status": "verified", "errorClass": None,
                     "identitySource": source,
                     "expectedBuildSha": fallback,
                     "actualBuildSha": backend_sha,
                     "upstreamStatus": "unavailable"}, state)
        return ({"status": "failure", "errorClass": "github_unavailable",
                 "identitySource": source,
                 "expectedBuildSha": fallback or None,
                 "actualBuildSha": backend_sha,
                 "upstreamStatus": "unavailable"}, state)

    if not trusted_sha:
        return ({"status": "failure", "errorClass": "trusted_sha_invalid",
                 "identitySource": "github_main",
                 "expectedBuildSha": None, "actualBuildSha": backend_sha}, state)

    if _matches(trusted_sha, backend_sha):
        state.update({"schemaVersion": 1, "lastVerifiedSha": trusted_sha,
                      "lastVerifiedAt": now_iso})
        state.pop("transitionSha", None)
        state.pop("transitionStartedAt", None)
        return ({"status": "verified", "errorClass": None,
                 "identitySource": "github_main",
                 "expectedBuildSha": trusted_sha,
                 "actualBuildSha": backend_sha,
                 "buildMismatch": False}, state)

    transition_sha = _valid_sha(state.get("transitionSha"))
    transition_started = state.get("transitionStartedAt")
    if transition_sha != trusted_sha or _epoch(transition_started) is None:
        transition_started = now_iso
    state.update({"schemaVersion": 1, "transitionSha": trusted_sha,
                  "transitionStartedAt": transition_started})
    now_epoch = _epoch(now_iso)
    start_epoch = _epoch(transition_started)
    elapsed = max(0, int((now_epoch or 0) - (start_epoch or 0)))
    if elapsed <= max(0, int(grace_seconds)):
        return ({"status": "expected_skip",
                 "errorClass": "deployment_transition",
                 "identitySource": "github_main",
                 "expectedBuildSha": trusted_sha,
                 "actualBuildSha": backend_sha,
                 "buildMismatch": True,
                 "transitionElapsedSeconds": elapsed}, state)
    return ({"status": "failure",
             "errorClass": "deployment_transition_timeout",
             "identitySource": "github_main",
             "expectedBuildSha": trusted_sha,
             "actualBuildSha": backend_sha,
             "buildMismatch": True,
             "transitionElapsedSeconds": elapsed}, state)


def _fetch_json(url: str, *, timeout: int, attempts: int,
                opener: Callable[..., Any] = urllib.request.urlopen) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json, application/json",
                      "User-Agent": "argus-build-identity/1"})
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=timeout) as response:
                if int(response.status) != 200:
                    raise urllib.error.HTTPError(
                        url, int(response.status), "unexpected status", {}, None)
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                json.JSONDecodeError, UnicodeDecodeError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(2)
    raise RuntimeError(type(last).__name__ if last else "fetch_failed")


def _load_state(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: str, value: dict[str, Any], *, mode: int,
                 directory_mode: int) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=directory_mode, exist_ok=True)
    os.chown(directory, 0, 0)
    os.chmod(directory, directory_mode)
    fd, temporary = tempfile.mkstemp(prefix=".argus-build-", dir=directory)
    try:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"))
               + "\n").encode("utf-8")
        os.write(fd, raw)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chown(temporary, 0, 0)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


def _emit(decision: dict[str, Any]) -> None:
    safe = {key: value for key, value in decision.items() if key in {
        "status", "errorClass", "identitySource", "expectedBuildSha",
        "actualBuildSha", "buildMismatch", "transitionElapsedSeconds",
        "upstreamStatus"}}
    for key in ("expectedBuildSha", "actualBuildSha"):
        if safe.get(key):
            safe[key] = str(safe[key])[:7]
    safe["component"] = "argus-build-identity"
    print(json.dumps(safe, sort_keys=True), flush=True)


def main() -> int:
    if os.geteuid() != 0:
        _emit({"status": "failure", "errorClass": "root_preflight_required"})
        return 77
    now_iso = _iso(dt.datetime.now(tz=UTC))
    base = os.environ.get("ARGUS_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")
    ref_url = os.environ.get("ARGUS_TRUSTED_BUILD_REF_URL", DEFAULT_REF_URL)
    state_file = os.environ.get(
        "ARGUS_BUILD_IDENTITY_STATE_FILE", DEFAULT_STATE_FILE)
    decision_file = os.environ.get(
        "ARGUS_BUILD_IDENTITY_DECISION_FILE", DEFAULT_DECISION_FILE)
    timeout = min(30, max(3, int(os.environ.get(
        "ARGUS_BUILD_IDENTITY_TIMEOUT_SECONDS", "15"))))
    attempts = min(2, max(1, int(os.environ.get(
        "ARGUS_BUILD_IDENTITY_MAX_ATTEMPTS", "2"))))
    grace = min(3600, max(60, int(os.environ.get(
        "ARGUS_BUILD_TRANSITION_GRACE_SECONDS", "900"))))
    state = _load_state(state_file)
    trusted_sha = ""
    upstream_error = None
    try:
        ref = _fetch_json(ref_url, timeout=timeout, attempts=attempts)
        trusted_sha = _valid_sha(ref.get("sha") if isinstance(ref, dict) else "")
        if not trusted_sha:
            upstream_error = "trusted_sha_invalid"
    except RuntimeError:
        upstream_error = "github_unavailable"
    try:
        health = _fetch_json(base + "/healthz", timeout=timeout,
                             attempts=attempts)
        backend_sha = _valid_sha(
            health.get("buildSha") if isinstance(health, dict) else "")
    except RuntimeError:
        backend_sha = ""
    decision, next_state = resolve_identity(
        trusted_sha=trusted_sha, backend_sha=backend_sha, state=state,
        now_iso=now_iso, grace_seconds=grace, upstream_error=upstream_error,
        static_sha=os.environ.get("ARGUS_EXPECTED_BUILD_SHA", ""))
    decision["checkedAt"] = now_iso
    _atomic_json(state_file, next_state, mode=0o600, directory_mode=0o700)
    _atomic_json(decision_file, decision, mode=0o644, directory_mode=0o755)
    _emit(decision)
    # ExecStart consumes the decision so expected skips and failures receive a
    # single structured classification.  Only inability to publish it is fatal.
    return 0


if __name__ == "__main__":
    sys.exit(main())
