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
    # ai-persist-v1: with keys present the truth source would now try to
    # RESTORE from the real ledger branch over the network — tests must stay
    # hermetic, so pin the restore to a no-op here.
    monkeypatch.setattr(scanner, "_ai_try_restore", lambda: None)
    assert scanner._ai_judgment_truth()["status"] == "no_cached_result"


def test_ai_truth_one_key_is_partial(monkeypatch):
    monkeypatch.setattr(scanner, "_AI_JUDGE_ENABLED", True)
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "x")
    monkeypatch.setattr(scanner, "GEMINI_API_KEY", "")
    monkeypatch.setitem(scanner._AI_RESULT_CACHE, "data", None)
    monkeypatch.setattr(scanner, "_ai_try_restore", lambda: None)
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


# ── Calibration plumbing (calibration-v1, v10.8) ─────────────────────
def test_calibration_neutral_while_accumulating():
    cal = scanner._calibration_for({"byPosture": {}}, "CAUTIOUS")
    assert cal["factor"] == 1.0 and "蓄積中" in cal["basisJa"]
    cal = scanner._calibration_for(None, "CAUTIOUS")
    assert cal["factor"] == 1.0
    # below the 33-row evidence floor → still neutral even with a strong rate
    s = {"byPosture": {"CAUTIOUS": {"n": 22, "hitRate": 0.9}}}
    assert scanner._calibration_for(s, "CAUTIOUS")["factor"] == 1.0


def test_calibration_trust_and_doubt_bands():
    up = {"byPosture": {"CAUTIOUS": {"n": 44, "hitRate": 0.65}}}
    mid = {"byPosture": {"CAUTIOUS": {"n": 44, "hitRate": 0.50}}}
    down = {"byPosture": {"CAUTIOUS": {"n": 44, "hitRate": 0.30}}}
    assert scanner._calibration_for(up, "CAUTIOUS")["factor"] == scanner._CAL_UP
    assert scanner._calibration_for(mid, "CAUTIOUS")["factor"] == 1.0
    assert scanner._calibration_for(down, "CAUTIOUS")["factor"] == scanner._CAL_DOWN


def test_calibration_only_reads_matching_posture_bucket():
    s = {"byPosture": {"RISK_OFF": {"n": 99, "hitRate": 0.2}}}
    cal = scanner._calibration_for(s, "CAUTIOUS")  # different context day
    assert cal["factor"] == 1.0 and cal["n"] == 0


def test_calibration_survives_malformed_summary():
    assert scanner._calibration_for({"byPosture": {"CAUTIOUS": {"n": "x"}}}, "CAUTIOUS")["factor"] == 1.0
    assert scanner._calibration_for("garbage", "CAUTIOUS")["factor"] == 1.0


def test_action_labels_response_carries_calibration(monkeypatch):
    # Hermetic: don't let the test reach the real ledger summary on GitHub.
    monkeypatch.setattr(scanner, "_ledger_summary", lambda: None)
    out = scanner.get_action_labels()
    assert "calibration" in out and out["calibration"]["factor"] >= 0.8


# ── ledger-v3: 3-layer learning universe (v10.9) ─────────────────────
def test_layer1_sensor_universe_is_fixed_16():
    n = len(scanner._L1_SENSORS_JP) + len(scanner._L1_SENSORS_US) + 3  # +BTC/USDJPY/VIX
    assert n == 16
    syms = [s for s, _ in scanner._L1_SENSORS_JP] + scanner._L1_SENSORS_US
    assert len(set(syms)) == len(syms)
    # 9984/7011 were deliberately moved OUT of Layer 1 (idiosyncratic risk)
    assert "9984" not in syms and "7011" not in syms
    assert "8058" in syms and "SMH" in syms


def test_layer_attribution():
    assert scanner._layer_of("6584") == 3       # experimental / high noise
    assert scanner._layer_of("8058") == 1       # doubles as a Layer-1 sensor
    assert scanner._layer_of("9984") == 2
    assert scanner._layer_of("7011") == 2
    assert scanner._layer_of("NVDA") == 2


def test_scenarios_scaled_band_units():
    # a 0.5% FX move ≙ a 2% equity move → identical distributions
    assert scanner._scenarios_scaled(0.5, 0.5) == scanner._scenarios_for(2.0)
    assert scanner._scenarios_scaled(-2.0, 8.0) == scanner._scenarios_for(-0.5)
    assert scanner._scenarios_scaled(None, 0.5) == scanner._scenarios_for(None)


