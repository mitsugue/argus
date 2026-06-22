"""Tests for Layer 2B owner watchlist sync (argus_watchlist_sync.py)."""
import argus_watchlist_sync as W


def test_accepts_clean_membership():
    ok, cleaned, errs = W.validate_sync_payload({"items": [
        {"symbol": "7203", "market": "JP", "enabled": True},
        {"symbol": "AAPL", "market": "US"},
        {"symbol": "285A", "market": "JP"},
        {"symbol": "bitcoin", "market": "CRYPTO"},
    ]})
    assert ok and not errs
    assert len(cleaned["items"]) == 4


def test_rejects_portfolio_fields():
    for bad in ("quantity", "averageCost", "unrealizedPL", "notes", "holdings", "trades"):
        ok, _, errs = W.validate_sync_payload({"items": [
            {"symbol": "7203", "market": "JP", bad: 100}]})
        assert ok is False
        assert any(bad in e for e in errs)


def test_rejects_nested_portfolio_fields():
    ok, _, errs = W.validate_sync_payload(
        {"items": [{"symbol": "7203", "market": "JP"}], "meta": {"costBasis": 999}})
    assert ok is False and any("costBasis" in e for e in errs)


def test_invalid_symbol_rejected():
    ok, _, errs = W.validate_sync_payload({"items": [
        {"symbol": "NOTREAL!!", "market": "JP"}]})
    assert ok is False


def test_max_symbols():
    items = [{"symbol": f"{1000+i}", "market": "JP"} for i in range(W.MAX_SYMBOLS + 5)]
    ok, _, errs = W.validate_sync_payload({"items": items})
    assert ok is False and any("too many" in e for e in errs)


def test_idempotent_dedup():
    ok, cleaned, _ = W.validate_sync_payload({"items": [
        {"symbol": "7203", "market": "JP"}, {"symbol": "7203", "market": "JP"}]})
    assert ok and len(cleaned["items"]) == 1


def test_content_hash_order_independent():
    a = [{"symbol": "7203", "market": "JP", "enabled": True},
         {"symbol": "AAPL", "market": "US", "enabled": True}]
    b = list(reversed(a))
    assert W.content_hash(a) == W.content_hash(b)


def test_content_hash_changes_on_membership_change():
    a = [{"symbol": "7203", "market": "JP", "enabled": True}]
    b = [{"symbol": "7203", "market": "JP", "enabled": True},
         {"symbol": "AAPL", "market": "US", "enabled": True}]
    assert W.content_hash(a) != W.content_hash(b)


def test_membership_snapshot_immutable_shape():
    ok, cleaned, _ = W.validate_sync_payload({"items": [
        {"symbol": "5803", "market": "JP", "enabled": True},
        {"symbol": "META", "market": "US", "enabled": True},
        {"symbol": "9501", "market": "JP", "enabled": False}]})
    snap = W.build_membership_snapshot(
        cleaned["items"], effective_date="2026-06-24",
        generated_at="2026-06-23T12:00:00Z", snapshot_id="wl-abc")
    assert snap["immutable"] is True
    assert snap["symbolCount"] == 2          # disabled 9501 excluded
    assert snap["cohortId"] == "owner_watchlist_dynamic"
    assert snap["contentHash"].startswith("sha256:")
    syms = {m["symbol"] for m in snap["members"]}
    assert "5803" in syms and "META" in syms and "9501" not in syms


def test_brkb_dotted_ticker_ok():
    ok, _, _ = W.validate_sync_payload({"items": [{"symbol": "BRK.B", "market": "US"}]})
    assert ok
