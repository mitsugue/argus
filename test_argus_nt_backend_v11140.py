"""V11.14.0 backend wiring — notification status redacted + SD cap flags."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_notifications_status_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/notifications/status").get_json()
        assert d["schemaVersion"] == "notification-status-v1"
        assert d["serverStoresNotifications"] is False
        assert d["deliveryChannelsEnabled"] == ["in_app"]
        assert set(d["deliveryChannelsDisabled"]) == {"browser_push", "email", "webhook"}
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
        assert "意図的" in d["noteJa"]


def test_sd_status_has_cap_flags(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/supply-demand/status").get_json()
        assert d["directionLevelModelEnabled"] is True
        assert d["heavyOverhangCapEnabled"] is True


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/bridge/status", "bridge-status-v1"),
                             ("/api/argus/session-brief/status", "session-brief-status-v1"),
                             ("/api/argus/action-priority/status", "action-priority-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/decision-quality/status", "decision-quality-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
