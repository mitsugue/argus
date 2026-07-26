import json
import subprocess
from pathlib import Path

from scripts.resolve_backend_identity import resolve


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    ).strip()


def _commit(repo: Path, relative: str, body: str, message: str) -> str:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", relative)
    _git(
        repo, "-c", "user.name=ARGUS Test",
        "-c", "user.email=argus-test@example.invalid",
        "commit", "-m", message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    backend = _commit(repo, "scanner.py", "print('backend')\n", "backend")
    frontend = _commit(repo, "web/src/App.tsx", "export default 1\n", "frontend")
    return repo, backend, frontend


def test_frontend_main_sha_does_not_replace_backend_identity(tmp_path):
    repo, backend, frontend = _repo(tmp_path)
    result = resolve(
        repo=repo,
        main_sha=frontend,
        actual_backend_sha=backend[:7],
        now_epoch=2_000_000_000,
    )
    assert result.status == "verified"
    assert result.mainSha == frontend
    assert result.expectedBackendSha == backend
    assert result.latestBackendSensitiveSha == backend
    assert result.actualBackendSha == backend[:7]


def test_latest_backend_sensitive_sha_uses_shared_scope(tmp_path):
    repo, _, _ = _repo(tmp_path)
    workflow = _commit(
        repo, ".github/workflows/caos-scan.yml", "name: workflow\n",
        "workflow-only",
    )
    backend = _commit(
        repo, "argus_runtime.py", "VALUE = 2\n", "backend-sensitive",
    )
    latest_frontend = _commit(
        repo, "web/src/App.tsx", "export default 2\n", "frontend again",
    )
    result = resolve(
        repo=repo,
        main_sha=latest_frontend,
        actual_backend_sha=backend,
        now_epoch=2_000_000_000,
    )
    assert workflow != backend
    assert result.status == "verified"
    assert result.latestBackendSensitiveSha == backend


def test_genuine_backend_mismatch_remains_failure(tmp_path):
    repo, _, frontend = _repo(tmp_path)
    result = resolve(
        repo=repo,
        main_sha=frontend,
        actual_backend_sha="deadbee",
        now_epoch=2_000_000_000,
    )
    assert result.status == "genuine_mismatch"
    assert result.mismatchReason == "actual_not_authoritative_backend_commit"


def test_backend_deploy_transition_is_bounded(tmp_path):
    repo, previous, _ = _repo(tmp_path)
    latest = _commit(repo, "scanner.py", "print('next')\n", "next backend")
    committed_at = int(_git(repo, "show", "-s", "--format=%ct", latest))
    result = resolve(
        repo=repo,
        main_sha=latest,
        actual_backend_sha=previous[:7],
        transition_grace_sec=900,
        now_epoch=committed_at + 120,
    )
    assert result.status == "deploy_transition"
    assert result.transitionState == "within_grace"
    assert result.transitionGraceRemainingSec == 780

    expired = resolve(
        repo=repo,
        main_sha=latest,
        actual_backend_sha=previous[:7],
        transition_grace_sec=900,
        now_epoch=committed_at + 901,
    )
    assert expired.status == "genuine_mismatch"


def test_verified_deployment_manifest_has_priority(tmp_path):
    repo, backend, frontend = _repo(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "backendDeploy": True,
        "backendBuildSha": backend,
    }), encoding="utf-8")
    result = resolve(
        repo=repo,
        main_sha=frontend,
        actual_backend_sha=backend[:7],
        deployment_manifest=manifest,
        now_epoch=2_000_000_000,
    )
    assert result.status == "verified"
    assert result.identitySource == "deployment_manifest"
