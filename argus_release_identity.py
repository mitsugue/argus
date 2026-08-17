# -*- coding: utf-8 -*-
"""Independent release identity for the Render backend and Pages frontend."""
# V13 final release control intentionally touches this backend-sensitive module
# so Render and Pages converge on one main SHA before the production seed.  The
# touchpoint changes no product, provider, decision, privacy, or recovery logic.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parent
PRODUCT_VERSION_FILE = ROOT / "product-version.json"
BACKEND_VERSION_FILE = ROOT / "backend-version.json"
FRONTEND_VERSION_FILE = ROOT / "web" / "package.json"
PRODUCT_VERSION_SCHEMA = "argus-product-version-v1"


def _read_version(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("version")
        return str(value or "")
    except (OSError, ValueError, TypeError):
        return ""


def product_version() -> str:
    """Return the canonical product generation, never a component version."""
    try:
        value = json.loads(PRODUCT_VERSION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(value, dict) or set(value) != {
            "schemaVersion", "productVersion"}:
        return ""
    version = value.get("productVersion")
    if (value.get("schemaVersion") != PRODUCT_VERSION_SCHEMA
            or not isinstance(version, str)
            or not version.startswith("v")
            or not version[1:].isdigit()
            or version[1:].startswith("0")):
        return ""
    return version


def backend_version() -> str:
    return _read_version(BACKEND_VERSION_FILE)


def frontend_version() -> str:
    return _read_version(FRONTEND_VERSION_FILE)


def release_identity(*, backend_sha: Optional[str],
                     frontend_sha: Optional[str] = None) -> Dict[str, Any]:
    """Return product identity plus independent component coordinates."""
    return {
        "productVersion": product_version() or "unknown",
        "backendVersion": backend_version() or "unknown",
        "backendBuildSha": backend_sha or "unknown",
        "frontendVersion": frontend_version() or "unknown",
        "frontendBuildSha": frontend_sha or "unknown",
    }
