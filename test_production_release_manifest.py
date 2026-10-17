import pytest

from scripts.production_release_manifest import (
    ManifestValidationError,
    create_manifest,
    select_deployed_at,
    validate_manifest,
)


SHA = "c" * 40


def manifest(**overrides):
    value = {
        "schema": "argus-production-release-manifest-v1",
        "service": "argus-backend",
        "environment": "production",
        "buildSha": SHA,
        "version": "13.3.6",
        "deployedAt": "2026-07-31T00:00:00Z",
        "deploymentId": "dep-abc123",
        "verifiedHealth": True,
        "verifiedReady": True,
    }
    value.update(overrides)
    return value


def test_create_requires_matching_health_ready_and_version():
    value = create_manifest(
        build_sha=SHA,
        version="13.3.6",
        deployed_at="2026-07-31T00:00:00Z",
        deployment_id="dep-abc123",
        health={
            "status": "ok",
            "buildSha": SHA,
            "backendVersion": "13.3.6",
        },
        ready={"ready": True, "buildSha": SHA},
    )
    assert value == manifest(renderDeploymentId="dep-abc123")


@pytest.mark.parametrize(
    ("patch", "error"),
    [
        ({"buildSha": SHA[:7]}, "manifest_full_sha_required"),
        ({"schema": "wrong"}, "manifest_schema_invalid"),
        ({"service": "wrong"}, "manifest_service_invalid"),
        ({"environment": "staging"}, "manifest_environment_invalid"),
        ({"verifiedHealth": False}, "manifest_health_not_verified"),
        ({"verifiedReady": False}, "manifest_ready_not_verified"),
        ({"deployedAt": "bad"}, "deployed_at_invalid"),
        ({"deploymentId": "github-main-31283850019"},
         "manifest_deployment_id_invalid"),
        ({"renderDeploymentId": "dep-other1"},
         "manifest_deployment_identity_mismatch"),
        ({"renderDeploymentId": ""},
         "manifest_render_deployment_id_invalid"),
    ],
)
def test_invalid_manifest_fails_closed(patch, error):
    with pytest.raises(ManifestValidationError, match=error):
        validate_manifest(manifest(**patch))


def test_stale_cached_manifest_is_rejected_but_newer_rollback_is_valid():
    with pytest.raises(ManifestValidationError, match="manifest_stale"):
        validate_manifest(
            manifest(deployedAt="2026-07-30T00:00:00Z"),
            minimum_deployed_at="2026-07-31T00:00:00Z",
        )
    rollback = validate_manifest(
        manifest(
            buildSha="d" * 40,
            deployedAt="2026-07-31T01:00:00Z",
        ),
        minimum_deployed_at="2026-07-31T00:00:00Z",
    )
    assert rollback["buildSha"] == "d" * 40


def test_future_manifest_and_secret_shaped_fields_are_rejected():
    with pytest.raises(
        ManifestValidationError, match="manifest_deployed_at_future"
    ):
        validate_manifest(
            manifest(deployedAt="2026-07-31T02:00:00Z"),
            now_iso="2026-07-31T00:00:00Z",
        )
    with pytest.raises(
        ManifestValidationError, match="manifest_contains_secret_key"
    ):
        validate_manifest(manifest(apiToken="do-not-emit"))


def test_public_manifest_contains_no_secret_material():
    rendered = str(validate_manifest(manifest())).lower()
    for word in ("token", "secret", "password", "credential"):
        assert word not in rendered


def test_repeated_exact_identity_is_idempotent_but_new_dep_is_not():
    existing = manifest()
    assert select_deployed_at(
        existing=existing,
        build_sha=SHA,
        version="13.3.6",
        deployment_id="dep-abc123",
        fallback="2026-07-31T01:00:00Z",
    ) == "2026-07-31T00:00:00Z"
    assert select_deployed_at(
        existing=existing,
        build_sha=SHA,
        version="13.3.6",
        deployment_id="dep-new123",
        fallback="2026-07-31T01:00:00Z",
    ) == "2026-07-31T01:00:00Z"


@pytest.mark.parametrize(
    ("health_sha", "ready_sha", "error"),
    [
        (SHA[:7], SHA, "health_build_sha_mismatch"),
        (SHA, SHA[:7], "ready_build_sha_mismatch"),
        ("d" * 40, SHA, "health_build_sha_mismatch"),
        (SHA, "d" * 40, "ready_build_sha_mismatch"),
    ],
)
def test_manifest_creation_requires_exact_full_runtime_sha(
    health_sha, ready_sha, error
):
    with pytest.raises(ManifestValidationError, match=error):
        create_manifest(
            build_sha=SHA,
            version="13.3.6",
            deployed_at="2026-07-31T00:00:00Z",
            deployment_id="dep-abc123",
            health={
                "status": "ok",
                "buildSha": health_sha,
                "backendVersion": "13.3.6",
            },
            ready={"ready": True, "buildSha": ready_sha},
        )
