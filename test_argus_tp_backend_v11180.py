"""V11.18.0 backend — position-plans public watchlist-level + no execution wording + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_position_plans_public_watchlist_level_no_execution_wording(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/position-plans").get_json()
        assert d["schemaVersion"] == "trade-plan-response-v1"
        plans = d["plans"]
        assert plans, "watchlist must produce plans"
        for p in plans:
            assert p["isHeld"] == "unknown"          # server never knows holdings
            assert p["privacyLevel"] == "public_safe"
            assert p["planType"] in scanner.argus_trade_plan.PLAN_TYPES
            assert p["currentStance"] in scanner.argus_trade_plan.STANCES
            assert p["invalidationJa"] and p["nextChecksJa"]
            assert "売買指示ではない" in p["complianceNote"]
        blob = json.dumps(d, ensure_ascii=False).lower()
        for bad in scanner.argus_trade_plan.FORBIDDEN_WORDING:
            assert bad.lower() not in blob, bad
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
        assert "計画サマリ" in d["portfolioSummary"]["summaryJa"]


def test_position_plans_symbol_query(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/position-plans?symbol=5803").get_json()
        assert d["plan"]["symbol"] == "5803"
        assert d["plan"]["entryPlan"]["allowedMode"] in scanner.argus_trade_plan.ENTRY_MODES
        r404 = c.get("/api/argus/position-plans?symbol=ZZZZ9")
        assert r404.status_code == 404


def test_position_plans_status_and_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/position-plans/status").get_json()
        assert d["schemaVersion"] == "trade-plan-status-v1"
        assert d["publicLeakSafe"] is True
        assert d["storageMode"] == "public_redacted"
        assert d["sourceAvailability"]["positionExposure"] is False  # device-local
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
        # regressions — all prior layers stay intact
        for path, schema in (("/api/argus/scenarios/status", "scenario-status-v1"),
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
