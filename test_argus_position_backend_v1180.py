"""V11.8.0 backend wiring tests — position-exposure endpoint is structurally
leak-free (watchlist counts only), Pro Handoff gains the watchlist-level
section with the privacy note, and nothing about the bridge changed."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


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
