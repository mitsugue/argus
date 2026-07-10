"""ARGUS V12.2.5 — Release Gate Integrity Hotfixの恒久ガード。"""
import os

ROOT = os.path.dirname(__file__)


def _gate_src():
    return open(os.path.join(ROOT, "scripts", "release_gate.sh"),
                encoding="utf-8").read()


def test_no_tautology_clean_tree_check():
    src = _gate_src()
    assert '-o "$DIRTY" = "0"' not in src         # 常真条件の禁止
    assert '[ "$DIRTY" = "0" ]  || ELIGIBLE=false' in src


def test_manifest_in_ignored_artifacts_path():
    src = _gate_src()
    assert "artifacts/release_manifest.json" in src
    gi = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    assert "artifacts/" in gi
    assert "release_manifest.json" in gi
    # committed manifestが存在しないこと
    assert not os.path.exists(os.path.join(ROOT, "release_manifest.json"))


def test_dirty_tree_reason_recorded():
    src = _gate_src()
    assert "dirty_tree" in src
    assert "failureReasons" in src


def test_workflow_runs_on_pull_request():
    wf = open(os.path.join(ROOT, ".github", "workflows", "release-gate.yml"),
              encoding="utf-8").read()
    assert "pull_request:" in wf
    assert "GITHUB_SHA" in wf                     # 正確SHA照合
    assert "STALE MANIFEST" in wf                 # 古いmanifest=不適格
    assert "upload-artifact" in wf
    assert "After CI Checks Pass" in wf           # Renderオーナー設定の文書化


def test_gate_uses_full_sha_for_exactness():
    src = _gate_src()
    assert "git rev-parse HEAD" in src            # 短縮でなく完全SHA


def test_no_secrets_in_gate_outputs():
    src = _gate_src()
    for banned in ("ARGUS_ADMIN_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY",
                   "HMAC", "passphrase"):
        assert banned not in src
