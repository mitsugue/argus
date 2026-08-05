"""Market-specific moomoo truth and private registered-universe contract."""
import datetime as dt
import importlib.util
import json
import sys
import types

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)

import argus_market_universe as universe
import scanner


class FakeDF:
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        for index, row in enumerate(self.rows):
            yield index, row


class FakeQC:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_market_snapshot(self, codes):
        market = str(codes[0]).split(".", 1)[0]
        self.calls.append((market, list(codes)))
        return self.responses[market]


def load_bridge(monkeypatch):
    monkeypatch.delenv("ARGUS_DISABLE_JP_QUOTES", raising=False)
    spec = importlib.util.spec_from_file_location("moomoo_push_market_truth", "bridge/moomoo_push.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quote(market, symbol, stamp):
    return {"market": market, "symbol": symbol, "price": 100.0,
            "exchangeTs": stamp, "quoteRight": "realtime"}


NOW = dt.datetime(2026, 8, 4, 7, 0, tzinfo=dt.timezone.utc)


def test_us_live_jp_entitlement_unavailable():
    rows = [quote("US", "AAPL", "2026-08-04T06:59:50Z")]
    us = universe.market_telemetry("US", ["US.AAPL"], rows, now=NOW)
    jp = universe.market_telemetry(
        "JP", ["JP.7203"], rows, now=NOW, availability="entitlement_unavailable")
    assert us["status"] == "live" and us["freshness"] == "REALTIME"
    assert jp["status"] == "entitlement_unavailable"
    assert jp["fallbackProvider"] == "J-Quants" and jp["freshness"] == "EOD"


def test_jp_and_us_live_are_independently_proven():
    rows = [quote("US", "AAPL", "2026-08-04T06:59:50Z"),
            quote("JP", "7203", "2026-08-04T06:59:40Z")]
    assert universe.market_telemetry("US", ["US.AAPL"], rows, now=NOW)["status"] == "live"
    assert universe.market_telemetry("JP", ["JP.7203"], rows, now=NOW)["status"] == "live"


def test_bridge_down_cannot_leave_markets_live(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1000.0)
    monkeypatch.setitem(scanner._BRIDGE_HB, "receivedAt", 1.0)
    monkeypatch.setitem(scanner._BRIDGE_HB, "data", {
        "openDStatus": "connected",
        "marketData": universe.public_transport("live", {
            "us": {"status": "live", "provider": "moomoo", "freshness": "REALTIME"},
            "jp": {"status": "live", "provider": "moomoo", "freshness": "REALTIME"},
        }),
    })
    doc = scanner._bridge_status_doc()
    assert doc["transportStatus"] == "stale"
    assert doc["markets"]["us"]["status"] == "transport_unavailable"
    assert doc["markets"]["jp"]["status"] == "transport_unavailable"


def test_fixed_baseline_plus_owner_universe_and_duplicates():
    codes, meta = universe.bounded_universe(
        ["US.SPY", "JP.1306", "US.SPY"],
        ["US.AAPL", "JP.7203", "US.AAPL"])
    assert codes["US"].count("US.SPY") == 1
    assert "US.AAPL" in codes["US"] and "JP.7203" in codes["JP"]
    assert meta["rejectedCount"] == 0


def test_universe_sync_failure_preserves_last_verified(monkeypatch):
    bridge = load_bridge(monkeypatch)
    state = dict(bridge.STATE)
    last = ["US.SPY", "US.PRIVATE"]
    codes, status = bridge.sync_registered_codes(
        ["US.SPY"], last, state=state, fetcher=lambda: None)
    assert codes == last
    assert status == "preserved_last_verified"


def test_symbol_cap_is_market_specific():
    owner = [f"US.A{i}" for i in range(8)] + [f"JP.{7000 + i}" for i in range(8)]
    # US.A0 is invalid and rejected; caps still apply independently.
    codes, meta = universe.bounded_universe([], owner, jp_cap=3, us_cap=4)
    assert len(codes["JP"]) == 3 and len(codes["US"]) == 4
    assert meta["truncatedCount"]["JP"] > 0


def test_stale_timestamp_and_partial_coverage_are_not_live():
    stale = universe.market_telemetry(
        "US", ["US.AAPL"], [quote("US", "AAPL", "2026-08-04T06:40:00Z")], now=NOW)
    partial = universe.market_telemetry(
        "US", ["US.AAPL", "US.MSFT"],
        [quote("US", "AAPL", "2026-08-04T06:59:50Z")], now=NOW)
    assert stale["status"] == "stale" and stale["staleCount"] == 1
    assert partial["status"] == "partial" and partial["unavailableCount"] == 1


def test_private_symbol_never_enters_heartbeat_or_public_status(monkeypatch, capsys):
    bridge = load_bridge(monkeypatch)
    state = dict(bridge.STATE)
    payload = {"verified": True, "markets": {
        "us": {"codes": ["US.PLTR"]}, "jp": {"codes": ["JP.7203"]}}}
    codes, status = bridge.sync_registered_codes(
        ["US.SPY"], ["US.SPY"], state=state, fetcher=lambda: payload,
        now_iso="2026-08-04T07:00:00Z")
    assert status == "verified" and "US.PLTR" in codes
    heartbeat = json.dumps(bridge.build_heartbeat(state), sort_keys=True)
    assert "PLTR" not in heartbeat and "7203" not in heartbeat
    assert capsys.readouterr().out == ""


def test_jp_recovery_probe_and_automatic_fallback_exit(monkeypatch):
    bridge = load_bridge(monkeypatch)
    state = dict(bridge.STATE)
    state.update({"jpBlockUntil": 1000.0, "jpLastErrorClass": "permission",
                  "lastJpPushAt": None})
    jp_df = FakeDF([{"code": "JP.7203", "last_price": 100.0,
                     "prev_close_price": 99.0, "volume": 1,
                     "update_time": "2026-08-04 16:00:00"}])
    qc = FakeQC({"JP": (0, jp_df), "US": (0, FakeDF([]))})
    rows, attempted = bridge.fetch_market_quotes(
        qc, {"JP": ["JP.7203"], "US": []}, state=state,
        disable_jp=False, now=1001.0, ret_ok=0)
    assert attempted is True and state["jpLastErrorClass"] is None
    bridge.record_push_result(rows, 1, state=state, now_iso="2026-08-04T07:00:00Z")
    assert bridge.jp_realtime_status(state, False) == "ok"
    assert bridge.bridge_mode(state, False) == "full"


def test_authenticated_private_endpoint_is_bounded_and_position_free(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_layer2b_read_latest", lambda: {
        "members": [
            {"symbol": "AAPL", "market": "US", "ownerState": "held"},
            {"symbol": "7203", "market": "JP", "ownerState": "watch"},
        ]})
    monkeypatch.setattr(scanner, "_private_symbol_manifest_read", lambda: {
        "schemaVersion": universe.CLIENT_MANIFEST_SCHEMA,
        "revision": "abcd1234", "asOf": "2026-08-05T00:00:00Z",
        "symbols": ["JP.6758", "US.NVDA"],
    })
    with scanner.app.test_client() as client:
        response = client.get("/api/argus/bridge/private-symbol-universe")
    assert response.status_code == 200
    body = response.get_json()
    assert body["verified"] is True
    assert "US.AAPL" in body["markets"]["us"]["codes"]
    assert "US.NVDA" in body["markets"]["us"]["codes"]
    blob = json.dumps(body)
    for forbidden in ("quantity", "averageCost", "costBasis", "pnl", "positions"):
        assert forbidden not in blob


