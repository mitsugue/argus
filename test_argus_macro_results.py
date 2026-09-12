"""ARGUS V11.5 — macro result adapters + market reaction (pure, fixture-based)."""
import json
import argus_macro_results as MR
import argus_macro_market_reaction as RX

NOW = "2026-07-15T12:35:00Z"


def _bls(series_id, values):
    # values newest-first list of (year, period, value)
    return {"Results": {"series": [{"seriesID": series_id,
            "data": [{"year": y, "period": p, "value": str(v)} for (y, p, v) in values]}]}}


def _bls_multi(mapping):
    return {"Results": {"series": [
        {"seriesID": sid, "data": [{"year": y, "period": p, "value": str(v)} for (y, p, v) in vals]}
        for sid, vals in mapping.items()]}}


def _fred(obs):
    return {"observations": [{"date": d, "value": str(v)} for (d, v) in obs]}


def _months(n, start_index=310.0, step=0.4):
    # newest-first synthetic monthly index series
    out = []
    for i in range(n):
        out.append(("2026" if i < 6 else "2025", f"M{(7 - i) % 12 + 1:02d}", start_index - i * step))
    return out


# ── CPI ──────────────────────────────────────────────────────────────────────
def test_cpi_parses_headline_and_core():
    raw = _bls_multi({
        "CUSR0000SA0": [("2026", "M06", 312.0), ("2026", "M05", 311.0)] + [("2025", f"M{m:02d}", 300.0) for m in range(12, 0, -1)],
        "CUSR0000SA0L1E": [("2026", "M06", 320.0), ("2026", "M05", 319.0)],
    })
    r = MR.parse_cpi(raw, {"eventCode": "CPI"}, NOW)
    assert r["available"] is True
    assert r["metrics"]["headlineCpiMoM"] == round((312.0 / 311.0 - 1) * 100, 2)
    assert r["metrics"]["coreCpiMoM"] == round((320.0 / 319.0 - 1) * 100, 2)
    assert r["metrics"]["headlineCpiYoY"] is None  # NSA series absent; never replace with SA
    assert "消費者物価指数" in r["headline"]
    assert "consensus" not in json.dumps(r).lower()


def test_cpi_partial_when_series_empty():
    r = MR.parse_cpi({"Results": {"series": []}}, {"eventCode": "CPI"}, NOW)
    assert r["available"] is False and r["status"] == "partial"
    assert r["limitationsJa"]


def test_cpi_never_fabricates_yoy_without_12_months():
    raw = _bls("CUSR0000SA0", [("2026", "M06", 312.0), ("2026", "M05", 311.0)])
    r = MR.parse_cpi(raw, {"eventCode": "CPI"}, NOW)
    assert r["metrics"]["headlineCpiYoY"] is None
    assert r["status"] == "partial"       # honest: y/y not yet computable


# ── PPI / JOLTS ────────────────────────────────────────────────────────────────
def test_ppi_parses():
    raw = _bls("WPSFD4", [("2026", "M06", 145.0), ("2026", "M05", 144.5)])
    r = MR.parse_ppi(raw, {"eventCode": "PPI"}, NOW)
    assert r["available"] and "生産者物価指数" in r["headline"]
    assert r["metrics"]["headlinePpiMoM"] == round((145.0 / 144.5 - 1) * 100, 2)


def test_jolts_parses_openings():
    raw = _bls("JTS000000000000000JOL", [("2026", "M05", 8100.0), ("2026", "M04", 8000.0)])
    r = MR.parse_jolts(raw, {"eventCode": "JOLTS"}, NOW)
    assert r["available"] and r["metrics"]["jobOpeningsK"] == 8100.0


# ── PCE / GDP (FRED) ───────────────────────────────────────────────────────────
def test_pce_parses():
    head = _fred([("2026-06-01", 124.0), ("2026-05-01", 123.6)])
    core = _fred([("2026-06-01", 122.0), ("2026-05-01", 121.7)])
    r = MR.parse_pce(head, core, {"eventCode": "PCE"}, NOW)
    assert r["available"] and r["metrics"]["headlinePceMoM"] == round((124.0 / 123.6 - 1) * 100, 2)


def test_gdp_takes_annualized_value_directly():
    raw = _fred([("2026-04-01", 2.8), ("2026-01-01", 1.9)])
    r = MR.parse_gdp(raw, {"eventCode": "GDP"}, NOW)
    assert r["available"] and r["metrics"]["realGdpQoQAnnualized"] == 2.8
    assert "+2.8%" in r["headline"]


