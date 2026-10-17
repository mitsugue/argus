"""Current PER definition, source time, and reference conversion parity."""
import copy
import pytest
from jp_market_level_map import weighted_eps, EPS_BASIS
from jp_market_price_paths import current_estimate_scale, index_valuation_scale, convert_shape_to_yen

CUTOFF = "2026-10-05T06:00:00Z"
DAY = "2026-10-02"

def estimate():
    row = weighted_eps({"A": {"MktCap": 2000, "FwdPER": 20},
                        "B": {"MktCap": 1000, "FwdPER": -40}},
                       ["A", "B"], index_close=68000, date=DAY, constituents_as_of="2026-09-30")
    return {**row, "instrumentId": "NIKKEI_225_INDEX", "currency": "JPY",
            "recordedAt": "2026-10-04T09:00:00Z", "sourceRef": "level-map-eps:" + DAY}

def scale(row):
    return current_estimate_scale(row, cutoff=CUTOFF, anchor_date=DAY, anchor_price=68000)

def test_reuses_the_exact_estimate_and_preserves_negative_earnings_and_price_conversion():
    row = estimate(); original = copy.deepcopy(row)
    actual = scale(row)
    assert actual["status"] == "AVAILABLE"
    assert actual["basis"] == EPS_BASIS
    assert actual["per"] == row["per"] == 40
    assert actual["eps"] == row["eps"] == 1700
    assert actual["proxyCoverage"]["negativeForecast"] == 1
    assert actual["historicalVintageVerified"] is False
    assert actual["officialValue"] is False
    assert row == original
    through_existing = index_valuation_scale(row, cutoff=CUTOFF, anchor_date=DAY, anchor_price=68000)
    assert through_existing == actual
    points = convert_shape_to_yen([{"value": 100}, {"value": 101}], scale=actual)
    assert [p["value"] for p in points] == [68000, 68680]
    assert all(p["scaleBasis"] == EPS_BASIS for p in points)

@pytest.mark.parametrize("patch", [
    {"basis": "ARGUS_PROXY_INDEX_BASED_PER"}, {"instrumentId": "1321"}, {"currency": "USD"},
    {"date": "2026-10-01"}, {"recordedAt": "2026-10-05T06:01:00Z"},
    {"recordedAt": "2026-10-04"}, {"recordedAt": "2026-10-04T09:00:00"}, {"recordedAt": None},
    {"per": 0}, {"eps": 1}, {"indexClose": 67500}, {"eps": float("nan")},
    {"officialValue": True}, {"sourceRef": None}, {"constituentsAsOf": None},
    {"coverage": {}}, {"coverage": {"marketCapShareUsed": 1.1}},
])
def test_missing_future_inconsistent_or_other_definition_never_becomes_current_per(patch):
    row = {**estimate(), **patch}
    actual = scale(row)
    assert actual["status"] == "UNAVAILABLE"
    assert actual["per"] is None and actual["eps"] is None
    assert convert_shape_to_yen([{"value": 100}], scale=actual) == []

def test_missing_current_estimate_has_no_old_definition_fallback():
    assert scale({})["status"] == "UNAVAILABLE"
    assert scale(None)["status"] == "UNAVAILABLE"


