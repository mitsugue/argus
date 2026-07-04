"""V11.13.0 backend wiring — session-brief endpoints redacted, regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_session_brief_public_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/session-brief")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "session-brief-response-v1"
        b = d["brief"]
        assert b["sessionType"] in ("morning", "pre_market", "intraday", "close",
                                    "after_close", "weekend", "unknown")
        assert b["ownerModeJa"] and b["headlineJa"] and b["summaryJa"]
        assert b["privacyLevel"] == "public_safe"
        assert b["whatNotToDoJa"] and b["nextChecksJa"]
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("quantity", "averageCost", "weightPct", "unrealizedPnl",
                       "accountType", "ownerActionNote"):
            assert banned not in blob, banned
        assert "売買指示ではない" in d["disclaimerJa"]


def test_session_brief_status(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/session-brief/status").get_json()
        assert d["schemaVersion"] == "session-brief-status-v1"
        assert d["publicLeakSafe"] is True
        assert d["privateComposition"] == "public_redacted"
        assert d["sourceAvailability"]["positionExposure"] is False
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/bridge/status", "bridge-status-v1"),
                             ("/api/argus/action-priority/status", "action-priority-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/decision-quality/status", "decision-quality-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