def test_sensor_row_carries_band_and_valid_distribution():
    r = scanner._sensor_row("USDJPY", "USD/JPY", "fx", 155.0, 0.3)
    assert r["bandPct"] == 0.5 and r["kind"] == "fx"
    assert abs(sum(s["p"] for s in r["scenarios"]) - 100) < 1e-6
    v = scanner._sensor_row("VIX", "VIX", "vol", 18.0, -4.0)
    assert v["bandPct"] == 8.0


# ── Vault relay (sync-v1, v10.10) ────────────────────────────────────
def test_vault_relay_roundtrip_and_validation():
    c = scanner.app.test_client()
    assert c.get("/api/argus/vault-relay?vaultId=bogus").status_code == 400
    vid = "cd" * 32
    assert c.get(f"/api/argus/vault-relay?vaultId={vid}").status_code == 404
    r = c.post("/api/argus/vault-push", json={"vaultId": vid, "blob": "ciphertext-xyz"})
    assert r.status_code == 200
    r = c.get(f"/api/argus/vault-relay?vaultId={vid}")
    assert r.status_code == 200
    d = r.get_json()
    assert d["blob"] == "ciphertext-xyz" and isinstance(d["ts"], float)
    # relay reads are non-destructive
    assert c.get(f"/api/argus/vault-relay?vaultId={vid}").status_code == 200


# ── Close Pin Intraday Ledger (closepin-v1, v10.11) ──────────────────
def test_closepin_scenarios_sum_to_one_and_baseline_flat():
    sc = scanner._closepin_scenarios(0.0, None, "neutral")
    assert abs(sum(sc.values()) - 1.0) < 1e-6
    assert max(sc, key=sc.get) == "flat"          # calm day → flat is argmax


def test_closepin_scenarios_momentum_and_flow_tilt():
    up = scanner._closepin_scenarios(2.5, 0.4, "neutral")
    down = scanner._closepin_scenarios(-2.5, -0.4, "neutral")
    assert up["up"] > up["down"] and down["down"] > down["up"]
    assert abs(sum(up.values()) - 1.0) < 1e-6
    # tilts are capped — flat must stay a serious contender even on a big day
    assert up["flat"] >= 0.3


def test_closepin_scenarios_elevated_damps_strong_up():
    neu = scanner._closepin_scenarios(1.0, None, "neutral")
    ele = scanner._closepin_scenarios(1.0, None, "elevated")
    assert ele["strongUp"] < neu["strongUp"]


def test_closepin_snapshot_realtime_only(monkeypatch):
    # T-1 J-Quants rows (source != moomoo-rt) must NOT be pinned.
    fake = {"status": "live", "asOf": None, "stocks": [
        {"symbol": "8058", "name": "Mitsubishi Corporation", "price": 4600.0,
         "changePct": 1.2, "volume": 1, "date": "2026-06-11", "status": "live",
         "source": "moomoo-rt", "flow": {"bigNetRatio": 0.3}},
        {"symbol": "9432", "name": "NTT", "price": 150.0, "changePct": 0.1,
         "volume": 1, "date": "2026-06-10", "status": "live", "source": "jquants"},
    ]}
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda syms=None: fake)
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {"status": "mock"})
    monkeypatch.setattr(scanner, "_rates_posture", lambda r: "neutral")
    snap = scanner.get_closepin_snapshot()
    assert snap["status"] == "live" and len(snap["rows"]) == 1
    r = snap["rows"][0]
    assert r["symbol"] == "8058" and r["layer"] == 1 and r["pinPrice"] == 4600.0
    assert abs(sum(r["scenarios"].values()) - 1.0) < 1e-6


# ── Market News feed (news-v2, v10.12) ───────────────────────────────
def test_news_major_keyword_detection():
    assert scanner._NEWS_MAJOR_RE.search("ECB raises rates by 25 basis points")
    assert scanner._NEWS_MAJOR_RE.search("Fed signals rate cut in September")
    assert scanner._NEWS_MAJOR_RE.search("Japan intervenes to support yen")
    assert scanner._NEWS_MAJOR_RE.search("US will hit Iran very hard tonight")
    assert scanner._NEWS_MAJOR_RE.search("Missile strikes reported near Taiwan")
    assert not scanner._NEWS_MAJOR_RE.search("Apple unveils new MacBook lineup")


