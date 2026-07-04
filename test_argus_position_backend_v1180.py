"""V11.8.0 backend wiring tests — position-exposure endpoint is structurally
leak-free (watchlist counts only), Pro Handoff gains the watchlist-level
section with the privacy note, and nothing about the bridge changed."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_position_exposure_status_public_and_leak_free(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())     # cached-only guarantee
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/position-exposure/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "position-exposure-status-v1"
        assert d["positionData"] == "device_local_only"
        assert "送信・保存されません" in d["positionDataNoteJa"]
        wl = d["watchlistExposure"]
        assert wl["totalSymbols"] > 0 and wl["byTheme"]
        # STRUCTURAL leak check: no quantity/cost/value keys anywhere
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("quantity", "averageCost", "avgCost", "marketValue",
                       "totalMarketValue", "costBasis", "unrealizedPnl",
                       "accountType", "ownerNote"):
            assert banned not in blob, banned


def test_handoff_prompt_has_position_section_and_privacy_note():
    ph = scanner.argus_position_exposure.handoff_section(
        scanner.argus_position_exposure.watchlist_theme_exposure(
            scanner._watchlist_theme_items()))
    assert "watchlist-level" in ph["title"]
    assert "サーバーは保有を一切知りません" in ph["privacyNoteJa"]


def test_watchlist_theme_items_shape():
    items = scanner._watchlist_theme_items()
    assert items and all(set(i) == {"symbol", "market", "name"} for i in items)


def test_bridge_status_regression(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/bridge/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "bridge-status-v1"
        for k in ("bridgeProcess", "usRealtimeStatus", "jpRealtimeStatus", "bridgeMode"):
            assert k in d


def test_flow_and_institutional_regression(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        r1 = c.get("/api/argus/flow-attribution/status")
        assert r1.status_code == 200
        assert r1.get_json()["schemaVersion"] == "flow-attribution-status-v1"
        r2 = c.get("/api/argus/institutional-intel/status")
        assert r2.status_code == 200
        assert r2.get_json()["schemaVersion"] == "institutional-intel-status-v1"
