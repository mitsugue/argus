"""Derived market artifacts leave the sealed checkpoint (scanner integration).

Contract:
- the sealed checkpoint keeps only the artifact state hashes and a status
  projection; the five payloads are written to hash-gated files;
- an unchanged artifact is not rewritten on the next checkpoint;
- restore merges the files, still accepts a legacy inline checkpoint, and a
  corrupt file never blocks boot;
- the Remote Journal projection no longer carries the payloads.
"""
import copy
import json
import pathlib
import tempfile
from unittest import mock

import pytest

import argus_asset_chart_cache as asset_cache
import argus_chart_intelligence as chart_intelligence
import argus_market_artifact_store as artifact_store
import argus_market_replay as market_replay
import argus_persistent_storage as storage
import argus_today_intelligence as today_intelligence
import argus_verified_snapshot as snapshots
import scanner
from test_argus_persistent_mission_storage import remote_snapshot, scanner_storage
from test_argus_verified_snapshot import candidate


ARTIFACTS = artifact_store.ARTIFACTS


def _seed_verified(symbol="1321", dataset_hash="split-a"):
    item = candidate(symbol=symbol, dataset_hash=dataset_hash,
                     method=scanner._VERIFIED_VIEW_METHOD_VERSION)
    updated, reason = snapshots.publish_atomic(
        scanner._VERIFIED_VIEW_SNAPSHOTS, item,
        now_iso="2026-07-23T06:02:00Z")
    assert reason == "published", reason
    scanner._VERIFIED_VIEW_SNAPSHOTS.clear()
    scanner._VERIFIED_VIEW_SNAPSHOTS.update(updated)
    return item["snapshotId"]


_STORES = ("_VERIFIED_VIEW_SNAPSHOTS", "_ASSET_CHART_REPORTS",
           "_CHART_INTELLIGENCE", "_TODAY_INTELLIGENCE", "_MARKET_REPLAY",
           "_MARKET_ARTIFACT_STATUS")


@pytest.fixture(autouse=True)
def _isolate_market_stores():
    """Leave every shared store exactly as found so test order never matters."""
    saved = {name: copy.deepcopy(getattr(scanner, name)) for name in _STORES}
    try:
        yield
    finally:
        for name in _STORES:
            live = getattr(scanner, name)
            live.clear()
            live.update(saved[name])


def _reset_market_stores():
    for target in (scanner._MARKET_ARTIFACT_STATUS,):
        target.clear()
    for name, empty in (
            ("_VERIFIED_VIEW_SNAPSHOTS", snapshots.empty_store()),
            ("_ASSET_CHART_REPORTS", asset_cache.empty_store()),
            ("_CHART_INTELLIGENCE", chart_intelligence.normalize_state({})),
            ("_TODAY_INTELLIGENCE", today_intelligence.normalize_state({})),
            ("_MARKET_REPLAY", market_replay.normalize_state({}))):
        live = getattr(scanner, name)
        live.clear()
        live.update(empty)


def _checkpoint_blob(value):
    return storage.load_checkpoint(value["checkpoint"], require_seal=True)


def test_checkpoint_excludes_payloads_and_files_are_hash_gated():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        root = value["root"]
        _reset_market_stores()
        snapshot_id = _seed_verified()
        first = scanner._osint_persist()
        assert first["verified"] is True
        blob = _checkpoint_blob(value)
        for name in ARTIFACTS:
            assert name not in blob, name
            assert blob[f"{name}StateHash"]
            doc = artifact_store.load(root, name)
            assert doc is not None, name
            assert doc["stateHash"] == blob[f"{name}StateHash"]
        assert blob["marketArtifacts"]["schemaVersion"] == artifact_store.SCHEMA
        status = blob["marketArtifacts"]["artifacts"]["verifiedViewSnapshots"]
        assert status["lastStatus"] == "written"
        assert status["bytes"] > 0
        verified_doc = artifact_store.load(root, "verifiedViewSnapshots")
        assert [s["snapshotId"] for s in
                verified_doc["payload"]["current"].values()] == [snapshot_id]
        assert verified_doc["methodVersion"] == \
            scanner._VERIFIED_VIEW_METHOD_VERSION
        # The checkpoint itself shrank to control state: no snapshot body,
        # only the status row keyed by artifact name.
        assert snapshot_id not in json.dumps(blob)
        assert "current" not in blob.get("marketArtifacts", {}).get(
            "artifacts", {}).get("verifiedViewSnapshots", {})
        path = pathlib.Path(artifact_store.path_for(root, "verifiedViewSnapshots"))
        identity = (path.stat().st_ino, path.stat().st_mtime_ns)

        second = scanner._osint_persist()
        assert second["verified"] is True
        assert (path.stat().st_ino, path.stat().st_mtime_ns) == identity
        for name in ARTIFACTS:
            assert scanner._MARKET_ARTIFACT_STATUS[name]["lastStatus"] == \
                "unchanged", name

        _seed_verified(dataset_hash="split-b")
        third = scanner._osint_persist()
        assert third["verified"] is True
        assert scanner._MARKET_ARTIFACT_STATUS["verifiedViewSnapshots"][
            "lastStatus"] == "written"
        assert scanner._MARKET_ARTIFACT_STATUS["marketReplay"][
            "lastStatus"] == "unchanged"


