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
    assert "render" not in text.lower() or "never deploys" in text.lower()


def test_frontend_scope_skips_manifest_publication():
    text = WORKFLOW.read_text()
    assert 'publish = classify(paths)["backendDeploy"]' in text
    assert "if: needs.classify.outputs.publish == 'true'" in text


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
