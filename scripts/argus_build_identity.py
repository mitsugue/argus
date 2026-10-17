#!/usr/bin/env python3
"""Resolve trusted production backend identity before an EC2 mission tick.

Trust comes only from the external production release manifest.  Backend
``/healthz`` is observed input and can never promote itself.  A static SHA is
accepted only for first-install/emergency bootstrap when no verified state
exists, and only when it matches the observed backend.
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

try:
    from scripts.production_release_manifest import (
        ManifestValidationError,
        validate_manifest,
    )
except ModuleNotFoundError:
    from production_release_manifest import (  # type: ignore
        ManifestValidationError,
        validate_manifest,
    )


UTC = dt.timezone.utc
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/mitsugue/argus/"
    "production-release/production/argus-backend.json"
)
DEFAULT_BACKEND_URL = "https://argus-backend-3j2m.onrender.com"
DEFAULT_STATE_FILE = "/var/lib/argus-build-identity/state.json"
DEFAULT_DECISION_FILE = "/run/argus-build-identity/decision.json"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OBSERVED_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


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


def _valid_full_sha(value: object) -> str:
    value = str(value or "").strip().lower()
    return value if FULL_SHA_RE.fullmatch(value) else ""


def _valid_observed_sha(value: object) -> str:
    value = str(value or "").strip().lower()
    return value if OBSERVED_SHA_RE.fullmatch(value) else ""


def _matches(trusted: str, observed: str) -> bool:
    trusted = _valid_full_sha(trusted)
    observed = _valid_observed_sha(observed)
    return bool(trusted and observed and trusted.startswith(observed))


def resolve_identity(
    *,
    manifest: dict[str, Any] | None,
    backend_sha: str,
    backend_version: str = "",
    state: dict[str, Any],
    now_iso: str,
    grace_seconds: int,
    manifest_error: str | None = None,
    static_sha: str = "",
) -> Tuple[dict[str, Any], dict[str, Any]]:
    """Pure production-manifest state machine used by EC2 and tests."""
    state = dict(state) if isinstance(state, dict) else {}
    if manifest is not None and not manifest_error:
        try:
            manifest = validate_manifest(manifest, now_iso=now_iso)
        except ManifestValidationError as exc:
            manifest = None
            manifest_error = str(exc)
    backend_sha = _valid_observed_sha(backend_sha)
    if not backend_sha:
        return ({
            "status": "failure",
            "errorClass": "backend_build_unavailable",
            "identitySource": "backend_health",
            "expectedBuildSha": None,
            "actualBuildSha": None,
            "degraded": False,
        }, state)

    trusted_sha = _valid_full_sha((manifest or {}).get("buildSha"))
    if manifest_error or not trusted_sha:
        last_verified = _valid_full_sha(state.get("lastVerifiedSha"))
        bootstrap = _valid_full_sha(static_sha) if not last_verified else ""
        fallback = last_verified or bootstrap
        source = (
            "last_verified_fallback" if last_verified
            else "static_bootstrap_fallback"
        )
        error_class = manifest_error or "production_manifest_invalid"
        if fallback and _matches(fallback, backend_sha):
            return ({
                "status": "verified",
                "errorClass": error_class,
                "identitySource": source,
                "expectedBuildSha": fallback,
                "actualBuildSha": backend_sha,
                "upstreamStatus": "unavailable",
                "degraded": True,
                "buildMismatch": False,
            }, state)
        return ({
            "status": "failure",
            "errorClass": error_class,
            "identitySource": source,
            "expectedBuildSha": fallback or None,
            "actualBuildSha": backend_sha,
            "upstreamStatus": "unavailable",
            "degraded": True,
        }, state)

    deployed_at = str((manifest or {}).get("deployedAt") or "")
    expected_version = str((manifest or {}).get("version") or "")
    backend_version = str(backend_version or "").strip()
    render_deployment_id = str(
        (manifest or {}).get("renderDeploymentId")
        or (manifest or {}).get("deploymentId")
        or ""
    )
    if backend_version and backend_version != expected_version:
        return ({
            "status": "failure",
            "errorClass": "backend_version_mismatch",
            "identitySource": "production_release_manifest",
            "expectedBuildSha": trusted_sha,
            "actualBuildSha": backend_sha,
            "expectedBackendVersion": expected_version,
            "actualBackendVersion": backend_version,
            "renderDeploymentId": render_deployment_id,
            "degraded": False,
        }, state)
    if _matches(trusted_sha, backend_sha):
        state.update({
            "schemaVersion": 2,
            "lastVerifiedSha": trusted_sha,
            "lastVerifiedAt": now_iso,
            "lastManifestDeployedAt": deployed_at,
            "lastDeploymentId": (manifest or {}).get("deploymentId"),
            "lastRenderDeploymentId": render_deployment_id,
        })
        state.pop("transitionSha", None)
        state.pop("transitionStartedAt", None)
        return ({
            "status": "verified",
            "errorClass": None,
            "identitySource": "production_release_manifest",
            "expectedBuildSha": trusted_sha,
            "actualBuildSha": backend_sha,
            "buildMismatch": False,
            "renderDeploymentId": render_deployment_id,
            "degraded": False,
        }, state)

    transition_sha = _valid_full_sha(state.get("transitionSha"))
    transition_started = state.get("transitionStartedAt")
    if transition_sha != trusted_sha or _epoch(transition_started) is None:
        transition_started = now_iso
    state.update({
        "schemaVersion": 2,
        "transitionSha": trusted_sha,
        "transitionStartedAt": transition_started,
    })
    now_epoch = _epoch(now_iso)
    start_epoch = _epoch(transition_started)
    elapsed = max(0, int((now_epoch or 0) - (start_epoch or 0)))
    if elapsed <= max(0, int(grace_seconds)):
        return ({
            "status": "expected_skip",
            "errorClass": "deployment_transition",
            "identitySource": "production_release_manifest",
            "expectedBuildSha": trusted_sha,
            "actualBuildSha": backend_sha,
            "buildMismatch": True,
            "renderDeploymentId": render_deployment_id,
            "transitionElapsedSeconds": elapsed,
            "degraded": False,
        }, state)
    return ({
        "status": "failure",
        "errorClass": "deployment_transition_timeout",
        "identitySource": "production_release_manifest",
        "expectedBuildSha": trusted_sha,
        "actualBuildSha": backend_sha,
        "buildMismatch": True,
        "renderDeploymentId": render_deployment_id,
        "transitionElapsedSeconds": elapsed,
        "degraded": False,
    }, state)


def _fetch_json(
    url: str,
    *,
    timeout: int,
    attempts: int,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "argus-build-identity/2",
        },
    )
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=timeout) as response:
                if int(response.status) != 200:
                    raise urllib.error.HTTPError(
                        url, int(response.status), "unexpected status", {}, None)
                return json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
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


def _atomic_json(
    path: str,
    value: dict[str, Any],
    *,
    mode: int,
    directory_mode: int,
) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=directory_mode, exist_ok=True)
    os.chown(directory, 0, 0)
    os.chmod(directory, directory_mode)
    fd, temporary = tempfile.mkstemp(prefix=".argus-build-", dir=directory)
    try:
        raw = (
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
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
    safe = {
        key: value for key, value in decision.items()
        if key in {
            "status", "errorClass", "identitySource", "expectedBuildSha",
            "actualBuildSha", "buildMismatch", "transitionElapsedSeconds",
            "upstreamStatus", "degraded",
        }
    }
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
    manifest_url = os.environ.get(
        "ARGUS_PRODUCTION_RELEASE_MANIFEST_URL", DEFAULT_MANIFEST_URL)
    state_file = os.environ.get(
        "ARGUS_BUILD_IDENTITY_STATE_FILE", DEFAULT_STATE_FILE)
    decision_file = os.environ.get(
        "ARGUS_BUILD_IDENTITY_DECISION_FILE", DEFAULT_DECISION_FILE)
    timeout = min(30, max(3, int(os.environ.get(
        "ARGUS_BUILD_IDENTITY_TIMEOUT_SECONDS", "15"))))
    attempts = min(3, max(1, int(os.environ.get(
        "ARGUS_BUILD_IDENTITY_MAX_ATTEMPTS", "2"))))
    grace = min(3600, max(60, int(os.environ.get(
        "ARGUS_BUILD_TRANSITION_GRACE_SECONDS", "900"))))
    state = _load_state(state_file)
    manifest: dict[str, Any] | None = None
    manifest_error = None
    try:
        fetched = _fetch_json(
            manifest_url, timeout=timeout, attempts=attempts)
        manifest = validate_manifest(
            fetched,
            minimum_deployed_at=state.get("lastManifestDeployedAt"),
            now_iso=now_iso,
        )
    except ManifestValidationError as exc:
        manifest_error = str(exc)
    except RuntimeError:
        manifest_error = "production_manifest_unavailable"
    try:
        health = _fetch_json(
            base + "/healthz", timeout=timeout, attempts=attempts)
        backend_sha = _valid_observed_sha(
            health.get("buildSha") if isinstance(health, dict) else "")
        backend_version = str(
            health.get("backendVersion") or health.get("appVersion") or ""
        ) if isinstance(health, dict) else ""
    except RuntimeError:
        backend_sha = ""
        backend_version = ""
    decision, next_state = resolve_identity(
        manifest=manifest,
        backend_sha=backend_sha,
        backend_version=backend_version,
        state=state,
        now_iso=now_iso,
        grace_seconds=grace,
        manifest_error=manifest_error,
        static_sha=os.environ.get("ARGUS_EXPECTED_BUILD_SHA", ""),
    )
    decision["checkedAt"] = now_iso
    _atomic_json(state_file, next_state, mode=0o600, directory_mode=0o700)
    _atomic_json(decision_file, decision, mode=0o644, directory_mode=0o755)
    _emit(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