# ── Finnhub US quote fallback (v10.12.1) ─────────────────────────────
def test_us_watchlist_finnhub_backfill(monkeypatch):
    monkeypatch.setattr(scanner, "_get_us_watchlist_core",
        lambda syms=None: {"status": "partial", "asOf": None, "provider": "twelvedata",
                           "stocks": [{"symbol": "NVDA", "name": "NVIDIA", "price": 200.0,
                                       "changeAbs": 1.0, "changePct": 0.5, "volume": 1,
                                       "date": "2026-06-11", "status": "live"}]})
    monkeypatch.setattr(scanner, "_overlay_pushed", lambda snap, m, req: snap)
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "x")
    monkeypatch.setattr(scanner, "_finnhub_quote_row",
        lambda s: {"symbol": s, "name": s, "price": 40.0, "changeAbs": 0.5,
                   "changePct": 1.2, "volume": 0, "date": "2026-06-11",
                   "status": "live", "source": "finnhub"})
    out = scanner.get_us_watchlist_snapshot(["NVDA", "IONQ"])
    syms = {s["symbol"]: s for s in out["stocks"]}
    assert "IONQ" in syms and syms["IONQ"]["source"] == "finnhub"
    assert syms["NVDA"]["price"] == 200.0  # TD row untouched


# ── Entry Scout (entry-scout-v1, v10.15) ─────────────────────────────
def test_entry_metrics_oversold_series():
    # 8 straight down days into a 60-session window → oversold signals fire.
    closes = [100.0 - 0 + i * 1.5 for i in range(8)] + [112.0] * 52  # newest-first: 100,101.5,...
    m = scanner._entry_metrics(closes, [100] * 60)
    assert m is not None and m["sessions"] == 60
    assert m["consecDown"] >= 3
    assert m["ma25DiffPct"] is not None and m["ma25DiffPct"] < 0
    assert m["rsi14"] < 50


def test_entry_metrics_requires_history():
    assert scanner._entry_metrics([100.0] * 10) is None
    assert scanner._entry_metrics([]) is None


def test_entry_scout_oversold_plus_inflow_is_aggressive():
    m = {"ret1": -1.0, "ret5": -4.0, "ret20": 2.0, "ret60": 5.0,
         "ma5DiffPct": -3.0, "ma25DiffPct": -9.0, "rsi14": 28.0, "consecDown": 4,
         "offHigh60Pct": -12.0, "offLow60Pct": 1.0, "volRatio5v20": 1.2, "sessions": 60}
    a = scanner._entry_scout_assess(m, 0.20, None, "neutral", "normal", 4)
    assert a["stance"] == "攻め好機(候補)" and a["score"] >= 1.5
    assert any("金曜" in r for r in a["reasonsJa"])  # noted, not scored


def test_entry_scout_overheat_plus_event_is_avoid():
    m = {"ret1": 2.0, "ret5": 6.0, "ret20": 15.0, "ret60": 30.0,
         "ma5DiffPct": 5.0, "ma25DiffPct": 12.0, "rsi14": 78.0, "consecDown": 0,
         "offHigh60Pct": 0.0, "offLow60Pct": 25.0, "volRatio5v20": 1.0, "sessions": 60}
    a = scanner._entry_scout_assess(m, -0.2, "D-1", "elevated", "elevated", 1)
    assert a["stance"] == "見送り" and a["score"] <= -1


def test_entry_scout_v2_factors():
    m = {"ret1": -1.0, "ret5": -4.0, "ret20": 2.0, "ret60": 5.0,
         "ma5DiffPct": -3.0, "ma25DiffPct": -9.0, "rsi14": 28.0, "consecDown": 4,
         "offHigh60Pct": -12.0, "offLow60Pct": 1.0, "volRatio5v20": 1.2, "sessions": 60}
    base = scanner._entry_scout_assess(m, 0.20, None, "neutral", "normal", 2)
    # RISK_OFF regime + imminent earnings + AI disagree drags an aggressive
    # setup down hard; relative strength adds back a little.
    v2 = scanner._entry_scout_assess(m, 0.20, None, "neutral", "normal", 2,
                                     regime_label="RISK_OFF", vix_spike=True,
                                     rel_strength=1.5, earnings_days=2, ai_view="disagree")
    assert v2["score"] < base["score"] - 2
    assert any("レジーム" in r for r in v2["reasonsJa"])
    assert any("決算" in r for r in v2["reasonsJa"])
    assert any("相対力" in r for r in v2["reasonsJa"])
    assert any("不同意" in r for r in v2["reasonsJa"])


