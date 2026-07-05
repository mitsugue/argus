"""V11.20.0 backend — review-pack status redacted + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_review_pack_status_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/review-pack/status").get_json()
        assert d["schemaVersion"] == "review-pack-status-v1"
        assert d["serverStoresPacks"] is False
        assert d["autoExternalAICall"] is False
        assert d["generatedLocally"] is True
        assert d["storageMode"] == "public_redacted"
        assert d["publicLeakSafe"] is True
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("quantity", "averageCost", "fundName", "monthlyContribution",
                       "ownerAction", "weightPct", "vaultPass", "Bearer "):
            assert banned not in blob, banned
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/fire-core/status", "fire-core-status-v1"),
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
        # pro-handoff (server watchlist context) still works and stays wording-clean
        d = c.get("/api/argus/pro-handoff").get_json()
        assert isinstance(d.get("promptText"), str) and d["promptText"]
        low = d["promptText"].lower()
        for bad in scanner.argus_trade_plan.FORBIDDEN_WORDING:
            assert bad.lower() not in low, bad
