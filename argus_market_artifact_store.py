"""Durable per-artifact files for rebuildable market state.

The market ledger and the derived market artifacts (chart intelligence, today
intelligence, market replay, verified view snapshots, asset chart reports)
are the large market-state sections of the operational checkpoint; the
derived ones are deterministic outputs of the ledger and provider history.  They used to travel
inside the sealed operational checkpoint, which made every 30-minute save
re-serialize, re-hash, encrypt-verify and re-install roughly 110 MB of
presentation cache that had usually not changed.

This module keeps each artifact in its own fsynced JSON file under the
persistent root.  A file is rewritten only when the artifact's state hash
changes, every write is read back and compared, and a corrupt or missing
file never blocks startup: the artifact simply regenerates from the
authoritative ledger on the next tick.  Nothing here touches the sealed
checkpoint, the WAL, nonce authority or the encrypted recovery sidecar.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Callable, Dict, Mapping, Optional

SCHEMA = "argus-market-artifact-v1"
DIRECTORY = "argus_market_artifacts"
ARTIFACTS = (
    "marketLedger",
    "chartIntelligence",
    "todayIntelligence",
    "marketReplay",
    "verifiedViewSnapshots",
    "assetChartReports",
)
# marketLedger holds owner-imported observations (not regenerable from a
# provider), so it stays in the Remote Journal projection for off-disk
# recovery even though it no longer rides in the sealed local checkpoint.
REMOTE_PROJECTED = frozenset({"marketLedger"})
# Generous per-file ceilings sized from the 2026-09-28 production projection
# (verifiedViewSnapshots 48.5 MB, marketLedger 34.3 MB, assetChartReports
# 23.8 MB, chartIntelligence 18.9 MB, todayIntelligence 15.1 MB, marketReplay
# 5.3 MB) plus headroom.
MAX_BYTES = {
    "marketLedger": 128 * 1024 * 1024,
    "chartIntelligence": 48 * 1024 * 1024,
    "todayIntelligence": 48 * 1024 * 1024,
    "marketReplay": 24 * 1024 * 1024,
    "verifiedViewSnapshots": 96 * 1024 * 1024,
    "assetChartReports": 48 * 1024 * 1024,
}
# Module state hashes are lowercase hex; some stores emit 32-hex digests,
# the normalized-store hashes emit 64-hex.
_HASH_RE = re.compile(r"^[0-9a-f]{16,128}$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class ArtifactError(ValueError):
    """A stored artifact file is not usable; callers regenerate instead."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def directory_for(root: str) -> str:
    return os.path.join(os.path.abspath(str(root)), DIRECTORY)


def path_for(root: str, name: str) -> str:
    if name not in ARTIFACTS:
        raise ArtifactError("market_artifact_unknown")
    return os.path.join(directory_for(root), f"{name}.json")


def envelope(name: str, payload: Mapping[str, Any], *, state_hash: str,
             written_at: str, method_version: Optional[str] = None,
             build_sha: Optional[str] = None) -> Dict[str, Any]:
    if name not in ARTIFACTS:
        raise ArtifactError("market_artifact_unknown")
    if not isinstance(payload, Mapping):
        raise ArtifactError("market_artifact_payload_invalid")
    if not isinstance(state_hash, str) or not _HASH_RE.match(state_hash):
        raise ArtifactError("market_artifact_state_hash_invalid")
    if not isinstance(written_at, str) or not _ISO_RE.match(written_at):
        raise ArtifactError("market_artifact_written_at_invalid")
    doc: Dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "artifact": name,
        "stateHash": state_hash,
        "payloadSha256": payload_sha256(payload),
        "writtenAt": written_at,
        "payload": dict(payload),
    }
    if method_version:
        doc["methodVersion"] = str(method_version)
    if build_sha:
        doc["buildSha"] = str(build_sha)
    return doc


