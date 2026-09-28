"""Per-item files for the two largest derived market artifacts (pure module).

Why: after the 2026-09-28 allocator fix the web process holds about 1 GB
between mission ticks, and the resident inventory names the largest
containers: ``verifiedViewSnapshots`` (47 MiB of JSON, 12 verified market
views of ~4 MB each) and ``assetChartReports`` (23 MiB).  Both are read by
public GETs one item at a time (one instrument/horizon, one asset report),
so they do not need to be resident: the mission tick generates them, the
checkpoint writes the whole-artifact file, and this module additionally
writes **one file per item** plus a small index so the routes can serve a
single item from disk while the in-memory store is detached.

Contract
--------
* ``sync(root, name, normalized, state_hash, ...)`` writes every item whose
  id (``snapshotId`` for verified views, the record key for asset reports)
  differs from the index, deletes files for keys no longer present, and
  rewrites the index ``{stateHash, items: {key: id}}``.  It is idempotent
  and hash-gated: an unchanged artifact costs one index read.
* ``read(root, name, key, cache)`` returns the item document for one key or
  ``None``; symlinks and oversized files are rejected.  ``ItemCache`` is a
  tiny byte-level LRU keyed by file identity (size + mtime), so a republished
  item is never served stale and the cache never holds more than a few MB.
* ``index(root, name)`` returns ``{"stateHash", "items"}`` or ``None``.

Nothing here decides *when* the store is detached; that policy lives in the
scanner.  Nothing here is a recovery authority: the sealed checkpoint and
the whole-artifact file remain the truth, these files are a read cache that
regenerates from them.
"""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import argus_market_artifact_store as store

SCHEMA = "argus-market-artifact-items-v1"
ITEM_ARTIFACTS = ("verifiedViewSnapshots", "assetChartReports")
MAX_ITEM_BYTES = 12 * 1024 * 1024
MAX_INDEX_BYTES = 256 * 1024
INDEX_NAME = "index.json"
_KEY_RE = re.compile(r"[^A-Za-z0-9._-]+")


class ItemError(ValueError):
    """A stored item or index is not usable; callers fall back or regenerate."""


def directory_for(root: str, name: str) -> str:
    if name not in ITEM_ARTIFACTS:
        raise ItemError("market_artifact_items_unknown")
    return os.path.join(store.directory_for(root), name)


def file_name(key: str) -> str:
    """Deterministic, filesystem-safe name for an item key (collision-free
    for the keys these artifacts use: ``kind:INSTRUMENT:HORIZON`` and
    ``MARKET:SYMBOL:timeframe``)."""
    safe = _KEY_RE.sub("_", str(key))
    if not safe or safe in {".", ".."} or len(safe) > 160:
        raise ItemError("market_artifact_item_key_invalid")
    return safe + ".json"


def path_for(root: str, name: str, key: str) -> str:
    return os.path.join(directory_for(root, name), file_name(key))


def items_of(name: str, normalized: Mapping[str, Any]) -> Dict[str, Tuple[str, Any]]:
    """``{key: (item_id, document)}`` for one normalized store."""
    out: Dict[str, Tuple[str, Any]] = {}
    if name == "verifiedViewSnapshots":
        for key, snapshot in (normalized.get("current") or {}).items():
            if isinstance(snapshot, dict) and snapshot.get("snapshotId"):
                out[str(key)] = (str(snapshot["snapshotId"]), snapshot)
    elif name == "assetChartReports":
        records = normalized.get("records") or {}
        for identity, record_key in (normalized.get("current") or {}).items():
            record = records.get(record_key)
            if isinstance(record, dict):
                out[str(identity)] = (str(record_key), {"key": str(record_key), "record": record})
    else:
        raise ItemError("market_artifact_items_unknown")
    return out