# ── FOMC (target range decision) ───────────────────────────────────────────────
def test_fomc_cut_detected_from_range():
    # decision DAY: latest daily value differs from the day before → cut.
    up = _fred([("2026-06-18", 5.00), ("2026-06-17", 5.25), ("2026-06-16", 5.25)])
    lo = _fred([("2026-06-18", 4.75), ("2026-06-17", 5.00)])
    r = MR.parse_fomc(up, lo, {"eventCode": "FOMC"}, NOW)
    assert r["available"] and r["metrics"]["decision"] == "cut"
    assert "利下げ" in r["headline"]
    assert any("ドットプロット" in x for x in r["limitationsJa"])   # SEP not fabricated


def test_fomc_hold_on_realistic_daily_series():
    # REGRESSION (v11.5 review): a real HOLD meeting has a long tail of identical
    # daily values after the last hike. The parser must read HOLD, not the last change.
    up = _fred([("2026-06-18", 5.50)] + [(f"2026-05-{d:02d}", 5.50) for d in range(31, 0, -1)]
               + [("2024-07-26", 5.25)])   # older pre-hike value present in the window
    lo = _fred([("2026-06-18", 5.25)] + [(f"2026-05-{d:02d}", 5.25) for d in range(31, 0, -1)])
    r = MR.parse_fomc(up, lo, {"eventCode": "FOMC"}, NOW)
    assert r["metrics"]["decision"] == "hold" and "据え置き" in r["headline"]


def test_fomc_hike_on_decision_day():
    up = _fred([("2026-06-18", 5.50), ("2026-06-17", 5.25), ("2026-05-01", 5.25)])
    lo = _fred([("2026-06-18", 5.25), ("2026-06-17", 5.00)])
    r = MR.parse_fomc(up, lo, {"eventCode": "FOMC"}, NOW)
    assert r["metrics"]["decision"] == "hike" and "利上げ" in r["headline"]


def test_fomc_partial_when_series_missing():
    r = MR.parse_fomc({"observations": []}, {"observations": []}, {"eventCode": "FOMC"}, NOW)
    assert r["available"] is False and r["status"] == "partial"


# ── BOJ / not_implemented ──────────────────────────────────────────────────────
def test_boj_partial_no_fabrication():
    r = MR.boj_partial({"eventCode": "BOJ"}, NOW)
    assert r["available"] is False and r["status"] == "partial"
    assert r["metrics"] == {} and r["sourceUrl"]
    assert any("捏造" in x for x in r["limitationsJa"])


def test_not_implemented_shape():
    r = MR.not_implemented("TREASURY_AUCTION", NOW)
    assert r["status"] == "not_implemented" and r["available"] is False


def test_metrics_available_excludes_reference():
    r = MR.parse_ppi(_bls("WPSFD4", [("2026", "M06", 145.0), ("2026", "M05", 144.5)]),
                     {"eventCode": "PPI"}, NOW)
    ma = MR.metrics_available(r)
    assert "headlinePpiMoM" in ma and not any(k.startswith("reference") for k in ma)


# ── market reaction ────────────────────────────────────────────────────────────
def test_reaction_computes_moves():
    io = [{"window": "1h", "before": {"us10y": 4.25, "usdJpy": 149.0, "spy": 500.0, "vix": 15.0},
           "after": {"us10y": 4.30, "usdJpy": 149.6, "spy": 494.0, "vix": 16.5}}]
    rx = RX.build_reaction(event_id="cpi-x", event_code="CPI", windows_io=io, now_iso=NOW)
    w = rx["windows"][0]
    assert w["us10yMoveBp"] == 5.0                    # 4.30-4.25 = 0.05pp = 5bp
    assert w["spyMovePct"] == round((494 / 500 - 1) * 100, 2)
    assert w["marketConfirmed"] is True
    assert w["riskTone"] in ("risk_off", "rates_up", "mixed")
    assert rx["summaryJa"]


def test_reaction_null_when_no_data():
    io = [{"window": "1h", "before": {}, "after": {}}]
    rx = RX.build_reaction(event_id="x", event_code="CPI", windows_io=io, now_iso=NOW)
    w = rx["windows"][0]
    assert all(w.get(k) is None for k in RX._ASSET_KEYS)
    assert w["marketConfirmed"] is False and w["riskTone"] == "unknown"
    assert any("未取得" in x for x in w["limitationsJa"])
    assert any("未取得" in x for x in rx["limitationsJa"])
    assert rx["summaryJa"] == ""


def test_reaction_alone_is_not_confirmed_cause():
    # marketConfirmed on a window is about the WINDOW's data density, not causation.
    io = [{"window": "1h", "before": {"spy": 500, "qqq": 400}, "after": {"spy": 505, "qqq": 408}}]
    rx = RX.build_reaction(event_id="x", event_code="GDP", windows_io=io, now_iso=NOW)
    # the reaction doc has no "causeStatus"/"confirmed_cause" field at all
    assert "causeStatus" not in rx and "confirmed_cause" not in json.dumps(rx)


