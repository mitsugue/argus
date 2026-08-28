#!/usr/bin/env python3
"""Bound one authenticated Remote Journal drain to a terminal result.

The publisher has already created an immutable commit and fsynced its receipt
intent before this helper runs.  A process-local backend writer may be busy,
so a 202/pending response is retryable work, not success.  This helper
re-triggers the same idempotent operation inside one wall-clock budget and
returns success only after the exact receipt is verified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
import time
import urllib.error
from typing import Any, Callable, Mapping, Optional

try:
    from scripts import workflow_http
except ImportError:  # Copied beside workflow_http.py in GitHub Actions.
    import workflow_http  # type: ignore


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OPERATION_RE = re.compile(r"^rr-[0-9a-f]{24}$")
MIN_BUDGET_SECONDS = 1
MAX_BUDGET_SECONDS = 240
REQUEST_TIMEOUT_CAP_SECONDS = 180
FINAL_STATUS_RESERVE_SECONDS = 15
RETRY_DELAYS_SECONDS = (1, 2, 4, 8, 15, 30)


class DrainError(RuntimeError):
    """A scalar-only terminal classification safe for workflow logs."""


def _full_sha(value: object, *, name: str) -> str:
    candidate = str(value or "").strip().lower()
    if not FULL_SHA_RE.fullmatch(candidate):
        raise DrainError(name + "_invalid")
    return candidate


def _operation_id(value: object) -> str:
    candidate = str(value or "").strip().lower()
    if not OPERATION_RE.fullmatch(candidate):
        raise DrainError("operation_id_invalid")
    return candidate


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool):
        raise DrainError(name + "_invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DrainError(name + "_invalid") from exc
    if parsed <= 0:
        raise DrainError(name + "_invalid")
    return parsed


def _iso_timestamp(value: object, *, name: str) -> str:
    candidate = str(value or "")
    try:
        parsed = dt.datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DrainError(name + "_invalid") from exc
    if parsed.tzinfo is None:
        raise DrainError(name + "_invalid")
    return candidate


def _decode_response(code: int, raw: str) -> Mapping[str, Any]:
    try:
        body = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DrainError("drain_response_invalid_json") from exc
    if not isinstance(body, Mapping):
        raise DrainError("drain_response_invalid_shape")
    if not 200 <= int(code) < 300:
        raise DrainError("drain_http_" + str(int(code)))
    if body.get("ok") is False or body.get("error") not in (None, "", False):
        raise DrainError("drain_business_failure")
    return body


def _validate_identity(
        body: Mapping[str, Any], *, operation_id: str,
        remote_commit_sha: str, target_wal_sequence: int) -> str:
    if str(body.get("operationId") or "") != operation_id:
        raise DrainError("drain_operation_mismatch")
    if str(body.get("remoteCommitSha") or "").lower() != remote_commit_sha:
        raise DrainError("drain_commit_mismatch")
    if _positive_int(body.get("targetWalSequence"),
                     name="drain_target_wal") != target_wal_sequence:
        raise DrainError("drain_target_wal_mismatch")
    state = str(body.get("durabilityState") or "").lower()
    if state not in ("pending", "verified"):
        raise DrainError("drain_state_invalid")
    age = body.get("ageSeconds")
    if isinstance(age, bool) or not isinstance(age, int) or age < 0:
        raise DrainError("drain_age_invalid")
    return state


def _verified_result(
        body: Mapping[str, Any], *, operation_id: str,
        remote_commit_sha: str, target_wal_sequence: int,
        attempts: int, contention_count: int, elapsed_seconds: float,
        budget_seconds: int) -> dict[str, Any]:
    state = _validate_identity(
        body, operation_id=operation_id,
        remote_commit_sha=remote_commit_sha,
        target_wal_sequence=target_wal_sequence)
    if state != "verified" or body.get("readBackVerified") is not True:
        raise DrainError("receipt_not_verified")
    verified_sequence = _positive_int(
        body.get("verifiedWalSequence"), name="verified_wal_sequence")
    verified_commit = _full_sha(
        body.get("verifiedByRemoteCommitSha"), name="verified_commit_sha")
    if verified_commit == remote_commit_sha:
        if verified_sequence != target_wal_sequence:
            raise DrainError("verified_wal_sequence_mismatch")
    elif verified_sequence < target_wal_sequence:
        raise DrainError("verified_wal_sequence_regression")
    verified_at = _iso_timestamp(body.get("verifiedAt"), name="verified_at")
    return {
        "status": "verified",
        "operationId": operation_id,
        "remoteCommitSha": remote_commit_sha,
        "verifiedByRemoteCommitSha": verified_commit,
        "targetWalSequence": target_wal_sequence,
        "verifiedWalSequence": verified_sequence,
        "readBackVerified": True,
        "verifiedAt": verified_at,
        "ageSeconds": body.get("ageSeconds"),
        "attempts": attempts,
        "lockContentionCount": contention_count,
        "elapsedSeconds": round(elapsed_seconds, 3),
        "budgetSeconds": budget_seconds,
    }


def drain_until_verified(
        *, base_url: str, operation_id: str, backend_build_sha: str,
        remote_commit_sha: str, target_wal_sequence: int, token: str,
        budget_seconds: int = MAX_BUDGET_SECONDS,
        request_json: Callable[..., tuple[int, str]] =
        workflow_http.request_json,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Retry one exact drain and fail visibly unless it becomes verified."""
    operation = _operation_id(operation_id)
    build = _full_sha(backend_build_sha, name="backend_build_sha")
    commit = _full_sha(remote_commit_sha, name="remote_commit_sha")
    target = _positive_int(target_wal_sequence, name="target_wal_sequence")
    if not token:
        raise DrainError("admin_token_unavailable")
    try:
        budget = int(budget_seconds)
    except (TypeError, ValueError) as exc:
        raise DrainError("drain_budget_invalid") from exc
    if not MIN_BUDGET_SECONDS <= budget <= MAX_BUDGET_SECONDS:
        raise DrainError("drain_budget_invalid")

    base = str(base_url or "").rstrip("/")
    if not base.startswith("https://"):
        raise DrainError("backend_url_invalid")
    trigger_url = base + "/api/argus/admin/remote-journal/trigger-drain"
    status_url = base + "/api/argus/admin/remote-journal/receipts/" + operation
    headers = {"X-ARGUS-ADMIN-TOKEN": token,
               "Content-Type": "application/json"}
    payload = json.dumps({
        "operationId": operation,
        "backendBuildSha": build,
        "triggerClass": "publisher_receipt",
    }, separators=(",", ":"))
    started = monotonic()
    attempts = 0
    contention_count = 0
    last_body: Optional[Mapping[str, Any]] = None
    status_only = False

    while monotonic() - started < budget:
        elapsed = monotonic() - started
        remaining = budget - elapsed
        if remaining <= 0:
            break
        if status_only or remaining <= FINAL_STATUS_RESERVE_SECONDS:
            url, method, data = status_url, "GET", None
            timeout = max(1, min(10, int(remaining)))
        else:
            url, method, data = trigger_url, "POST", payload
            timeout = max(1, min(
                REQUEST_TIMEOUT_CAP_SECONDS,
                int(remaining - FINAL_STATUS_RESERVE_SECONDS)))
            attempts += 1
        try:
            code, raw = request_json(
                url=url, method=method, timeout=timeout,
                headers=headers, data=data)
            body = _decode_response(code, raw)
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError):
            # The backend may still be completing a request after the client
            # timeout.  Never submit a concurrent duplicate; reserve the rest
            # of the budget for idempotent status observation.
            status_only = True
            continue
        last_body = body
        state = _validate_identity(
            body, operation_id=operation, remote_commit_sha=commit,
            target_wal_sequence=target)
        if state == "verified":
            return _verified_result(
                body, operation_id=operation,
                remote_commit_sha=commit, target_wal_sequence=target,
                attempts=attempts, contention_count=contention_count,
                elapsed_seconds=monotonic() - started,
                budget_seconds=budget)
        if body.get("drainStatus") == "writer_lock_contended":
            contention_count += 1
        if status_only:
            delay = 1
        else:
            delay = RETRY_DELAYS_SECONDS[min(
                max(0, attempts - 1), len(RETRY_DELAYS_SECONDS) - 1)]
        remaining = budget - (monotonic() - started)
        if remaining <= 0:
            break
        sleep(min(float(delay), max(0.0, remaining)))

    detail = "receipt_not_verified_within_budget"
    if last_body is not None and last_body.get("drainStatus"):
        detail += ":" + str(last_body.get("drainStatus"))[:80]
    raise DrainError(detail)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--backend-build-sha", required=True)
    parser.add_argument("--remote-commit-sha", required=True)
    parser.add_argument("--target-wal-sequence", required=True, type=int)
    parser.add_argument("--token-env", default="ARGUS_ADMIN_TOKEN")
    parser.add_argument("--budget-seconds", type=int,
                        default=MAX_BUDGET_SECONDS)
    args = parser.parse_args(argv)
    try:
        result = drain_until_verified(
            base_url=args.base_url,
            operation_id=args.operation_id,
            backend_build_sha=args.backend_build_sha,
            remote_commit_sha=args.remote_commit_sha,
            target_wal_sequence=args.target_wal_sequence,
            token=os.environ.get(args.token_env, ""),
            budget_seconds=args.budget_seconds)
    except DrainError as exc:
        print(json.dumps({
            "status": "failed",
            "errorClass": str(exc)[:120],
            "budgetSeconds": args.budget_seconds,
        }, separators=(",", ":")))
        print(f"[remote-receipt-drain] name={args.name} outcome=failure "
              f"reason={str(exc)[:120]}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    print(f"[remote-receipt-drain] name={args.name} outcome=verified "
          f"attempts={result['attempts']} "
          f"contentions={result['lockContentionCount']} "
          f"elapsed={result['elapsedSeconds']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