def test_d04_reads_current_per_without_transplanting_old_19_threshold():
    import jp_market_engine as engine
    row = estimate()
    actual = engine.evaluate_d04(cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX", current_estimate=row)
    assert actual["status"] == "AVAILABLE" and actual["per"] == 40
    assert actual["eps"] == 1700 and actual["valuationBasis"] == EPS_BASIS
    assert actual["conditionMet"] is None and actual["activationRule"] is None
    assert actual["ruleStatus"] == "RULE_NOT_DEFINED" and actual["actionAuthority"] is False
    assert all("高評価帯" not in level["labelJa"] for level in actual["levels"])
    assert "最新" in engine.fact_note_ja("D04", actual)

def test_d04_missing_current_input_does_not_return_available_legacy_per():
    import jp_market_engine as engine
    legacy = {"basis": "ARGUS_PROXY_INDEX_BASED_PER", "instrumentId": "NIKKEI_225_INDEX",
              "currency": "JPY", "date": DAY, "indexClose": 68000, "per": 25,
              "availableFrom": "2026-10-04T09:00:00Z", "sourceRef": "synthetic-legacy"}
    actual = engine.evaluate_d04(cutoff=CUTOFF, analysis_instrument="NIKKEI_225_INDEX",
                                current_estimate={}, proxy_valuation=legacy)
    assert actual["status"] == "MISSING" and actual["per"] is None
    assert actual["conditionMet"] is None

def test_modern_d04_projection_retains_rule_and_basis_and_does_not_count_as_warning():
    import jp_market_engine as engine
    record = engine.evaluate_d01_d07(cutoff=CUTOFF, nikkei_current_estimate=estimate())
    view = engine.project_today_sda_safe(cutoff=CUTOFF, evidence=record)
    d04 = view["families"]["D04"]
    assert d04["valuationBasis"] == EPS_BASIS and d04["ruleStatus"] == "RULE_NOT_DEFINED"
    sign = next(row for row in view["marketSignals"]["signals"] if row["family"] == "D04")
    assert sign["state"] == "DATA_GATED" and sign["conditionMet"] is None
    assert sign["valuationBasis"] == EPS_BASIS
    assert "旧方式の19倍判定は使いません" in sign["gateNoteJa"]

def _cached_current(monkeypatch, *, values=None, bars=None):
    import scanner
    row = estimate()
    monkeypatch.setattr(scanner, "_LEVEL_MAP", {"eps": values if values is not None else {DAY: row}})
    original = copy.deepcopy(scanner._LEVEL_MAP)
    bars = bars if bars is not None else [{"date": DAY, "close": 68000,
             "instrumentId": "NIKKEI_225_INDEX", "availableFrom": "2026-10-02T07:00:00Z"}]
    actual = scanner._level_map_current_valuation(CUTOFF, nikkei_rows=bars)
    assert scanner._LEVEL_MAP == original
    return actual

def test_consumer_reuses_the_existing_current_estimate_without_fetch_or_new_store(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner.requests, "get", lambda *_a, **_k: pytest.fail("cache-only consumer fetched"))
    current = _cached_current(monkeypatch)
    assert current["per"] == estimate()["per"] and current["eps"] == estimate()["eps"]
    assert current["basis"] == EPS_BASIS and current["recordedAt"] == estimate()["recordedAt"]

@pytest.mark.parametrize("bars", [
    [], [{"date": DAY, "close": 68000, "instrumentId": "1321", "availableFrom": "2026-10-02T07:00:00Z"}],
    [{"date": DAY, "close": 68000, "instrumentId": "NIKKEI_225_INDEX"}],
    [{"date": DAY, "close": 68000, "instrumentId": "NIKKEI_225_INDEX", "availableFrom": "2026-10-05T06:01:00Z"}],
    [{"date": DAY, "close": 67900, "instrumentId": "NIKKEI_225_INDEX", "availableFrom": "2026-10-02T07:00:00Z"}],
])
def test_consumer_rejects_unknown_unclosed_other_identity_or_inconsistent_index(monkeypatch, bars):
    assert _cached_current(monkeypatch, bars=bars) == {}

def test_newer_completed_session_without_estimate_is_not_filled_by_older_estimate(monkeypatch):
    bars = [{"date": "2026-10-01", "close": 67000, "instrumentId": "NIKKEI_225_INDEX", "availableFrom": "2026-10-01T07:00:00Z"},
            {"date": DAY, "close": 68000, "instrumentId": "NIKKEI_225_INDEX", "availableFrom": "2026-10-02T07:00:00Z"}]
    older = {**estimate(), "date": "2026-10-01", "indexClose": 67000}
    assert _cached_current(monkeypatch, values={"2026-10-01": older}, bars=bars) == {}


def test_current_event_study_never_scores_old_19_multiple_as_current_warning():
    import jp_market_sign_event_study as study
    actual = study.sign_event_study([], {DAY: 68000}, [DAY], cutoff=CUTOFF, valuation_basis=EPS_BASIS)
    d04 = actual["conditions"]["D04"]
    assert d04["status"] == "NOT_EVALUABLE"
    assert d04["valuationBasis"] == EPS_BASIS and d04["legacy19RuleApplied"] is False
    assert actual["actionAuthority"] is False and actual["predictiveProbabilities"] is None

def test_missing_current_reference_keeps_the_current_definition_instead_of_old_missing_label():
    actual = index_valuation_scale({"basis": EPS_BASIS}, cutoff=CUTOFF, anchor_date=DAY, anchor_price=68000)
    assert actual["basis"] == EPS_BASIS and actual["reason"] == "missing_current_per_estimate"


def test_undefined_rule_never_counts_even_if_an_inconsistent_row_says_met():
    import argus_market_signals as signals
    row = {"status": "AVAILABLE", "conditionMet": True, "ruleStatus": "RULE_NOT_DEFINED"}
    assert signals.signal_state(row) == "DATA_GATED"
    view = signals.project_market_signals({"D04": row})
    assert view["activeCount"] == 0
