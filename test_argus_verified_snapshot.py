import copy
import sys
import threading
import time
import types

import argus_verified_snapshot as snapshots


VERIFIED_BOUNDARY_STATE_HASH = \
    "bed35eda35d476b28112eece7186cf058191ce43da1b279f3cda95df9ab0f5e1"


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


def boundary_store():
    store = snapshots.empty_store()
    for index in range(snapshots.MAX_CURRENT):
        symbol = f"S{index:02d}"
        body = payload(symbol, f"data-{index:02d}")
        body["instrumentMetadata"]["nameJa"] = f"日経連動ETF {index} 🌐"
        item = candidate(
            symbol=symbol, dataset_hash=f"data-{index:02d}", body=body,
            generated_at=f"2026-07-23T06:{index:02d}:00Z")
        key = snapshots.snapshot_key("market-chart", symbol, "5D")
        store["current"][key] = item
    store["history"] = [{
        "key": f"market-chart:S{index % snapshots.MAX_CURRENT:02d}:5D",
        "snapshotId": f"vs-history-{index:02d}",
        "replacedAt": f"2026-07-{21 + index // 24:02d}T05:{index % 24:02d}:00Z",
    } for index in range(snapshots.MAX_HISTORY)]
    store["lastPublishedAt"] = "2026-07-23T06:23:00Z"
    assert len(store["current"]) == snapshots.MAX_CURRENT
    assert len(store["history"]) == snapshots.MAX_HISTORY
    return store


def legacy_state_hash(store):
    return snapshots._sha(snapshots.normalize_store(store))


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


def test_state_hash_diagnostic_observer_is_scalar_and_bit_identical():
    store = boundary_store()
    original = copy.deepcopy(store)
    baseline = legacy_state_hash(store)
    assert baseline == VERIFIED_BOUNDARY_STATE_HASH
    events = []
    observed = snapshots.state_hash(
        store, diagnostic_observer=lambda phase, metadata: events.append(
            (phase, metadata)))
    assert observed == baseline
    assert [phase for phase, _ in events] == [
        "hash_enter", "internal_normalize_complete", "stable_tree_ready",
        "canonical_string_ready", "utf8_bytes_ready", "hash_complete"]
    assert all(isinstance(value, (type(None), bool, int, float, str))
               for _, metadata in events for value in metadata.values())
    by_phase = dict(events)
    assert by_phase["canonical_string_ready"][
        "canonicalCharacterCount"] < by_phase["utf8_bytes_ready"][
            "canonicalByteCount"]
    assert store == original


def test_state_hash_integral_floats_match_integer_json_truth():
    floating = boundary_store()
    integral = copy.deepcopy(floating)
    for item in integral["current"].values():
        for bar in item["payload"]["indicators"]["bars"]:
            for field in ("open", "high", "low", "close"):
                bar[field] = int(bar[field])
    assert snapshots.state_hash(floating) == VERIFIED_BOUNDARY_STATE_HASH
    assert snapshots.state_hash(integral) == VERIFIED_BOUNDARY_STATE_HASH
    assert snapshots.read_back_verified(floating, integral)


def test_state_hash_observer_exceptions_and_mutation_are_fail_open():
    store = boundary_store()
    original = copy.deepcopy(store)
    expected = legacy_state_hash(store)
    events = []

    def hostile_observer(phase, metadata):
        events.append(phase)
        metadata.clear()
        metadata["payload"] = {"mustNotEscape": store}
        raise RuntimeError("diagnostic failure")

    assert snapshots.state_hash(
        store, diagnostic_observer=hostile_observer) == expected
    assert events == [
        "hash_enter", "internal_normalize_complete", "stable_tree_ready",
        "canonical_string_ready", "utf8_bytes_ready", "hash_complete"]
    assert store == original


def test_state_hash_normalized_reuses_provenance_and_keeps_pinned_truth(
        monkeypatch):
    normalized = snapshots.normalize_store(boundary_store())
    original = copy.deepcopy(normalized)
    events = []

    def forbidden_normalize(_value):
        raise AssertionError("trusted normalized hash must not normalize again")

    monkeypatch.setattr(snapshots, "normalize_store", forbidden_normalize)
    digest = snapshots.state_hash_normalized(
        normalized, diagnostic_observer=lambda phase, metadata: events.append(
            (phase, metadata)))
    assert digest == VERIFIED_BOUNDARY_STATE_HASH
    assert [phase for phase, _ in events] == [
        "hash_enter", "normalized_input_reused", "stable_tree_ready",
        "canonical_string_ready", "utf8_bytes_ready", "hash_complete"]
    assert all(isinstance(value, (type(None), bool, int, float, str))
               for _, metadata in events for value in metadata.values())
    assert normalized == original


