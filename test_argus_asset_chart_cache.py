import copy

import argus_asset_chart_cache as cache


ASSET_BOUNDARY_STATE_HASH = "28570d01647a5d1f45b655d5"


def report(symbol="5803", market="JP", period_end="2026-07-24"):
    return {
        "schemaVersion": "chart-intelligence-phase2-v1",
        "methodVersion": "chart-intelligence-phase2-v1",
        "reportId": f"chart-{symbol}-{period_end}",
        "symbol": symbol,
        "market": market,
        "status": "complete",
        "periodEnd": period_end,
        "indicators": {
            "status": "complete",
            "bars": [{"date": period_end, "close": 100.0}],
        },
    }


def boundary_store():
    store = cache.empty_store()
    for index in range(cache.MAX_RECORDS):
        symbol = f"S{index:02d}"
        item = report(symbol=symbol)
        item["displayNameJa"] = f"日経連動ETF {index} 🌐"
        store, status = cache.publish(
            store, market="JP", symbol=symbol, timeframe="daily",
            dataset_hash=f"dataset-{index:02d}", method_version="method-a",
            report=item, published_at=f"2026-07-26T08:{index:02d}:00Z")
        assert status == "published"
    assert len(store["records"]) == cache.MAX_RECORDS
    assert len(store["current"]) == cache.MAX_RECORDS
    return store


def legacy_state_hash(store):
    normalized = cache.normalize_store(store)
    return cache._hash({
        "schemaVersion": normalized["schemaVersion"],
        "records": normalized["records"],
        "current": normalized["current"],
    })


def test_logical_key_contains_complete_cache_identity():
    key = cache.logical_key(
        "JP", "5803", "daily", "dataset-a", "method-a")
    assert key == "JP:5803:daily:dataset-a:method-a"


def test_publish_readback_and_unchanged_are_idempotent():
    first, status = cache.publish(
        cache.empty_store(), market="JP", symbol="5803", timeframe="daily",
        dataset_hash="dataset-a", method_version="method-a",
        report=report(), published_at="2026-07-26T08:00:00Z")
    assert status == "published"
    record = cache.current(first, "JP", "5803", "daily")
    assert record["payload"]["reportId"] == "chart-5803-2026-07-24"
    second, status = cache.publish(
        first, market="JP", symbol="5803", timeframe="daily",
        dataset_hash="dataset-a", method_version="method-a",
        report=report(), published_at="2026-07-26T08:30:00Z")
    assert status == "unchanged"
    assert cache.state_hash(second) == cache.state_hash(first)
    assert cache.read_back_verified(first, copy.deepcopy(first))
    cursor_only = copy.deepcopy(first)
    cursor_only["cursor"] = 7
    assert cache.read_back_verified(first, cursor_only)


def test_invalid_or_tampered_report_never_becomes_current():
    missing, status = cache.publish(
        cache.empty_store(), market="JP", symbol="5803", timeframe="daily",
        dataset_hash="dataset-a", method_version="method-a",
        report={**report(), "status": "expected_skip"},
        published_at="2026-07-26T08:00:00Z")
    assert status == "report_invalid"
    assert cache.current(missing, "JP", "5803", "daily") is None

    valid, _ = cache.publish(
        cache.empty_store(), market="JP", symbol="5803", timeframe="daily",
        dataset_hash="dataset-a", method_version="method-a",
        report=report(), published_at="2026-07-26T08:00:00Z")
    key = valid["current"]["JP:5803:daily"]
    valid["records"][key]["payload"]["indicators"]["bars"][0]["close"] = 1.0
    assert cache.current(valid, "JP", "5803", "daily") is None


def test_restore_is_monotonic_and_keeps_newer_local_pointer():
    local, _ = cache.publish(
        cache.empty_store(), market="JP", symbol="5803", timeframe="daily",
        dataset_hash="new", method_version="method-a",
        report=report(period_end="2026-07-25"),
        published_at="2026-07-26T09:00:00Z")
    old, _ = cache.publish(
        cache.empty_store(), market="JP", symbol="5803", timeframe="daily",
        dataset_hash="old", method_version="method-a",
        report=report(period_end="2026-07-24"),
        published_at="2026-07-26T08:00:00Z")
    merged = cache.merge_restored(local, old)
    assert cache.current(
        merged, "JP", "5803", "daily")["datasetHash"] == "new"


def test_state_hash_diagnostic_observer_is_scalar_and_bit_identical():
    store = boundary_store()
    original = copy.deepcopy(store)
    baseline = legacy_state_hash(store)
    assert baseline == ASSET_BOUNDARY_STATE_HASH
    events = []
    observed = cache.state_hash(
        store, diagnostic_observer=lambda phase, metadata: events.append(
            (phase, metadata)))
    assert observed == baseline
    assert [phase for phase, _ in events] == [
        "hash_enter", "internal_normalize_complete",
        "hash_projection_ready", "canonical_string_ready",
        "utf8_bytes_ready", "hash_complete"]
    assert all(isinstance(value, (type(None), bool, int, float, str))
               for _, metadata in events for value in metadata.values())
    by_phase = dict(events)
    assert by_phase["canonical_string_ready"][
        "canonicalCharacterCount"] < by_phase["utf8_bytes_ready"][
            "canonicalByteCount"]
    assert store == original


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

    assert cache.state_hash(
        store, diagnostic_observer=hostile_observer) == expected
    assert events == [
        "hash_enter", "internal_normalize_complete",
        "hash_projection_ready", "canonical_string_ready",
        "utf8_bytes_ready", "hash_complete"]
    assert store == original


def test_state_hash_releases_serialization_temporaries_without_observer(
        monkeypatch):
    store = boundary_store()
    released = []
    original_canonical = cache._canonical
    original_sha256 = cache.hashlib.sha256

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
            assert "canonical" in released
            assert "bytes" in released
            return self.delegate.hexdigest()

    def tracked_canonical(value):
        return TrackedCanonical(original_canonical(value))

    def tracked_sha256(value):
        assert "canonical" in released
        assert "bytes" not in released
        return TrackedHasher(original_sha256(value))

    monkeypatch.setattr(cache, "_canonical", tracked_canonical)
    monkeypatch.setattr(cache.hashlib, "sha256", tracked_sha256)
    assert cache.state_hash(store) == ASSET_BOUNDARY_STATE_HASH
    assert released == ["canonical", "bytes"]
