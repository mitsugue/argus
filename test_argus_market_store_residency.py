"""Store residency: the two largest derived stores leave RAM between saves.

Contract (v13.7.58):
- after a verified save whose per-item files match the artifact, the
  in-memory verified-view and asset-report stores are emptied (detached);
- public reads (verified snapshot, today-headline closes, asset report,
  the daily public report pointer) are served from the per-item files;
- a save while detached carries the resident hash into the checkpoint and
  the public projection, never normalizes or rewrites an empty store, and
  the remote read-back still verifies against that hash;
- every generator re-attaches (reloads the artifact) before publishing;
- the owner diagnostics route exposes the residency scalars only.
"""
import copy
import tempfile
from unittest import mock

import pytest

import argus_asset_chart_cache as asset_cache
import argus_market_artifact_items as artifact_items
import argus_market_artifact_store as artifact_store
import argus_verified_snapshot as snapshots
import scanner
from test_argus_market_artifact_split import (
    _isolate_market_stores, _reset_market_stores, _seed_verified)  # noqa: F401
from test_argus_persistent_mission_storage import scanner_storage
from test_argus_v12_2_10 import _snapshot as remote_journal_snapshot


def _asset_report(symbol="7203", timeframe="daily"):
    return {"symbol": symbol, "market": "JP", "status": "live", "reportId": f"r-{timeframe}",
            "indicators": {"bars": [{"date": "2026-09-26", "close": 2980.0}]}}


def _seed_asset():
    scanner._attach_market_store("assetChartReports", "test_seed")
    store = asset_cache.normalize_store(scanner._ASSET_CHART_REPORTS)
    for timeframe in ("daily", "weekly"):
        store, publication = asset_cache.publish(
            store, market="JP", symbol="7203", timeframe=timeframe,
            dataset_hash="ds-1", method_version=scanner._ASSET_CHART_METHOD_VERSION,
            report=_asset_report(timeframe=timeframe), published_at="2026-09-28T12:00:00Z")
        assert publication == "published", publication
    scanner._ASSET_CHART_REPORTS.clear()
    scanner._ASSET_CHART_REPORTS.update(store)


def test_save_detaches_and_public_reads_come_from_item_files():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        _reset_market_stores()
        snapshot_id = _seed_verified()
        _seed_asset()
        assert scanner._osint_persist()["verified"] is True
        residency = scanner._MARKET_STORE_RESIDENCY
        assert residency["verifiedViewSnapshots"]["attached"] is False
        assert residency["assetChartReports"]["attached"] is False
        assert residency["verifiedViewSnapshots"]["counts"] == {"currentCount": 1}
        assert residency["assetChartReports"]["counts"] == {"recordCount": 2, "currentCount": 2}
        assert scanner._VERIFIED_VIEW_SNAPSHOTS["current"] == {}
        assert scanner._ASSET_CHART_REPORTS["records"] == {}
        # Verified view from its file, verified through the unchanged verifier.
        served = scanner._verified_market_snapshot("1321", 5)
        assert served["snapshotId"] == snapshot_id
        assert scanner._verified_snapshot_closes("1321")
        # Asset report from its file, through the unchanged validator.
        record = scanner._asset_chart_current("JP", "7203", "weekly")
        assert record["payload"]["reportId"] == "r-weekly"
        assert scanner._asset_chart_current("JP", "9999", "daily") is None
        with scanner.app.test_client() as client:
            body = client.get("/api/argus/chart-intelligence?scope=asset&market=JP"
                              "&symbol=7203&timeframe=daily").get_json()
            assert body["assetChartCache"]["status"] == "hit"
            verified = client.get("/api/argus/chart-intelligence?scope=market&symbol=1321"
                                  "&horizon=5D&snapshot=verified")
            assert verified.status_code == 200
            assert verified.get_json()["snapshotId"] == snapshot_id
        assert scanner._MARKET_ITEM_CACHE.status()["entries"] >= 2
        # Residency scalars ride the owner diagnostics route.
        projection = scanner._market_store_residency_projection()
        assert projection["stores"]["verifiedViewSnapshots"]["lastDetachReason"] == "checkpoint_persist"
        assert set(projection) == {"schemaVersion", "stores", "itemCache", "itemReadFailures"}


