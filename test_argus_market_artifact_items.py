"""Per-item files for detached market stores (pure module contract)."""
import json
import os
import pathlib
import tempfile

import pytest

import argus_market_artifact_items as items
import argus_persistent_storage as storage


def _verified_store(*ids):
    return {"current": {f"market-chart:{i}:5D": {"snapshotId": f"vs-{i}", "payload": {"n": i}}
                        for i in ids}, "history": [], "lastPublishedAt": None}


def _asset_store():
    return {"records": {"JP:1321:daily:h1:m1": {"payload": {"symbol": "1321"}, "payloadHash": "x"},
                        "JP:1321:weekly:h1:m1": {"payload": {"symbol": "1321"}, "payloadHash": "y"}},
            "current": {"JP:1321:daily": "JP:1321:daily:h1:m1",
                        "JP:1321:weekly": "JP:1321:weekly:h1:m1"}, "cursor": 3}


def test_sync_writes_index_and_items_then_is_hash_gated_and_prunes():
    with tempfile.TemporaryDirectory() as root:
        first = items.sync(root, "verifiedViewSnapshots", _verified_store(1, 2),
                           state_hash="h1", now_iso="2026-09-28T12:00:00Z",
                           atomic_write_json=storage.atomic_write_json)
        assert first == {"status": "written", "itemCount": 2, "written": 2, "removed": 0}
        index = items.index(root, "verifiedViewSnapshots")
        assert index["stateHash"] == "h1"
        assert index["items"] == {"market-chart:1:5D": "vs-1", "market-chart:2:5D": "vs-2"}
        assert items.read(root, "verifiedViewSnapshots", "market-chart:2:5D") == {
            "snapshotId": "vs-2", "payload": {"n": 2}}
        # Same hash: nothing rewritten.
        again = items.sync(root, "verifiedViewSnapshots", _verified_store(1, 2),
                           state_hash="h1", now_iso="2026-09-28T12:30:00Z",
                           atomic_write_json=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no write")))
        assert again["status"] == "unchanged"
        # New hash, one item replaced, one removed, one unchanged.
        store = _verified_store(1, 3)
        store["current"]["market-chart:1:5D"]["snapshotId"] = "vs-1b"
        third = items.sync(root, "verifiedViewSnapshots", store, state_hash="h2",
                           now_iso="2026-09-28T13:00:00Z",
                           atomic_write_json=storage.atomic_write_json)
        assert third == {"status": "written", "itemCount": 2, "written": 2, "removed": 1}
        assert items.read(root, "verifiedViewSnapshots", "market-chart:2:5D") is None
        assert items.read(root, "verifiedViewSnapshots", "market-chart:1:5D")["snapshotId"] == "vs-1b"
        assert items.counts("verifiedViewSnapshots", items.index(root, "verifiedViewSnapshots")) == {
            "currentCount": 2}


def test_asset_items_are_keyed_by_identity_and_carry_the_record_key():
    with tempfile.TemporaryDirectory() as root:
        result = items.sync(root, "assetChartReports", _asset_store(), state_hash="a1",
                            now_iso="2026-09-28T12:00:00Z",
                            atomic_write_json=storage.atomic_write_json)
        assert result["itemCount"] == 2
        item = items.read(root, "assetChartReports", "JP:1321:daily")
        assert item == {"key": "JP:1321:daily:h1:m1",
                        "record": {"payload": {"symbol": "1321"}, "payloadHash": "x"}}
        assert items.counts("assetChartReports", items.index(root, "assetChartReports")) == {
            "recordCount": 2, "currentCount": 2}


def test_read_rejects_symlinks_oversized_and_foreign_documents():
    with tempfile.TemporaryDirectory() as root:
        items.sync(root, "verifiedViewSnapshots", _verified_store(1), state_hash="h",
                   now_iso="2026-09-28T12:00:00Z", atomic_write_json=storage.atomic_write_json)
        path = items.path_for(root, "verifiedViewSnapshots", "market-chart:1:5D")
        link = items.path_for(root, "verifiedViewSnapshots", "market-chart:9:5D")
        os.symlink(path, link)
        with pytest.raises(items.ItemError, match="symlink"):
            items.read(root, "verifiedViewSnapshots", "market-chart:9:5D")
        pathlib.Path(path).write_text(json.dumps({"schemaVersion": items.SCHEMA, "artifact": "assetChartReports",
                                                  "key": "market-chart:1:5D", "item": {}}))
        with pytest.raises(items.ItemError, match="shape"):
            items.read(root, "verifiedViewSnapshots", "market-chart:1:5D")
        assert items.read(root, "verifiedViewSnapshots", "market-chart:404:5D") is None
        with pytest.raises(items.ItemError):
            items.file_name("")
        with pytest.raises(items.ItemError):
            items.directory_for(root, "marketLedger")


def test_item_cache_is_bounded_and_invalidated_by_file_identity():
    with tempfile.TemporaryDirectory() as root:
        cache = items.ItemCache(max_entries=2, max_total_bytes=1_000_000)
        items.sync(root, "verifiedViewSnapshots", _verified_store(1, 2, 3), state_hash="h1",
                   now_iso="2026-09-28T12:00:00Z", atomic_write_json=storage.atomic_write_json)
        for i in (1, 2, 3):
            items.read(root, "verifiedViewSnapshots", f"market-chart:{i}:5D", cache=cache)
        assert cache.status()["entries"] == 2 and cache.status()["misses"] == 3
        items.read(root, "verifiedViewSnapshots", "market-chart:3:5D", cache=cache)
        assert cache.status()["hits"] == 1
        # Republish item 3: the cached bytes are dropped by identity, not TTL.
        store = _verified_store(1, 2, 3)
        store["current"]["market-chart:3:5D"]["snapshotId"] = "vs-3b"
        os.utime(items.path_for(root, "verifiedViewSnapshots", "market-chart:3:5D"), (1, 1))
        items.sync(root, "verifiedViewSnapshots", store, state_hash="h2",
                   now_iso="2026-09-28T13:00:00Z", atomic_write_json=storage.atomic_write_json)
        assert items.read(root, "verifiedViewSnapshots", "market-chart:3:5D", cache=cache)["snapshotId"] == "vs-3b"