def test_impact_fallback_by_event_type():
    assert "逆風" in RX.impact_fallback("CPI", {"headlineCpiMoM": 0.6})
    assert "支援" in RX.impact_fallback("CPI", {"headlineCpiMoM": 0.0})
    assert "利下げ" in RX.impact_fallback("FOMC", {"decision": "cut"})
    assert "利上げ" in RX.impact_fallback("FOMC", {"decision": "hike"})
    boj = RX.impact_fallback("BOJ", {})
    assert "円高" in boj or "円安" in boj
    for code in ("CPI", "FOMC", "BOJ", "GDP", "JOLTS", "AUCTION"):
        assert "consensus" not in RX.impact_fallback(code, {}).lower()
        assert "コンセンサス" not in RX.impact_fallback(code, {})


def test_compact_for_store_flattens_best_window():
    io = [{"window": "15m", "before": {}, "after": {}},
          {"window": "1h", "before": {"us10y": 4.2, "spy": 500}, "after": {"us10y": 4.25, "spy": 503}}]
    rx = RX.build_reaction(event_id="x", event_code="CPI", windows_io=io, now_iso=NOW)
    c = RX.compact_for_store(rx)
    assert c["us10yMoveBp"] == 5.0 and c["spyMovePct"] is not None
    assert c["window"] == "1h" and isinstance(c["windows"], list)


def test_cpi_separate_adjustment_exact_month_and_receipt():
    raw = _bls_multi({
        "CUSR0000SA0": [("2026", "M06", 312), ("2026", "M05", 311), ("2025", "M06", 290)],
        "CUSR0000SA0L1E": [("2026", "M06", 320), ("2026", "M05", 319)],
        "CUUR0000SA0": [("2026", "M06", 313), ("2025", "M06", 300)],
        "CUUR0000SA0L1E": [("2026", "M06", 322), ("2025", "M06", 310)],
    })
    r = MR.parse_cpi(raw, {"eventDate": "2026-07-15"}, NOW)
    assert r["status"] == "live" and r["referenceMatched"]
    assert r["metrics"]["headlineCpiYoY"] == 4.33
    assert r["metrics"]["coreCpiYoY"] == 3.87
    assert r["metricDefinitions"]["headlineCpiMoM"]["seasonalAdjustment"] == "SA"
    assert r["metricDefinitions"]["headlineCpiYoY"]["seasonalAdjustment"] == "NSA"
    assert r["metricInputs"]["headlineCpiYoY"]["comparisonMonth"] == "2025-06"
    assert r["releasedAt"] is None and r["receivedAt"] == r["availableFrom"] == NOW
    assert len(r["sourceResponseSha256"]) == 64


def test_cpi_does_not_attach_previous_month_result_to_new_release():
    raw = _bls("CUSR0000SA0", [("2026", "M05", 311), ("2026", "M04", 310)])
    r = MR.parse_cpi(raw, {"eventDate": "2026-07-15"}, NOW)
    assert not r["available"] and r["expectedReferenceMonth"] == "2026-06"


def test_cpi_selects_event_month_even_if_newer_observations_present():
    raw = _bls("CUSR0000SA0", [("2026", "M07", 350), ("2026", "M06", 312), ("2026", "M05", 311)])
    r = MR.parse_cpi(raw, {"eventDate": "2026-07-15"}, NOW)
    assert r["metrics"]["referenceMonth"] == "2026-06"
    assert r["metrics"]["headlineCpiMoM"] == 0.32
    assert r["metricInputs"]["headlineCpiMoM"]["currentIndex"] == 312


def test_monthly_changes_ignore_annual_and_never_bridge_missing_months():
    rows = [{"year": "2026", "period": "M13", "value": "999"},
            {"year": "2026", "period": "M06", "value": "312"},
            {"year": "2026", "period": "M04", "value": "300"},
            {"year": "2025", "period": "M06", "value": "300"}]
    mom, yoy, month = MR._mom_yoy(rows)
    assert mom is None and yoy == 4 and month == "2026-06"


def test_cpi_does_not_combine_core_from_another_month():
    raw = _bls_multi({"CUSR0000SA0": [("2026", "M06", 312), ("2026", "M05", 311)],
                      "CUSR0000SA0L1E": [("2026", "M05", 320), ("2026", "M04", 319)]})
    r = MR.parse_cpi(raw, {"eventDate": "2026-07-15"}, NOW)
    assert r["metrics"]["coreCpiMoM"] is None


def test_conflicting_duplicate_and_non_finite_monthly_values_are_missing():
    rows = [{"year": "2026", "period": "M06", "value": "312"},
            {"year": "2026", "period": "M06", "value": "313"},
            {"year": "2026", "period": "M05", "value": "NaN"}]
    assert MR._mom_yoy(rows) == (None, None, "2026-06")
