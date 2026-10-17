#!/usr/bin/env python3
"""Resolve workflow backend identity from the production release manifest.

Repository history and ``GITHUB_SHA`` are deliberately absent from the trust
decision.  The manifest must contain a full SHA and verified production health
and readiness; the live backend SHA is observed input only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional

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


OBSERVED_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class IdentityResult:
    expectedBackendSha: Optional[str]
    actualBackendSha: Optional[str]
    expectedBackendVersion: Optional[str]
    actualBackendVersion: Optional[str]
    identitySource: str
    status: str
    mismatchReason: Optional[str]
    manifestDeploymentId: Optional[str]
    manifestRenderDeploymentId: Optional[str]
    manifestDeployedAt: Optional[str]


def resolve(
    *,
    manifest: Any,
    actual_backend_sha: str,
    actual_backend_version: str = "",
    now_iso: str | None = None,
) -> IdentityResult:
    actual = str(actual_backend_sha or "").strip().lower()
    actual_version = str(actual_backend_version or "").strip()
    if not OBSERVED_SHA_RE.fullmatch(actual):
        return IdentityResult(
            None, None, None, actual_version or None,
            "production_release_manifest", "resolver_failure",
            "actual_backend_sha_invalid", None, None, None,
        )
    try:
        trusted = validate_manifest(manifest, now_iso=now_iso)
    except ManifestValidationError as exc:
        return IdentityResult(
            None, actual, None, actual_version or None,
            "production_release_manifest", "resolver_failure",
            str(exc), None, None, None,
        )
    expected = trusted["buildSha"]
    expected_version = trusted["version"]
    if actual_version and actual_version != expected_version:
        return IdentityResult(
            expected, actual, expected_version, actual_version,
            "production_release_manifest", "genuine_mismatch",
            "actual_backend_version_not_manifest", trusted["deploymentId"],
            trusted.get("renderDeploymentId", trusted["deploymentId"]),
            trusted["deployedAt"],
        )
    if expected.startswith(actual):
        return IdentityResult(
            expected, actual, expected_version, actual_version or None,
            "production_release_manifest", "verified",
            None, trusted["deploymentId"],
            trusted.get("renderDeploymentId", trusted["deploymentId"]),
            trusted["deployedAt"],
        )
    return IdentityResult(
        expected, actual, expected_version, actual_version or None,
        "production_release_manifest", "genuine_mismatch",
        "actual_not_production_release_manifest", trusted["deploymentId"],
        trusted.get("renderDeploymentId", trusted["deploymentId"]),
        trusted["deployedAt"],
    )


def _write_github_output(
    path: pathlib.Path,
    values: Iterable[tuple[str, Any]],
) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values:
            rendered = "" if value is None else str(value)
            handle.write(f"{key}={rendered}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--actual-backend-sha", required=True)
    parser.add_argument("--actual-backend-version", default="")
    parser.add_argument("--now")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = None
    result = resolve(
        manifest=manifest,
        actual_backend_sha=args.actual_backend_sha,
        actual_backend_version=args.actual_backend_version,
        now_iso=args.now,
    )
    payload = asdict(result)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if args.github_output:
        _write_github_output(pathlib.Path(args.github_output), payload.items())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
