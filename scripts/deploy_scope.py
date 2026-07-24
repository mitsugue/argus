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
    "entity_profiles_seed.json",
    "web/src/types/**",
)
BACKEND_EXCEPTIONS = ("render.yaml",)
FRONTEND_PATHS: Tuple[str, ...] = (
    "web/**",
    ".github/workflows/deploy-pages.yml",
)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    clean = path.replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatchcase(clean, pattern) for pattern in patterns)


def classify(changed_paths: Iterable[str]) -> Dict[str, bool]:
    paths = tuple(str(path).replace("\\", "/").lstrip("./")
                  for path in changed_paths)
    backend = any(_matches(path, RENDER_BACKEND_PATHS + BACKEND_EXCEPTIONS)
                  for path in paths)
    frontend = any(_matches(path, FRONTEND_PATHS) for path in paths)
    return {
        "frontendDeploy": frontend,
        "backendDeploy": backend,
        "newBackendSoak": backend,
        "preserveBackendSoak": not backend,
    }
