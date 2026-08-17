"""Hostile provider-time contracts for current catalysts and canonical packs."""

from __future__ import annotations

from datetime import datetime, timezone

import argus_market_clock
import argus_research_mesh
import pytest

import scanner


NOW_DT = datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc)
NOW = NOW_DT.timestamp()


def _latest_us() -> str:
    return argus_market_clock.latest_completed_session_date(
        argus_market_clock.US_EQUITY, NOW_DT).isoformat()


def _upgrade(date):
    return {"gradeDate": date, "company": "Goldman Sachs",
            "action": "upgrade", "toGrade": "buy"}


def test_upgrade_adapter_rejects_future_old_malformed_and_raw_scoring(
        monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "finnhub_get", lambda *_a, **_k: [
        _upgrade("9999-12-31"), _upgrade("2020-01-01"),
        _upgrade("2026-02-30"), _upgrade(_latest_us()),
    ])

    rows = scanner.get_upgrade_downgrade("AAPL")
    assert [row["gradeDate"] for row in rows] == [_latest_us()]
    assert rows[0]["decisionUsable"] is True
    assert scanner.process_whale_ratings(
        [_upgrade("9999-12-31")], {"change_pct": 2}) == (0, "")
    assert scanner.process_whale_ratings(
        rows, {"change_pct": 2})[0] == 10


@pytest.mark.parametrize("timestamp", [None, "bad", NOW + 1, NOW + 86_400,
                                         NOW - 25 * 3600])
def test_decision_news_row_rejects_invalid_or_overage_time(timestamp):
    row = {"headline": "AAPL update", "datetime": timestamp}
    assert scanner._decision_news_row(
        row, now_epoch=NOW, timestamp_keys=("datetime",)) is None


def test_finnhub_catalyst_keeps_only_current_exact_news(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "fixture")
    scanner._FINN_CACHE.clear()

    def provider(endpoint, _params=None):
        if endpoint == "calendar/earnings":
            return {"earningsCalendar": []}
        return [
            {"headline": "missing", "source": "Wire"},
            {"headline": "future", "source": "Wire", "datetime": NOW + 1},
            {"headline": "old", "source": "Wire", "datetime": NOW - 25 * 3600},
            {"headline": "current", "source": "Wire", "datetime": NOW - 60},
        ]

    monkeypatch.setattr(scanner, "finnhub_get", provider)
    data, status = scanner._finnhub_catalyst("AAPL")
    assert status == "delayed"
    assert [row["headline"] for row in data["news"]] == ["current"]
    assert data["news"][0]["decisionUsable"] is True


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _market_news_run(monkeypatch, payload):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "fixture")
    monkeypatch.setattr(scanner.requests, "get", lambda *_a, **_k: _Response(payload))
    monkeypatch.setattr(scanner, "_translate_headlines_ja", lambda _rows: {})
    monkeypatch.setattr(scanner, "_annotate_news_corroboration", lambda _rows: None)
    scanner._MARKET_NEWS_CACHE.update({
        "data": None, "expires": 0.0, "lastSuccessfulPollAt": None,
        "lastPollAt": None, "lastErrorClass": None})
    scanner._INTEL_STORE[:] = []
    return scanner.get_market_news()


def test_market_news_transport_success_does_not_make_invalid_time_live(
        monkeypatch):
    body = _market_news_run(monkeypatch, [
        {"headline": "missing", "source": "Wire"},
        {"headline": "future", "source": "Wire", "datetime": NOW + 1},
        {"headline": "old", "source": "Wire", "datetime": NOW - 25 * 3600},
    ])
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["fetchedCount"] == 0


def test_market_news_current_item_retains_source_truth(monkeypatch):
    body = _market_news_run(monkeypatch, [{
        "headline": "Markets move", "source": "Reuters",
        "datetime": NOW - 60,
    }])
    assert body["status"] == "live"
    assert len(body["items"]) == 1
    assert body["items"][0]["decisionUsable"] is True
    assert body["items"][0]["sourceAgeSec"] == 60


