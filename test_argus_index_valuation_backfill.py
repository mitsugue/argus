"""The backfill rebuilds the index valuation proxy for past sessions strictly as
of each date: factors in force, forecasts disclosed before the date, closes of
that session. A five-member price-weighted index with a known divisor is built
here so the arithmetic and the point-in-time rules can be checked exactly.
"""
import pytest

import argus_index_valuation_backfill as backfill
import argus_index_valuation_proxy as proxy

FACTORS = {"1001": 1.0, "1002": 1.0, "1003": 1.0, "1004": 0.1, "1005": 0.5}
DIVISOR = 25.0
CLOSES = {
    "2026-07-31": {"1001": 1000.0, "1002": 2500.0, "1003": 800.0, "1004": 60000.0, "1005": 9000.0},
    "2026-08-31": {"1001": 1010.0, "1002": 2450.0, "1003": 810.0, "1004": 61000.0, "1005": 9100.0},
    "2026-09-15": {"1001": 1020.0, "1002": 2400.0, "1003": 790.0, "1004": 62000.0, "1005": 9200.0},
}


def _stmt(code, disclosed, *, period="2Q", fy_end="2027-03-31", feps=None, nx_feps=None, eps=None,
          next_fy_end=None):
    row = {"Code": code + "0", "DiscDate": disclosed, "DiscTime": "15:00", "CurPerType": period,
           "DocType": ("FYFinancialStatements_Consolidated_JP" if period == "FY"
                       else f"{period}FinancialStatements_Consolidated_JP"),
           "CurFYEn": fy_end, "FEPS": feps, "NxFEPS": nx_feps, "EPS": eps}
    if next_fy_end:
        row["NxtFYEn"] = next_fy_end
    return row


STATEMENTS = [
    # FY2026/3 annual result on 2026-05-12 carries the FY2027/3 forecast.
    *[_stmt(code, "2026-05-12", period="FY", fy_end="2026-03-31", eps=eps * 0.9, nx_feps=eps,
            next_fy_end="2027-03-31")
      for code, eps in (("1001", 50.0), ("1002", 125.0), ("1003", 40.0), ("1004", 3000.0), ("1005", 450.0))],
    # 1001 revises its forecast on 2026-08-31 (same day as a session).
    _stmt("1001", "2026-08-31", feps=60.0),
]


def _index_close(day, factors=FACTORS, divisor=DIVISOR):
    return sum(CLOSES[day][c] * f for c, f in factors.items()) / divisor


def _table_set(as_of="2026-07-31", factors=FACTORS):
    return backfill.weight_table_factor_set({"asOf": as_of, "factors": factors})


def test_a_forecast_disclosed_on_the_date_is_not_used_until_the_next_date():
    index = backfill.statement_index(STATEMENTS)
    on_day = backfill.eps_in_force(index["1001"], "2026-08-31", code="1001")
    after = backfill.eps_in_force(index["1001"], "2026-09-01", code="1001")
    assert on_day["forecast"] == 50.0 and on_day["forecastDisclosed"] == "2026-05-12"
    assert after["forecast"] == 60.0 and after["fiscalYearEnd"] == "2027-03-31"
    assert backfill.eps_in_force(index["1001"], "2026-05-12", code="1001")["forecast"] is None


def test_the_target_year_rolls_only_at_the_annual_result():
    rows = [_stmt("2001", "2026-02-10", period="3Q", fy_end="2026-03-31", feps=80.0),
            _stmt("2001", "2026-05-12", period="FY", fy_end="2026-03-31", eps=82.0, nx_feps=95.0)]
    index = backfill.statement_index(rows)["2001"]
    # After the fiscal year ended but before its result: the old forecast stays in force.
    before = backfill.eps_in_force(index, "2026-04-20", code="2001")
    assert before["forecast"] == 80.0 and before["fiscalYearEnd"] == "2026-03-31"
    assert before["actual"] is None
    # The annual result reports that year and opens the next one (end derived when absent).
    after = backfill.eps_in_force(index, "2026-05-13", code="2001")
    assert after["forecast"] == 95.0 and after["fiscalYearEnd"] == "2027-03-31"
    assert after["actual"] == 82.0


def test_a_fiscal_year_long_past_without_a_result_is_a_hole_not_a_forecast():
    index = backfill.statement_index([_stmt("2002", "2025-11-10", fy_end="2026-03-31", feps=10.0)])["2002"]
    assert backfill.eps_in_force(index, "2026-06-30", code="2002")["forecast"] == 10.0
    assert backfill.eps_in_force(index, "2026-10-15", code="2002")["forecast"] is None


