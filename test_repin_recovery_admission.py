"""The re-pin helper does the arithmetic; the human still decides what a change is.

A Recovery pin legitimately moves when mainline edits a file inside the pinned
scope, so a rebase means the proof must be re-established. Re-typing a
64-character digest by hand into the file that decides what may enter main is the
wrong way to do that: a mistyped digest fails loudly, but a digest pasted from the
wrong candidate pins something real that nobody reviewed.

These tests hold the helper to the only terms on which that is acceptable: it
rewrites nothing but the named constants, it refuses every candidate whose shape
does not match what the caller declared, and it rolls its own edit back if the
rewritten file does not actually admit the candidate.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from scripts import recovery_admission as admission
from scripts import repin_recovery_admission as repin


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          stdout=subprocess.PIPE, text=True).stdout.strip()


def _write(repo: pathlib.Path, relative: str, value: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


@pytest.fixture()
def candidate(tmp_path, monkeypatch):
    """A repository with one Recovery payload change and its own module copy."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Repin Test")
    _git(repo, "config", "user.email", "repin@example.invalid")
    _write(repo, "product-version.json", json.dumps({
        "schemaVersion": "argus-product-version-v1",
        "productVersion": "13.7.60",
    }))
    _write(repo, "scanner.py", "payload = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, "scanner.py", "payload = 2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "recovery payload change")
    head = _git(repo, "rev-parse", "HEAD")

    module_copy = tmp_path / "recovery_admission.py"
    shutil.copy(pathlib.Path(admission.__file__), module_copy)
    monkeypatch.setattr(repin, "MODULE_PATH", module_copy)
    return {"repo": repo, "base": base, "head": head, "module": module_copy}


def _stale(module: pathlib.Path) -> None:
    """Point the payload pin at something this candidate certainly is not."""
    source = module.read_text(encoding="utf-8")
    module.write_text(
        repin.rewrite_constant(source, repin.PAYLOAD_CONSTANT, "0" * 64),
        encoding="utf-8")


def test_the_rewrite_changes_exactly_one_line_and_only_the_digest():
    source = pathlib.Path(admission.__file__).read_text(encoding="utf-8")
    updated = repin.rewrite_constant(source, repin.PAYLOAD_CONSTANT, "a" * 64)
    before, after = source.split("\n"), updated.split("\n")
    assert len(before) == len(after)
    differing = [index for index, line in enumerate(before)
                 if line != after[index]]
    assert len(differing) == 1
    changed = after[differing[0]]
    assert "a" * 64 in changed
    # The surrounding syntax is untouched, so the module still parses.
    compile(updated, "recovery_admission.py", "exec")


def test_the_inline_paired_constant_is_rewritten_just_as_precisely():
    source = pathlib.Path(admission.__file__).read_text(encoding="utf-8")
    updated = repin.rewrite_constant(source, repin.PRODUCT_CONSTANT, "b" * 64)
    differing = [index for index, line in enumerate(source.split("\n"))
                 if line != updated.split("\n")[index]]
    assert len(differing) == 1
    assert repin.PRODUCT_CONSTANT in updated.split("\n")[differing[0]]
    compile(updated, "recovery_admission.py", "exec")


def test_an_unknown_constant_is_refused_rather_than_guessed():
    source = pathlib.Path(admission.__file__).read_text(encoding="utf-8")
    with pytest.raises(repin.RepinError, match="constant_not_uniquely_matched"):
        repin.rewrite_constant(source, "EXPECTED_NOTHING_AT_ALL", "c" * 64)


def test_it_measures_the_scope_the_classifier_would_see(candidate):
    measured = repin.measure(
        candidate["repo"], candidate["base"], candidate["head"])
    assert measured["payloadPaths"] == ["scanner.py"]
    assert measured["productPaths"] == []
    assert measured["payloadDigest"] == admission._digest_bytes(
        admission._patch_bytes(candidate["repo"], candidate["base"],
                               candidate["head"], ["scanner.py"]))
    assert measured["productDigest"] is None


