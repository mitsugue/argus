#!/usr/bin/env python3
"""Recompute the Recovery admission digest pins for a rebased candidate, verifiably.

Why this exists
---------------
`scripts/recovery_admission.py` pins the exact digest of a reviewed change's patch
bytes. Those bytes legitimately move when mainline modifies a file inside the pinned
scope, so a rebase onto a moved main requires a new pin. That is correct: the change
really is different, and the proof must be re-established rather than assumed.

What was wrong was HOW. The pin is a 64-character hexadecimal constant, re-typed by
hand, in the middle of the file that decides what may enter main, at the end of a long
session, under the pressure of a branch that will not merge until it is right. A
mistyped digest fails loudly, but a digest pasted from the wrong candidate does not:
it pins something real that nobody reviewed.

So the arithmetic moves here, and the human decision stays where it was. This script
recomputes the digests from the repository, rewrites nothing but those constants, and
then RE-RUNS the classifier to prove the result admits the candidate under the exact
classification the caller said to expect. If it does not, the edit is rolled back.

What it deliberately does NOT do
--------------------------------
  * It never runs in CI and never commits. A proof that re-pins itself on the way in
    proves nothing; a human still has to look at the change and say what it is.
  * It never invents a classification. `--expect` is mandatory, so a candidate that
    has silently grown into MIXED, or acquired a payload path nobody intended, fails
    instead of being pinned.
  * It never touches a pin it was not asked for, and it refuses to run when the
    admission module already has uncommitted edits, so it cannot bury a hand change.

Usage
-----
    python3 scripts/repin_recovery_admission.py --expect RECOVERY_ONLY
    python3 scripts/repin_recovery_admission.py --expect PRODUCT_AND_RECOVERY --apply

Without --apply it only reports. The exit status is 0 when the pins already admit the
candidate, 0 after a verified rewrite with --apply, and non-zero on anything else.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

# Import the SAME module object the rest of the repository uses. Two copies of
# the admission module in one process would mean two sets of pinned constants,
# and this script's whole job is to agree with the one that decides admission.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    from scripts import recovery_admission as admission     # noqa: E402
except ImportError:                                         # pragma: no cover
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import recovery_admission as admission                   # noqa: E402

MODULE_PATH = pathlib.Path(__file__).resolve().parent / "recovery_admission.py"

PAYLOAD_CONSTANT = "EXPECTED_RECOVERY_PAYLOAD_DIFF_SHA256"
PRODUCT_CONSTANT = "EXPECTED_PAIRED_PRODUCT_DIFF_SHA256"

EXPECTED_CLASSIFICATIONS = ("RECOVERY_ONLY", "PRODUCT_AND_RECOVERY")

_SHA_RE = re.compile(r"[0-9a-f]{64}")


class RepinError(RuntimeError):
    pass


def _git(repo: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RepinError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def module_is_dirty(repo: pathlib.Path) -> bool:
    """True when the admission module already carries uncommitted edits.

    Refusing then is the point: this script must never be the thing that hides a
    hand edit to the proof inside an automated rewrite.
    """
    relative = MODULE_PATH.relative_to(repo.resolve()).as_posix() \
        if MODULE_PATH.is_relative_to(repo.resolve()) \
        else "scripts/recovery_admission.py"
    return bool(_git(repo, "status", "--porcelain", "--", relative).strip())


def measure(repo: pathlib.Path, base: str, head: str) -> dict[str, object]:
    """The digests and paths this candidate actually has, per the classifier."""
    rows = admission._path_entries(repo, base, head)
    paths = {row["path"] for row in rows}
    def digest(selected: list[str]) -> str | None:
        if not selected:
            return None
        return admission._digest_bytes(
            admission._patch_bytes(repo, base, head, selected))
    # scanner.py appears in both path lists, and the classifier treats it as
    # dual-scope ONLY when the candidate is exactly the one reviewed cap patch.
    # Mirroring that here is not a detail: getting it wrong would re-pin the
    # ordinary Recovery route while reporting the one-time route, or refuse
    # every scanner.py change as if it were the cap patch.
    all_payload = sorted(paths.intersection(admission.RECOVERY_PAYLOAD_PATHS))
    possible_dual = sorted(
        paths.intersection(admission.DUAL_SCOPE_RECOVERY_PAYLOAD_PATHS))
    dual_payload = (
        possible_dual
        if possible_dual and digest(possible_dual) ==
        admission.EXPECTED_DUAL_SCOPE_RECOVERY_PAYLOAD_DIFF_SHA256 else [])
    payload = sorted(set(all_payload) - set(dual_payload))
    dual_tests = sorted(paths.intersection(admission.DUAL_SCOPE_TEST_PATHS))
    support = sorted(
        paths.intersection(admission.RECOVERY_CLASSIFICATION_SUPPORT_PATHS))
    other = sorted(paths - set(payload) - set(dual_payload)
                   - set(dual_tests) - set(support))
    return {"payloadPaths": payload, "productPaths": other,
            "payloadDigest": digest(payload), "productDigest": digest(other),
            "dualScopePayloadPaths": dual_payload,
            "dualScopeTestPaths": dual_tests}


def rewrite_constant(source: str, constant: str, digest: str) -> str:
    """Replace exactly one constant's 64-hex literal, or fail.

    The two constants are spelled differently in the module (one over three lines,
    one inline), so each is matched on its own name and its own single literal.
    """
    pattern = re.compile(
        r"(^" + re.escape(constant) + r"[^\n]*?=\s*\(?\s*\n?\s*\")"
        r"[0-9a-f]{64}(\")", re.MULTILINE)
    matches = pattern.findall(source)
    if len(matches) != 1:
        raise RepinError(f"constant_not_uniquely_matched:{constant}")
    return pattern.sub(lambda m: m.group(1) + digest + m.group(2), source, count=1)


def plan(measured: dict[str, object], expect: str) -> dict[str, str]:
    """Which constants need which values for this expectation."""
    if expect not in EXPECTED_CLASSIFICATIONS:
        raise RepinError(f"unsupported_expectation:{expect}")
    # The one-time routes are reported first: a candidate that IS the reviewed
    # cap patch has no ordinary payload, and "nothing changed" would be a
    # misleading way to say "this belongs to a route I must not touch".
    if measured["dualScopePayloadPaths"] or measured["dualScopeTestPaths"]:
        raise RepinError("dual_scope_pins_are_one_time_and_not_repinned_here")
    if not measured["payloadPaths"]:
        raise RepinError("no_recovery_payload_path_changed")
    wanted = {PAYLOAD_CONSTANT: measured["payloadDigest"]}
    if expect == "RECOVERY_ONLY":
        if measured["productPaths"]:
            raise RepinError(
                "product_paths_present_expected_PRODUCT_AND_RECOVERY")
    else:
        if not measured["productPaths"]:
            raise RepinError("no_product_path_changed_expected_RECOVERY_ONLY")
        wanted[PRODUCT_CONSTANT] = measured["productDigest"]
    for constant, digest in wanted.items():
        if not isinstance(digest, str) or not _SHA_RE.fullmatch(digest):
            raise RepinError(f"computed_digest_invalid:{constant}")
    return wanted


def verify(repo: pathlib.Path, base: str, head: str, expect: str) -> dict:
    """Re-run the classifier from the bytes just written, not from memory.

    Loading the file back is the whole verification: it proves the rewritten
    constants — not the ones this process started with — admit the candidate.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "recovery_admission_repinned", MODULE_PATH)
    if spec is None or spec.loader is None:      # pragma: no cover - defensive
        raise RepinError("module_reload_failed")
    reloaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reloaded)
    result = reloaded.classify_repository(repo, base, head)
    if result.get("classification") != expect or result.get("status") != "PASS":
        raise RepinError(
            "verification_failed:"
            f"{result.get('classification')}/{result.get('status')}")
    reloaded.validate_classification(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--expect", required=True,
                        choices=EXPECTED_CLASSIFICATIONS,
                        help="the classification a human has decided this is")
    parser.add_argument("--apply", action="store_true",
                        help="rewrite the constants, then verify or roll back")
    args = parser.parse_args(argv)
    repo = pathlib.Path(args.repo).resolve()

    try:
        measured = measure(repo, args.base, args.head)
        wanted = plan(measured, args.expect)
    except (RepinError, admission.AdmissionError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2

    print(f"payload paths : {', '.join(measured['payloadPaths']) or '(none)'}")
    print(f"product paths : {', '.join(measured['productPaths']) or '(none)'}")
    source = MODULE_PATH.read_text(encoding="utf-8")
    stale = {constant: digest for constant, digest in wanted.items()
             if digest not in source}
    for constant, digest in wanted.items():
        mark = "STALE" if constant in stale else "ok"
        print(f"{mark:5} {constant} -> {digest}")
    if not stale:
        print("pins already match this candidate; nothing to do")
        return 0
    if not args.apply:
        print("re-run with --apply to rewrite the stale pins", file=sys.stderr)
        return 1
    if module_is_dirty(repo):
        print("refused: the admission module has uncommitted edits",
              file=sys.stderr)
        return 2

    updated = source
    try:
        for constant, digest in stale.items():
            updated = rewrite_constant(updated, constant, digest)
        MODULE_PATH.write_text(updated, encoding="utf-8")
        verify(repo, args.base, args.head, args.expect)
    except (RepinError, admission.AdmissionError) as error:
        MODULE_PATH.write_text(source, encoding="utf-8")
        print(f"rolled back: {error}", file=sys.stderr)
        return 3
    print(f"re-pinned {len(stale)} constant(s) and verified "
          f"{args.expect}/PASS")
    return 0


if __name__ == "__main__":       # pragma: no cover - entry point
    raise SystemExit(main())
