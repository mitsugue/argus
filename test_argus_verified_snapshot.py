import copy
import sys
import threading
import time
import types

import argus_verified_snapshot as snapshots


def payload(symbol="1321", dataset_hash="data-a", *, status="complete"):
    bars = [
        {"date": "2026-07-22", "open": 100.0, "high": 102.0,
         "low": 99.0, "close": 101.0, "volume": 10},
        {"date": "2026-07-23", "open": 101.0, "high": 104.0,
         "low": 100.0, "close": 103.0, "volume": 12},
    ]
    contexts = {
        str(horizon): {
            "datasetHash": dataset_hash,
            "methodVersion": "market-context-replay-v2-standard-excursion",
            "asOf": "2026-07-23T06:00:00Z",
        }
        for horizon in (1, 5, 20)
    }
    return {
        "schemaVersion": "chart-intelligence-phase2-v1",
        "methodVersion": "chart-intelligence-phase2-v1",
        "asOf": "2026-07-23T06:00:00Z",
        "symbol": symbol,
        "status": status,
        "source": "verified-provider-cache",
        "automaticAiCalls": 0,
        "instrumentMetadata": {"symbol": symbol},
        "indicators": {"status": "complete", "bars": bars},
        "marketReplay": {"contexts": contexts, "cacheStatus": "updated"},
    }


def candidate(symbol="1321", horizon="5D", dataset_hash="data-a",
              method="view-method-a", quality="live", generated_at=None,
              body=None):
    generated_at = generated_at or "2026-07-23T06:01:00Z"
    return snapshots.build_snapshot(
        payload=body or payload(symbol, dataset_hash),
        kind="market-chart", instrument=symbol, horizon=horizon,
        dataset_hash=dataset_hash, method_version=method,
        as_of="2026-07-23T06:00:00Z", generated_at=generated_at,
        quality=quality,
        source_status={"chart": "complete", "replay": "updated"},
    )


def test_valid_readback_publishes_and_unchanged_dataset_skips():
    store, status = snapshots.publish_atomic(
        snapshots.empty_store(), candidate(),
        now_iso="2026-07-23T06:02:00Z")
    assert status == "published"
    assert not snapshots.needs_generation(
        store, kind="market-chart", instrument="1321", horizon="5D",
        dataset_hash="data-a", method_version="view-method-a")
    assert snapshots.needs_generation(
        store, kind="market-chart", instrument="1321", horizon="5D",
        dataset_hash="data-b", method_version="view-method-a")
    assert snapshots.needs_generation(
        store, kind="market-chart", instrument="1321", horizon="5D",
        dataset_hash="data-a", method_version="view-method-b")


def test_failed_temporary_verification_keeps_old_pointer():
    old_store, _ = snapshots.publish_atomic(
        snapshots.empty_store(), candidate(),
        now_iso="2026-07-23T06:02:00Z")
    broken = candidate(dataset_hash="data-b")
    broken["payload"]["indicators"]["bars"] = []
    broken["snapshotId"] = snapshots.snapshot_id(broken)
    result, status = snapshots.publish_atomic(
        old_store, broken, now_iso="2026-07-23T06:02:00Z")
    key = snapshots.snapshot_key("market-chart", "1321", "5D")
    assert status == "payload_hash_mismatch"
    assert result["current"][key]["datasetHash"] == "data-a"


def test_readback_and_snapshot_id_are_integrity_boundaries():
    item = candidate()
    assert snapshots.verify_snapshot(
        item, expected_kind="market-chart", expected_instrument="1321",
        expected_horizon="5D", expected_method_version="view-method-a",
        now_iso="2026-07-23T06:02:00Z") == (True, "verified")
    tampered = copy.deepcopy(item)
    tampered["payload"]["indicators"]["bars"][0]["close"] = 99.5
    assert snapshots.verify_snapshot(tampered)[1] == "payload_hash_mismatch"
    unverified = copy.deepcopy(item)
    unverified["verificationStatus"] = "temporary"
    unverified["snapshotId"] = snapshots.snapshot_id(unverified)
    assert snapshots.verify_snapshot(unverified)[1] == "readback_unverified"


