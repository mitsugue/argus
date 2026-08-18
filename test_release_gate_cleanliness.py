import json
import os
import pathlib
import shutil
import subprocess
import textwrap


ROOT = pathlib.Path(__file__).resolve().parent
GATE = ROOT / "scripts" / "release_gate.sh"


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fixture(tmp_path):
    repo = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    repo.mkdir()
    bin_dir.mkdir()
    _write(repo / ".gitignore", "artifacts/\n")
    _write(repo / "backend-version.json", '{"version":"13.4.13"}\n')
    _write(repo / "web" / "package.json", '{"version":"13.3.6"}\n')
    _write(repo / "scripts" / "release_gate.sh", GATE.read_text())
    (repo / "scripts" / "release_gate.sh").chmod(0o755)
    _write(
        bin_dir / "python3",
        textwrap.dedent(
            """\
            #!/bin/sh
            case "$*" in
              *"web/package.json"*) echo 13.3.6 ;;
              *"backend-version.json"*) echo 13.4.13 ;;
              *"argus_release_identity"*)
                if [ "${PYTHONDONTWRITEBYTECODE:-}" != "1" ]; then
                  mkdir -p __pycache__
                  : > __pycache__/argus_release_identity.pyc
                fi
                echo v13 ;;
              "-m pytest -q -p no:cacheprovider") echo "4 passed" ;;
              *) exit 2 ;;
            esac
            """
        ),
    )
    (bin_dir / "python3").chmod(0o755)
    _write(bin_dir / "npm", "#!/bin/sh\nexit 0\n")
    (bin_dir / "npm").chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Gate Test", "-c",
         "user.email=gate@example.invalid", "commit", "-qm", "fixture"],
        cwd=repo, check=True,
    )
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env.pop("PYTHONPYCACHEPREFIX", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return repo, env


def _run(repo, env):
    result = subprocess.run(
        ["bash", "scripts/release_gate.sh"], cwd=repo, env=env,
        text=True, capture_output=True,
    )
    manifest = json.loads(
        (repo / "artifacts" / "release_manifest.json").read_text())
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo, text=True)
    return result, manifest, status


def test_clean_gate_stays_clean_and_bytecode_cache_is_suppressed(tmp_path):
    repo, env = _fixture(tmp_path)
    result, manifest, status = _run(repo, env)
    assert result.returncode == 0
    assert manifest["eligibleForDeploy"] is True
    assert manifest["dirtyFiles"] == 0
    assert manifest["testCount"] == "4 passed"
    assert status == ""
    assert not (repo / "__pycache__").exists()


def test_tracked_change_remains_release_ineligible(tmp_path):
    repo, env = _fixture(tmp_path)
    with (repo / "backend-version.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")
    result, manifest, status = _run(repo, env)
    assert result.returncode != 0
    assert manifest["eligibleForDeploy"] is False
    assert manifest["dirtyFiles"] == 1
    assert "backend-version.json" in status


def test_unexpected_untracked_artifact_remains_release_ineligible(tmp_path):
    repo, env = _fixture(tmp_path)
    _write(repo / "unexpected.generated", "not allowlisted\n")
    result, manifest, status = _run(repo, env)
    assert result.returncode != 0
    assert manifest["eligibleForDeploy"] is False
    assert manifest["dirtyFiles"] == 1
    assert "unexpected.generated" in status


def test_gate_detects_dirt_created_after_initial_snapshot(tmp_path):
    repo, env = _fixture(tmp_path)
    npm = pathlib.Path(env["PATH"].split(os.pathsep)[0]) / "npm"
    _write(npm, "#!/bin/sh\n: > unexpected-after-gate-start\nexit 0\n")
    npm.chmod(0o755)
    result, manifest, status = _run(repo, env)
    assert result.returncode != 0
    assert manifest["eligibleForDeploy"] is False
    assert manifest["dirtyFiles"] == 1
    assert "unexpected-after-gate-start" in status
