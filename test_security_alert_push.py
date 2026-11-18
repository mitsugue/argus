"""2026-11-15 owner 「警報を通知で」: which alerts become an app notification."""
import scanner


def _reset(monkeypatch):
    monkeypatch.setattr(scanner, "_SECURITY_PUSH", {})
    monkeypatch.setattr(scanner, "add_log", lambda *a, **k: None)


def test_tokenless_request_is_not_an_alert_but_a_wrong_token_is(monkeypatch):
    _reset(monkeypatch)
    scanner.send_security_alert({"type": "admin_auth_failed", "tokenPresent": False, "meta": {}})
    assert scanner._SECURITY_PUSH == {}          # the scheduled smoke test sends no token
    scanner.send_security_alert({"type": "admin_auth_failed", "tokenPresent": True,
                                 "meta": {"country": "US", "ip": "203.0.113.9"}})
    row = scanner._SECURITY_PUSH["admin_token_mismatch"]
    assert row["count"] == 1 and row["country"] == "US" and "ip" not in row


def test_one_notice_per_type_an_hour(monkeypatch):
    _reset(monkeypatch)
    scanner._security_push_note("bridge_signature_rejected", {}, now=1000.0)
    scanner._security_push_note("bridge_signature_rejected", {}, now=1000.0 + 3599)
    assert scanner._SECURITY_PUSH["bridge_signature_rejected"] == {
        "type": "bridge_signature_rejected", "at": 1000.0, "count": 2, "country": ""}
    scanner._security_push_note("bridge_signature_rejected", {}, now=1000.0 + 3600)
    assert scanner._SECURITY_PUSH["bridge_signature_rejected"]["at"] == 4600.0
    scanner._security_push_note("run_blocked_budget", {}, now=5000.0)   # not a security alert
    assert "run_blocked_budget" not in scanner._SECURITY_PUSH


def test_wrong_admin_token_marks_the_alert(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "synthetic-correct")
    seen = []
    monkeypatch.setattr(scanner, "send_security_alert", lambda event: seen.append(event))
    with scanner.app.test_request_context(headers={"X-ARGUS-ADMIN-TOKEN": "synthetic-wrong"}):
        assert scanner._require_admin()[2] == 401
    with scanner.app.test_request_context():
        assert scanner._require_admin()[2] == 401
    assert [event["tokenPresent"] for event in seen] == [True, False]


def test_wrong_token_refused_by_the_sign_in_boundary_is_an_alert(monkeypatch):
    # 2026-11-18 08:30 production test: a wrong admin token without an owner
    # session was answered 401 by the sign-in boundary and no alert was made.
    _reset(monkeypatch)
    auth = scanner.app.extensions["argus_owner_auth"]
    monkeypatch.setattr(auth, "enabled", True)
    monkeypatch.setattr(auth, "admin", "synthetic-correct")
    monkeypatch.setattr(auth, "session", lambda: None)
    before = scanner._AI_GATE_STATE["failedAttempts"]
    client = scanner.app.test_client()
    response = client.get("/api/argus/security-status",
                          headers={"X-ARGUS-ADMIN-TOKEN": "synthetic-wrong", "CF-IPCountry": "us"})
    assert response.status_code == 401
    row = scanner._SECURITY_PUSH["admin_token_mismatch"]
    assert row["count"] == 1 and row["country"] == "US"
    assert scanner._AI_GATE_STATE["failedAttempts"] == before + 1
    # The scheduled smoke test sends no token: still not an alert.
    assert client.get("/api/argus/security-status").status_code == 401
    assert scanner._SECURITY_PUSH["admin_token_mismatch"]["count"] == 1
    notices = scanner.argus_web_push.security_proposals(
        list(scanner._SECURITY_PUSH.values()), row["at"] + 1)
    assert [n["title"] for n in notices] == ["ARGUS 警報｜違う鍵で管理の操作が試されました"]