def test_wrong_instrument_horizon_mock_empty_and_future_are_rejected():
    item = candidate()
    assert snapshots.verify_snapshot(
        item, expected_instrument="SPY")[1] == "instrument_mismatch"
    assert snapshots.verify_snapshot(
        item, expected_horizon="20D")[1] == "horizon_mismatch"
    mocked = candidate(body=payload(status="mock"))
    assert snapshots.verify_snapshot(mocked)[1] == "mock_payload"
    empty = candidate()
    empty["payload"]["indicators"]["bars"] = []
    empty["payloadHash"] = snapshots.payload_hash(empty["payload"])
    empty["snapshotId"] = snapshots.snapshot_id(empty)
    assert snapshots.verify_snapshot(empty)[1] == "empty_required_series"
    future = candidate(generated_at="2026-07-24T06:00:00Z")
    assert snapshots.verify_snapshot(
        future, now_iso="2026-07-23T06:00:00Z")[1] == "future_timestamp"


def test_old_or_lower_quality_response_cannot_overwrite_current():
    current, _ = snapshots.publish_atomic(
        snapshots.empty_store(),
        candidate(dataset_hash="new", generated_at="2026-07-23T06:02:00Z"),
        now_iso="2026-07-23T06:03:00Z")
    result, status = snapshots.publish_atomic(
        current,
        candidate(dataset_hash="old", generated_at="2026-07-23T06:01:00Z"),
        now_iso="2026-07-23T06:03:00Z")
    assert status == "older_rejected"
    lower = candidate(
        dataset_hash="newer", generated_at="2026-07-23T06:03:00Z",
        quality="partial")
    result, status = snapshots.publish_atomic(
        result, lower, now_iso="2026-07-23T06:04:00Z")
    assert status == "quality_downgrade_rejected"
    key = snapshots.snapshot_key("market-chart", "1321", "5D")
    assert result["current"][key]["datasetHash"] == "new"