def test_state_hash_normalized_hostile_observer_is_fail_open():
    normalized = snapshots.normalize_store(boundary_store())
    original = copy.deepcopy(normalized)
    events = []

    def hostile_observer(phase, metadata):
        events.append(phase)
        metadata.clear()
        metadata["payload"] = {"mustNotEscape": normalized}
        raise RuntimeError("diagnostic failure")

    assert snapshots.state_hash_normalized(
        normalized,
        diagnostic_observer=hostile_observer) == VERIFIED_BOUNDARY_STATE_HASH
    assert events == [
        "hash_enter", "normalized_input_reused", "stable_tree_ready",
        "canonical_string_ready", "utf8_bytes_ready", "hash_complete"]
    assert normalized == original


def test_state_hash_normalized_untrusted_copy_falls_back_to_raw_contract(
        monkeypatch):
    untrusted = copy.deepcopy(snapshots.normalize_store(boundary_store()))
    original = copy.deepcopy(untrusted)
    normalize_calls = []
    events = []
    original_normalize = snapshots.normalize_store

    def counted_normalize(value):
        normalize_calls.append(value)
        return original_normalize(value)

    monkeypatch.setattr(snapshots, "normalize_store", counted_normalize)
    assert snapshots.state_hash_normalized(
        untrusted, diagnostic_observer=lambda phase, metadata: events.append(
            (phase, metadata))) == VERIFIED_BOUNDARY_STATE_HASH
    assert normalize_calls == [untrusted]
    assert [phase for phase, _ in events] == [
        "normalized_input_fallback", "hash_enter",
        "internal_normalize_complete", "stable_tree_ready",
        "canonical_string_ready", "utf8_bytes_ready", "hash_complete"]
    assert events[0][1] == {"reason": "untrusted_provenance"}
    assert untrusted == original


def test_state_hash_releases_serialization_temporaries_without_observer(
        monkeypatch):
    store = boundary_store()
    released = []
    original_dumps = snapshots.json.dumps
    original_sha256 = snapshots.hashlib.sha256

    class TrackedStable(dict):
        def __del__(self):
            released.append("stable")

    class TrackedBytes(bytes):
        def __del__(self):
            released.append("bytes")

    class TrackedCanonical(str):
        def encode(self, *args, **kwargs):
            return TrackedBytes(super().encode(*args, **kwargs))

        def __del__(self):
            released.append("canonical")

    class TrackedHasher:
        def __init__(self, delegate):
            self.delegate = delegate

        def hexdigest(self):
            assert "stable" in released
            assert "canonical" in released
            assert "bytes" in released
            return self.delegate.hexdigest()

    def stable_clone(value):
        if isinstance(value, float) and snapshots.math.isfinite(value) and \
                value.is_integer():
            return int(value)
        if isinstance(value, list):
            return [stable_clone(item) for item in value]
        if isinstance(value, dict):
            return {key: stable_clone(item) for key, item in value.items()}
        return value

    def tracked_stable(value):
        cloned = stable_clone(value)
        if isinstance(value, dict) and \
                value.get("schemaVersion") == snapshots.STORE_SCHEMA_VERSION:
            return TrackedStable(cloned)
        return cloned

    def tracked_dumps(*args, **kwargs):
        encoded = original_dumps(*args, **kwargs)
        return (TrackedCanonical(encoded)
                if args and isinstance(args[0], TrackedStable) else encoded)

    def tracked_sha256(value):
        delegate = original_sha256(value)
        if not isinstance(value, TrackedBytes):
            return delegate
        assert "stable" in released
        assert "canonical" in released
        assert "bytes" not in released
        return TrackedHasher(delegate)

    monkeypatch.setattr(snapshots, "_stable_json_value", tracked_stable)
    monkeypatch.setattr(snapshots.json, "dumps", tracked_dumps)
    monkeypatch.setattr(snapshots.hashlib, "sha256", tracked_sha256)
    assert snapshots.state_hash(store) == VERIFIED_BOUNDARY_STATE_HASH
    assert released == ["stable", "canonical", "bytes"]


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
    weak_not_modified = client.get(
        "/api/argus/chart-intelligence?"
        "scope=market&symbol=1321&horizon=5D&snapshot=verified",
        headers={"If-None-Match": f'W/{response.headers["ETag"]}'})
    assert weak_not_modified.status_code == 304
    assert weak_not_modified.data == b""


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
