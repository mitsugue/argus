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


# ── Context-aware VIX assessment (v9.12) ─────────────────────────────
def test_vix_calm_regime():
    v = scanner._vix_assess([12.0] * 60)
    assert v["zone"] == "calm" and v["spike"] is False


def test_vix_spike_into_shock():
    # 18 → 30 overnight: velocity + level → shock, spike True
    v = scanner._vix_assess([30.0, 18.0] + [15.0] * 58)
    assert v["zone"] == "shock" and v["spike"] is True


def test_vix_relative_elevation_without_big_absolute():
    # 19 after months of 13s: top of ITS OWN range → elevated (no magic 26)
    v = scanner._vix_assess([19.0] + [13.0] * 59)
    assert v["zone"] == "elevated"
    assert v["percentile60d"] == 100


def test_vix_high_level_in_high_regime_not_shock():
    # 26 inside a 28-vol regime: relatively LOW for its regime — elevated by
    # absolute band, but NOT shock and NOT a spike.
    v = scanner._vix_assess([26.0, 27.0] + [28.0] * 58)
    assert v["zone"] == "elevated" and v["spike"] is False
    assert v["percentile60d"] <= 10


def test_vix_short_history_no_crash():
    v = scanner._vix_assess([20.0])
    assert v is not None and v["zone"] in ("calm", "normal", "elevated", "shock")
    assert scanner._vix_assess([]) is None


# ── moomoo real-time overlay (v9.11) ─────────────────────────────────
def _snap(*rows):
    return {"status": "live", "asOf": "2026-06-10", "stocks": list(rows)}


def test_overlay_replaces_and_fills(monkeypatch):
    import time as _t
    monkeypatch.setitem(scanner._PUSHED_QUOTES, "JP", {
        "8058": {"row": {"symbol": "8058", "price": 5000.0, "changeAbs": 10.0,
                         "changePct": 0.2, "volume": 1, "date": "2026-06-10",
                         "status": "live", "source": "moomoo-rt"}, "ts": _t.time()},
        "7203": {"row": {"symbol": "7203", "price": 2900.0, "changeAbs": 5.0,
                         "changePct": 0.17, "volume": 2, "date": "2026-06-10",
                         "status": "live", "source": "moomoo-rt"}, "ts": _t.time()},
    })
    base = _snap({"symbol": "8058", "name": "三菱商事", "price": 4805.0,
                  "changePct": -0.58, "volume": 9, "date": "2026-06-09", "status": "live"})
    out = scanner._overlay_pushed(base, "JP", ["8058", "7203"])
    by = {s["symbol"]: s for s in out["stocks"]}
    assert by["8058"]["price"] == 5000.0          # overlaid
    assert by["8058"]["name"] == "三菱商事"        # name preserved
    assert "7203" in by                            # hole filled
    assert out["realtimeCount"] == 2
    assert base["stocks"][0]["price"] == 4805.0    # cached object untouched


def test_overlay_ignores_stale_pushes(monkeypatch):
    import time as _t
    monkeypatch.setitem(scanner._PUSHED_QUOTES, "JP", {
        "8058": {"row": {"symbol": "8058", "price": 5000.0, "status": "live",
                         "changeAbs": 0, "changePct": 0, "volume": 0,
                         "date": "2026-06-10", "source": "moomoo-rt"},
                 "ts": _t.time() - scanner._PUSH_TTL - 1},
    })
    base = _snap({"symbol": "8058", "name": "三菱商事", "price": 4805.0, "status": "live"})
    out = scanner._overlay_pushed(base, "JP", ["8058"])
    assert out["stocks"][0]["price"] == 4805.0     # stale push not applied
    assert "realtimeCount" not in out


# ── JP symbol-search code detection (v10.1 fix) ──────────────────────
def test_jp_query_is_code_alphanumeric():
    # TSE codes are digit-led and may END IN A LETTER — isdigit() broke these.
    assert scanner._jp_query_is_code("8058")
    assert scanner._jp_query_is_code("314A")
    assert scanner._jp_query_is_code("285a")
    assert scanner._jp_query_is_code("13")        # prefix search
    assert not scanner._jp_query_is_code("NVDA")  # letter-led = name search
    assert not scanner._jp_query_is_code("三菱")
    assert not scanner._jp_query_is_code("12345")


# ── Big-money flow confirmation (v10.2) ──────────────────────────────
def test_flow_buy_dip_on_mild_dip_with_inflow():
    a, c, r, n = scanner._flow_adjust("HOLD", 0.45, "r", "n", -3.0, 0.3, None, "neutral", "CAUTIOUS")
    assert a == "BUY DIP" and c <= 0.6 and "大口" in r


def test_flow_buy_dip_blocked_by_imminent_event():
    a, *_ = scanner._flow_adjust("HOLD", 0.45, "r", "n", -3.0, 0.3, "D", "neutral", "CAUTIOUS")
    assert a != "BUY DIP"


def test_flow_buy_dip_blocked_by_risk_off_regime():
    a, *_ = scanner._flow_adjust("HOLD", 0.45, "r", "n", -3.0, 0.3, None, "neutral", "RISK_OFF")
    assert a != "BUY DIP"


