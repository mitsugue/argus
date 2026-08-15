"""V11.22.0 backend — data-quality console/status redacted + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_data_quality_console_redacted(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality/status").get_json()
        assert d["schemaVersion"] == "argus-public-diagnostics-v1"
        assert d["service"]["overall"] in ("ok", "degraded", "unavailable")
        assert d["freshness"]["expectedDisabledCount"] == 3
        assert d["recovery"]["exactColdRecovery"] == "NOT_PROVEN"
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("vaultPass", "passphrase=", "X-ARGUS-ADMIN-TOKEN", "login_pwd",
                       "Bearer ", "quantity", "averageCost", "monthlyContribution",
                       "ownerAction"):
            assert banned not in blob, banned
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_data_quality_compatibility_alias_is_retired():
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/data-quality").status_code == 404


def test_data_quality_status_summary(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality/status").get_json()
        assert d["schemaVersion"] == "argus-public-diagnostics-v1"
        assert d["freshness"]["expectedDisabledCount"] == 3
        assert "lastSuccessAt" not in json.dumps(d)      # counts/buckets only
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