def test_a_recovery_only_expectation_refuses_a_candidate_with_product_paths(
        candidate):
    _write(candidate["repo"], "web/src/App.tsx", "export default 1\n")
    _git(candidate["repo"], "add", ".")
    _git(candidate["repo"], "commit", "-m", "product too")
    head = _git(candidate["repo"], "rev-parse", "HEAD")
    measured = repin.measure(candidate["repo"], candidate["base"], head)
    with pytest.raises(repin.RepinError,
                       match="product_paths_present_expected_PRODUCT_AND_RECOVERY"):
        repin.plan(measured, "RECOVERY_ONLY")


def test_a_paired_expectation_refuses_a_candidate_with_no_product_path(
        candidate):
    measured = repin.measure(
        candidate["repo"], candidate["base"], candidate["head"])
    with pytest.raises(repin.RepinError,
                       match="no_product_path_changed_expected_RECOVERY_ONLY"):
        repin.plan(measured, "PRODUCT_AND_RECOVERY")


def test_a_candidate_touching_no_payload_path_is_refused(candidate):
    _write(candidate["repo"], "README.md", "docs only\n")
    _git(candidate["repo"], "add", ".")
    _git(candidate["repo"], "commit", "-m", "docs")
    docs_only = _git(candidate["repo"], "rev-parse", "HEAD")
    measured = repin.measure(candidate["repo"], candidate["head"], docs_only)
    with pytest.raises(repin.RepinError,
                       match="no_recovery_payload_path_changed"):
        repin.plan(measured, "RECOVERY_ONLY")


def test_the_one_time_dual_scope_pin_is_never_rewritten(candidate):
    """An ordinary change to a dual-scope path is ordinary payload.

    scanner.py sits in both path lists, and the dual-scope route belongs to one
    reviewed cap patch alone. So a run over any other scanner.py change must
    re-pin the ordinary Recovery route and leave the one-time constant exactly
    where the owner put it.
    """
    dual_constant = admission.EXPECTED_DUAL_SCOPE_RECOVERY_PAYLOAD_DIFF_SHA256
    assert "scanner.py" in admission.DUAL_SCOPE_RECOVERY_PAYLOAD_PATHS
    measured = repin.measure(
        candidate["repo"], candidate["base"], candidate["head"])
    assert measured["payloadPaths"] == ["scanner.py"]
    assert measured["dualScopePayloadPaths"] == []
    _stale(candidate["module"])
    assert repin.main(["--repo", str(candidate["repo"]),
                       "--base", candidate["base"], "--head", candidate["head"],
                       "--expect", "RECOVERY_ONLY", "--apply"]) == 0
    assert dual_constant in candidate["module"].read_text(encoding="utf-8")


def test_a_change_that_is_the_reviewed_cap_patch_is_left_to_its_own_route(
        candidate, monkeypatch):
    """When the dual-scope digest does match, this helper refuses to touch it."""
    measured = repin.measure(
        candidate["repo"], candidate["base"], candidate["head"])
    monkeypatch.setattr(admission,
                        "EXPECTED_DUAL_SCOPE_RECOVERY_PAYLOAD_DIFF_SHA256",
                        measured["payloadDigest"])
    recomputed = repin.measure(
        candidate["repo"], candidate["base"], candidate["head"])
    assert recomputed["dualScopePayloadPaths"] == ["scanner.py"]
    with pytest.raises(repin.RepinError, match="dual_scope_pins_are_one_time"):
        repin.plan(recomputed, "RECOVERY_ONLY")


