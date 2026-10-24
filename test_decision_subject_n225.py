"""2026-10-23 (owner approval): 日経平均の値(立花リアルタイム、無い時はYahooの遅延値)を
日本の判断の取得元として認めます。現在の判断の対象を日経平均に移してください.

The current judgment's JP subject is the Nikkei 225 itself. Its value comes
from the existing index quote (Tachibana code 101 when current, else Yahoo
delayed) and, without one, from the Yahoo daily series. Nothing else may
become a JP decision source, and the Nikkei follows the Tokyo calendar."""
from datetime import datetime, timedelta, timezone

import argus_market_clock
import argus_market_data_truth
import scanner


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _client():
    scanner._DECISION_EVIDENCE_CACHE.clear()
    return scanner.app.test_client()


def _quote(now, *, realtime):
    return {"status": "AVAILABLE", "quote": {
        "price": 49210.5, "changePct": -0.8, "realtime": realtime,
        "tradedAt": _iso(now - timedelta(seconds=40 if realtime else 1200)),
        "receivedAt": _iso(now - timedelta(seconds=5))}}


def test_default_subjects_name_the_nikkei_225_not_1321():
    assert scanner._DECISION_EVIDENCE_DEFAULT_SYMBOLS[0] == "N225"
    assert "1321" not in scanner._DECISION_EVIDENCE_DEFAULT_SYMBOLS


def test_only_tachibana_and_yahoo_are_added_after_the_existing_jp_sources():
    assert argus_market_data_truth.repository_provider_priority("JP", "QUOTE") == (
        "moomoo", "jquants", "tachibana", "yahoo")
    assert argus_market_data_truth.repository_provider_priority("JP", "OHLCV_BAR") == ("jquants",)


def test_the_nikkei_225_runs_on_the_tokyo_calendar():
    assert argus_market_clock.asset_market("N225") == argus_market_clock.JP_EQUITY
    assert argus_market_clock.asset_market("^N225") == argus_market_clock.JP_EQUITY
    assert argus_market_clock.forecast_clock("N225")["market"] == argus_market_clock.JP_EQUITY


def test_tachibana_value_is_the_nikkei_subject_when_current(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe",
                        lambda: _quote(now, realtime=True))
    entry = _client().get("/api/argus/decision-evidence?symbols=N225").get_json()["subjects"]["N225"]
    assert entry["subject"]["market"] == "JP"
    assert entry["marketTruth"]["status"] == "AVAILABLE"
    assert entry["predictionLedger"]["status"] == "AVAILABLE"
    assert entry["jpMarketEngineBuyEligible"] is False
    row, provider = scanner._decision_evidence_watch_row("N225", "JP")
    assert provider == "tachibana" and row["status"] == "live" and row["price"] == 49210.5


def test_yahoo_delayed_value_is_used_when_tachibana_has_none(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe",
                        lambda: _quote(now, realtime=False))
    row, provider = scanner._decision_evidence_watch_row("N225", "JP")
    assert provider == "yahoo" and row["status"] == "delayed"


def test_without_a_quote_the_yahoo_daily_close_is_the_fallback(monkeypatch):
    now = datetime.now(timezone.utc)
    session = argus_market_clock.latest_completed_session_date(argus_market_clock.JP_EQUITY, now)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe",
                        lambda: {"status": "UNAVAILABLE", "quote": None})
    monkeypatch.setattr(scanner, "_verified_snapshot_closes", lambda symbol: [])
    monkeypatch.setattr(scanner, "_chart_history_cached", lambda symbol, market: [
        {"date": (session - timedelta(days=1)).isoformat(), "close": 49000.0},
        {"date": session.isoformat(), "close": 49210.0}])
    row, provider = scanner._decision_evidence_history_row("N225", "JP")
    assert provider == "yahoo" and row["price"] == 49210.0
    entry = _client().get("/api/argus/decision-evidence?symbols=N225").get_json()["subjects"]["N225"]
    assert str(entry["marketTruth"]["observedAt"])[:10] == session.isoformat()
    assert entry["marketTruth"]["status"] == "AVAILABLE"


def test_no_value_at_all_fails_closed(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe",
                        lambda: {"status": "UNAVAILABLE", "quote": None})
    monkeypatch.setattr(scanner, "_verified_snapshot_closes", lambda symbol: [])
    monkeypatch.setattr(scanner, "_chart_history_cached", lambda symbol, market: [])
    entry = _client().get("/api/argus/decision-evidence?symbols=N225").get_json()["subjects"]["N225"]
    assert entry["marketTruth"]["status"] == "MISSING"
    assert entry["verificationFailures"]["marketTruth"] == "quote_row_unavailable"
