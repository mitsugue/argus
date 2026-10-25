"""The ledger lives in the owner's private repository (owner decision 2026-10-17).

Writers push the same branch there; the server reads it with the private key;
nothing reads or writes the public ledger branch any more.
"""
import os
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "ledger_use_private.sh"
WRITERS = ("event-ledger", "macro-event-analysis", "learning-memory", "mover-causes",
           "prediction-ledger", "caos-scan", "caos-watchtower")


def test_every_ledger_writer_points_at_the_private_repository_before_fetching():
    for name in WRITERS:
        text = (ROOT / ".github/workflows" / f"{name}.yml").read_text(encoding="utf-8")
        lines = text.splitlines()
        fetches = [i for i, l in enumerate(lines) if re.match(r'\s*git fetch origin "ledger:refs/remotes/origin/ledger"', l)]
        assert fetches, name
        for i in fetches:
            assert "bash scripts/ledger_use_private.sh" in lines[i - 1], (name, i)
            assert 'LEDGER_TOKEN="${{ secrets.ARGUS_PRIVATE_LEDGER_TOKEN }}"' in lines[i - 1]
    # No other workflow pushes the ledger branch.
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        if path.stem not in WRITERS:
            assert "HEAD:ledger" not in path.read_text(encoding="utf-8"), path.name


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "none"), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/mitsugue/argus.git"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "config", "--local", "http.https://github.com/.extraheader", "AUTHORIZATION: basic workflow"],
                   cwd=repo, check=True, env=env)
    return repo, env


def test_the_script_replaces_the_remote_and_the_stored_credential(tmp_path):
    repo, env = _repo(tmp_path)
    done = subprocess.run(["bash", str(SCRIPT)], cwd=repo, env={**env, "LEDGER_TOKEN": "synthetic-key"},
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    get = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, capture_output=True, text=True).stdout.strip()
    assert get("remote", "get-url", "origin") == "https://github.com/mitsugue/argus-l2b-private.git"
    headers = get("config", "--local", "--get-all", "http.https://github.com/.extraheader").splitlines()
    assert len(headers) == 1 and headers[0].startswith("AUTHORIZATION: basic ") and "workflow" not in headers[0]
    assert "synthetic-key" not in done.stdout and "::add-mask::" in done.stdout


def test_the_script_fails_without_the_key(tmp_path):
    repo, env = _repo(tmp_path)
    done = subprocess.run(["bash", str(SCRIPT)], cwd=repo, env={k: v for k, v in env.items() if k != "LEDGER_TOKEN"},
                          capture_output=True, text=True)
    assert done.returncode != 0 and "ARGUS_PRIVATE_LEDGER_TOKEN" in done.stderr


def test_the_server_reads_the_private_ledger_with_the_key_only_there(monkeypatch):
    import scanner
    assert scanner._LEDGER_RAW_BASE.startswith("https://raw.githubusercontent.com/mitsugue/argus-l2b-private/ledger/")
    monkeypatch.setenv("ARGUS_LAYER2B_PRIVATE_TOKEN", "synthetic-key")
    monkeypatch.delenv("ARGUS_RECOVERY_GITHUB_READ_TOKEN", raising=False)
    private = scanner._ledger_auth_headers("https://raw.githubusercontent.com/mitsugue/argus-l2b-private/ledger/ledger/a.json")
    assert private == {"Authorization": "Bearer synthetic-key"}
    assert scanner._ledger_auth_headers("https://api.github.com/repos/mitsugue/argus-l2b-private/commits")["Authorization"]
    for other in ("https://raw.githubusercontent.com/mitsugue/argus/main/x", "https://example.com/mitsugue/argus-l2b-private/"):
        assert "Authorization" not in scanner._ledger_auth_headers(other)
    source = (ROOT / "scanner.py").read_text(encoding="utf-8")
    assert 'requests.get(f"{_LEDGER_RAW_BASE}' not in source
    assert "raw.githubusercontent.com/mitsugue/argus/ledger" not in source
    assert (ROOT / "web/src/lib/vault.ts").read_text(encoding="utf-8").count("raw.githubusercontent.com") == 0
