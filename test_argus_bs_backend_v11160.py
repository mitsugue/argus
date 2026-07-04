"""V11.16.0 backend — backup-safety status architecture-only + regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_backup_safety_status_architecture_only(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/backup-safety/status").get_json()
        assert d["schemaVersion"] == "backup-safety-status-v1"
        assert d["architecture"]["serverKnowsDeviceProtectionState"] is False
        assert d["architecture"]["vaultPayloadVisibleToServer"] is False
        assert d["storageMode"] == "redacted"
        blob = json.dumps(d, ensure_ascii=False)
        for banned in scanner.argus_backup_safety.FORBIDDEN_SUBSTRINGS:
            assert banned not in blob, banned
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_regressions(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/bridge/status", "bridge-status-v1"),
                             ("/api/argus/learning-review/status", "learning-review-status-v1"),
                             ("/api/argus/notifications/status", "notification-status-v1"),
                             ("/api/argus/session-brief/status", "session-brief-status-v1"),
                             ("/api/argus/action-priority/status", "action-priority-status-v1"),
                             ("/api/argus/supply-demand/status", "supply-demand-status-v1"),
                             ("/api/argus/decision-quality/status", "decision-quality-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
