"""V11.9.0 backend wiring — sync endpoints disabled-by-default + leak-free,
plus the standing regressions (bridge / II / Flow / Position)."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_plaintext_sync_routes_are_retired_even_for_admin(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-token-123")
    with scanner.app.test_client() as c:
        for path, method in (("/api/argus/portfolio-sync/pull", c.get),
                             ("/api/argus/portfolio-sync/push", c.post),
                             ("/api/argus/portfolio-sync/snapshots", c.get)):
            for headers in ({}, {"X-ARGUS-ADMIN-TOKEN": "test-token-123"}):
                r = method(path, headers=headers)
                assert r.status_code == 404
                assert "quantity" not in r.get_data(as_text=True)


def test_server_plaintext_sync_flag_is_hardcoded_off():
    # not an env flip — enabling requires a deliberate code change + auth work
    assert scanner._PORTFOLIO_SERVER_SYNC_ENABLED is False
