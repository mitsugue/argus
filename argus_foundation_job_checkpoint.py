"""Small, integrity-bound persistence for foundation-job control state.

The main ARGUS checkpoint contains the complete market ledger and can exceed
100 MiB. Foundation-job progress is only a few KiB, so persisting it separately
prevents a scheduled job from serializing the whole checkpoint while its
memory-bounded worker is alive.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import argus_foundation_jobs


SCHEMA_VERSION = "argus-foundation-job-checkpoint-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def envelope(state: Any, *, saved_at: str) -> Dict[str, Any]:
    normalized = argus_foundation_jobs.normalize_state(state)
    unsigned = {
        "schemaVersion": SCHEMA_VERSION,
        "savedAt": str(saved_at),
        "state": normalized,
    }
    return {
        **unsigned,
        "stateHash": hashlib.sha256(_canonical(unsigned)).hexdigest(),
    }


def verify(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        return False
    unsigned = {
        "schemaVersion": value.get("schemaVersion"),
        "savedAt": value.get("savedAt"),
        "state": value.get("state"),
    }
    if not isinstance(unsigned["savedAt"], str) or not unsigned["savedAt"]:
        return False
    try:
        normalized = argus_foundation_jobs.normalize_state(unsigned["state"])
    except (TypeError, ValueError):
        return False
    if normalized != unsigned["state"]:
        return False
    return value.get("stateHash") == hashlib.sha256(
        _canonical(unsigned)
    ).hexdigest()


def restored_state(value: Any, current: Any) -> Dict[str, Any]:
    """Prefer the newer valid sidecar and mark orphaned workers interrupted."""
    if not verify(value):
        raise ValueError("foundation_job_checkpoint_invalid")
    incoming = argus_foundation_jobs.normalize_state(value["state"])
    existing = argus_foundation_jobs.normalize_state(current)
    selected = incoming if str(incoming.get("lastUpdatedAt") or "") >= str(
        existing.get("lastUpdatedAt") or ""
    ) else existing
    for job in selected.get("jobs", []):
        if job.get("status") in ("queued", "running"):
            job["status"] = "failed"
            job["errorClass"] = "process_restarted_resume_required"
            job["completedAt"] = str(value.get("savedAt"))
    selected["activeJobId"] = None
    return selected
