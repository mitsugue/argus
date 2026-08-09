from pathlib import Path


ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/publish-production-release-manifest.yml"


def test_workflow_is_valid_yaml_and_uses_verified_get_only_publication():
    text = WORKFLOW.read_text()
    assert text.startswith("name: publish-production-release-manifest")
    assert "verify_production_backend_release.py" in text
    assert "production_release_manifest.py create" in text
    assert "production-release" in text
    assert "--method POST" not in text
    assert "render_deployment_identity.py" in text
    assert "RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}" in text
    assert "deploys" in text


def test_frontend_scope_skips_manifest_publication():
    text = WORKFLOW.read_text()
    assert 'publish = classify(paths)["backendDeploy"]' in text
    assert "if: needs.classify.outputs.publish == 'true'" in text


def test_push_selects_exact_main_merge_commit_not_pr_or_moving_main():
    text = WORKFLOW.read_text()
    assert '["git", "rev-parse", "HEAD"]' in text
    assert '["git", "diff", "--name-only", parent, target]' in text
    assert "github.event.pull_request.head.sha" not in text
    assert "github.event.before" not in text
    assert (
        '--expected-sha "${{ needs.classify.outputs.target_sha }}"'
        in text
    )
    assert "TARGET_SHA: ${{ needs.classify.outputs.target_sha }}" in text
    assert '--build-sha "$TARGET_SHA"' in text
    assert "github-main-" not in text
    assert "expected_deployment_id" in text


def test_render_and_publication_identity_are_not_conflated():
    text = WORKFLOW.read_text()
    assert 'deployment_id = "github-main-"' not in text
    assert '"production: verify backend ${TARGET_SHA:0:12} (run ' in text
    assert '--expected-deployment-id "$EXPECTED_DEPLOYMENT_ID"' in text
    assert 're.fullmatch(r"dep-[0-9a-z]+"' in text


def test_same_sha_dispatch_and_repeated_publication_are_safe():
    text = WORKFLOW.read_text()
    assert "workflow_dispatch:" in text
    assert "select_deployed_at(" in text
    assert "manifest already matches verified deployment" in text


def test_authoritative_then_bounded_raw_verification():
    text = WORKFLOW.read_text()
    assert "verify_manifest_publication.py" in text
    assert "--timeout-seconds 300" in text
    assert "--poll-seconds 5" in text
    assert "PUBLISHED=$(curl" not in text


def test_manifest_publication_failure_does_not_mutate_backend():
    text = WORKFLOW.read_text()
    assert "git push origin HEAD:production-release" in text
    assert "argus-backend-3j2m.onrender.com/healthz" in text
    assert "argus-backend-3j2m.onrender.com/readyz" in text
    assert 'cp scripts/production_release_manifest.py \\' in text
    assert '"$RUNNER_TEMP/production_release_manifest.py"' in text
    assert (
        'python3 -B "$GITHUB_WORKSPACE/scripts/production_release_manifest.py"'
        not in text
    )
    assert "systemctl" not in text
