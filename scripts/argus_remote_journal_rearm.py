#!/usr/bin/env python3
"""Bounded EC2 natural re-arm for Remote Journal publication.

The process reads only bounded public-safe metadata and asks Watchtower
workflow to run its natural durability policy when a verified local checkpoint
is ahead of the verified remote WAL cursor.  It never fetches a memory
snapshot, calls a backend write endpoint, or waits for workflow completion.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping


DEFAULT_BACKEND_URL = "https://argus-backend-3j2m.onrender.com"
DISPATCH_URL = (
    "https://api.github.com/repos/mitsugue/argus/actions/workflows/"
    "caos-watchtower.yml/dispatches"
)
MAX_PUBLIC_RESPONSE_BYTES = 256 * 1024
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OBSERVED_SHA_RE = re.compile(r"^(?:[0-9a-f]{7}|[0-9a-f]{40})$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class RearmError(RuntimeError):
    """A fail-closed, scalar-only re-arm error."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the GitHub Authorization header to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _emit(**fields: object) -> None:
    allowed = {
        "status", "reason", "errorClass", "localIncludedWalSequence",
        "remoteVerifiedWalSequence", "walGap", "publicAttempts",
        "dispatchAttempts", "httpStatus",
    }
    safe = {key: value for key, value in fields.items() if key in allowed}
    safe.update({
        "schemaVersion": "argus-remote-journal-rearm-v1",
        "component": "argus-remote-journal-rearm",
    })
    print(json.dumps(safe, sort_keys=True), flush=True)


def _integer(value: object, *, name: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RearmError(name + "_invalid")
    if value < (1 if positive else 0):
        raise RearmError(name + "_invalid")
    return value


def _full_sha(value: object, *, name: str) -> str:
    candidate = str(value or "").strip().lower()
    if not FULL_SHA_RE.fullmatch(candidate):
        raise RearmError(name + "_invalid")
    return candidate


def _observed_sha(value: object, *, name: str) -> str:
    candidate = str(value or "").strip().lower()
    if not OBSERVED_SHA_RE.fullmatch(candidate):
        raise RearmError(name + "_invalid")
    return candidate


def evaluate_truth(
    health: Mapping[str, Any],
    ready: Mapping[str, Any],
    data_quality: Mapping[str, Any],
) -> dict[str, object]:
    """Return the scalar dispatch decision from verified public metadata."""
    if not all(isinstance(value, Mapping)
               for value in (health, ready, data_quality)):
        raise RearmError("public_truth_invalid")
    if health.get("status") != "ok":
        raise RearmError("health_not_ok")
    if ready.get("ready") is not True:
        raise RearmError("backend_not_ready")

    health_sha = _full_sha(health.get("buildSha"), name="health_build_sha")
    ready_sha = _full_sha(ready.get("buildSha"), name="ready_build_sha")
    if health_sha != ready_sha:
        raise RearmError("health_ready_identity_mismatch")
    health_version = str(health.get("backendVersion") or "").strip()
    ready_version = str(ready.get("appVersion") or "").strip()
    if not SEMVER_RE.fullmatch(health_version) or \
            ready_version != health_version:
        raise RearmError("health_ready_version_mismatch")

    if data_quality.get("schemaVersion") != "data-quality-v1":
        raise RearmError("data_quality_schema_invalid")
    build = data_quality.get("buildIdentity")
    if not isinstance(build, Mapping):
        raise RearmError("data_quality_identity_missing")
    projected_sha = _observed_sha(
        build.get("backendBuildSha") or build.get("buildSha"),
        name="data_quality_build_sha")
    data_quality_version = str(
        build.get("backendVersion") or build.get("appVersion") or ""
    ).strip()
    if not health_sha.startswith(projected_sha) or \
            str(build.get("appVersion") or "").strip() != health_version or \
            data_quality_version != health_version:
        raise RearmError("data_quality_identity_mismatch")

    durable = data_quality.get("durableState")
    if not isinstance(durable, Mapping) or \
            durable.get("integrityStatus") != "ok":
        raise RearmError("durable_integrity_invalid")
    for key in ("journalCorrupt", "missionWalCorrupt"):
        if _integer(durable.get(key), name=key) != 0:
            raise RearmError("durable_corruption_detected")
    checkpoint = durable.get("lastCheckpoint")
    if not isinstance(checkpoint, Mapping) or \
            checkpoint.get("verified") is not True or \
            checkpoint.get("readBackVerified") is not True:
        raise RearmError("local_checkpoint_unverified")
    local_wal = _integer(
        checkpoint.get("includedWalSequence"),
        name="local_checkpoint_wal", positive=True)

    remote = data_quality.get("remoteJournalVerification")
    if not isinstance(remote, Mapping) or \
            remote.get("readBackVerified") is not True or \
            remote.get("walReadBackVerified") is not True or \
            remote.get("remoteDurabilityState") != "verified":
        raise RearmError("remote_readback_unverified")
    remote_applied = _integer(
        remote.get("remoteWalAppliedSequence"),
        name="remote_applied_wal", positive=True)
    remote_verified = _integer(
        remote.get("verifiedWalSequence"),
        name="remote_verified_wal", positive=True)
    if remote_applied != remote_verified:
        raise RearmError("remote_wal_identity_mismatch")
    if any(remote.get(key) not in (None, "") for key in (
            "errorClass", "walErrorClass", "receiptErrorClass")):
        raise RearmError("remote_verification_error_present")

    scalar = {
        "localIncludedWalSequence": local_wal,
        "remoteVerifiedWalSequence": remote_verified,
        "walGap": max(0, local_wal - remote_verified),
    }
    if local_wal < remote_verified:
        raise RearmError("local_wal_regressed")
    if local_wal == remote_verified:
        return {"action": "skip", "reason": "remote_caught_up", **scalar}
    return {"action": "dispatch", "reason": "verified_wal_gap", **scalar}


def _request_json(
    url: str,
    *,
    timeout: int,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "argus-remote-journal-rearm/1",
        },
    )
    with opener(request, timeout=timeout) as response:
        if int(response.status) != 200:
            raise RearmError("public_http_status")
        raw = response.read(MAX_PUBLIC_RESPONSE_BYTES + 1)
        if len(raw) > MAX_PUBLIC_RESPONSE_BYTES:
            raise RearmError("public_response_oversized")
        value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise RearmError("public_json_invalid")
    return value


