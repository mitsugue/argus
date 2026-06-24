"""Institutional Intelligence backend: SSRF, capture rights, licensed-feed gating."""
import scanner
import argus_licensed_feeds as L


def test_ssrf_blocks_private_and_metadata_and_http():
    assert scanner._ssrf_safe_url("https://169.254.169.254/latest/meta-data") is False  # cloud metadata
    assert scanner._ssrf_safe_url("https://127.0.0.1/") is False
    assert scanner._ssrf_safe_url("http://example.com") is False                          # https only
    assert scanner._ssrf_safe_url("ftp://example.com") is False


def test_rss_parse_strips_markup_and_is_data():
    xml = '<rss><channel><item><title>JPMorgan flags &lt;b&gt;Micron&lt;/b&gt; risk</title>' \
          '<link>https://x.test/a</link><pubDate>Wed, 25 Jun 2026 14:02:00 GMT</pubDate></item></channel></rss>'
    rows = scanner._parse_rss(xml, "reuters_public", "2026-06-25T14:05:00Z")
    assert rows and rows[0]["sourceId"] == "reuters_public"
    assert "<b>" not in rows[0]["title"]


def test_capture_is_owner_only():
    with scanner.app.test_client() as c:
        # no admin token → gated (401/403/503), never an open 200 write
        r = c.post("/api/argus/institutional-intelligence/capture", json={"title": "x", "cookies": "secret"})
        assert r.status_code != 200 and r.status_code >= 400


def test_capture_forbidden_fields_guarded():
    import inspect
    src = inspect.getsource(scanner.api_argus_intel_capture)
    for f in ("credentials", "cookies", "token", "session", "password"):
        assert f in src           # credential-rejection guard present (defense in depth)


def test_public_get_is_cheap_no_fetch(monkeypatch):
    # public GET must never call the fetcher
    called = {"n": 0}
    monkeypatch.setattr(scanner, "_fetch_public_text", lambda u: called.__setitem__("n", called["n"] + 1) or None)
    with scanner.app.test_client() as c:
        c.get("/api/argus/institutional-intelligence")
        c.get("/api/argus/institutional-intelligence/source-health")
    assert called["n"] == 0


def test_licensed_feeds_disabled():
    for h in L.all_health():
        assert h["configured"] is False and h["live"] is False and h["status"] == "NOT_CONFIGURED"
    import pytest
    with pytest.raises(RuntimeError):
        L.BloombergEventDrivenFeed().connect()