def test_entry_metrics_macd_and_cross_detection():
    # 25 flat sessions, then a 30-session downtrend, then a sharp 5-day
    # rebound (newest-first): MA5 crosses above MA25 and MACD turns up.
    newest_first = [106.0, 105.0, 104.0, 103.0, 102.0] + [90.0] * 30 + [100.0] * 25
    m = scanner._entry_metrics(newest_first, [100] * 60)
    assert m["maCross"] == "golden"
    assert m["macdHist"] is not None and m["macdHist"] > 0
    assert m["bollPctB"] is not None and m["bollPctB"] > 1  # spike above the band


def test_entry_scout_technicals_scored_and_visible():
    m = {"ret1": 1.0, "ret5": 2.0, "ret20": 1.0, "ret60": None,
         "ma5DiffPct": 1.0, "ma25DiffPct": 1.0, "rsi14": 50.0, "consecDown": 0,
         "offHigh60Pct": -5.0, "offLow60Pct": 5.0, "volRatio5v20": 1.0, "sessions": 60,
         "macdCross": "golden", "maCross": "golden", "bollPctB": -0.1, "macdHist": 0.5}
    a = scanner._entry_scout_assess(m, None, None, "neutral", "normal", 2)
    assert a["score"] >= 1.5
    assert any("MACD" in r for r in a["reasonsJa"])
    assert any("ゴールデンクロス" in r for r in a["reasonsJa"])
    assert any("ボリンジャー" in r for r in a["reasonsJa"])


# ── Scout narrative (callJa + story, v3, v10.30) ────────────────────
def _narr_metrics(rsi=45.0):
    return {"rsi14": rsi, "ret1": 0.5, "ret5": -1.0, "ret20": 2.0}


def test_scout_narrative_short_covering_story_leads_with_moat():
    assess = {"stance": "押し目買い検討圏", "score": 0.8, "reasonsJa": []}
    flow = {"classification": "SHORT_COVERING"}
    ctx = {"posture": "elevated", "regime": "EVENT_WAIT"}
    jsf = {"ratio": 0.7}
    short = {"ratio": 0.06}
    track = {"n": 12, "upRate": 0.75, "avgRetPct": 3.1}
    eng = {"n": 133, "hitRate": 0.586}
    pcal = {"posture": "EVENT_WAIT", "n": 89, "hitRate": 0.618}
    call, narr = scanner._scout_narrative(assess, flow, ctx, jsf, short,
                                          _narr_metrics(), track, eng, pcal, False)
    assert call.startswith("押し目買い検討")
    assert "買い戻し主導" in call                      # flow class surfaced in the call
    assert "買い戻し主導の疑い" in narr                  # moat story
    assert "日証金倍率0.7・売り長=踏み上げ余地" in narr and "機関空売り6.0%" in narr
    assert "過去12件" in narr                           # score-bucket calibration
    assert "EVENT_WAIT" in narr and "62%" in narr       # this-regime engine hit rate


def test_scout_narrative_extreme_ratio_formatted_as_buy_long():
    assess = {"stance": "中立(急がない)", "score": -0.5, "reasonsJa": []}
    flow = {"classification": "NEW_LONG_ACCUMULATION"}
    _, narr = scanner._scout_narrative(assess, flow, {"posture": "neutral", "regime": "MIXED"},
                                       {"ratio": 4753.0}, None, _narr_metrics(),
                                       None, {"n": 133, "hitRate": 0.586}, None, False)
    assert "日証金倍率4753・買い長(貸株僅少)" in narr     # int format + meaningful tag, no ".0"


def test_scout_narrative_us_omits_credit_and_notes_gap():
    assess = {"stance": "中立(急がない)", "score": 0.0, "reasonsJa": []}
    flow = {"classification": "UNCONFIRMED"}
    ctx = {"posture": "neutral", "regime": "RISK_ON"}
    call, narr = scanner._scout_narrative(assess, flow, ctx, None, None,
                                          _narr_metrics(72.0), None, {"n": 133, "hitRate": 0.586},
                                          None, True)
    assert "様子見" in call and "RSI72.0買われすぎ" in call
    assert "信用需給" in narr and "未接続" in narr        # honest US gap
    assert "エンジン全体の的中率59%" in narr             # falls back to engine-overall