class _LegacyNewsResponse:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._payload


def test_legacy_news_requires_provider_publication_time_before_prompt_or_sentinel(
        monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "NEWS_API_KEY", "fixture")
    rss = """<rss><channel><title>fixture</title>
      <item><title>Current RSS market report</title>
        <pubDate>Sun, 16 Aug 2026 02:58:00 GMT</pubDate></item>
      <item><title>Undated nuclear invasion report</title></item>
      <item><title>Old financial crisis report</title>
        <pubDate>Wed, 01 Jan 2020 00:00:00 GMT</pubDate></item>
    </channel></rss>"""
    api_payload = {"articles": [
        {"title": "Current market report", "publishedAt":
         "2026-08-16T02:59:00Z", "source": {"name": "Wire"}},
        {"title": "Missing bank collapse", "publishedAt": None,
         "source": {"name": "Wire"}},
        {"title": "Future market crash", "publishedAt":
         "2026-08-16T03:00:01Z", "source": {"name": "Wire"}},
        {"title": "Old nuclear invasion", "publishedAt":
         "2020-01-01T00:00:00Z", "source": {"name": "Wire"}},
    ]}

    def fetch(url, **_kwargs):
        if "newsapi.org" in url:
            return _LegacyNewsResponse(payload=api_payload)
        return _LegacyNewsResponse(text=rss)

    monkeypatch.setattr(scanner.requests, "get", fetch)
    rows = scanner.get_news()
    assert {row["title"] for row in rows} == {
        "Current market report", "Current RSS market report"}
    assert all(row["decisionUsable"] is True for row in rows)
    assert scanner.sentinel_check(rows)["action"] == "HOLD"


def test_sentinel_needs_two_distinct_current_reports_and_never_double_counts(
        monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    one = {"title": "Nuclear invasion and financial crisis",
           "publishedAt": "2026-08-16T02:59:00Z"}
    assert scanner.sentinel_check([one]) == {
        "action": "HOLD", "risk": 2,
        "reason": "Nuclear invasion and financial crisis"}
    assert scanner.sentinel_check([one, dict(one)])["action"] == "HOLD"
    second = {"title": "Bank collapse triggers circuit breaker",
              "publishedAt": "2026-08-16T02:58:00Z"}
    assert scanner.sentinel_check([one, second])["action"] == "SELL_ALL"
    assert scanner.sentinel_check([{
        "title": "Bank collapse", "publishedAt": None,
        "firstDetectedAt": "2026-08-16T02:59:00Z"}])["risk"] == 0
    assert scanner.detect_leaks([{
        "title": "Breaking: emergency rate cut", "publishedAt": None,
        "firstDetectedAt": "2026-08-16T02:59:00Z"}]) == []


def test_corroboration_ignores_receipt_only_old_and_future_mesh_rows(
        monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    primary = {"headline": "Fed rate cut shakes markets",
               "source": "Reuters",
               "publishedAt": "2026-08-16T02:59:00Z"}
    for published in (None, "2020-01-01T00:00:00Z",
                      "2026-08-16T03:00:01Z"):
        scanner._INTEL_STORE[:] = [{
            "sourceId": "cnbc_public",
            "title": primary["headline"], "publishedAt": published,
            "firstDetectedAt": "2026-08-16T02:59:30Z",
            "linkedAssets": []}]
        row = scanner._annotate_news_corroboration([dict(primary)])[0]
        assert row["corroboration"] == "single"
    scanner._INTEL_STORE[0]["publishedAt"] = "2026-08-16T02:58:00Z"
    assert scanner._annotate_news_corroboration(
        [dict(primary)])[0]["corroboration"] == "corroborated"


def test_event_intel_never_uses_receipt_as_publication_authority(monkeypatch):
    monkeypatch.setattr(scanner, "_ai_now_iso",
                        lambda: "2026-08-16T03:00:00Z")
    raw = {"sourceId": "yahoo_finance_public",
           "title": "Goldman upgrades NVDA", "linkedAssets": ["NVDA"],
           "firstDetectedAt": "2026-08-16T02:59:00Z",
           "fetchedAt": "2026-08-16T02:59:00Z"}
    scanner._INTEL_STORE[:] = [argus_research_mesh.normalize_item(raw)]
    with scanner.app.test_client() as client:
        body = client.get(
            "/api/argus/events/NVDA/institutional-intelligence").get_json()
    assert body["items"] == []
    assert body["omittedOldCount"] == 1

    raw["publishedAt"] = "2026-08-16T02:59:00Z"
    scanner._INTEL_STORE[:] = [argus_research_mesh.normalize_item(raw)]
    with scanner.app.test_client() as client:
        body = client.get(
            "/api/argus/events/NVDA/institutional-intelligence").get_json()
    assert body["count"] == 1
    assert body["items"][0]["decisionUsable"] is True
    assert body["items"][0]["publishedAt"] == "2026-08-16T02:59:00Z"


def test_mover_session_start_is_canonical_and_holidays_fail_closed(monkeypatch):
    holiday = datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc)
    trading = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)
    assert scanner._mover_move_started_iso("JP", holiday) is None
    assert scanner._mover_move_started_iso(
        "JP", trading) == "2026-08-12T00:00:00Z"
    monkeypatch.setattr(scanner, "_ai_now_iso",
                        lambda: "2026-08-11T01:00:00Z")
    monkeypatch.setattr(scanner, "_build_mover_cause_inputs",
                        lambda *_a, **_k: {})
    with pytest.raises(ValueError, match="current_trading_session_unavailable"):
        scanner._mover_cause_for("7203", "JP", -6.0)


