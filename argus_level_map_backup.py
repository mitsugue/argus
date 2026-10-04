"""Remote copy of the morning level map record (2026-10-04).

The two append-only level-map tables live in the market analysis history
file, whose remote archive format (views, then outcomes) is not changed.
This module copies them to the same private store over the same
authenticated, read-back-verified connection, under their own prefix:

* every stored estimate and morning map is one immutable object named by
  its date; an existing object with different bytes is a conflict, never
  overwritten;
* one manifest lists the objects with their digests and is replaced by
  compare-and-swap after the objects are written, then read back;
* restore runs only when the local tables are empty and inserts through the
  same first-body-wins functions, after checking every digest.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import argus_analysis_history as history

PREFIX = "market-analysis/v1/level-map"
SCHEMA = "argus-level-map-backup-v1"
MAX_WRITES_PER_SYNC = 40


def _encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _key(kind: str, day: str) -> str:
    if kind not in ("eps", "mornings") or len(day) != 10:
        raise ValueError("level_map_backup_key_invalid")
    return f"{kind}/{day}"


def _manifest(remote):
    raw, version = remote.get(PREFIX + "/manifest.json")
    if raw is None:
        return {"schemaVersion": SCHEMA, "entries": {}}, None
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA or not isinstance(value.get("entries"), dict):
        raise ValueError("level_map_backup_manifest_invalid")
    return value, version


def _local_items(path) -> Dict[str, Any]:
    state = history.read_level_map_state(path)
    items = {_key("eps", day): record for day, record in state["eps"].items()}
    items.update({_key("mornings", record["morningOf"]): record for record in state["mornings"]})
    return items


def synchronize(path, remote) -> Dict[str, Any]:
    """Write the local records the remote manifest lacks, then the manifest."""
    manifest, version = _manifest(remote)
    entries = dict(manifest["entries"])
    local = _local_items(path)
    if not local and entries:
        return {"status": "RESTORE_REQUIRED", "remoteCount": len(entries), "written": 0}
    written = 0
    for key in sorted(local):
        if key in entries:
            continue
        if written >= MAX_WRITES_PER_SYNC:
            break
        raw = _encode(local[key])
        target = f"{PREFIX}/{key}.json"
        existing, existing_version = remote.get(target)
        if existing is not None and existing != raw:
            raise ValueError("level_map_backup_immutable_conflict")
        if existing is None:
            remote.put(target, raw, expected_version=existing_version)
            if remote.get(target)[0] != raw:
                raise ValueError("level_map_backup_readback_mismatch")
        entries[key] = hashlib.sha256(raw).hexdigest()
        written += 1
    if entries != manifest["entries"]:
        new_raw = _encode({"schemaVersion": SCHEMA, "entries": entries})
        remote.put(PREFIX + "/manifest.json", new_raw, expected_version=version)
        if remote.get(PREFIX + "/manifest.json")[0] != new_raw:
            raise ValueError("level_map_backup_manifest_readback_mismatch")
    pending = sum(1 for key in local if key not in entries)
    return {"status": "VERIFIED" if not pending else "PARTIAL", "remoteCount": len(entries),
            "localCount": len(local), "written": written, "pending": pending}


def restore(path, remote) -> Dict[str, Any]:
    """Insert the remote records into empty local tables (digest-checked)."""
    if _local_items(path):
        return {"status": "LOCAL_NOT_EMPTY", "restored": 0}
    manifest, _ = _manifest(remote)
    restored = 0
    for key, digest in sorted(manifest["entries"].items()):
        raw, _ = remote.get(f"{PREFIX}/{key}.json")
        if raw is None or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("level_map_backup_object_invalid")
        record = json.loads(raw)
        kind = key.split("/", 1)[0]
        result = (history.append_level_map_eps(path, record) if kind == "eps"
                  else history.append_level_map(path, record))
        restored += int(result["inserted"])
    return {"status": "RESTORED", "restored": restored, "remoteCount": len(manifest["entries"])}
