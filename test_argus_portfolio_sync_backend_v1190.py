"""V11.9.0 backend wiring — sync endpoints disabled-by-default + leak-free,
plus the standing regressions (bridge / II / Flow / Position)."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_sync_status_public_and_leak_free(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/portfolio-sync/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "portfolio-sync-status-v1"
        assert d["storageLayers"]["privateCloud"]["serverPlaintextSync"] == "disabled"
        # tripwire: no sensitive field names anywhere in the public payload
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []
        blob = json.dumps(d, ensure_ascii=False)
        for banned in ("quantity", "averageCost", "costBasis", "unrealizedPnl",
                       "portfolioTotal", "accountType"):
            assert banned not in blob, banned


def test_sync_endpoints_admin_gated_and_disabled(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        # unauthenticated → 503 (no token configured in tests) or 401, never data
        for path, method in (("/api/argus/portfolio-sync/pull", c.get),
                             ("/api/argus/portfolio-sync/push", c.post),
                             ("/api/argus/portfolio-sync/snapshots", c.get)):
            r = method(path)
            assert r.status_code in (401, 403, 503)
            d = r.get_json()
            assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_sync_disabled_even_with_valid_admin(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-token-123")
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/portfolio-sync/pull",
                  headers={"X-ARGUS-ADMIN-TOKEN": "test-token-123"})
        assert r.status_code == 403
        d = r.get_json()
        assert d["status"] == "disabled"
        assert "暗号化" in d["reasonJa"]


def test_server_plaintext_sync_flag_is_hardcoded_off():
    # not an env flip — enabling requires a deliberate code change + auth work
    assert scanner._PORTFOLIO_SERVER_SYNC_ENABLED is False


def test_regressions_bridge_ii_flow_position(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/bridge/status", "bridge-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
