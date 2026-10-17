"""v13.5.3 dedicated news-mailbox intake — reliability matrix (§32 INTAKE)."""
import base64
import json

import argus_gmail_intake as gi

ENV = {
    "ARGUS_NEWS_GMAIL_CLIENT_ID": "cid",
    "ARGUS_NEWS_GMAIL_CLIENT_SECRET": "sec",
    "ARGUS_NEWS_GMAIL_REFRESH_TOKEN": "rt",
}
NOW = 1_800_000_000.0


class Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(mid, subject, *, sender="news@nikkei.com",
                  auth="spf=pass dkim=pass header.d=nikkei.com dmarc=pass",
                  body="米長期金利が上昇 https://www.nikkei.com/article/x1"):
    return {
        "id": mid, "internalDate": str(int(NOW * 1000)),
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": f"日経速報 <{sender}>"},
                {"name": "Return-Path", "value": f"<bounce@nikkei.com>"},
                {"name": "Authentication-Results",
                 "value": f"mx.google.com; {auth}"},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{mid}@nikkei.com>"},
                {"name": "Date", "value": "Wed, 20 Aug 2026 01:00:00 +0900"},
            ],
            "parts": [{"mimeType": "text/plain",
                       "body": {"data": b64(body)}}],
        },
    }


def transport(routes):
    """routes: list of (matcher, response-or-callable) consumed in order of
    match; records every call for assertions."""
    calls = []

    def http(method, url, **kw):
        calls.append((method, url, kw))
        for match, response in routes:
            if match in url:
                return response(method, url, kw) if callable(response) \
                    else response
        raise AssertionError(f"unexpected url {url}")

    http.calls = calls
    return http


TOKEN_OK = ("oauth2.googleapis.com", Resp(200, {"access_token": "at"}))


def test_unconfigured_and_oauth_failures_are_visible_states():
    result = gi.run_intake_cycle(env={}, state={}, http=transport([]),
                                 now_epoch=NOW)
    assert result["status"] == "MAILBOX_UNCONFIGURED"

    http = transport([("oauth2.googleapis.com", Resp(400, {}))])
    result = gi.run_intake_cycle(env=ENV, state={}, http=http, now_epoch=NOW)
    assert result["status"] == "OAUTH_EXPIRED"


def test_first_run_reconciles_and_sets_cursor():
    http = transport([
        TOKEN_OK,
        ("messages/m1", Resp(200, gmail_message("m1", "米30年債利回り5%突破"))),
        ("messages", Resp(200, {"messages": [{"id": "m1"}]})),
        ("profile", Resp(200, {"historyId": "777"})),
    ])
    result = gi.run_intake_cycle(env=ENV, state={}, http=http, now_epoch=NOW)
    assert result["status"] == "HEALTHY"
    assert result["mode"] == "reconcile"
    assert result["state"]["historyId"] == "777"
    assert [m["messageId"] for m in result["messages"]] == ["m1"]
    subject = result["messages"][0]["subject"]
    assert "30年債" in subject


def test_incremental_history_and_duplicate_notifications():
    history = Resp(200, {"historyId": "801", "history": [
        {"messagesAdded": [{"message": {"id": "m2"}},
                           {"message": {"id": "m2"}},   # duplicate notification
                           {"message": {"id": "m3"}}]},
    ]})
    http = transport([
        TOKEN_OK,
        ("history", history),
        ("messages/m2", Resp(200, gmail_message("m2", "日銀が臨時会合"))),
        ("messages/m3", Resp(200, gmail_message("m3", "コラム:今週のまとめ"))),
    ])
    state = {"historyId": "800", "seenMessageIds": ["m1"]}
    result = gi.run_intake_cycle(env=ENV, state=state, http=http,
                                 now_epoch=NOW)
    assert result["status"] == "HEALTHY"
    assert result["mode"] == "incremental"
    assert [m["messageId"] for m in result["messages"]] == ["m2", "m3"]
    assert result["state"]["historyId"] == "801"
    # duplicate email across cycles is suppressed by the seen-set
    again = gi.run_intake_cycle(env=ENV, state=result["state"],
                                http=transport([TOKEN_OK, ("history", Resp(
                                    200, {"historyId": "801", "history": [
                                        {"messagesAdded": [
                                            {"message": {"id": "m2"}}]}]}))]),
                                now_epoch=NOW + 60)
    assert again["messages"] == []


