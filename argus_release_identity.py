# -*- coding: utf-8 -*-
"""Independent release identity for the Render backend and Pages frontend."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parent
BACKEND_VERSION_FILE = ROOT / "backend-version.json"
FRONTEND_VERSION_FILE = ROOT / "web" / "package.json"


def _read_version(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("version")
        return str(value or "")
    except (OSError, ValueError, TypeError):
        return ""


def backend_version() -> str:
    return _read_version(BACKEND_VERSION_FILE)


def frontend_version() -> str:
    return _read_version(FRONTEND_VERSION_FILE)


def release_identity(*, backend_sha: Optional[str],
                     frontend_sha: Optional[str] = None) -> Dict[str, Any]:
    """Return four explicit coordinates without inferring one plane from another."""
    return {
        "backendVersion": backend_version() or "unknown",
        "backendBuildSha": backend_sha or "unknown",
        "frontendVersion": frontend_version() or "unknown",
        "frontendBuildSha": frontend_sha or "unknown",
    }
