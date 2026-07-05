"""V11.19.1 backend — fire-core status redacted + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_fire_core_status_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/fire-core/status").get_json()
        assert d["schemaVersion"] == "fire-core-status-v1"
        assert d["serverKnowsFundData"] is False
        assert d["trackingComputed"] == "on_device_only"
        assert d["manualInputSupported"] is True
        assert d["realtimePricingRequired"] is False
        assert d["storageMode"] == "public_redacted"
        assert d["publicLeakSafe"] is True
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("units", "navPrice", "marketValue", "monthlyContribution",
                       "accountType", "fireCoreTotal", "quantity", "averageCost",
                       "fundName", "mortgage", "income"):
            assert banned not in blob, banned
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/portfolio-strategy/status", "portfolio-strategy-status-v1"),
                             ("/api/argus/position-plans/status", "trade-plan-status-v1"),
                             ("/api/argus/scenarios/status", "scenario-status-v1"),
                             ("/api/argus/backup-safety/status", "backup-safety-status-v1"),
                             ("/api/argus/learning-review/status", "learning-review-status-v1"),
                             ("/api/argus/notifications/status", "notification-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/bridge/status", "bridge-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