def test_save_while_detached_keeps_hash_and_never_writes_an_empty_artifact():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        _reset_market_stores()
        _seed_verified()
        assert scanner._osint_persist()["verified"] is True
        root = value["root"]
        doc_before = artifact_store.load(root, "verifiedViewSnapshots")
        hash_before = doc_before["stateHash"]
        with mock.patch.object(scanner.argus_market_artifact_store, "write_if_changed",
                               side_effect=AssertionError("detached store must not be written")), \
                mock.patch.object(scanner.argus_verified_snapshot, "normalize_store",
                                  side_effect=AssertionError("detached store must not be normalized")):
            result = scanner._osint_persist()
        assert result["verified"] is True
        blob = scanner.argus_persistent_storage.load_checkpoint(value["checkpoint"], require_seal=True)
        assert blob["verifiedViewSnapshotsStateHash"] == hash_before
        assert artifact_store.load(root, "verifiedViewSnapshots")["payload"] == doc_before["payload"]
        # The public projection and the remote read-back use the same hash.
        scanner._OSINT_PERSIST_STATE.update({"restored": True})
        body = scanner.app.test_client().get("/api/argus/osint/memory-snapshot").get_json()
        assert body["verifiedViewSnapshotsStateHash"] == hash_before
        assert body["verifiedViewSnapshotsStateHash"] != snapshots.state_hash(snapshots.empty_store())
        saved = dict(scanner._VERIFIED_VIEW_SNAPSHOT_REMOTE)
        saved_ack = copy.deepcopy(scanner._REMOTE_ACK)
        try:
            # A valid Remote Journal snapshot carrying the same hash verifies
            # the detached store without any resident copy.
            blob = remote_journal_snapshot(list(scanner._OPS_JOURNAL))
            blob["verifiedViewSnapshotsStateHash"] = hash_before
            scanner._remote_readback_ack(now_iso="2026-07-15T12:00:00+09:00", blob=blob)
            assert scanner._VERIFIED_VIEW_SNAPSHOT_REMOTE["verificationStatus"] == "verified"
        finally:
            scanner._VERIFIED_VIEW_SNAPSHOT_REMOTE.clear()
            scanner._VERIFIED_VIEW_SNAPSHOT_REMOTE.update(saved)
            scanner._REMOTE_ACK.clear()
            scanner._REMOTE_ACK.update(saved_ack)


def test_generators_reattach_before_publishing_and_nothing_is_lost():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        _reset_market_stores()
        first_id = _seed_verified(symbol="1321")
        assert scanner._osint_persist()["verified"] is True
        assert scanner._market_store_attached("verifiedViewSnapshots") is False
        # A publish through the production path reloads the file first, so
        # the earlier snapshot survives alongside the new one.
        from test_argus_verified_snapshot import payload
        report = payload()
        report["instrumentMetadata"]["symbol"] = "SPY"
        report["symbol"] = "SPY"
        published = scanner._publish_verified_market_views(
            report, "SPY", "2026-09-28T12:05:00Z")
        assert [row["publication"] for row in published] == ["published"] * 3
        assert scanner._market_store_attached("verifiedViewSnapshots") is True
        current = scanner._VERIFIED_VIEW_SNAPSHOTS["current"]
        assert first_id in {s["snapshotId"] for s in current.values()}
        assert len(current) == 4
        assert scanner._osint_persist()["verified"] is True
        assert scanner._market_store_attached("verifiedViewSnapshots") is False
        assert len(artifact_items.index(value["root"], "verifiedViewSnapshots")["items"]) == 4
        # The daily public report resolves through the pointer, not a copy.
        pointer = scanner._MARKET_PUBLIC_REPORT_CACHE[("market", "SPY", "daily")]
        assert pointer == {"verifiedPointer": {"symbol": "SPY", "horizon": 5}}
        body = scanner.app.test_client().get(
            "/api/argus/chart-intelligence?scope=market&symbol=SPY").get_json()
        assert body["symbol"] == "SPY" and body["marketReplay"]["cacheStatus"] == "hit"


def test_detach_refuses_when_item_files_are_missing_or_stale():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        _reset_market_stores()
        _seed_verified()
        with mock.patch.object(scanner.argus_market_artifact_items, "sync",
                               side_effect=OSError("disk full")):
            assert scanner._osint_persist()["verified"] is True
        assert scanner._market_store_attached("verifiedViewSnapshots") is True
        assert scanner._MARKET_STORE_RESIDENCY["verifiedViewSnapshots"][
            "lastDetachOutcome"].startswith(("items_not_current", "index_invalid"))
        assert scanner._MARKET_ARTIFACT_STATUS["verifiedViewSnapshots"]["items"] == {
            "status": "sync_failed", "errorClass": "OSError"}
        # Next healthy save writes the items and detaches.
        assert scanner._osint_persist()["verified"] is True
        assert scanner._market_store_attached("verifiedViewSnapshots") is False


def test_reader_tolerates_missing_root_and_corrupt_item_files():
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as value:
        _reset_market_stores()
        _seed_verified()
        assert scanner._osint_persist()["verified"] is True
        path = artifact_items.path_for(value["root"], "verifiedViewSnapshots", "market-chart:1321:5D")
        open(path, "w", encoding="utf-8").write("{corrupt")
        scanner._MARKET_ITEM_CACHE.clear()
        assert scanner._verified_market_snapshot("1321", 5) is None
        assert scanner._MARKET_ITEM_READ_FAILURES.get("verifiedViewSnapshots") == 1
        with scanner.app.test_client() as client:
            response = client.get("/api/argus/chart-intelligence?scope=market&symbol=1321"
                                  "&horizon=5D&snapshot=verified")
        assert response.status_code == 503 and response.get_json()["status"] == "not_ready"
    # Without a durability root the reader degrades to "absent", never raises.
    with mock.patch.object(scanner, "_market_artifact_root", lambda: None):
        assert scanner._market_store_item("verifiedViewSnapshots", "x") is None