def test_caos_lead_rejects_undated_future_and_old_intel(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_entity_link", lambda _blob: [{
        "symbol": "AAPL", "via": "name", "term": "AAPL",
        "relationJa": "direct",
    }])
    monkeypatch.setattr(scanner, "_caos_audit_maybe_record", lambda *_a, **_k: None)
    invalid = [
        {"title": "missing"},
        {"title": "future", "publishedAt": "2026-08-16T03:00:01Z"},
        {"title": "old", "publishedAt": "2020-01-01T00:00:00Z"},
    ]
    assert scanner._caos_catalyst_for("AAPL", [], invalid) is None
    current = scanner._caos_catalyst_for("AAPL", [], [{
        "title": "current", "publishedAt": "2026-08-16T02:59:00Z",
        "sourceId": "wire",
    }])
    assert current["titleJa"] == "current"
    assert current["publishedAt"] == "2026-08-16T02:59:00Z"


def test_event_card_context_rejects_untimed_official_confirmation(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    context = scanner._event_card_context([{
        "eventId": "ev-1", "eventType": "PRICE_MOVE", "symbol": "7203",
        "source": "price",
    }], tdnet_snapshot={
        "official": True,
        "bySymbol": {"7203": [{
            "title": "増配", "official": True, "material": True,
            "disclosedAt": None,
        }]},
    })["ev-1"]
    assert context["has_official"] is False
    assert "official:tdnet" not in (context["source_ids"] or [])


def test_evidence_pack_invalid_official_time_is_not_groundable(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    monkeypatch.setattr(scanner, "_ai_now_iso",
                        lambda: "2026-08-16T03:00:00Z")
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_a: None)
    monkeypatch.setattr(scanner, "_visibility_guard_cached_only", lambda: {})
    monkeypatch.setattr(scanner, "_events_active_list", lambda: [])
    monkeypatch.setattr(scanner, "_tdnet_recent_cached_only", lambda: {
        "official": True,
        "bySymbol": {"7203": [{
            "title": "増配", "official": True, "material": True,
            "disclosedAt": "9999-12-31T00:00:00Z",
        }]},
    })
    monkeypatch.setattr(scanner, "_source_coverage_cached_only", lambda: None)
    monkeypatch.setattr(scanner, "_market_depth_proof_cached_only", lambda: None)
    monkeypatch.setattr(scanner, "_learning_memory_compact_for_symbol", lambda *_a: None)
    scanner._INTEL_STORE[:] = []

    pack = scanner._build_evidence_pack("7203", "JP")
    assert pack["officialDisclosures"] == []
    assert pack["allowedUse"]["canGroundJudgment"] is False
    assert pack["allowedUse"]["canAffectTodayCall"] is False
    assert "cache:tdnet:source_time_unusable" in pack["missingConfirmations"]


def test_expired_regime_cannot_confirm_macro_cause(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: NOW)
    scanner._REGIME_CACHE.update({
        "data": {"regime": {"label": "RISK_ON"}}, "expires": 0.0})
    monkeypatch.setattr(scanner, "_MOVER_MACRO_VIEW", lambda: [{
        "phase": "post_result", "eventTimeUtc": "2026-08-16T01:00:00Z",
        "eventCode": "CPI", "title": "CPI", "source": "official",
    }])
    monkeypatch.setattr(scanner, "_ai_now_iso",
                        lambda: "2026-08-16T03:00:00Z")
    monkeypatch.setattr(scanner, "_official_events_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_official_events_by_symbol", lambda *_a: [])
    monkeypatch.setattr(scanner, "_macro_analysis_restore_once", lambda: None)
    scanner._FINN_CACHE.clear()
    scanner._CAT_CACHE.update({"data": None, "expires": 0.0})

    evidence = scanner._build_mover_cause_inputs(
        "AAPL", "US", change_pct=3.2, cached_only=True)
    assert evidence["macroEvents"][0]["marketConsistent"] is False


def test_public_cause_attribution_preserves_unofficial_yanoshin_authority(
        monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW_DT if tz is None else NOW_DT.astimezone(tz)

    monkeypatch.setattr(scanner, "datetime", FixedDatetime)
    monkeypatch.setattr(scanner, "_ai_now_iso",
                        lambda: "2026-08-16T03:00:00Z")
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot",
                        lambda: {"stocks": []})
    monkeypatch.setattr(scanner, "get_us_watchlist_snapshot",
                        lambda: {"stocks": []})
    monkeypatch.setattr(scanner, "get_catalysts_snapshot",
                        lambda: {"items": []})
    monkeypatch.setattr(scanner, "get_tdnet_recent", lambda: {
        "official": False, "status": "fallback-live",
        "provider": "yanoshin-tdnet",
        "bySymbol": {"6965": [{
            "provider": "yanoshin-tdnet", "official": False,
            "time": "2026-08-16T11:59:00+09:00",
            "title": "浜松ホトニクス、業績予想を下方修正",
            "sentiment": "negative", "category": "guidance_down",
        }]},
    })
    monkeypatch.setattr(scanner, "_news_ja_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_institutional_signals",
                        lambda **_kwargs: [])
    monkeypatch.setattr(scanner, "_flow_attribution_for",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scanner, "_mover_causes_restore_once", lambda: None)
    monkeypatch.setattr(
        scanner, "_mover_cause_for",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("none")))
    scanner._INTEL_STORE[:] = []

    result = scanner.get_cause_attribution("6965", "JP")
    news = next(row for row in result["news"]
                if "下方修正" in row.get("titleJa", ""))
    assert news["source"] == "yanoshin-tdnet"
    assert news["provider"] == "yanoshin-tdnet"
    assert news["official"] is False
    assert news["decisionUsable"] is False
    assert result["osint"]["primary"] is None
    assert result["osint"]["causes"][0]["sourceClass"] == "unknown"