def test_scout_narrative_thin_calibration_warns():
    assess = {"stance": "見送り", "score": -1.5, "reasonsJa": []}
    call, narr = scanner._scout_narrative(assess, {"classification": "DISTRIBUTION"},
                                          {"posture": "elevated"}, None, None,
                                          _narr_metrics(), {"n": 2}, None, None, False)
    assert call.startswith("見送り")
    assert "20件未満" in narr                           # thin-data caveat, not a fake stat


def test_scout_narrative_none_when_no_assessment():
    assert scanner._scout_narrative(None, {}, {}, None, None, {}, None, None, None, False) == (None, None)


# ── 24/7 event backbone wiring (v10.39) ──────────────────────────────
def _clear_events():
    scanner._EVENTS_ACTIVE.clear()
    scanner._EVENTS_LOG.clear()


def test_event_backbone_detects_limit_up(monkeypatch):
    _clear_events()
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)        # no real push in tests
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    # prev close 1000 (limit ±300) → price 1300 = S高. changeAbs = 300.
    scanner._process_events_from_push("JP", [{"symbol": "9999", "price": 1300.0,
                                              "changeAbs": 300.0, "changePct": 30.0}])
    active = scanner._events_active_list()
    types = {e["eventType"] for e in active}
    assert "LIMIT_UP" in types
    assert any(e["lifecycleState"] == "HIGH_ALERT" for e in active if e["eventType"] == "LIMIT_UP")


def test_event_backbone_dedup_no_duplicate(monkeypatch):
    _clear_events()
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    row = [{"symbol": "9999", "price": 1300.0, "changeAbs": 300.0, "changePct": 30.0}]
    scanner._process_events_from_push("JP", row)
    scanner._process_events_from_push("JP", row)           # same anomaly again
    limit_ups = [e for e in scanner._events_active_list() if e["eventType"] == "LIMIT_UP"]
    assert len(limit_ups) == 1                              # deduped, no spam


def test_event_backbone_respects_session_gate(monkeypatch):
    _clear_events()
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)  # market closed
    scanner._process_events_from_push("JP", [{"symbol": "9999", "price": 1300.0,
                                              "changeAbs": 300.0, "changePct": 30.0}])
    assert scanner._events_active_list() == []             # no fire when closed


def test_event_backbone_disabled_flag(monkeypatch):
    _clear_events()
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", False)
    scanner._process_events_from_push("JP", [{"symbol": "9999", "price": 1300.0,
                                              "changeAbs": 300.0, "changePct": 30.0}])
    assert scanner._events_active_list() == []


# ── Research dossier orchestration (v10.41.1) ────────────────────────
def test_build_event_dossier_orchestration(monkeypatch):
    monkeypatch.setattr(scanner, "get_entry_scout", lambda sym, mkt="JP": {
        "name": "テスト", "asOf": "2026-06-22T01:00:00Z",
        "flowInference": {"classification": "SHORT_COVERING",
                          "probabilities": {"newLongAccumulation": 0.2, "shortCovering": 0.5,
                                            "distribution": 0.1, "retailNoise": 0.1, "unconfirmed": 0.1},
                          "reasonsJa": ["貸株残縮小"]},
        "metrics": {"rsi14": 72},
        "catalystContext": {"items": [{"kind": "news", "headline": "上方修正観測"}]}})
    env = {"eventId": "e-test", "eventType": "LIMIT_UP", "severity": 5, "symbol": "9999",
           "market": "JP", "session": "JP_MORNING", "lifecycleState": "HIGH_ALERT",
           "eventVersion": 1, "reasonJa": "S高到達", "observedAt": "2026-06-22T01:00:00Z"}
    d = scanner._build_event_dossier(env, {"changePct": 18.0})
    assert d["schemaVersion"] == "dossier-v2" and d["researchPosture"] == "LIMIT_UP_RISK"
    assert "squeeze_exhaustion" in d["trapRisks"]
    assert d["confirmedFacts"] == []                       # news headline is NOT a confirmed fact
    assert d["dossierMode"] == "event_time_snapshot" and d["evidenceHash"]
    # a generic news item must NOT create an official catalyst
    cause = {c["label"]: c["probability"] for c in d["probableCause"]}
    assert cause.get("official_catalyst", 0) == 0 and cause.get("reported_catalyst", 0) > 0
    assert "自動売買" in d["disclaimerJa"]