def verify(doc: Any, *, name: Optional[str] = None) -> Dict[str, Any]:
    """Validate an artifact envelope; return it or raise ArtifactError."""
    if not isinstance(doc, Mapping):
        raise ArtifactError("market_artifact_envelope_invalid")
    if doc.get("schemaVersion") != SCHEMA:
        raise ArtifactError("market_artifact_schema_mismatch")
    artifact = doc.get("artifact")
    if artifact not in ARTIFACTS or (name is not None and artifact != name):
        raise ArtifactError("market_artifact_name_mismatch")
    state_hash = doc.get("stateHash")
    if not isinstance(state_hash, str) or not _HASH_RE.match(state_hash):
        raise ArtifactError("market_artifact_state_hash_invalid")
    written_at = doc.get("writtenAt")
    if not isinstance(written_at, str) or not _ISO_RE.match(written_at):
        raise ArtifactError("market_artifact_written_at_invalid")
    payload = doc.get("payload")
    if not isinstance(payload, Mapping):
        raise ArtifactError("market_artifact_payload_invalid")
    if doc.get("payloadSha256") != payload_sha256(payload):
        raise ArtifactError("market_artifact_payload_hash_mismatch")
    return dict(doc)


def write_if_changed(
        root: str, name: str, payload: Mapping[str, Any], *,
        state_hash: str, now_iso: str, last_state_hash: Optional[str],
        atomic_write_json: Callable[..., Mapping[str, Any]],
        method_version: Optional[str] = None,
        build_sha: Optional[str] = None,
        file_mode: int = 0o600) -> Dict[str, Any]:
    """Persist ``payload`` when its state hash moved; verify by read-back.

    ``atomic_write_json`` is the caller's fsync+rename writer (injected so
    this module stays free of process state).  The returned status is safe
    to publish: hashes, byte counts and timestamps only.
    """
    path = path_for(root, name)
    if last_state_hash == state_hash and os.path.isfile(path):
        return {"artifact": name, "status": "unchanged",
                "stateHash": state_hash, "path": path}
    doc = envelope(name, payload, state_hash=state_hash, written_at=now_iso,
                   method_version=method_version, build_sha=build_sha)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    result = atomic_write_json(
        path, doc, maximum_bytes=MAX_BYTES[name], file_mode=file_mode,
        temp_label=f"market-artifact-{name}")
    restored = load(root, name)
    if restored is None or restored["stateHash"] != state_hash or \
            restored["payloadSha256"] != doc["payloadSha256"]:
        raise ArtifactError("market_artifact_readback_mismatch")
    return {"artifact": name, "status": "written",
            "stateHash": state_hash, "path": path,
            "bytes": int(result.get("bytes") or 0),
            "writtenAt": now_iso, "readBackVerified": True}


def load(root: str, name: str) -> Optional[Dict[str, Any]]:
    """Return the verified envelope, or None when no file exists."""
    path = path_for(root, name)
    if os.path.lexists(path) and os.path.islink(path):
        raise ArtifactError("market_artifact_symlink_rejected")
    try:
        size = os.stat(path).st_size
    except FileNotFoundError:
        return None
    if size > MAX_BYTES[name]:
        raise ArtifactError("market_artifact_oversized")
    with open(path, "rb") as handle:
        raw = handle.read(MAX_BYTES[name] + 1)
    if len(raw) > MAX_BYTES[name]:
        raise ArtifactError("market_artifact_oversized")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactError("market_artifact_json_invalid") from exc
    return verify(doc, name=name)


def status_projection(status: Mapping[str, Any]) -> Dict[str, Any]:
    """Public-safe summary: per-artifact hash, bytes, timestamps, outcome."""
    out: Dict[str, Any] = {"schemaVersion": SCHEMA, "artifacts": {}}
    for name in ARTIFACTS:
        row = status.get(name) if isinstance(status, Mapping) else None
        row = row if isinstance(row, Mapping) else {}
        out["artifacts"][name] = {
            "stateHash": row.get("stateHash"),
            "bytes": int(row.get("bytes") or 0),
            "writtenAt": row.get("writtenAt"),
            "lastStatus": row.get("lastStatus"),
            "restoreStatus": row.get("restoreStatus"),
            "errorClass": row.get("errorClass"),
        }
    return out