def test_restore_merges_artifact_files_after_process_restart():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp):
        _reset_market_stores()
        snapshot_id = _seed_verified()
        assert scanner._osint_persist()["verified"] is True
        # Simulate a fresh process: empty stores, restore not yet attempted.
        _reset_market_stores()
        scanner._OSINT_PERSIST_STATE.update({"restored": False})
        with mock.patch.object(scanner.requests, "get") as request_get:
            source = scanner._osint_restore_once()
        request_get.assert_not_called()
        assert source == "persistent_local"
        current = scanner._VERIFIED_VIEW_SNAPSHOTS["current"]
        assert [s["snapshotId"] for s in current.values()] == [snapshot_id]
        for name in ARTIFACTS:
            assert scanner._MARKET_ARTIFACT_STATUS[name]["restoreStatus"] == \
                "restored", name


def test_legacy_inline_checkpoint_still_restores_and_migrates_to_files():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        root = value["root"]
        _reset_market_stores()
        legacy_store = snapshots.empty_store()
        item = candidate(symbol="1306", dataset_hash="legacy-a",
                         method=scanner._VERIFIED_VIEW_METHOD_VERSION)
        legacy_store, reason = snapshots.publish_atomic(
            legacy_store, item, now_iso="2026-07-23T06:02:00Z")
        assert reason == "published"
        legacy = dict(remote_snapshot())
        legacy["verifiedViewSnapshots"] = snapshots.normalize_store(legacy_store)
        storage.write_checkpoint(
            value["checkpoint"], legacy,
            temp_directory=value["tempDirectory"])
        with mock.patch.object(scanner.requests, "get") as request_get:
            source = scanner._osint_restore_once()
        request_get.assert_not_called()
        assert source == "persistent_local"
        current = scanner._VERIFIED_VIEW_SNAPSHOTS["current"]
        assert [s["snapshotId"] for s in current.values()] == [item["snapshotId"]]
        assert scanner._MARKET_ARTIFACT_STATUS["verifiedViewSnapshots"][
            "restoreStatus"] == "absent"
        # The next checkpoint moves the payload into its own file.
        assert scanner._osint_persist()["verified"] is True
        assert "verifiedViewSnapshots" not in _checkpoint_blob(value)
        assert artifact_store.load(root, "verifiedViewSnapshots") is not None


def test_corrupt_artifact_file_never_blocks_restore():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        root = value["root"]
        _reset_market_stores()
        snapshot_id = _seed_verified()
        assert scanner._osint_persist()["verified"] is True
        corrupt = pathlib.Path(artifact_store.path_for(root, "marketReplay"))
        corrupt.write_text("{corrupt", encoding="utf-8")
        _reset_market_stores()
        scanner._OSINT_PERSIST_STATE.update({"restored": False})
        with mock.patch.object(scanner.requests, "get"):
            source = scanner._osint_restore_once()
        assert source == "persistent_local"
        assert scanner._MARKET_ARTIFACT_STATUS["marketReplay"] == {
            "restoreStatus": "invalid",
            "errorClass": "ArtifactError"}
        assert scanner._MARKET_ARTIFACT_STATUS["verifiedViewSnapshots"][
            "restoreStatus"] == "restored"
        current = scanner._VERIFIED_VIEW_SNAPSHOTS["current"]
        assert [s["snapshotId"] for s in current.values()] == [snapshot_id]


def test_artifact_write_failure_is_recorded_but_checkpoint_still_verifies():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        _reset_market_stores()
        _seed_verified()
        with mock.patch.object(
                scanner.argus_market_artifact_store, "write_if_changed",
                side_effect=OSError("disk full")):
            result = scanner._osint_persist()
        assert result["verified"] is True
        blob = _checkpoint_blob(value)
        row = blob["marketArtifacts"]["artifacts"]["verifiedViewSnapshots"]
        assert row["lastStatus"] == "write_failed"
        assert row["errorClass"] == "OSError"
        assert "disk full" not in json.dumps(blob)


def test_remote_projection_carries_hashes_and_status_not_payloads():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp):
        _reset_market_stores()
        _seed_verified()
        assert scanner._osint_persist()["verified"] is True
        scanner._OSINT_PERSIST_STATE.update({"restored": True})
        body = scanner.app.test_client().get(
            "/api/argus/osint/memory-snapshot").get_json()
        for name in ARTIFACTS:
            assert name not in body, name
            assert body[f"{name}StateHash"] == \
                scanner._MARKET_ARTIFACT_STATUS[name]["stateHash"]
        assert body["marketArtifacts"]["artifacts"]["verifiedViewSnapshots"][
            "lastStatus"] == "written"
        # marketLedger (owner-imported observations) stays in the projection.
        assert "marketLedger" in body