def test_event_dossier_endpoint_http_semantics():
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/event-dossier").status_code == 400          # missing eventId
        assert c.get("/api/argus/event-dossier?eventId=nope").status_code == 404


def test_notification_test_requires_admin():
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/event-test-notify")           # no admin token
        assert r.status_code in (401, 503)                   # never silently sends


def test_bridge_hmac_signature(monkeypatch):
    import hmac as _h, hashlib as _hl
    secret, body = "s3cr3t", b'{"stocks":[]}'
    import time as _t
    ts, nonce = str(_t.time()), "nonce-abc"
    sig = _h.new(secret.encode(), f"{ts}.{nonce}.".encode() + body, _hl.sha256).hexdigest()
    assert scanner._hmac_ok(secret, ts, nonce, sig, body, float(ts))[0]          # valid
    assert not scanner._hmac_ok(secret, ts, nonce, "deadbeef", body, float(ts))[0]  # forged
    assert not scanner._hmac_ok(secret, ts, nonce, sig, b'{"stocks":[1]}', float(ts))[0]  # body tampered
    assert not scanner._hmac_ok(secret, "0", nonce, sig, body, 1e10)[0]          # stale timestamp
    assert not scanner._hmac_ok(secret, "", "", "", body, 0)[0]                  # missing
    # quote-push without admin token is still rejected (HMAC is additive)
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/quote-push", json={"stocks": []}).status_code in (401, 503)


def test_crypto_scan_requires_admin():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/crypto-scan").status_code in (401, 503)   # admin-gated


def test_crypto_event_records_with_long_dedup(monkeypatch):
    scanner._EVENTS_ACTIVE.clear(); scanner._EVENTS_LOG.clear()
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    import datetime as _dt
    now = _dt.datetime(2026, 6, 21, 3, 0, tzinfo=_dt.timezone.utc)   # a Sunday night
    trig = scanner.argus_events.detect_crypto_anomaly("BTC", -9.0)[0]
    env = scanner._record_event("CRYPTO", "BTC", trig, now, "CRYPTO_24H",
                                bucket_minutes=360, source="coingecko", session_override="CRYPTO_24H")
    assert env and env["eventType"] == "CRYPTO_SHOCK" and env["session"] == "CRYPTO_24H"
    assert any(e["eventType"] == "CRYPTO_SHOCK" for e in scanner._events_active_list())
    scanner._EVENTS_ACTIVE.clear(); scanner._EVENTS_LOG.clear()


# ── Weekly margin signal (信用残, entry-scout v2.2, v10.18) ──────────
def test_margin_signal_requires_two_weeks():
    assert scanner._margin_signal(None) is None
    assert scanner._margin_signal([{"date": "2026-06-05", "longVol": 100, "shortVol": 50}]) is None


def test_margin_signal_computes_ratio_and_deltas():
    rows = [{"date": "2026-06-12", "longVol": 120.0, "shortVol": 200.0},
            {"date": "2026-06-05", "longVol": 100.0, "shortVol": 150.0}]
    s = scanner._margin_signal(rows)
    assert s["creditRatio"] == 0.6
    assert s["shortWoWPct"] == round((200-150)/150*100, 1)
    assert s["longWoWPct"] == 20.0


def test_margin_assess_short_covering_is_tailwind():
    sig = {"creditRatio": 0.6, "shortWoWPct": 20.0, "longWoWPct": 2.0,
           "longVol": 120, "shortVol": 200, "date": "2026-06-12"}
    sc, reasons = scanner._margin_assess_lines(sig)
    assert sc >= 1.0
    assert any("買い戻し" in r or "踏み上げ" in r for r in reasons)
    assert any("売り残" in r for r in reasons)


def test_margin_assess_overhang_is_headwind():
    sig = {"creditRatio": 6.0, "shortWoWPct": 1.0, "longWoWPct": 25.0,
           "longVol": 600, "shortVol": 100, "date": "2026-06-12"}
    sc, reasons = scanner._margin_assess_lines(sig)
    assert sc <= -1.0
    assert any("戻り売り" in r for r in reasons)