def test_a_forecast_disclosed_before_a_split_is_put_into_the_dates_share_units():
    index = backfill.statement_index([_stmt("2003", "2026-05-12", period="FY", fy_end="2026-03-31",
                                            eps=180.0, nx_feps=200.0)])["2003"]
    splits = {"2003": [("2026-07-01", 0.5)]}
    before = backfill.eps_in_force(index, "2026-06-30", splits=splits, code="2003")
    after = backfill.eps_in_force(index, "2026-07-01", splits=splits, code="2003")
    assert (before["forecast"], before["splitAdjusted"]) == (200.0, False)
    assert (after["forecast"], after["splitAdjusted"], after["actual"]) == (100.0, True, 90.0)
    untouched = backfill.eps_in_force(index, "2026-07-01", splits=splits, code="2003", split_policy="NONE")
    assert untouched["forecast"] == 200.0


def test_a_point_is_the_live_formula_on_point_in_time_inputs():
    index = backfill.statement_index(STATEMENTS)
    day = "2026-08-31"
    point = backfill.rebuild_point(day, factor_sets=[_table_set()], closes=CLOSES[day],
                                   index_close=_index_close(day), statements=index)
    forecasts = {"1001": 50.0, "1002": 125.0, "1003": 40.0, "1004": 3000.0, "1005": 450.0}
    expected = (sum(CLOSES[day][c] * f for c, f in FACTORS.items())
                / sum(forecasts[c] * f for c, f in FACTORS.items()))
    assert point["status"] == "AVAILABLE" and point["usable"] is True
    assert point["per"] == pytest.approx(expected, rel=1e-12)
    assert point["indexEps"] == pytest.approx(_index_close(day) / expected, rel=1e-12)
    assert point["impliedDivisor"] == pytest.approx(DIVISOR, rel=1e-9)
    live = proxy.proxy_valuation(factors={"factors": FACTORS}, closes=CLOSES[day], forecast_eps=forecasts,
                                 actual_eps={}, index_close=_index_close(day), date=day,
                                 available_from="x", known_at="x", source_ref="x")
    assert point["per"] == live["variants"][proxy.RECOMMENDED_VARIANT]["per"]
    assert point["coverage"]["forecastPriceShare"] == 1.0
    assert point["coverage"]["memberForecastRatio"] == 1.0
    assert point["factorsAsOf"] == "2026-07-31" and point["factorAgeDays"] == 31


def test_every_point_is_labelled_and_available_only_after_the_session():
    index = backfill.statement_index(STATEMENTS)
    point = backfill.rebuild_point("2026-08-31", factor_sets=[_table_set()], closes=CLOSES["2026-08-31"],
                                   index_close=_index_close("2026-08-31"), statements=index)
    assert point["basis"] == proxy.PROXY_BASIS != proxy.OFFICIAL_BASIS
    assert point["method"] == backfill.METHOD and point["epsVariant"] == proxy.RECOMMENDED_VARIANT
    assert point["availableFrom"] == "2026-09-01T00:00:00Z"
    assert point["availabilityBasis"] == "RECONSTRUCTED_SCHEDULED_PUBLICATION"
    assert point["historicalVintageVerified"] is False and point["actionAuthority"] is False
    assert point["validationStatus"] == "UNVALIDATED"


def test_no_factor_set_in_force_means_no_point_and_no_price_request():
    index = backfill.statement_index(STATEMENTS)
    asked = []

    def closes_for(day):
        asked.append(day)
        return CLOSES[day]

    points = backfill.backfill(["2026-09-15", "2026-07-31", "2026-08-31"],
                               factor_sets=[_table_set("2026-08-31")], closes=closes_for,
                               index_close_by_date={d: _index_close(d) for d in CLOSES}, statements=index)
    assert [p["date"] for p in points] == ["2026-07-31", "2026-08-31", "2026-09-15"]
    assert [p["status"] for p in points] == ["NO_FACTORS_IN_FORCE", "AVAILABLE", "AVAILABLE"]
    assert asked == ["2026-08-31", "2026-09-15"]
    # A table older than the bound is not in force either.
    stale = backfill.rebuild_point("2026-09-15", factor_sets=[_table_set("2026-07-31")],
                                   closes=CLOSES["2026-09-15"], index_close=1.0, statements=index)
    assert stale["status"] == "NO_FACTORS_IN_FORCE" and stale["per"] is None


def test_low_forecast_coverage_keeps_the_number_but_marks_it_unusable():
    index = backfill.statement_index([r for r in STATEMENTS if r["Code"] != "10040"])
    point = backfill.rebuild_point("2026-08-31", factor_sets=[_table_set()], closes=CLOSES["2026-08-31"],
                                   index_close=_index_close("2026-08-31"), statements=index)
    assert point["status"] == "LOW_FORECAST_COVERAGE" and point["usable"] is False
    assert point["per"] is not None and point["coverage"]["forecastPriceShare"] < 0.8
    assert point["coverage"]["missingForecastEpsCount"] == 1
    assert backfill.index_per_rows([point]) == []