def test_a_stale_pin_is_reported_without_apply_and_the_file_is_untouched(
        candidate, capsys):
    _stale(candidate["module"])
    before = candidate["module"].read_text(encoding="utf-8")
    code = repin.main(["--repo", str(candidate["repo"]),
                       "--base", candidate["base"], "--head", candidate["head"],
                       "--expect", "RECOVERY_ONLY"])
    assert code == 1
    assert "STALE" in capsys.readouterr().out
    assert candidate["module"].read_text(encoding="utf-8") == before


def test_apply_rewrites_the_pin_and_proves_the_candidate_is_admitted(
        candidate, capsys):
    _stale(candidate["module"])
    code = repin.main(["--repo", str(candidate["repo"]),
                       "--base", candidate["base"], "--head", candidate["head"],
                       "--expect", "RECOVERY_ONLY", "--apply"])
    assert code == 0
    assert "verified RECOVERY_ONLY/PASS" in capsys.readouterr().out
    expected = admission._digest_bytes(
        admission._patch_bytes(candidate["repo"], candidate["base"],
                               candidate["head"], ["scanner.py"]))
    assert expected in candidate["module"].read_text(encoding="utf-8")


def test_matching_pins_are_left_alone(candidate, capsys):
    repin.main(["--repo", str(candidate["repo"]), "--base", candidate["base"],
                "--head", candidate["head"], "--expect", "RECOVERY_ONLY",
                "--apply"])
    before = candidate["module"].read_text(encoding="utf-8")
    code = repin.main(["--repo", str(candidate["repo"]),
                       "--base", candidate["base"], "--head", candidate["head"],
                       "--expect", "RECOVERY_ONLY"])
    assert code == 0
    assert "nothing to do" in capsys.readouterr().out
    assert candidate["module"].read_text(encoding="utf-8") == before


def test_a_rewrite_that_does_not_admit_the_candidate_is_rolled_back(
        candidate, capsys, monkeypatch):
    """The verification is the safeguard, so its failure must undo the edit."""
    _stale(candidate["module"])
    before = candidate["module"].read_text(encoding="utf-8")
    monkeypatch.setattr(repin, "verify", lambda *args, **kwargs: (_ for _ in ()
                        ).throw(repin.RepinError("verification_failed:MIXED")))
    code = repin.main(["--repo", str(candidate["repo"]),
                       "--base", candidate["base"], "--head", candidate["head"],
                       "--expect", "RECOVERY_ONLY", "--apply"])
    assert code == 3
    assert "rolled back" in capsys.readouterr().err
    assert candidate["module"].read_text(encoding="utf-8") == before


def test_it_refuses_to_bury_an_uncommitted_hand_edit(candidate, capsys,
                                                     monkeypatch):
    _stale(candidate["module"])
    before = candidate["module"].read_text(encoding="utf-8")
    monkeypatch.setattr(repin, "module_is_dirty", lambda repo: True)
    code = repin.main(["--repo", str(candidate["repo"]),
                       "--base", candidate["base"], "--head", candidate["head"],
                       "--expect", "RECOVERY_ONLY", "--apply"])
    assert code == 2
    assert "uncommitted edits" in capsys.readouterr().err
    assert candidate["module"].read_text(encoding="utf-8") == before


def test_the_expectation_is_mandatory_and_closed():
    with pytest.raises(SystemExit):
        repin.main(["--repo", ".", "--expect", "PRODUCT"])
    with pytest.raises(SystemExit):
        repin.main([])
    assert repin.EXPECTED_CLASSIFICATIONS == (
        "RECOVERY_ONLY", "PRODUCT_AND_RECOVERY")


def test_the_helper_cannot_commit_or_run_itself_in_ci():
    source = pathlib.Path(repin.__file__).read_text(encoding="utf-8")
    for forbidden in ('"commit"', '"push"', "'commit'", "'push'"):
        assert forbidden not in source, forbidden
    workflows = pathlib.Path(".github/workflows")
    for workflow in workflows.glob("*.yml"):
        assert "repin_recovery_admission" not in workflow.read_text(
            encoding="utf-8"), workflow.name