def _read_json(path: str, limit: int) -> Optional[Dict[str, Any]]:
    if os.path.lexists(path) and os.path.islink(path):
        raise ItemError("market_artifact_item_symlink_rejected")
    try:
        size = os.stat(path).st_size
    except FileNotFoundError:
        return None
    if size > limit:
        raise ItemError("market_artifact_item_oversized")
    with open(path, "rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ItemError("market_artifact_item_oversized")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ItemError("market_artifact_item_json_invalid") from exc
    if not isinstance(doc, dict):
        raise ItemError("market_artifact_item_shape")
    return doc


def index(root: str, name: str) -> Optional[Dict[str, Any]]:
    doc = _read_json(os.path.join(directory_for(root, name), INDEX_NAME), MAX_INDEX_BYTES)
    if doc is None:
        return None
    if doc.get("schemaVersion") != SCHEMA or doc.get("artifact") != name \
            or not isinstance(doc.get("items"), dict) \
            or not isinstance(doc.get("stateHash"), str):
        raise ItemError("market_artifact_index_invalid")
    return doc


def sync(root: str, name: str, normalized: Mapping[str, Any], *,
         state_hash: str, now_iso: str,
         atomic_write_json: Callable[..., Mapping[str, Any]]) -> Dict[str, Any]:
    """Bring the per-item files and index in line with ``normalized``."""
    directory = directory_for(root, name)
    os.makedirs(directory, exist_ok=True)
    try:
        previous = index(root, name)
    except ItemError:
        previous = None
    if previous is not None and previous.get("stateHash") == state_hash:
        return {"status": "unchanged", "itemCount": len(previous["items"]),
                "written": 0, "removed": 0}
    previous_items = (previous or {}).get("items") or {}
    wanted = items_of(name, normalized)
    written = 0
    for key, (item_id, document) in wanted.items():
        path = path_for(root, name, key)
        if previous_items.get(key) == item_id and os.path.isfile(path) \
                and not os.path.islink(path):
            continue
        atomic_write_json(path, {"schemaVersion": SCHEMA, "artifact": name,
                                 "key": key, "id": item_id, "writtenAt": now_iso,
                                 "item": document},
                          maximum_bytes=MAX_ITEM_BYTES)
        written += 1
    removed = 0
    for key in set(previous_items) - set(wanted):
        try:
            os.unlink(path_for(root, name, key))
            removed += 1
        except (FileNotFoundError, ItemError):
            pass
        except OSError:
            pass
    atomic_write_json(os.path.join(directory, INDEX_NAME), {
        "schemaVersion": SCHEMA, "artifact": name, "stateHash": state_hash,
        "writtenAt": now_iso,
        "items": {key: item_id for key, (item_id, _doc) in wanted.items()},
    }, maximum_bytes=MAX_INDEX_BYTES)
    return {"status": "written", "itemCount": len(wanted),
            "written": written, "removed": removed}


class ItemCache:
    """Byte-level LRU keyed by (name, key) and validated by file identity."""

    # The cache holds raw bytes and every read re-parses them, so it only
    # saves an open()+read() that the operating system's page cache already
    # serves.  In production it grew to 33 MB of anonymous memory for that
    # (2026-09-28 diagnostics), which is the opposite of the point: keep it
    # small enough to help the tiny artifacts and let the page cache serve
    # the multi-megabyte ones.
    def __init__(self, *, max_entries: int = 4,
                 max_total_bytes: int = 4 * 1024 * 1024) -> None:
        self._entries: "OrderedDict[Tuple[str, str], Tuple[Tuple[int, int], bytes]]" = OrderedDict()
        self._max_entries = max(1, int(max_entries))
        self._max_total = max(1, int(max_total_bytes))
        self.hits = 0
        self.misses = 0

    def _total(self) -> int:
        return sum(len(raw) for _sig, raw in self._entries.values())

    def get(self, name: str, key: str, path: str) -> Optional[bytes]:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            self._entries.pop((name, key), None)
            return None
        signature = (int(st.st_size), int(st.st_mtime_ns))
        cached = self._entries.get((name, key))
        if cached and cached[0] == signature:
            self._entries.move_to_end((name, key))
            self.hits += 1
            return cached[1]
        self.misses += 1
        return None

    def put(self, name: str, key: str, path: str, raw: bytes) -> None:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return
        if len(raw) > self._max_total:
            return
        self._entries[(name, key)] = ((int(st.st_size), int(st.st_mtime_ns)), raw)
        self._entries.move_to_end((name, key))
        while len(self._entries) > self._max_entries or self._total() > self._max_total:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def status(self) -> Dict[str, Any]:
        return {"entries": len(self._entries), "bytes": self._total(),
                "hits": self.hits, "misses": self.misses}


def read(root: str, name: str, key: str,
         cache: Optional[ItemCache] = None) -> Optional[Any]:
    """The stored item document for ``key`` (the snapshot, or
    ``{"key", "record"}`` for asset reports), or ``None`` when absent."""
    path = path_for(root, name, key)
    raw = cache.get(name, key, path) if cache is not None else None
    if raw is None:
        if os.path.lexists(path) and os.path.islink(path):
            raise ItemError("market_artifact_item_symlink_rejected")
        try:
            size = os.stat(path).st_size
        except FileNotFoundError:
            return None
        if size > MAX_ITEM_BYTES:
            raise ItemError("market_artifact_item_oversized")
        with open(path, "rb") as handle:
            raw = handle.read(MAX_ITEM_BYTES + 1)
        if len(raw) > MAX_ITEM_BYTES:
            raise ItemError("market_artifact_item_oversized")
        if cache is not None:
            cache.put(name, key, path, raw)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ItemError("market_artifact_item_json_invalid") from exc
    if not isinstance(doc, dict) or doc.get("schemaVersion") != SCHEMA \
            or doc.get("artifact") != name or doc.get("key") != key \
            or "item" not in doc:
        raise ItemError("market_artifact_item_shape")
    return doc["item"]


def counts(name: str, index_doc: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    """Scalar counts for checkpoint/telemetry rows while the store is detached."""
    total = len((index_doc or {}).get("items") or {})
    if name == "verifiedViewSnapshots":
        return {"currentCount": total}
    return {"recordCount": total, "currentCount": total}