def test_margin_assess_none_is_neutral():
    sc, reasons = scanner._margin_assess_lines(None)
    assert sc == 0.0 and reasons == []


# ── 日証金 JSF daily balance (entry-scout v2.3, v10.19) ─────────────
def test_jsf_assess_short_heavy_is_covering_fuel():
    j = {"ratio": 0.6, "loan": 60000, "short": 100000, "net": -40000,
         "loanNew": 100, "loanRepay": 100, "shortNew": 5000, "shortRepay": 1000,
         "date": "2026/06/11"}
    sc, reasons = scanner._jsf_assess_lines(j)
    assert sc >= 0.5
    assert any("踏み上げ" in r or "買い戻し" in r for r in reasons)
    assert any("新規売り" in r for r in reasons)   # shortNew >> shortRepay


def test_jsf_assess_loan_heavy_is_overhang():
    j = {"ratio": 4.0, "loan": 400000, "short": 100000, "net": 300000,
         "loanNew": 100, "loanRepay": 100, "shortNew": 0, "shortRepay": 0,
         "date": "2026/06/11"}
    sc, reasons = scanner._jsf_assess_lines(j)
    assert sc <= -0.5
    assert any("戻り売り" in r for r in reasons)


def test_jsf_assess_none_is_neutral():
    sc, reasons = scanner._jsf_assess_lines(None)
    assert sc == 0.0 and reasons == []


# ── JPX disclosed institutional short (entry-scout v2.4, v10.20) ────
def test_short_disclosed_heavy_is_squeeze_fuel():
    sc, reasons = scanner._short_disclosed_assess({"ratio": 0.08, "reporters": 4})
    assert sc == 0.5
    assert any("踏み上げ" in r and "8.0%" in r for r in reasons)


def test_short_disclosed_moderate():
    sc, reasons = scanner._short_disclosed_assess({"ratio": 0.03, "reporters": 2})
    assert sc == 0.3 and any("買い戻し余地" in r for r in reasons)


def test_short_disclosed_none_or_empty():
    assert scanner._short_disclosed_assess(None) == (0.0, [])
    assert scanner._short_disclosed_assess({"ratio": 0.0, "reporters": 0}) == (0.0, [])


# ── Flow Intelligence (大口の正体推定, v10.21) ────────────────────────
def test_flow_infer_short_covering():
    m = {"ret1": 3.0, "ret5": 5.0, "ret20": 2.0, "volRatio5v20": 1.6}
    jsf = {"ratio": 0.7, "shortNew": 1000, "shortRepay": 9000, "loanNew": 100, "loanRepay": 100}
    sd = {"ratio": 0.06, "reporters": 3}
    out = scanner._flow_inference(m, 0.1, jsf, sd)
    assert out["classification"] == "SHORT_COVERING"
    p = out["probabilities"]
    assert abs(sum(p.values()) - 1.0) < 0.01
    assert p["shortCovering"] == max(p[k] for k in p)
    assert any("買い戻し" in r for r in out["reasonsJa"])


def test_flow_infer_new_long():
    m = {"ret1": 1.5, "ret5": 4.0, "ret20": 8.0, "volRatio5v20": 1.6}
    jsf = {"ratio": 5.0, "shortNew": 100, "shortRepay": 100, "loanNew": 9000, "loanRepay": 1000}
    out = scanner._flow_inference(m, 0.3, jsf, None)
    assert out["classification"] == "NEW_LONG_ACCUMULATION"
    assert abs(sum(out["probabilities"].values()) - 1.0) < 0.01


def test_flow_infer_distribution():
    m = {"ret1": -0.5, "ret5": -1.0, "ret20": 3.0, "volRatio5v20": 2.2}
    jsf = {"ratio": 6.0, "shortNew": 0, "shortRepay": 0, "loanNew": 100, "loanRepay": 5000}
    out = scanner._flow_inference(m, -0.25, jsf, None)
    assert out["classification"] == "DISTRIBUTION"


def test_flow_infer_unconfirmed_when_thin():
    m = {"ret1": 0.2, "ret5": 0.1, "ret20": 0.0, "volRatio5v20": 1.0}
    out = scanner._flow_inference(m, None, None, None)
    assert out["classification"] == "UNCONFIRMED"
    assert out["probabilities"]["unconfirmed"] == 1.0
    assert out["confidence"] == "low"