def test_factor_sets_roll_back_through_declared_events_and_keep_the_divisor():
    # 1003 joined on 2026-08-03 replacing 1006 (factor 1.0); the divisor is
    # unchanged here only because the fixture prices 1006 like 1003 on the eve.
    events = [{"effectiveDate": "2026-08-03", "code": "1003", "factorBefore": None, "factorAfter": 1.0},
              {"effectiveDate": "2026-08-03", "code": "1006", "factorBefore": 1.0, "factorAfter": None}]
    anchor = _table_set("2026-08-31")
    sets = [anchor, *backfill.backroll_factor_sets(anchor, events, complete_since="2026-07-01")]
    july = backfill.factor_set_in_force("2026-07-31", sets)
    assert july["origin"] == "EVENT_BACKROLL" and "1006" in july["factors"] and "1003" not in july["factors"]
    assert backfill.factor_set_in_force("2026-08-03", sets)["factors"] == FACTORS
    assert backfill.factor_set_in_force("2026-06-30", sets) is None
    closes = {**CLOSES["2026-07-31"], "1006": 800.0}
    july_factors = {**{c: f for c, f in FACTORS.items() if c != "1003"}, "1006": 1.0}
    index_close = sum(closes[c] * f for c, f in july_factors.items()) / DIVISOR
    rows = [*STATEMENTS, _stmt("1006", "2026-05-12", period="FY", fy_end="2026-03-31", eps=30.0,
                               nx_feps=35.0, next_fy_end="2027-03-31")]
    point = backfill.rebuild_point("2026-07-31", factor_sets=sets, closes=closes, index_close=index_close,
                                   statements=backfill.statement_index(rows))
    assert point["factorOrigin"] == "EVENT_BACKROLL" and point["usable"] is True
    assert point["impliedDivisor"] == pytest.approx(DIVISOR, rel=1e-9)


def test_an_event_list_that_disagrees_with_the_anchor_is_refused():
    anchor = _table_set("2026-08-31")
    wrong = [{"effectiveDate": "2026-08-10", "code": "1004", "factorBefore": 1.0, "factorAfter": 0.2}]
    with pytest.raises(proxy.ProxyError, match="factor_event_inconsistent"):
        backfill.backroll_factor_sets(anchor, wrong, complete_since="2026-07-01")


def test_a_split_after_the_table_is_counted_and_the_scaling_rule_keeps_the_divisor():
    splits = {"1002": [("2026-09-01", 0.5)]}
    closes = {**CLOSES["2026-09-15"], "1002": 1200.0}          # post-split raw close
    # Under a rule that scales the factor by the split, the index is continuous
    # with the factor 2.0 and the same divisor.
    scaled = {**FACTORS, "1002": 2.0}
    index_close = sum(closes[c] * f for c, f in scaled.items()) / DIVISOR
    index = backfill.statement_index(STATEMENTS)
    kept = backfill.rebuild_point("2026-09-15", factor_sets=[_table_set("2026-08-31")], closes=closes,
                                  index_close=index_close, statements=index, splits=splits)
    rule = backfill.rebuild_point("2026-09-15", factor_sets=[_table_set("2026-08-31")], closes=closes,
                                  index_close=index_close, statements=index, splits=splits,
                                  factor_split_rule="SCALE_BY_SPLIT_RATIO")
    assert kept["coverage"]["membersWithSplitSinceFactors"] == 1
    assert kept["coverage"]["splitAdjustedForecasts"] == 1
    assert kept["impliedDivisor"] != pytest.approx(DIVISOR, rel=1e-6)
    assert rule["impliedDivisor"] == pytest.approx(DIVISOR, rel=1e-9)


def test_month_ends_rows_summary_and_the_overlap_comparison():
    assert backfill.month_end_sessions(["2026-07-30", "2026-07-31", "2026-08-28", "2026-08-03"]) == \
        ["2026-07-31", "2026-08-28"]
    index = backfill.statement_index(STATEMENTS)
    points = backfill.backfill(["2026-08-31", "2026-09-15", "2026-06-30"],
                               factor_sets=[_table_set("2026-08-31")], closes=CLOSES,
                               index_close_by_date={d: _index_close(d) for d in CLOSES}, statements=index)
    rows = backfill.index_per_rows(points)
    assert [r["date"] for r in rows] == ["2026-08-31", "2026-09-15"]
    assert all(r["derivationBasis"] == proxy.PROXY_BASIS and r["availableFrom"] > r["date"] for r in rows)
    report = backfill.summary(points)
    assert report["usable"] == 2 and report["firstUsable"] == "2026-08-31"
    assert report["byStatus"] == {"NO_FACTORS_IN_FORCE": 1, "AVAILABLE": 2}
    # The live lane's per-session history is the yardstick on the overlap.
    live = {p["date"]: p["per"] * 1.01 for p in points if p["usable"]}
    measured = proxy.compare_with_official(points, live)
    assert measured["variants"][proxy.RECOMMENDED_VARIANT]["meanErrorPct"] == pytest.approx(-0.990099, rel=1e-4)