def test_singleflight_runs_one_concurrent_producer():
    flight = snapshots.SingleFlight()
    calls = []
    results = []

    def producer():
        calls.append("called")
        time.sleep(0.03)
        return {"value": 7}

    def run():
        results.append(flight.run("same-key", producer))

    threads = [threading.Thread(target=run) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
    assert results == [{"value": 7}] * 6


def test_normalization_gc_never_removes_current_pointer():
    store = snapshots.empty_store()
    for index in range(snapshots.MAX_CURRENT + 4):
        symbol = f"S{index:02d}"
        body = payload(symbol)
        item = candidate(symbol=symbol, body=body,
                         generated_at=f"2026-07-23T06:{index:02d}:00Z")
        store, status = snapshots.publish_atomic(
            store, item, now_iso="2026-07-23T07:00:00Z")
        assert status == "published"
    assert len(store["current"]) == snapshots.MAX_CURRENT
    newest = snapshots.snapshot_key(
        "market-chart", f"S{snapshots.MAX_CURRENT + 3:02d}", "5D")
    assert newest in store["current"]
    restored = snapshots.normalize_store(store)
    assert snapshots.read_back_verified(store, restored)


def _scanner():
    if "scanner" not in sys.modules:
        moomoo = types.ModuleType("moomoo")
        moomoo.OpenQuoteContext = type("OpenQuoteContext", (), {})
        moomoo.OpenSecTradeContext = type("OpenSecTradeContext", (), {})
        moomoo.RET_OK = 0
        sys.modules["moomoo"] = moomoo
    import scanner
    return scanner


def test_public_verified_get_is_read_only_and_etag_returns_304(monkeypatch):
    scanner = _scanner()
    item = candidate(
        method=scanner._VERIFIED_VIEW_METHOD_VERSION,
        body=payload())
    store, _ = snapshots.publish_atomic(
        snapshots.empty_store(), item,
        now_iso="2026-07-23T06:02:00Z")
    monkeypatch.setattr(scanner, "_VERIFIED_VIEW_SNAPSHOTS", store)
    monkeypatch.setattr(
        scanner, "_chart_public_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("GET must not generate")))
    client = scanner.app.test_client()
    response = client.get(
        "/api/argus/chart-intelligence?"
        "scope=market&symbol=1321&horizon=5D&snapshot=verified")
    assert response.status_code == 200
    assert response.json["snapshotId"] == item["snapshotId"]
    assert response.headers["X-ARGUS-Compute-Mode"] == "read-only"
    assert response.headers["Cache-Control"] == \
        "private, max-age=0, must-revalidate"
    not_modified = client.get(
        "/api/argus/chart-intelligence?"
        "scope=market&symbol=1321&horizon=5D&snapshot=verified",
        headers={"If-None-Match": response.headers["ETag"]})
    assert not_modified.status_code == 304
    assert not_modified.data == b""


def test_public_get_returns_not_ready_without_invoking_generator(monkeypatch):
    scanner = _scanner()
    monkeypatch.setattr(scanner, "_VERIFIED_VIEW_SNAPSHOTS",
                        snapshots.empty_store())
    monkeypatch.setattr(scanner, "_MARKET_PUBLIC_REPORT_CACHE", {})
    monkeypatch.setattr(
        scanner, "_chart_public_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("GET must not generate")))
    response = scanner.app.test_client().get(
        "/api/argus/chart-intelligence?"
        "scope=market&symbol=SPY&horizon=20D&snapshot=verified")
    assert response.status_code == 503
    assert response.json["status"] == "not_ready"


def test_scheduler_publication_creates_isolated_horizon_pointers(monkeypatch):
    scanner = _scanner()
    monkeypatch.setattr(scanner, "_VERIFIED_VIEW_SNAPSHOTS",
                        snapshots.empty_store())
    monkeypatch.setattr(scanner, "_MARKET_PUBLIC_REPORT_CACHE", {})
    report = payload()
    published = scanner._publish_verified_market_views(
        report, "1321", "2026-07-23T06:01:00Z")
    assert [row["horizon"] for row in published] == [1, 5, 20]
    for horizon in (1, 5, 20):
        assert scanner._verified_market_snapshot("1321", horizon)


def test_natural_tick_skips_unchanged_and_regenerates_only_changed_target(
        monkeypatch):
    scanner = _scanner()
    rows = payload()["indicators"]["bars"]
    for row in rows:
        row.update({"availableFrom": row["date"], "adjusted": False})
    first_hash = scanner.argus_market_replay.dataset_hash(rows)
    first_report = payload(dataset_hash=first_hash)
    monkeypatch.setattr(scanner, "_VERIFIED_VIEW_SNAPSHOTS",
                        snapshots.empty_store())
    monkeypatch.setattr(scanner, "_MARKET_PUBLIC_REPORT_CACHE", {})
    scanner._publish_verified_market_views(
        first_report, "1321", "2026-07-23T06:01:00Z")
    monkeypatch.setattr(scanner, "_chart_history",
                        lambda symbol, market: copy.deepcopy(rows))
    monkeypatch.setattr(
        scanner, "_chart_public_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unchanged dataset must skip generation")))
    report, meta = scanner._precompute_verified_market_view(
        "1321", "JP", market_scope=True)
    assert meta["status"] == "unchanged"
    assert report["symbol"] == "1321"

    changed_rows = copy.deepcopy(rows)
    changed_rows[-1]["close"] = 102.5
    changed_hash = scanner.argus_market_replay.dataset_hash(changed_rows)
    changed_report = payload(dataset_hash=changed_hash)
    calls = []
    monkeypatch.setattr(scanner, "_chart_history",
                        lambda symbol, market: copy.deepcopy(changed_rows))
    monkeypatch.setattr(
        scanner, "_chart_public_report",
        lambda *args, **kwargs: calls.append(
            (args[0], kwargs["daily_rows_override"])) or changed_report)
    _, changed_meta = scanner._precompute_verified_market_view(
        "1321", "JP", market_scope=True)
    assert changed_meta["status"] == "published"
    assert [row[0] for row in calls] == ["1321"]
    assert changed_meta["datasetHash"] == changed_hash