def test_history_gap_fails_into_bounded_reconciliation():
    http = transport([
        TOKEN_OK,
        ("history", Resp(404, {})),
        ("messages/m9", Resp(200, gmail_message("m9", "原油急騰"))),
        ("messages", Resp(200, {"messages": [{"id": "m9"}]})),
        ("profile", Resp(200, {"historyId": "900"})),
    ])
    result = gi.run_intake_cycle(
        env=ENV, state={"historyId": "1", "seenMessageIds": []},
        http=http, now_epoch=NOW)
    assert result["status"] == "HEALTHY"
    assert result["mode"] == "reconcile"
    assert result["state"]["historyId"] == "900"
    assert [m["messageId"] for m in result["messages"]] == ["m9"]


def test_transient_api_error_is_degraded_not_silent_skip():
    http = transport([TOKEN_OK, ("history", Resp(503, {}))])
    result = gi.run_intake_cycle(
        env=ENV, state={"historyId": "5"}, http=http, now_epoch=NOW)
    assert result["status"] == "DEGRADED"
    assert result["state"].get("historyId") == "5"  # cursor untouched

    http = transport([TOKEN_OK, ("messages", Resp(500, {}))])
    result = gi.run_intake_cycle(env=ENV, state={}, http=http, now_epoch=NOW)
    assert result["status"] == "RECONCILIATION_FAILED"


def test_restart_resumes_from_persisted_cursor():
    # simulated restart: fresh process, only the durable state survives
    durable = {"historyId": "800", "seenMessageIds": ["m2"]}
    http = transport([
        TOKEN_OK,
        ("history", Resp(200, {"historyId": "802", "history": [
            {"messagesAdded": [{"message": {"id": "m2"}},
                               {"message": {"id": "m4"}}]}]})),
        ("messages/m4", Resp(200, gmail_message("m4", "半導体大手が決算"))),
    ])
    result = gi.run_intake_cycle(env=ENV, state=durable, http=http,
                                 now_epoch=NOW)
    assert [m["messageId"] for m in result["messages"]] == ["m4"]
    assert result["state"]["historyId"] == "802"


def test_sender_authentication_quarantines_spoof():
    genuine = gi.normalize_message(gmail_message("g1", "米金利上昇"))
    check = gi.authenticate_sender(genuine["headers"], ["nikkei.com"])
    assert check["authenticated"] is True

    spoof = gi.normalize_message(gmail_message(
        "s1", "重要なお知らせ", sender="news@nikkei.com.evil.example",
        auth="spf=fail dkim=fail"))
    check = gi.authenticate_sender(spoof["headers"], ["nikkei.com"])
    assert check["authenticated"] is False
    assert any("from_domain_not_allowed" in r
               for r in check["quarantineReasons"])

    unauth = gi.normalize_message(gmail_message(
        "s2", "速報", auth="spf=fail dkim=none"))
    check = gi.authenticate_sender(unauth["headers"], ["nikkei.com"])
    assert check["authenticated"] is False
    assert "no_spf_or_dkim_pass" in check["quarantineReasons"]


def test_excerpt_is_bounded_and_never_full_archive():
    huge = gmail_message("b1", "長文", body="あ" * 50_000)
    normalized = gi.normalize_message(huge)
    assert len(normalized["excerpt"]) <= gi.MAX_EXCERPT_CHARS


def test_read_only_scope_constant():
    assert gi.GMAIL_SCOPE.endswith("gmail.readonly")
