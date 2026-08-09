import pytest

from scripts.render_deployment_identity import (
    DeploymentResolutionError,
    resolve_deployment,
    wait_for_deployment,
)


SHA = "a" * 40


def row(deployment_id="dep-current1", status="live", sha=SHA):
    return {
        "deploy": {
            "id": deployment_id,
            "status": status,
            "commit": {"id": sha},
            "trigger": "new_commit",
            "createdAt": "2026-08-09T00:00:00Z",
            "startedAt": "2026-08-09T00:01:00Z",
            "finishedAt": "2026-08-09T00:02:00Z",
        },
        "cursor": "cursor",
    }


def test_natural_code_deploy_returns_actual_render_id_not_github_run():
    result = resolve_deployment([row()], target_sha=SHA)
    assert result.renderDeploymentId == "dep-current1"
    assert result.renderDeploymentId != "31283850019"


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ([], "matching_deployment_not_found"),
        ([row(status="build_in_progress")], "matching_deployment_pending"),
        ([row(status="build_failed")], "matching_deployment_failed"),
        ([row(sha="b" * 40)], "matching_deployment_not_found"),
        ([row("dep-one"), row("dep-two")],
         "matching_deployment_ambiguous"),
    ],
)
def test_render_resolution_fails_closed(payload, error):
    with pytest.raises(DeploymentResolutionError, match=error):
        resolve_deployment(payload, target_sha=SHA)


def test_building_deployment_is_polled_until_live():
    responses = iter([
        [row(status="build_in_progress")],
        [row(status="live")],
    ])
    result = wait_for_deployment(
        lambda: next(responses),
        target_sha=SHA,
        timeout_seconds=10,
        poll_seconds=0,
        monotonic=lambda: 0,
        sleep=lambda _: None,
    )
    assert result.status == "live"


def test_transient_render_api_failure_is_polled_but_terminal_is_not():
    calls = iter([
        DeploymentResolutionError("render_api_retryable_status_503"),
        [row()],
    ])

    def fetch():
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    assert wait_for_deployment(
        fetch,
        target_sha=SHA,
        poll_seconds=0,
        monotonic=lambda: 0,
        sleep=lambda _: None,
    ).status == "live"
    with pytest.raises(
        DeploymentResolutionError,
        match="render_api_unauthorized",
    ):
        wait_for_deployment(
            lambda: (_ for _ in ()).throw(
                DeploymentResolutionError("render_api_unauthorized")),
            target_sha=SHA,
            poll_seconds=0,
            monotonic=lambda: 0,
            sleep=lambda _: None,
        )


def test_same_sha_config_deploy_requires_owner_selected_new_live_id():
    payload = [row("dep-old1"), row("dep-new1")]
    selected = resolve_deployment(
        payload,
        target_sha=SHA,
        expected_deployment_id="dep-new1",
    )
    assert selected.renderDeploymentId == "dep-new1"
    with pytest.raises(
        DeploymentResolutionError,
        match="expected_deployment_not_found_for_target_sha",
    ):
        resolve_deployment(
            [row("dep-new1")],
            target_sha=SHA,
            expected_deployment_id="dep-old1",
        )


def test_workflow_dispatch_rejects_non_render_identifier():
    with pytest.raises(
        DeploymentResolutionError,
        match="expected_render_deployment_id_invalid",
    ):
        resolve_deployment(
            [row()],
            target_sha=SHA,
            expected_deployment_id="github-main-123",
        )
