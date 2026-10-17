#!/usr/bin/env python3
"""Resolve the exact live Render deployment for a backend build.

This module is read-only with respect to Render.  It lists deployments for a
single service, matches the full Git commit SHA, and returns a ``dep-*`` ID
only after the matching deployment is unambiguously live.  The optional
expected deployment ID is the owner-controlled reconciliation contract used
for same-SHA configuration deployments.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Sequence


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RENDER_DEPLOYMENT_ID_RE = re.compile(r"^dep-[0-9a-z]+$")
LIVE_STATUS = "live"
PENDING_STATUSES = {
    "created", "queued", "build_in_progress", "update_in_progress",
    "pre_deploy_in_progress",
}
FAILED_STATUSES = {
    "build_failed", "update_failed", "pre_deploy_failed", "canceled",
}


class DeploymentResolutionError(RuntimeError):
    """Stable fail-closed Render deployment resolution error."""


@dataclass(frozen=True)
class ResolvedDeployment:
    renderDeploymentId: str
    targetSha: str
    status: str
    trigger: str | None
    createdAt: str | None
    startedAt: str | None
    finishedAt: str | None


def _deploy_rows(payload: Any) -> list[Mapping[str, Any]]:
    """Normalize the Render list-deploys response without guessing fields."""
    if not isinstance(payload, Sequence) or isinstance(
            payload, (str, bytes, bytearray)):
        raise DeploymentResolutionError("render_deploy_list_invalid")
    rows: list[Mapping[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise DeploymentResolutionError("render_deploy_row_invalid")
        deploy = item.get("deploy")
        if not isinstance(deploy, Mapping):
            raise DeploymentResolutionError("render_deploy_row_missing")
        rows.append(deploy)
    return rows


def _commit_sha(deploy: Mapping[str, Any]) -> str:
    commit = deploy.get("commit")
    if not isinstance(commit, Mapping):
        return ""
    return str(commit.get("id") or "").strip().lower()


def _validate_target(target_sha: str) -> str:
    target = str(target_sha or "").strip().lower()
    if not FULL_SHA_RE.fullmatch(target):
        raise DeploymentResolutionError("target_full_sha_required")
    return target


def _validate_expected_id(expected_deployment_id: str | None) -> str:
    expected = str(expected_deployment_id or "").strip()
    if expected and not RENDER_DEPLOYMENT_ID_RE.fullmatch(expected):
        raise DeploymentResolutionError("expected_render_deployment_id_invalid")
    return expected


def resolve_deployment(
    payload: Any,
    *,
    target_sha: str,
    expected_deployment_id: str | None = None,
) -> ResolvedDeployment:
    """Resolve one live deployment or return a stable pending/failure class."""
    target = _validate_target(target_sha)
    expected = _validate_expected_id(expected_deployment_id)
    matching = [row for row in _deploy_rows(payload)
                if _commit_sha(row) == target]
    if expected:
        matching = [row for row in matching
                    if str(row.get("id") or "") == expected]
        if not matching:
            raise DeploymentResolutionError(
                "expected_deployment_not_found_for_target_sha")
    if not matching:
        raise DeploymentResolutionError("matching_deployment_not_found")

    live = [row for row in matching if row.get("status") == LIVE_STATUS]
    pending = [row for row in matching if row.get("status") in PENDING_STATUSES]
    failed = [row for row in matching if row.get("status") in FAILED_STATUSES]
    if len(live) > 1:
        raise DeploymentResolutionError("matching_deployment_ambiguous")
    if live:
        row = live[0]
        deployment_id = str(row.get("id") or "")
        if not RENDER_DEPLOYMENT_ID_RE.fullmatch(deployment_id):
            raise DeploymentResolutionError("render_deployment_id_invalid")
        return ResolvedDeployment(
            renderDeploymentId=deployment_id,
            targetSha=target,
            status=LIVE_STATUS,
            trigger=(str(row.get("trigger")) if row.get("trigger") else None),
            createdAt=(str(row.get("createdAt"))
                       if row.get("createdAt") else None),
            startedAt=(str(row.get("startedAt"))
                       if row.get("startedAt") else None),
            finishedAt=(str(row.get("finishedAt"))
                        if row.get("finishedAt") else None),
        )
    if failed:
        raise DeploymentResolutionError("matching_deployment_failed")
    if pending:
        raise DeploymentResolutionError("matching_deployment_pending")
    raise DeploymentResolutionError("matching_deployment_not_live")


def wait_for_deployment(
    fetch_deploys: Callable[[], Any],
    *,
    target_sha: str,
    expected_deployment_id: str | None = None,
    timeout_seconds: int = 1200,
    poll_seconds: int = 15,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ResolvedDeployment:
    """Bounded poll; only not-created/building states are retryable."""
    deadline = monotonic() + max(0, int(timeout_seconds))
    retryable = {
        "matching_deployment_not_found",
        "expected_deployment_not_found_for_target_sha",
        "matching_deployment_pending",
    }
    last_error = "matching_deployment_not_found"
    while True:
        try:
            return resolve_deployment(
                fetch_deploys(),
                target_sha=target_sha,
                expected_deployment_id=expected_deployment_id,
            )
        except DeploymentResolutionError as exc:
            last_error = str(exc)
            retryable_api = last_error.startswith(
                "render_api_retryable_status_") or last_error.startswith(
                    "render_api_unavailable:")
            if last_error not in retryable and not retryable_api:
                raise
        if monotonic() >= deadline:
            raise DeploymentResolutionError(
                "render_deployment_resolution_timeout:" + last_error)
        sleep(max(0.0, float(poll_seconds)))


def _render_fetcher(*, service_id: str, api_key: str) -> Callable[[], Any]:
    service = str(service_id or "").strip()
    if not re.fullmatch(r"srv-[0-9a-z]+", service):
        raise DeploymentResolutionError("render_service_id_invalid")
    if not api_key:
        raise DeploymentResolutionError("render_api_key_missing")
    url = (
        "https://api.render.com/v1/services/"
        + urllib.parse.quote(service, safe="")
        + "/deploys?limit=100"
    )

    def fetch() -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + api_key,
                "User-Agent": "argus-render-deployment-identity/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if int(response.status) != 200:
                    raise DeploymentResolutionError(
                        "render_api_status_" + str(response.status))
                return json.loads(response.read().decode("utf-8"))
        except DeploymentResolutionError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                error = "render_api_unauthorized"
            elif exc.code == 429 or 500 <= exc.code <= 599:
                error = "render_api_retryable_status_" + str(exc.code)
            else:
                error = "render_api_status_" + str(exc.code)
            raise DeploymentResolutionError(error) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                UnicodeDecodeError) as exc:
            raise DeploymentResolutionError(
                "render_api_unavailable:" + type(exc).__name__) from exc

    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--expected-deployment-id", default="")
    parser.add_argument("--api-key-env", default="RENDER_API_KEY")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    resolved = wait_for_deployment(
        _render_fetcher(
            service_id=args.service_id,
            api_key=os.environ.get(args.api_key_env, ""),
        ),
        target_sha=args.target_sha,
        expected_deployment_id=args.expected_deployment_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    payload = asdict(resolved)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
