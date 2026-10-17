from scripts.resolve_backend_identity import resolve


SHA = "a" * 40


def manifest(**overrides):
    value = {
        "schema": "argus-production-release-manifest-v1",
        "service": "argus-backend",
        "environment": "production",
        "buildSha": SHA,
        "version": "13.3.6",
        "deployedAt": "2026-07-31T00:00:00Z",
        "deploymentId": "dep-123abc",
        "verifiedHealth": True,
        "verifiedReady": True,
    }
    value.update(overrides)
    return value


def test_manifest_is_authoritative_for_workflow_identity():
    result = resolve(
        manifest=manifest(),
        actual_backend_sha=SHA[:7],
        now_iso="2026-07-31T00:01:00Z",
    )
    assert result.status == "verified"
    assert result.expectedBackendSha == SHA
    assert result.identitySource == "production_release_manifest"
    assert result.manifestDeploymentId == "dep-123abc"
    assert result.manifestRenderDeploymentId == "dep-123abc"


def test_consumer_rejects_legacy_or_disagreeing_render_identity():
    legacy = resolve(
        manifest=manifest(deploymentId="github-main-123"),
        actual_backend_sha=SHA[:7],
    )
    mismatch = resolve(
        manifest=manifest(renderDeploymentId="dep-other1"),
        actual_backend_sha=SHA[:7],
    )
    assert legacy.status == "resolver_failure"
    assert legacy.mismatchReason == "manifest_deployment_id_invalid"
    assert mismatch.status == "resolver_failure"
    assert mismatch.mismatchReason == "manifest_deployment_identity_mismatch"


def test_frontend_main_has_no_input_to_resolver():
    result = resolve(
        manifest=manifest(),
        actual_backend_sha=SHA[:7],
    )
    assert result.status == "verified"
    assert not hasattr(result, "mainSha")
    assert not hasattr(result, "latestBackendSensitiveSha")


def test_genuine_backend_mismatch_is_failure():
    result = resolve(
        manifest=manifest(),
        actual_backend_sha="b" * 7,
    )
    assert result.status == "genuine_mismatch"
    assert result.mismatchReason == "actual_not_production_release_manifest"


def test_backend_version_mismatch_fails_closed():
    result = resolve(
        manifest=manifest(),
        actual_backend_sha=SHA,
        actual_backend_version="13.3.5",
    )
    assert result.status == "genuine_mismatch"
    assert result.mismatchReason == "actual_backend_version_not_manifest"


def test_short_manifest_sha_is_rejected():
    result = resolve(
        manifest=manifest(buildSha=SHA[:7]),
        actual_backend_sha=SHA[:7],
    )
    assert result.status == "resolver_failure"
    assert result.mismatchReason == "manifest_full_sha_required"


def test_wrong_environment_and_service_are_rejected():
    wrong_environment = resolve(
        manifest=manifest(environment="staging"),
        actual_backend_sha=SHA[:7],
    )
    wrong_service = resolve(
        manifest=manifest(service="other"),
        actual_backend_sha=SHA[:7],
    )
    assert wrong_environment.mismatchReason == "manifest_environment_invalid"
    assert wrong_service.mismatchReason == "manifest_service_invalid"


def test_unverified_or_malformed_manifest_is_rejected():
    health = resolve(
        manifest=manifest(verifiedHealth=False),
        actual_backend_sha=SHA[:7],
    )
    malformed = resolve(manifest=None, actual_backend_sha=SHA[:7])
    assert health.status == "resolver_failure"
    assert malformed.status == "resolver_failure"
