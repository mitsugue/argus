#!/usr/bin/env python3
"""Create and validate the external ARGUS production release manifest.

The manifest is the trusted declaration of the backend release that completed
both production health and readiness verification.  It is intentionally kept
outside the backend process and never derives trust from a moving ``main`` ref.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
from typing import Any, Mapping


SCHEMA = "argus-production-release-manifest-v1"
SERVICE = "argus-backend"
ENVIRONMENT = "production"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
RENDER_DEPLOYMENT_ID_RE = re.compile(r"^dep-[0-9a-z]+$")
FORBIDDEN_KEY_PARTS = (
    "token", "secret", "password", "passphrase", "credential",
    "authorization", "apikey", "api_key", "hmac",
)


class ManifestValidationError(ValueError):
    """A public-safe, stable manifest validation failure."""


def _epoch(value: object) -> float:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError("deployed_at_invalid") from exc
    if parsed.tzinfo is None:
        raise ManifestValidationError("deployed_at_timezone_missing")
    return parsed.timestamp()


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return True
            if _contains_secret_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


def validate_manifest(
    value: Any,
    *,
    minimum_deployed_at: str | None = None,
    now_iso: str | None = None,
    max_future_skew_seconds: int = 300,
) -> dict[str, Any]:
    """Validate and normalize a production manifest.

    ``minimum_deployed_at`` is the last accepted deployment timestamp.  It
    prevents an eventually-consistent or cached response from rolling trusted
    identity back.  A legitimate rollback has a newer deployment timestamp and
    an older build SHA, so it remains valid.
    """
    if not isinstance(value, Mapping):
        raise ManifestValidationError("manifest_not_object")
    if _contains_secret_key(value):
        raise ManifestValidationError("manifest_contains_secret_key")
    required = {
        "schema", "service", "environment", "buildSha", "version",
        "deployedAt", "deploymentId", "verifiedHealth", "verifiedReady",
    }
    if not required.issubset(value):
        raise ManifestValidationError("manifest_required_field_missing")
    if value.get("schema") != SCHEMA:
        raise ManifestValidationError("manifest_schema_invalid")
    if value.get("service") != SERVICE:
        raise ManifestValidationError("manifest_service_invalid")
    if value.get("environment") != ENVIRONMENT:
        raise ManifestValidationError("manifest_environment_invalid")
    build_sha = str(value.get("buildSha") or "").strip().lower()
    if not SHA_RE.fullmatch(build_sha):
        raise ManifestValidationError("manifest_full_sha_required")
    version = str(value.get("version") or "").strip()
    if not VERSION_RE.fullmatch(version):
        raise ManifestValidationError("manifest_version_invalid")
    deployment_id = str(value.get("deploymentId") or "").strip()
    if not RENDER_DEPLOYMENT_ID_RE.fullmatch(deployment_id):
        raise ManifestValidationError("manifest_deployment_id_invalid")
    render_deployment_id = (
        str(value.get("renderDeploymentId") or "").strip()
        if "renderDeploymentId" in value else deployment_id
    )
    if not RENDER_DEPLOYMENT_ID_RE.fullmatch(render_deployment_id):
        raise ManifestValidationError("manifest_render_deployment_id_invalid")
    if render_deployment_id != deployment_id:
        raise ManifestValidationError("manifest_deployment_identity_mismatch")
    if value.get("verifiedHealth") is not True:
        raise ManifestValidationError("manifest_health_not_verified")
    if value.get("verifiedReady") is not True:
        raise ManifestValidationError("manifest_ready_not_verified")
    deployed_at = str(value.get("deployedAt") or "")
    deployed_epoch = _epoch(deployed_at)
    if minimum_deployed_at and deployed_epoch < _epoch(minimum_deployed_at):
        raise ManifestValidationError("manifest_stale")
    if now_iso and deployed_epoch > (
            _epoch(now_iso) + max(0, int(max_future_skew_seconds))):
        raise ManifestValidationError("manifest_deployed_at_future")
    normalized = {
        "schema": SCHEMA,
        "service": SERVICE,
        "environment": ENVIRONMENT,
        "buildSha": build_sha,
        "version": version,
        "deployedAt": deployed_at,
        "deploymentId": deployment_id,
        "verifiedHealth": True,
        "verifiedReady": True,
    }
    if "renderDeploymentId" in value:
        normalized["renderDeploymentId"] = render_deployment_id
    return normalized


def _sha_matches(full_sha: str, observed: object) -> bool:
    """Require the exact two full SHAs; a prefix is not release evidence."""
    observed_sha = str(observed or "").strip().lower()
    return bool(
        SHA_RE.fullmatch(full_sha)
        and SHA_RE.fullmatch(observed_sha)
        and full_sha == observed_sha
    )


def select_deployed_at(
    *,
    existing: Any,
    build_sha: str,
    version: str,
    deployment_id: str,
    fallback: str,
) -> str:
    """Preserve identity time only for an already-published exact identity."""
    try:
        trusted = validate_manifest(existing)
    except ManifestValidationError:
        return fallback
    same_identity = (
        trusted["buildSha"] == str(build_sha).strip().lower()
        and trusted["version"] == str(version)
        and trusted["deploymentId"] == str(deployment_id).strip()
    )
    return trusted["deployedAt"] if same_identity else fallback


def create_manifest(
    *,
    build_sha: str,
    version: str,
    deployed_at: str,
    deployment_id: str,
    health: Any,
    ready: Any,
) -> dict[str, Any]:
    """Create a manifest only from matching production health and readiness."""
    build_sha = str(build_sha or "").strip().lower()
    if not isinstance(health, Mapping) or health.get("status") != "ok":
        raise ManifestValidationError("health_verification_failed")
    if not _sha_matches(build_sha, health.get("buildSha")):
        raise ManifestValidationError("health_build_sha_mismatch")
    health_version = str(
        health.get("backendVersion") or health.get("appVersion") or "")
    if health_version and health_version != str(version):
        raise ManifestValidationError("health_version_mismatch")
    if not isinstance(ready, Mapping) or ready.get("ready") is not True:
        raise ManifestValidationError("ready_verification_failed")
    ready_sha = ready.get("buildSha")
    if ready_sha and not _sha_matches(build_sha, ready_sha):
        raise ManifestValidationError("ready_build_sha_mismatch")
    return validate_manifest({
        "schema": SCHEMA,
        "service": SERVICE,
        "environment": ENVIRONMENT,
        "buildSha": build_sha,
        "version": str(version),
        "deployedAt": deployed_at,
        "deploymentId": deployment_id,
        "renderDeploymentId": deployment_id,
        "verifiedHealth": True,
        "verifiedReady": True,
    })


def _read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("manifest", type=pathlib.Path)
    check.add_argument("--minimum-deployed-at")
    check.add_argument("--now")
    create = sub.add_parser("create")
    create.add_argument("--build-sha", required=True)
    create.add_argument("--version", required=True)
    create.add_argument("--deployed-at", required=True)
    create.add_argument("--deployment-id", required=True)
    create.add_argument("--health", required=True, type=pathlib.Path)
    create.add_argument("--ready", required=True, type=pathlib.Path)
    create.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    if args.command == "validate":
        result = validate_manifest(
            _read_json(args.manifest),
            minimum_deployed_at=args.minimum_deployed_at,
            now_iso=args.now,
        )
    else:
        result = create_manifest(
            build_sha=args.build_sha,
            version=args.version,
            deployed_at=args.deployed_at,
            deployment_id=args.deployment_id,
            health=_read_json(args.health),
            ready=_read_json(args.ready),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
