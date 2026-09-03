"""v13.5.44 — ARGUS-derived Japan valuation (argus_japan_valuation) tests."""
from __future__ import annotations

import json

import argus_japan_valuation as val
import argus_sho as sho

ROWS = [
    {"LocalCode": "58030", "DisclosedDate": "2026-08-05", "ForecastEarningsPerShare": "250.0",
     "EarningsPerShare": "60.1", "TypeOfDocument": "1QFinancialStatements_Consolidated_JP"},
    {"LocalCode": "58030", "DisclosedDate": "2026-05-10", "ForecastEarningsPerShare": "240.0"},
    {"LocalCode": "80580", "DisclosedDate": "2026-08-01", "ForecastEarningsPerShare": "400.0"},
    {"LocalCode": "99840", "DisclosedDate": "2026-08-07", "ForecastEarningsPerShare": "-10.0"},
    {"LocalCode": "12345", "DisclosedDate": "2026-08-07"},                     # no EPS → skipped
    {"Code": "6584", "DisclosedDate": "2026-07-30", "EarningsPerShare": "80.0"},  # actual only
]
PRICES = {"5803": 4951.0, "8058": 5059.0, "9984": 5001.0, "6584": 1600.0}


import pytest


@pytest.fixture(autouse=True)
def _isolate_product_stores():
    """Module stores (boot warm, derived valuation, statements state) must never
    leak into other auto-discovered suites (e.g. D07 expects MISSING when cold)."""
    import argus_chart_bootstrap as _boot
    import argus_japan_valuation as _val
    _boot._reset_for_tests(); _val._reset_for_tests()
    yield
    _boot._reset_for_tests(); _val._reset_for_tests()



def test_latest_forecast_eps_keeps_newest_disclosure_per_issuer():
    eps = val.latest_forecast_eps(ROWS)
    assert eps["5803"]["forecastEps"] == 250.0 and eps["5803"]["disclosedDate"] == "2026-08-05"
    assert eps["6584"]["forecastEps"] is None and eps["6584"]["actualEps"] == 80.0
    assert "1234" not in eps


def test_compute_derives_forward_per_median_and_condition_without_claiming_nikkei():
    evidence = val.compute(ROWS, PRICES, computed_at="2026-09-03T09:00:00Z",
                           universe=["5803", "8058", "9984", "6584", "7203"])
    assert evidence["status"] == "AVAILABLE" and evidence["lineage"] == "ARGUS_CANDIDATE"
    by_code = {row["code"]: row for row in evidence["issuers"]}
    assert by_code["5803"]["forwardPer"] == round(4951.0 / 250.0, 4)
    assert by_code["9984"]["forwardPer"] is None                # negative EPS → no PER
    assert by_code["6584"]["epsBasis"] == "ACTUAL"
    assert "7203" not in by_code                                # no statement → excluded
    assert evidence["coverage"] == 3 and evidence["universeSize"] == 5
    assert evidence["conditionMet"] == (evidence["medianForwardPer"] <= 21.0)
    assert evidence["nikkeiOfficialPer"] == "NOT_CLAIMED"
    assert evidence["knownAt"] == "2026-08-07" or evidence["knownAt"] == "2026-08-05"
    serialized = json.dumps(evidence).lower()
    assert "nikkei 225 per" not in serialized


def test_compute_reports_missing_when_no_coverage():
    evidence = val.compute(ROWS, {}, computed_at="2026-09-03T09:00:00Z", universe=["5803"])
    assert evidence["status"] == "MISSING" and evidence["conditionMet"] is None
    assert evidence["missing"] == ["derived_forward_per_coverage"]


