import copy

import argus_asset_chart_cache as cache


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
