"""V11.12.0 backend wiring — action-priority endpoints watchlist-level only,
leak-free, plus standing regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_action_priority_public_watchlist_level(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/action-priority")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "action-priority-response-v1"
        assert d["items"]
        for it in d["items"]:
            assert it["isHeld"] == "unknown"           # server never knows holdings
            assert it["privacyLevel"] == "public_safe"
            assert it["ownerReadableWhyJa"] and it["checkNextJa"]
            assert it["priorityRank"] != "P0"          # P0 needs held context
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("quantity", "averageCost", "weightPct", "unrealizedPnl",
                       "accountType", "ownerActionNote"):
            assert banned not in blob, banned
        assert "売買指示ではない" in d["disclaimerJa"]


def test_action_priority_status_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/action-priority/status").get_json()
        assert d["schemaVersion"] == "action-priority-status-v1"
        assert d["publicLeakSafe"] is True
        assert d["heldRiskCount"] == 0                 # held context never public
        assert d["sourceAvailability"]["positionExposure"] is False
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_handoff_has_action_priority_section():
    ah = scanner.argus_action_priority.handoff_section(
        scanner._action_priority_items(cap=10))
    assert ah["title"] == "Action Priority Summary"


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/bridge/status", "bridge-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/portfolio-sync/status", "portfolio-sync-status-v1"),
                             ("/api/argus/decision-quality/status", "decision-quality-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