def test_d04_uses_derived_evidence_only_when_available_and_visible():
    val._reset_for_tests()
    cutoff = "2026-09-03T09:00:00Z"
    blocked = sho.evaluate_d04(cutoff=cutoff, analysis_instrument="NIKKEI_225_INDEX")
    assert blocked["status"] == "LICENSE_BLOCKED"
    evidence = val.compute(ROWS, PRICES, computed_at=cutoff, universe=["5803", "8058"])
    val.publish(evidence)
    derived = sho.evaluate_d04(cutoff=cutoff, analysis_instrument="NIKKEI_225_INDEX")
    assert derived["status"] == "AVAILABLE" and derived["lineage"] == "ARGUS_CANDIDATE"
    assert derived["conditionMet"] is evidence["conditionMet"]
    assert derived["nikkeiOfficialPer"] == "NOT_CLAIMED" and derived["levels"] == []
    assert derived["derived"]["medianForwardPer"] == evidence["medianForwardPer"]
    # explicit argument wins; future-dated evidence is not visible at the cutoff
    future = {**evidence, "availableFrom": "2026-09-04T23:59:00+09:00"}
    assert sho.evaluate_d04(cutoff=cutoff, analysis_instrument="NIKKEI_225_INDEX",
                            derived_valuation=future)["status"] == "LICENSE_BLOCKED"
    val._reset_for_tests()
    assert sho.evaluate_d04(cutoff=cutoff, analysis_instrument="NIKKEI_225_INDEX")["status"] == "LICENSE_BLOCKED"


def test_d07_not_applicable_only_when_statements_feed_is_warm():
    val._reset_for_tests()
    cold = sho.evaluate_d07(cutoff="2026-09-03T09:00:00Z")
    assert cold["status"] == "MISSING"
    val.publish_statements_state({"warmedAt": "2026-09-03T08:59:00Z", "rowCount": 0, "source": "jquants"})
    warm = sho.evaluate_d07(cutoff="2026-09-03T09:00:00Z")
    assert warm["status"] == "NOT_APPLICABLE" and warm["missing"] == ["no_supported_earnings_event_in_window"]
    assert warm["statementsFeed"]["rowCount"] == 0
    val._reset_for_tests()
    explicit = sho.evaluate_d07(cutoff="2026-09-03T09:00:00Z",
                                statements_state={"warmedAt": "x", "rowCount": 3, "source": "jquants"})
    assert explicit["status"] == "NOT_APPLICABLE"


def test_family_conditions_are_deterministic_and_labelled():
    cutoff = "2026-09-03T09:00:00Z"
    proxy = {"instrumentId": "1321", "seriesId": "relative_strength_20d", "date": "2026-09-02",
             "value": 0.012, "availableFrom": "2026-09-02T07:00:00Z"}
    d03 = sho.evaluate_d03(cutoff=cutoff, proxy_evidence=proxy)
    assert d03["conditionMet"] is True and d03["conditionLineage"] == "ARGUS_CANDIDATE"
    assert sho.evaluate_d03(cutoff=cutoff, proxy_evidence={**proxy, "value": -0.02})["conditionMet"] is False
    assert sho.evaluate_d03(cutoff=cutoff)["conditionMet"] is None
    flow = {"seriesId": "flow.foreign", "periodEnd": "2026-08-29", "availableFrom": "2026-09-02T00:00:00Z", "value": -1099300000000.0}
    d05 = sho.evaluate_d05([flow], cutoff=cutoff)
    assert d05["direction"] == "OUTFLOW" and d05["conditionMet"] is False
    assert sho.evaluate_d05([{**flow, "value": 5.0}], cutoff=cutoff)["conditionMet"] is True
    closes = [20 + (i % 7) * 0.5 - (i / 10.0) for i in range(80)]
    rows = [{"instrumentId": "VIX", "seriesId": "vix.close", "value": c,
             "periodEnd": f"2026-0{1 + i // 28}-{1 + i % 28:02d}",
             "availableFrom": f"2026-0{1 + i // 28}-{2 + i % 28:02d}T00:00:00Z"} for i, c in enumerate(closes)]
    d06 = sho.evaluate_d06(rows, cutoff=cutoff)
    assert d06["status"] == "AVAILABLE" and d06["conditionMet"] in (True, False)
    assert d06["conditionMet"] == (d06["argusBaseline"]["histogram"] < 0)
    assert d06["conditionLineage"] == "ARGUS_CANDIDATE"