def fetch_public_truth(
    base: str,
    *,
    timeout: int,
    attempts: int,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], int]:
    """Fetch one complete truth set with at most two non-polling attempts."""
    bounded_attempts = min(2, max(1, attempts))
    for attempt in range(1, bounded_attempts + 1):
        try:
            health = _request_json(
                base + "/healthz", timeout=timeout, opener=opener)
            ready = _request_json(
                base + "/readyz", timeout=timeout, opener=opener)
            quality = _request_json(
                base + "/api/argus/data-quality",
                timeout=timeout, opener=opener)
            return health, ready, quality, attempt
        except (
            RearmError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            if attempt == bounded_attempts:
                break
    raise RearmError("public_truth_unavailable")


def dispatch_natural_rearm(
    token: str,
    *,
    timeout: int,
    opener: Callable[..., Any] | None = None,
) -> int:
    """Issue exactly one asynchronous dispatch and never poll its status."""
    body = json.dumps({
        "ref": "main",
        "inputs": {"remoteJournalRearm": "true"},
    }, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        DISPATCH_URL,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "argus-remote-journal-rearm/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    safe_opener = opener or urllib.request.build_opener(_NoRedirect()).open
    with safe_opener(request, timeout=timeout) as response:
        status = int(response.status)
    if status != 204:
        raise RearmError("workflow_dispatch_rejected")
    return status


def main() -> int:
    try:
        try:
            timeout = min(6, max(3, int(os.environ.get(
            "ARGUS_REMOTE_JOURNAL_REARM_TIMEOUT_SECONDS", "6"))))
            attempts = min(2, max(1, int(os.environ.get(
                "ARGUS_REMOTE_JOURNAL_REARM_MAX_ATTEMPTS", "2"))))
        except ValueError:
            raise RearmError("rearm_configuration_invalid") from None
        base = os.environ.get(
            "ARGUS_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")
        health, ready, quality, public_attempts = fetch_public_truth(
            base, timeout=timeout, attempts=attempts)
        decision = evaluate_truth(health, ready, quality)
        scalar = {key: value for key, value in decision.items()
                  if key != "action"}
        if decision["action"] == "skip":
            _emit(status="expected_skip", publicAttempts=public_attempts,
                  dispatchAttempts=0, **scalar)
            return 0
        token = os.environ.get("ARGUS_REMOTE_JOURNAL_REARM_PAT", "").strip()
        if not token:
            _emit(status="failure", errorClass="missing_workflow_pat",
                  publicAttempts=public_attempts, dispatchAttempts=0,
                  **scalar)
            return 1
        status = dispatch_natural_rearm(token, timeout=timeout)
        _emit(status="dispatched", httpStatus=status,
              publicAttempts=public_attempts, dispatchAttempts=1, **scalar)
        return 0
    except urllib.error.HTTPError as exc:
        _emit(status="failure", errorClass="workflow_dispatch_http_error",
              httpStatus=int(exc.code), dispatchAttempts=1)
        return 1
    except (urllib.error.URLError, TimeoutError):
        _emit(status="failure", errorClass="workflow_dispatch_unavailable",
              dispatchAttempts=1)
        return 1
    except RearmError as exc:
        _emit(status="failure", errorClass=str(exc)[:80])
        return 1


if __name__ == "__main__":
    sys.exit(main())
