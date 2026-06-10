# Unit tests for ARGUS's pure rule functions (v9.10). These guard the judgment
# core: a refactor that silently flips a threshold must fail CI, not reach the
# user. Run: python3 -m pytest test_rules.py -q   (no network, no API keys).
import datetime

import pytz

import scanner


# ── Rates / volatility classification ────────────────────────────────
def test_rates_pressure_edges():
    assert scanner._classify_rates_pressure(0.09) == "High"
    assert scanner._classify_rates_pressure(0.08) == "Medium"   # > 0.08 is High
    assert scanner._classify_rates_pressure(0.03) == "Medium"
    assert scanner._classify_rates_pressure(0.0) == "Neutral"
    assert scanner._classify_rates_pressure(-0.04) == "Relief"


def test_risk_volatility_edges():
    assert scanner._classify_risk_volatility(22) == "High"
    assert scanner._classify_risk_volatility(18) == "Medium"
    assert scanner._classify_risk_volatility(17.9) == "Low"


# ── Market-regime scoring ─────────────────────────────────────────────
def test_scale_ret_caps():
    assert scanner._scale_ret(0.05) == 0.5
    assert scanner._scale_ret(0.20) == 1.0    # capped at +10%
    assert scanner._scale_ret(-0.20) == -1.0  # capped at -10%


def test_etf_momentum_full_history():
    closes = [110.0, 108.0, 105.0] + [100.0] * 22  # newest-first
    m = scanner._etf_momentum(closes)
    assert m["limited"] is False
    assert -1.0 <= m["score"] <= 1.0
    assert m["momentum1d"] > 0 and m["momentum5d"] > 0 and m["momentum20d"] > 0


def test_etf_momentum_short_history_is_limited():
    m = scanner._etf_momentum([101.0, 100.0])
    assert m["limited"] is True
    assert -1.0 <= m["score"] <= 1.0


def test_regime_backdrop_stress_and_supportive():
    rates = {"us10y": {"latestValue": 4.4, "change": 0.0},
             "us2y": {"latestValue": 4.6}, "usReal10y": {"latestValue": 1.8},
             "vix": {"latestValue": 30.0}}
    assert scanner._regime_rates_backdrop(rates, {"latestValue": 3.0, "change": 0.0})["posture"] == "stress"
    rates["vix"]["latestValue"] = 13.0
    assert scanner._regime_rates_backdrop(rates, {"latestValue": 3.0, "change": 0.0})["posture"] == "supportive"


# ── Action Label Engine v0 ───────────────────────────────────────────
def test_classify_symbol_big_drop_is_wait_high():
    meta = {"symbol": "TEST", "market": "US", "name": "Test", "cls": "us_growth"}
    action, risk, conf, reason, nxt = scanner._classify_symbol(meta, -8.0, None, "neutral")
    assert action == "WAIT" and risk == "high" and conf >= 0.8
    assert reason and nxt


def test_classify_symbol_event_pullback():
    meta = {"symbol": "TEST", "market": "US", "name": "Test", "cls": "us_growth"}
    action, *_ = scanner._classify_symbol(meta, 3.0, "D", "neutral")
    assert action == "WAIT FOR PULLBACK"


def test_classify_symbol_quiet_day_is_hold():
    meta = {"symbol": "TEST", "market": "JP", "name": "Test", "cls": "jp_utility"}
    action, risk, *_ = scanner._classify_symbol(meta, 0.5, None, "neutral")
    assert action == "HOLD" and risk == "low"


# ── Input sanitization (public endpoints) ────────────────────────────
def test_sanitize_symbols_jp():
    out = scanner._sanitize_symbols(
        ["8058", "7203", "<bad>", "12345", "285a", "8058"], scanner._JP_SYM_RE, 20)
    assert out == ["8058", "7203", "285A"]  # dedup, upcase, junk dropped


def test_sanitize_symbols_us_cap():
    # US tickers are alphabetic (+ . / -); the cap keeps one Twelve Data batch
    # within the free tier's 8 credits/min.
    syms = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOG", "AMD",
            "AVGO", "CRM", "BRK.B", "NFLX"]
    out = scanner._sanitize_symbols(syms, scanner._US_SYM_RE, 8)
    assert len(out) == 8
    assert out[0] == "AAPL"
    assert scanner._sanitize_symbols(["aapl'", "1XYZ", ""], scanner._US_SYM_RE, 8) == []


# ── Freshness ────────────────────────────────────────────────────────
def test_quote_lag_days():
    today = datetime.datetime.now(pytz.timezone("Asia/Tokyo")).strftime("%Y-%m-%d")
    assert scanner._quote_lag_days(today) == 0
    assert scanner._quote_lag_days("not-a-date") is None
    assert scanner._quote_lag_days("2020-01-01") > 365


# ── AI judgment truth (key-aware, never flag-driven) ─────────────────
def test_ai_truth_disabled(monkeypatch):
    monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", False)
    assert scanner._ai_judgment_truth()["status"] == "disabled"


def test_ai_truth_missing_keys(monkeypatch):
    monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", True)
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "")
    monkeypatch.setattr(scanner, "GEMINI_API_KEY", "")
    assert scanner._ai_judgment_truth()["status"] == "missing_keys"


def test_ai_truth_no_cached_result(monkeypatch):
    monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", True)
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "x")
    monkeypatch.setattr(scanner, "GEMINI_API_KEY", "y")
    monkeypatch.setitem(scanner._AI_RESULT_CACHE, "data", None)
    assert scanner._ai_judgment_truth()["status"] == "no_cached_result"


def test_ai_truth_one_key_is_partial(monkeypatch):
    monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", True)
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "x")
    monkeypatch.setattr(scanner, "GEMINI_API_KEY", "")
    monkeypatch.setitem(scanner._AI_RESULT_CACHE, "data", None)
    assert scanner._ai_judgment_truth()["status"] == "partial"


# ── Crypto id sanitization ───────────────────────────────────────────
def test_crypto_id_regex():
    assert scanner._CRYPTO_ID_RE.match("bitcoin")
    assert scanner._CRYPTO_ID_RE.match("usd-coin")
    assert not scanner._CRYPTO_ID_RE.match("UPPER")
    assert not scanner._CRYPTO_ID_RE.match("bad;id")
