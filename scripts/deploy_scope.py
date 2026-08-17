#!/usr/bin/env python3
"""Deterministic frontend/backend deploy classification.

The backend list mirrors render.yaml's buildFilter.paths. Render always
processes render.yaml itself, so it is an explicit backend-sensitive exception.
"""
from __future__ import annotations

import fnmatch
from typing import Dict, Iterable, Tuple


RENDER_BACKEND_PATHS: Tuple[str, ...] = (
    "scanner.py",
    "wsgi.py",
    "argus_*.py",
    "bridge/**",
    "scripts/argus_mission_tick.py",
    "scripts/caos_watchtower_worker.py",
    "scripts/run_foundation_job.py",
    "requirements.txt",
    "Procfile",
    "gunicorn.conf.py",
    "backend-version.json",
    "product-version.json",
    "entity_profiles_seed.json",
    "web/src/types/**",
)
BACKEND_EXCEPTIONS = ("render.yaml",)
FRONTEND_PATHS: Tuple[str, ...] = (
    "web/**",
    "product-version.json",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/market-public-acceptance.yml",
    ".github/actions/warm-profile-seed/**",
    ".github/actions/warm-profile-consumer/**",
    "release/v13-snapshot-readiness-contract.json",
    "release/v13-accepted-fix-manifest.json",
    "scripts/verify_public_candidate_release.py",
)

# Stage 1 is a deliberately narrow backend release: it deploys the immutable
# validation writer while keeping the legacy checkpoint as restore authority
# and suppressing the ordinary new-backend formal-Soak path.  Fail closed when
# any other backend-sensitive path is mixed into the release.
CHECKPOINT_STAGE1_BACKEND_PATHS: Tuple[str, ...] = (
    "argus_chart_intelligence.py",
    "argus_checkpoint_v2.py",
    "argus_checkpoint_v2_stage1.py",
    "argus_market_ledger.py",
    "argus_market_replay.py",
    "argus_persistent_storage.py",
    "argus_runtime.py",
    "argus_tick_durability.py",
    "argus_today_intelligence.py",
    "backend-version.json",
    "scanner.py",
)


def _clean(path: str) -> str:
    clean = str(path).replace("\\", "/")
    return clean[2:] if clean.startswith("./") else clean


def _matches(path: str, patterns: Iterable[str]) -> bool:
    clean = _clean(path)
    return any(fnmatch.fnmatchcase(clean, pattern) for pattern in patterns)


def classify(changed_paths: Iterable[str]) -> Dict[str, bool]:
    paths = tuple(_clean(path) for path in changed_paths)
    backend_paths = tuple(
        path for path in paths
        if _matches(path, RENDER_BACKEND_PATHS + BACKEND_EXCEPTIONS)
    )
    backend = bool(backend_paths)
    frontend = any(_matches(path, FRONTEND_PATHS) for path in paths)
    checkpoint_stage1 = (
        "argus_checkpoint_v2_stage1.py" in backend_paths and
        all(path in CHECKPOINT_STAGE1_BACKEND_PATHS for path in backend_paths)
    )
    new_backend_soak = backend and not checkpoint_stage1
    return {
        "frontendDeploy": frontend,
        "backendDeploy": backend,
        "newBackendSoak": new_backend_soak,
        "preserveBackendSoak": not new_backend_soak,
        "checkpointStage1": checkpoint_stage1,
    }
