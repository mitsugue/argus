#!/usr/bin/env python3
"""Resolve the deployed backend identity from repository deployment scope.

Scheduled operational workflows run from the latest ``main`` commit, which can
be frontend-only.  Therefore ``GITHUB_SHA`` is context, never the expected
backend identity.  The expected SHA is the newest first-parent commit whose
diff matches the shared Render backend scope in :mod:`scripts.deploy_scope`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from scripts.deploy_scope import classify
except ModuleNotFoundError:  # Direct CLI execution sets sys.path to scripts/.
    from deploy_scope import classify


STATUSES = (
    "verified",
    "deploy_transition",
    "expected_skip",
    "genuine_mismatch",
    "resolver_failure",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _full_sha(repo: Path, value: str) -> str:
    return _git(repo, "rev-parse", f"{value}^{{commit}}")


def _parents(repo: Path, commit: str) -> list[str]:
    row = _git(repo, "rev-list", "--parents", "-n", "1", commit).split()
    return row[1:]


def _changed_paths(repo: Path, commit: str) -> tuple[str, ...]:
    parents = _parents(repo, commit)
    if parents:
        output = _git(
            repo, "diff", "--name-only", "--no-renames",
            parents[0], commit,
        )
    else:
        output = _git(repo, "ls-tree", "-r", "--name-only", commit)
    return tuple(line for line in output.splitlines() if line)


def backend_sensitive_history(repo: Path, main_sha: str) -> list[str]:
    """Return first-parent backend-sensitive commits, newest first."""
    commits = _git(repo, "rev-list", "--first-parent", main_sha).splitlines()
    return [
        commit for commit in commits
        if classify(_changed_paths(repo, commit))["backendDeploy"]
    ]


def _prefix_equal(left: str, right: str) -> bool:
    a, b = str(left or "").lower(), str(right or "").lower()
    return bool(a and b and (a.startswith(b) or b.startswith(a)))


def _commit_epoch(repo: Path, commit: str) -> int:
    return int(_git(repo, "show", "-s", "--format=%ct", commit))


def _manifest_sha(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if value.get("backendDeploy") is False:
        return None
    return (
        value.get("backendBuildSha")
        or value.get("deployedBackendSha")
        or value.get("commitSha")
    )


@dataclass(frozen=True)
class IdentityResult:
    expectedBackendSha: Optional[str]
    actualBackendSha: Optional[str]
    identitySource: str
    mainSha: Optional[str]
    latestBackendSensitiveSha: Optional[str]
    status: str
    transitionState: str
    transitionGraceRemainingSec: int
    mismatchReason: Optional[str]


def resolve(
    *,
    repo: Path,
    main_sha: str,
    actual_backend_sha: str,
    deployment_manifest: Optional[Path] = None,
    transition_grace_sec: int = 900,
    now_epoch: Optional[int] = None,
) -> IdentityResult:
    now = int(time.time() if now_epoch is None else now_epoch)
    try:
        main = _full_sha(repo, main_sha)
        history = backend_sensitive_history(repo, main)
    except (subprocess.CalledProcessError, ValueError):
        return IdentityResult(
            None, actual_backend_sha or None, "none", None, None,
            "resolver_failure", "none", 0, "repository_history_unavailable",
        )
    if not history:
        return IdentityResult(
            None, actual_backend_sha or None, "repository_history",
            main, None, "expected_skip", "none", 0,
            "no_backend_sensitive_commit",
        )

    latest = history[0]
    source = "repository_backend_sensitive_history"
    expected = latest
    manifest_value = _manifest_sha(deployment_manifest)
    if manifest_value:
        try:
            manifest_full = _full_sha(repo, manifest_value)
            if manifest_full in history:
                expected = manifest_full
                source = "deployment_manifest"
        except subprocess.CalledProcessError:
            pass

    actual = str(actual_backend_sha or "").strip()
    if not actual:
        return IdentityResult(
            expected, None, source, main, latest,
            "resolver_failure", "none", 0, "actual_backend_sha_missing",
        )
    if _prefix_equal(expected, actual):
        return IdentityResult(
            expected, actual, source, main, latest,
            "verified", "none", 0, None,
        )

    prior = next(
        (commit for commit in history if _prefix_equal(commit, actual)),
        None,
    )
    age = max(0, now - _commit_epoch(repo, latest))
    if prior and expected == latest and age <= transition_grace_sec:
        return IdentityResult(
            expected, actual, source, main, latest,
            "deploy_transition", "within_grace",
            max(0, transition_grace_sec - age),
            "latest_backend_sensitive_commit_not_live_yet",
        )
    return IdentityResult(
        expected, actual, source, main, latest,
        "genuine_mismatch", "none", 0,
        "actual_not_authoritative_backend_commit",
    )


def _write_github_output(path: Path, values: Iterable[tuple[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values:
            if value is None:
                rendered = ""
            elif isinstance(value, bool):
                rendered = str(value).lower()
            else:
                rendered = str(value)
            handle.write(f"{key}={rendered}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--actual-backend-sha", required=True)
    parser.add_argument("--deployment-manifest")
    parser.add_argument("--transition-grace-seconds", type=int, default=900)
    parser.add_argument("--now-epoch", type=int)
    parser.add_argument("--github-output")
    args = parser.parse_args()
    result = resolve(
        repo=Path(args.repo).resolve(),
        main_sha=args.main_sha,
        actual_backend_sha=args.actual_backend_sha,
        deployment_manifest=(
            Path(args.deployment_manifest)
            if args.deployment_manifest else None
        ),
        transition_grace_sec=max(0, args.transition_grace_seconds),
        now_epoch=args.now_epoch,
    )
    payload = asdict(result)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if args.github_output:
        _write_github_output(Path(args.github_output), payload.items())
    return 0 if result.status in STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