# ── Catalyst/material context (v10.22) ───────────────────────────────
def test_catalyst_context_surfaces_news_and_link():
    news = {"themes": [
        {"key": "geopolitics", "labelJa": "地政学", "level": "elevated", "count": 12,
         "headlines": ["Iran ceasefire talks advance"]},
        {"key": "fx", "labelJa": "為替", "level": "calm", "count": 1, "headlines": []}]}
    out = scanner._catalyst_context(news, "RISK_OFF", "D-1", 2, high_beta=True)
    kinds = [i["kind"] for i in out["items"]]
    assert "news" in kinds and "link" in kinds and "regime" in kinds
    assert "event" in kinds and "earnings" in kinds
    news_item = next(i for i in out["items"] if i["kind"] == "news")
    assert news_item["level"] == "elevated" and "Iran" in (news_item["headline"] or "")


def test_catalyst_context_quiet_is_empty():
    news = {"themes": [{"key": "x", "labelJa": "x", "level": "calm", "count": 0, "headlines": []}]}
    out = scanner._catalyst_context(news, "RISK_ON", "normal", None, high_beta=False)
    assert out["items"] == []


# ── Gap (窓) detection (entry-scout v2.5, v10.23) ────────────────────
def test_detect_gap_up_unfilled():
    # newest-first: today gapped up and stayed above the prior high
    closes = [120, 100, 99, 98]
    highs  = [122, 101, 100, 99]
    lows   = [118, 99, 98, 97]   # today's low 118 > prior high 101 = unfilled gap up
    g = scanner._detect_gap(closes, highs, lows)
    assert g and g["dir"] == "up" and g["sessionsAgo"] == 0 and g["filled"] is False
    assert g["pct"] > 0


def test_detect_gap_down():
    closes = [80, 81, 100, 101]
    highs  = [82, 83, 101, 102]   # today's high 82 < prior low 99 = gap down
    lows   = [79, 80, 99, 100]
    g = scanner._detect_gap(closes, highs, lows)
    assert g and g["dir"] == "down" and g["pct"] < 0


def test_detect_gap_none_without_hl():
    assert scanner._detect_gap([100, 101, 102], None, None) is None
    # contiguous bars (overlapping ranges) → no gap
    assert scanner._detect_gap([100, 100, 100], [101, 101, 101], [99, 99, 99]) is None


def test_detect_gap_ignores_noise():
    # a 0.04%-level gap is tick noise, not a 窓 → ignored
    closes = [100.04, 100.0, 99.9, 99.8]
    highs  = [100.05, 100.0, 99.95, 99.85]
    lows   = [100.005, 99.96, 99.85, 99.75]
    assert scanner._detect_gap(closes, highs, lows) is None


# ── Scout calibration buckets (scout-ledger-v1, v10.24/Phase3) ───────
def test_scout_score_bucket():
    assert scanner._scout_score_bucket(2.0) == "strong"
    assert scanner._scout_score_bucket(1.5) == "strong"
    assert scanner._scout_score_bucket(1.0) == "lean"
    assert scanner._scout_score_bucket(0.0) == "neutral"
    assert scanner._scout_score_bucket(-0.5) == "neutral"
    assert scanner._scout_score_bucket(-1.0) == "avoid"
    assert scanner._scout_score_bucket(None) == "neutral"


# ── JP market-hours awareness (v10.26) ───────────────────────────────
def test_jp_market_open_hours():
    import datetime as _dt
    jst = pytz.timezone("Asia/Tokyo")
    mon_open = jst.localize(_dt.datetime(2026, 6, 22, 10, 0))    # Mon 10:00
    mon_lunch = jst.localize(_dt.datetime(2026, 6, 22, 12, 0))   # Mon 12:00 (closed)
    mon_pm = jst.localize(_dt.datetime(2026, 6, 22, 14, 0))      # Mon 14:00
    mon_after = jst.localize(_dt.datetime(2026, 6, 22, 16, 0))   # Mon 16:00 (closed)
    sat = jst.localize(_dt.datetime(2026, 6, 20, 13, 0))         # Sat (closed)
    assert scanner._jp_market_open(mon_open) is True
    assert scanner._jp_market_open(mon_lunch) is False
    assert scanner._jp_market_open(mon_pm) is True
    assert scanner._jp_market_open(mon_after) is False
    assert scanner._jp_market_open(sat) is False
