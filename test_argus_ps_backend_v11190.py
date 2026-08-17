"""V11.19.0 backend — portfolio-strategy status redacted + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_portfolio_strategy_status_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/portfolio-strategy/status").get_json()
        assert d["schemaVersion"] == "portfolio-strategy-status-v1"
        assert d["serverKnowsHoldings"] is False
        assert d["serverKnowsStrategyDetails"] is False
        assert d["strategyComputed"] == "on_device_only"
        assert d["storageMode"] == "public_redacted"
        assert d["publicLeakSafe"] is True
        assert d["sourceAvailability"]["positionExposure"] is False
        blob = json.dumps(d, ensure_ascii=False)
        # no holdings / income / mortgage / weights ever in the public doc
        for banned in ("quantity", "averageCost", "weightPct", "ownerAction",
                       "mortgage", "income", "top1", "corePct", "tacticalPct",
                       "fireStatus"):
            assert banned not in blob, banned
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/position-plans/status", "trade-plan-status-v1"),
                             ("/api/argus/scenarios/status", "scenario-status-v1"),
                             ("/api/argus/backup-safety/status", "backup-safety-status-v1"),
                             ("/api/argus/learning-review/status", "learning-review-status-v1"),
                             ("/api/argus/notifications/status", "notification-status-v1"),
                             ("/api/argus/session-brief/status", "session-brief-status-v1"),
                             ("/api/argus/action-priority/status", "action-priority-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1"),
                             ("/api/argus/decision-quality/status", "decision-quality-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1"),
                             ("/api/argus/bridge/status", "bridge-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
        # v11.18 wording safeguard still holds with strategy wired in
        d = c.get("/api/argus/position-plans").get_json()
        blob = json.dumps(d, ensure_ascii=False).lower()
        for bad in scanner.argus_trade_plan.FORBIDDEN_WORDING:
            assert bad.lower() not in blob, bad
