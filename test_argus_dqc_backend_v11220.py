"""V11.22.0 backend — data-quality console/status redacted + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_data_quality_console_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json()
        assert d["schemaVersion"] == "data-quality-v1"
        assert d["overallStatus"] in scanner.argus_data_quality.OVERALL
        # 恒久の意図的無効3件 — 障害として数えられない
        dis = [s for s in d["sourceHealth"] if s["isExpectedDisabled"]]
        assert len(dis) == 3
        for s in dis:
            assert s["status"] == "disabled_expected"
        assert d["bridgeHealth"]["jpRealtimeStatus"] in ("disabled", "unknown", "ok",
                                                         "entitlement_unavailable")
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("vaultPass", "passphrase=", "X-ARGUS-ADMIN-TOKEN", "login_pwd",
                       "Bearer ", "quantity", "averageCost", "monthlyContribution",
                       "ownerAction"):
            assert banned not in blob, banned
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_data_quality_status_summary(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality/status").get_json()
        assert d["schemaVersion"] == "data-quality-status-v1"
        assert d["storageMode"] == "public_redacted"
        assert d["expectedDisabledCount"] == 3
        assert "lastSuccessAt" not in json.dumps(d)      # counts/buckets only
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/review-pack/status", "review-pack-status-v1"),
                             ("/api/argus/fire-core/status", "fire-core-status-v1"),
                             ("/api/argus/portfolio-strategy/status", "portfolio-strategy-status-v1"),
                             ("/api/argus/position-plans/status", "trade-plan-status-v1"),
                             ("/api/argus/scenarios/status", "scenario-status-v1"),
                             ("/api/argus/backup-safety/status", "backup-safety-status-v1"),
                             ("/api/argus/learning-review/status", "learning-review-status-v1"),
                             ("/api/argus/notifications/status", "notification-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1"),
                             ("/api/argus/bridge/status", "bridge-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