def test_flow_outflow_tightens_hold_to_wait():
    a, c, r, n = scanner._flow_adjust("HOLD", 0.45, "r", "n", 0.5, -0.3, None, "neutral", "CAUTIOUS")
    assert a == "WAIT" and "流出" in r


def test_flow_annotation_only_when_no_rule_change():
    a, c, r, n = scanner._flow_adjust("WAIT FOR PULLBACK", 0.65, "r", "n", 6.0, 0.4, None, "neutral", "RISK_ON")
    assert a == "WAIT FOR PULLBACK" and "純流入" in r


# ── Prediction ledger scenario port (v10.3) ──────────────────────────
def test_scenarios_for_sums_to_100():
    for chg in (None, -8.0, -4.0, 0.0, 3.0, 6.0):
        dist = scanner._scenarios_for(chg)
        assert sum(p for _, p in dist) == 100
        assert {s for s, _ in dist} == {"downside_continuation", "sideways_stabilization", "rebound_attempt"}


def test_scenarios_for_matches_frontend_thresholds():
    assert dict(scanner._scenarios_for(-8))["downside_continuation"] == 45
    assert dict(scanner._scenarios_for(0))["sideways_stabilization"] == 50
    assert dict(scanner._scenarios_for(6))["rebound_attempt"] == 25


# ── Backup vault relay (v10.3.4) ─────────────────────────────────────
def test_vault_push_validation():
    c = scanner.app.test_client()
    assert c.post("/api/argus/vault-push", json={"vaultId": "short", "blob": "x"}).status_code == 400
    assert c.post("/api/argus/vault-push", json={"vaultId": "g" * 64, "blob": "x"}).status_code == 400
    vid = "ab" * 32
    assert c.post("/api/argus/vault-push", json={"vaultId": vid, "blob": "x" * (300 * 1024)}).status_code == 413
    r = c.post("/api/argus/vault-push", json={"vaultId": vid, "blob": "ciphertext"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    # pull requires admin (503 locally: token unconfigured)
    assert c.post("/api/argus/vault-pull").status_code in (401, 503)


# ── Action Alerts class rules (v10.4) ────────────────────────────────
def test_alert_etf_strong_momentum_is_pullback_wait():
    m = {"score": 0.5, "momentum1d": 1.0, "momentum5d": 4.0, "momentum20d": 8.0}
    action, *_ = scanner._alert_action_for_etf(m, cautious=False)
    assert action == "WAIT FOR PULLBACK"


def test_alert_etf_neutral_goes_wait_when_cautious():
    m = {"score": 0.0, "momentum1d": 0.0, "momentum5d": 0.1, "momentum20d": 0.2}
    a1, *_ = scanner._alert_action_for_etf(m, cautious=True)
    a2, *_ = scanner._alert_action_for_etf(m, cautious=False)
    assert a1 == "WAIT" and a2 == "HOLD"


def test_alert_etf_deep_selloff_is_high_risk_wait():
    m = {"score": -0.6, "momentum1d": -3.0, "momentum5d": -7.0, "momentum20d": -12.0}
    action, conf, risk, *_ = scanner._alert_action_for_etf(m, cautious=True)
    assert action == "WAIT" and risk == "high"


# ── News Radar (v10.6) ───────────────────────────────────────────────
def test_news_theme_level_bands():
    assert scanner._news_theme_level(0) == "calm"
    assert scanner._news_theme_level(7) == "calm"
    assert scanner._news_theme_level(8) == "elevated"
    assert scanner._news_theme_level(20) == "high"


# ── AI judgment ledger restore (ai-persist-v1, v10.7) ────────────────
def _ai_payload(status="live", as_of=None, labels=None):
    as_of = as_of or datetime.datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    labels = [{"symbol": "8058"}] if labels is None else labels
    return {"status": status, "asOf": as_of, "labels": labels}


def test_ai_restore_accepts_fresh_live_run():
    assert scanner._ai_restore_validate(_ai_payload()) is not None
    assert scanner._ai_restore_validate(_ai_payload(status="partial")) is not None


def test_ai_restore_rejects_mock_and_garbage():
    assert scanner._ai_restore_validate(_ai_payload(status="mock")) is None
    assert scanner._ai_restore_validate(_ai_payload(status="no_cached_result")) is None
    assert scanner._ai_restore_validate(None) is None
    assert scanner._ai_restore_validate("not a dict") is None
    assert scanner._ai_restore_validate({}) is None


def test_ai_restore_rejects_empty_labels_or_missing_asof():
    assert scanner._ai_restore_validate(_ai_payload(labels=[])) is None
    p = _ai_payload(); del p["asOf"]
    assert scanner._ai_restore_validate(p) is None
    assert scanner._ai_restore_validate(_ai_payload(as_of="not-a-date")) is None


def test_ai_restore_rejects_runs_older_than_max_age():
    now = datetime.datetime(2026, 6, 11, 12, 0, tzinfo=pytz.utc)
    ok = (now - datetime.timedelta(hours=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - datetime.timedelta(hours=121)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = (now + datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert scanner._ai_restore_validate(_ai_payload(as_of=ok), now_utc=now) is not None
    assert scanner._ai_restore_validate(_ai_payload(as_of=old), now_utc=now) is None
    assert scanner._ai_restore_validate(_ai_payload(as_of=future), now_utc=now) is None
