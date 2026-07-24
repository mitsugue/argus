#!/usr/bin/env python3
"""Fail closed around Render's documented auto-deploy skip contract.

The repository keeps a Blueprint build-filter allowlist, but a Render service
that is not Blueprint-managed does not automatically consume render.yaml.
Until the live service is attached to that Blueprint (or receives the same
filter through the Render API), frontend-only squash merges must carry
Render's documented ``[skip render]`` phrase.  Backend-sensitive changes must
never carry a skip phrase.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from typing import Iterable, Sequence

try:
    from scripts.deploy_scope import classify
except ModuleNotFoundError:  # Direct CLI execution sets sys.path to scripts/.
    from deploy_scope import classify


SKIP_PHRASE = re.compile(
    r"\[(?:skip render|render skip|skip deploy|deploy skip|skip cd|cd skip)\]",
    re.IGNORECASE,
)


def validate(paths: Iterable[str], merge_text: str) -> tuple[bool, str]:
    normalized = tuple(path for path in paths if path)
    scope = classify(normalized)
    has_skip = bool(SKIP_PHRASE.search(merge_text or ""))
    if scope["backendDeploy"] and has_skip:
        return False, "backend_sensitive_change_must_not_skip_render"
    if not scope["backendDeploy"] and not has_skip:
        return False, "frontend_only_change_requires_skip_render"
    if scope["backendDeploy"]:
        return True, "backend_deploy_expected"
    return True, "frontend_only_render_skip_confirmed"


def changed_paths(base_sha: str, head_sha: str) -> Sequence[str]:
    if not base_sha or not head_sha or set(base_sha) == {"0"}:
        return ()
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        text=True,
    )
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--text", default=os.environ.get("ARGUS_RENDER_SKIP_TEXT", ""))
    parser.add_argument("--base", default=os.environ.get("ARGUS_RENDER_BASE_SHA", ""))
    parser.add_argument("--head", default=os.environ.get("ARGUS_RENDER_HEAD_SHA", ""))
    parser.add_argument("--event", default=os.environ.get("ARGUS_RENDER_EVENT", ""))
    args = parser.parse_args()

    if args.event == "workflow_dispatch" and not args.path:
        print("render-deploy-guard: expected_skip=manual_validation")
        return 0
    paths = tuple(args.path) or tuple(changed_paths(args.base, args.head))
    if not paths:
        print("render-deploy-guard: failure=no_changed_paths")
        return 1
    accepted, reason = validate(paths, args.text)
    scope = classify(paths)
    print(
        "render-deploy-guard:"
        f" accepted={str(accepted).lower()}"
        f" backendDeploy={str(scope['backendDeploy']).lower()}"
        f" changedPathCount={len(paths)}"
        f" reason={reason}"
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
