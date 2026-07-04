"""V11.17.0 backend — scenarios public watchlist-level + bands-only + regressions."""
import json
import re

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_scenarios_public_watchlist_level_bands_only(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/scenarios").get_json()
        assert d["schemaVersion"] == "scenario-response-v1"
        sets = d["scenarioSets"]
        assert sets, "watchlist must produce scenario sets"
        for s in sets:
            assert s["isHeld"] == "unknown"          # server never knows holdings
            assert s["privacyLevel"] == "public_safe"
            assert s["dominantScenario"] in scanner.argus_scenario.DOMINANTS
            assert s["invalidationJa"] and s["nextChecksJa"]
            for cs in s["cases"]:
                assert cs["probabilityBand"] in scanner.argus_scenario.BANDS
        blob = json.dumps(d, ensure_ascii=False)
        assert not re.search(r"の確率で|\d{1,3}\s*[%％]で(上|下)", blob)
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
        assert d.get("marketScenario", {}).get("scenarioType") == "market_regime"


def test_scenarios_symbol_query(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/scenarios?symbol=5803").get_json()
        assert d["scenarioSet"]["symbol"] == "5803"
        labels = [x["label"] for x in d["scenarioSet"]["cases"]]
        assert "base" in labels and "bullish" in labels and "bearish" in labels
        r404 = c.get("/api/argus/scenarios?symbol=ZZZZ9")
        assert r404.status_code == 404


def test_scenarios_status_and_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/scenarios/status").get_json()
        assert d["schemaVersion"] == "scenario-status-v1"
        assert d["publicLeakSafe"] is True
        assert d["storageMode"] == "public_redacted"
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
        for path, schema in (("/api/argus/backup-safety/status", "backup-safety-status-v1"),
                             ("/api/argus/learning-review/status", "learning-review-status-v1"),
                             ("/api/argus/action-priority/status", "action-priority-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