def test_client_manifest_rejects_portfolio_fields_and_empty_unknown():
    valid = {
        "schemaVersion": universe.CLIENT_MANIFEST_SCHEMA,
        "revision": "1234abcd", "asOf": "2026-08-05T00:00:00Z",
        "symbols": ["JP.7203", "US.NVDA", "JP.7203"],
    }
    assert universe.validate_client_symbol_manifest(valid)["symbols"] == [
        "JP.7203", "US.NVDA"]
    for forbidden in ("quantity", "avgCost", "currentValue", "pnl",
                      "allocation", "notes", "labels"):
        bad = dict(valid)
        bad[forbidden] = 1
        try:
            universe.validate_client_symbol_manifest(bad)
            assert False, forbidden
        except ValueError as exc:
            assert str(exc) == "client_symbol_manifest_fields_rejected"
    try:
        universe.validate_client_symbol_manifest({**valid, "symbols": []})
        assert False
    except ValueError as exc:
        assert str(exc) == "client_symbol_manifest_empty_or_unknown"


def test_owner_manifest_ingest_persists_only_sanitized_document(monkeypatch):
    captured = {}
    monkeypatch.setattr(scanner, "_require_owner_sync",
                        lambda _token=None: (True, None, 200))
    monkeypatch.setattr(scanner, "_gh_private_put",
                        lambda path, content, message, overwrite=True:
                        captured.update({"path": path, "content": content}) or True)
    manifest = {
        "schemaVersion": universe.CLIENT_MANIFEST_SCHEMA,
        "revision": "1234abcd", "asOf": "2026-08-05T00:00:00Z",
        "symbols": ["JP.7203", "US.NVDA"],
    }
    with scanner.app.test_client() as client:
        response = client.post(
            "/api/argus/calibration/private-symbol-manifest",
            json={"ownerToken": "not-persisted", "manifest": manifest})
    assert response.status_code == 200
    persisted = json.loads(captured["content"])
    assert persisted == manifest
    assert captured["path"] == \
        "market-universe/client-symbol-manifest.json"
    assert "ownerToken" not in captured["content"]


def test_public_private_universe_status_is_count_only(monkeypatch):
    monkeypatch.setattr(scanner, "_PRIVATE_SYMBOL_MANIFEST_STATE", {
        "status": "verified", "asOf": "2026-08-05T00:00:00Z",
        "verifiedAt": "2026-08-05T00:01:00Z",
        "counts": {"JP": 2, "US": 3},
    })
    with scanner.app.test_client() as client:
        body = client.get(
            "/api/argus/market-data/private-universe-status").get_json()
    assert body["configuredCount"] == {"JP": 2, "US": 3}
    blob = json.dumps(body)
    assert "symbols" not in blob.lower()
    assert "revision" not in blob.lower()


def test_unknown_or_empty_remote_universe_is_not_complete():
    baseline = ["US.SPY"]
    codes, status = universe.choose_verified_universe(
        {"verified": False, "markets": {}}, baseline=baseline,
        last_verified=None)
    assert codes == baseline and status == "preserved_last_verified"
