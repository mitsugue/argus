"""The proxy reconstructs the index-based PER from declared inputs, and says how well.

A five-member price-weighted index with known factors is built here so every
identity can be checked exactly: the factors come back from weights and closes,
Σ P·f / divisor reproduces the close, the PER equals Σ P·f / Σ EPS·f, and the
comparison with an official series ranks the EPS variants by measured error.
"""
import math

import pytest

import argus_index_valuation_proxy as proxy

CODES = ("1001", "1002", "1003", "1004", "1005")
FACTORS = {"1001": 1.0, "1002": 1.0, "1003": 1.0, "1004": 0.1, "1005": 0.5}
CLOSES_T0 = {"1001": 1000.0, "1002": 2500.0, "1003": 800.0, "1004": 60000.0, "1005": 9000.0}
DIVISOR = 25.0


def _weights_text(closes=CLOSES_T0, factors=FACTORS, day="2026/08/31"):
    total = sum(closes[c] * factors[c] for c in CODES)
    lines = [",".join(proxy.WEIGHT_COLUMNS)]
    for code in CODES:
        weight = closes[code] * factors[code] / total * 100
        lines.append(f'"{day}","{code}","社名{code}","業種","セクター","{weight:.4f}%"')
    lines.append('"本資料は日経の著作物であり、無断で複写、複製、転載または流布することができません。"')
    return "\r\n".join(lines) + "\r\n"


@pytest.fixture(autouse=True)
def _small_index(monkeypatch):
    # The production floor of 200 priced members guards a 225-name index; the
    # five-name fixture lowers it so the arithmetic itself is what is tested.
    monkeypatch.setattr(proxy, "MINIMUM_PRICED_MEMBERS", 3)


def test_the_weight_table_parses_and_the_notice_never_survives():
    table = proxy.parse_weight_table(_weights_text())
    assert table["asOf"] == "2026-08-31"
    assert table["memberCount"] == 5
    assert table["noticeSeen"] is True
    assert 99.99 < table["weightTotalPct"] < 100.01
    assert all(set(row) == {"code", "weightPct"} for row in table["members"])


@pytest.mark.parametrize("mutation, reason", [
    (lambda t: t.replace("ウエート", "重み"), "weight_table_columns"),
    (lambda t: t.replace('"1002"', '"1001"'), "weight_table_duplicate_code"),
    (lambda t: t.replace("%", ""), "weight_table_weight_unit"),
    (lambda t: t.replace("2026/08/31", "2026/07/31", 1), "weight_table_mixed_dates"),
])
def test_a_malformed_weight_table_is_refused_with_a_reason(mutation, reason):
    with pytest.raises(proxy.ProxyError, match=reason):
        proxy.parse_weight_table(mutation(_weights_text()))


def test_factors_are_recovered_from_weights_and_closes():
    table = proxy.parse_weight_table(_weights_text())
    derived = proxy.derive_factors(table, CLOSES_T0)
    assert derived["factors"] == FACTORS
    assert derived["coverage"]["reducedFactorMembers"] == ["1004", "1005"]
    assert derived["coverage"]["unsnapped"] == []
    assert derived["coverage"]["priced"] == 5


def test_a_member_without_a_close_is_reported_not_guessed():
    table = proxy.parse_weight_table(_weights_text())
    closes = {c: v for c, v in CLOSES_T0.items() if c != "1003"}
    derived = proxy.derive_factors(table, closes)
    assert "1003" not in derived["factors"]
    assert derived["coverage"]["unpriced"] == ["1003"]


def test_the_identity_check_reproduces_the_official_close():
    table = proxy.parse_weight_table(_weights_text())
    derived = proxy.derive_factors(table, CLOSES_T0)
    official = sum(CLOSES_T0[c] * FACTORS[c] for c in CODES) / DIVISOR
    check = proxy.factor_identity_check(derived, CLOSES_T0, divisor=DIVISOR, official_close=official)
    assert check["status"] == "AVAILABLE"
    assert abs(check["errorPct"]) < 1e-6


def test_the_proxy_per_is_the_factor_weighted_price_over_earnings_ratio():
    table = proxy.parse_weight_table(_weights_text())
    derived = proxy.derive_factors(table, CLOSES_T0)
    closes_t = {"1001": 1100.0, "1002": 2400.0, "1003": 820.0, "1004": 61000.0, "1005": 8800.0}
    fwd = {"1001": 50.0, "1002": 125.0, "1003": -10.0, "1004": 3000.0, "1005": 450.0}
    act = {"1001": 45.0, "1002": 120.0, "1003": 5.0, "1004": 2800.0, "1005": 400.0}
    index = sum(closes_t[c] * FACTORS[c] for c in CODES) / DIVISOR
    row = proxy.proxy_valuation(factors=derived, closes=closes_t, forecast_eps=fwd, actual_eps=act,
                                index_close=index, date="2026-09-10",
                                available_from="2026-09-10T15:30:00+09:00",
                                known_at="2026-09-10T15:40:00+09:00", source_ref="test:proxy",
                                official_per=21.5)
    price_sum = sum(closes_t[c] * FACTORS[c] for c in CODES)
    signed = sum(fwd[c] * FACTORS[c] for c in CODES)
    floored = sum(max(fwd[c], 0) * FACTORS[c] for c in CODES)
    assert math.isclose(row["variants"]["FORECAST_SIGNED"]["per"], price_sum / signed, rel_tol=1e-6)
    assert math.isclose(row["variants"]["FORECAST_NON_NEGATIVE"]["per"], price_sum / floored, rel_tol=1e-6)
    assert row["variants"]["FORECAST_SIGNED"]["per"] > row["variants"]["FORECAST_NON_NEGATIVE"]["per"]
    assert math.isclose(row["impliedDivisor"], DIVISOR, rel_tol=1e-9)
    assert row["coverage"]["negativeForecastEps"] == 1
    assert row["basis"] == proxy.PROXY_BASIS and row["basis"] != proxy.OFFICIAL_BASIS
    assert row["variants"]["FORECAST_SIGNED"]["errorPct"] is not None
    # index EPS = index / PER, on every variant
    for body in row["variants"].values():
        assert math.isclose(body["indexEps"], index / body["per"], rel_tol=1e-6)


def test_missing_prices_and_forecasts_travel_with_the_number():
    table = proxy.parse_weight_table(_weights_text())
    derived = proxy.derive_factors(table, CLOSES_T0)
    closes_t = dict(CLOSES_T0); del closes_t["1005"]
    fwd = {"1001": 50.0, "1002": 125.0, "1004": 3000.0}
    row = proxy.proxy_valuation(factors=derived, closes=closes_t, forecast_eps=fwd, actual_eps={},
                                index_close=1000.0, date="2026-09-10", available_from="x",
                                known_at="x", source_ref="test")
    assert row["coverage"]["missingPrice"] == ["1005"]
    assert row["coverage"]["missingForecastEps"] == ["1003"]
    assert row["variants"]["ACTUAL_SIGNED"]["per"] is None


def test_the_selected_variant_row_carries_the_proxy_basis_and_error():
    table = proxy.parse_weight_table(_weights_text())
    derived = proxy.derive_factors(table, CLOSES_T0)
    fwd = {c: 100.0 for c in CODES}
    row = proxy.proxy_valuation(factors=derived, closes=CLOSES_T0, forecast_eps=fwd, actual_eps={},
                                index_close=3000.0, date="2026-09-10", available_from="a",
                                known_at="k", source_ref="s", official_per=20.0)
    selected = proxy.select_variant(row, "FORECAST_SIGNED")
    assert selected["basis"] == proxy.PROXY_BASIS
    assert selected["officialErrorPct"] == row["variants"]["FORECAST_SIGNED"]["errorPct"]
    assert selected["date"] == "2026-09-10" and selected["per"] == row["variants"]["FORECAST_SIGNED"]["per"]
    with pytest.raises(proxy.ProxyError, match="unknown_eps_variant"):
        proxy.select_variant(row, "WHATEVER")


def test_the_comparison_ranks_variants_by_measured_error_and_names_gaps():
    proxies = [
        {"date": "2026-09-01", "variants": {"FORECAST_SIGNED": {"per": 22.5}, "FORECAST_NON_NEGATIVE": {"per": 22.1}, "ACTUAL_SIGNED": {"per": None}}},
        {"date": "2026-09-02", "variants": {"FORECAST_SIGNED": {"per": 21.9}, "FORECAST_NON_NEGATIVE": {"per": 21.5}, "ACTUAL_SIGNED": {"per": 19.0}}},
    ]
    official = {"2026-09-01": 22.02, "2026-09-02": 21.39, "2026-09-03": 21.35}
    report = proxy.compare_with_official(proxies, official)
    assert report["sessionsCompared"] == 2
    assert report["officialSessionsWithoutProxy"] == ["2026-09-03"]
    assert report["recommendedVariant"] == "FORECAST_NON_NEGATIVE"
    assert report["variants"]["ACTUAL_SIGNED"]["sessions"] == 1
    assert report["variants"]["FORECAST_SIGNED"]["maxAbsErrorPct"] >= report["variants"]["FORECAST_SIGNED"]["meanAbsErrorPct"]


def test_the_module_touches_no_network_clock_or_file():
    import inspect
    source = inspect.getsource(proxy)
    for forbidden in ("import requests", "urllib", "datetime.now", "open(", "import scanner", "time.time"):
        assert forbidden not in source, forbidden


def test_members_without_a_forecast_are_handled_by_the_two_fallback_variants():
    """A member with no forecast EPS must not inflate the PER silently: the
    fallback variant uses its actual EPS, the covered-only variant drops its
    price from the numerator as well, and the plain forecast variants keep
    the bias so the comparison against the official series can show it."""
    table = proxy.parse_weight_table(_weights_text())
    derived = proxy.derive_factors(table, CLOSES_T0)
    closes_t = {"1001": 1100.0, "1002": 2400.0, "1003": 820.0, "1004": 61000.0, "1005": 8800.0}
    fwd = {"1001": 50.0, "1002": 125.0, "1003": 40.0, "1005": 450.0}      # 1004 has no forecast
    act = {"1001": 45.0, "1002": 120.0, "1003": 5.0, "1004": 2800.0, "1005": 400.0}
    index = sum(closes_t[c] * FACTORS[c] for c in CODES) / DIVISOR
    row = proxy.proxy_valuation(factors=derived, closes=closes_t, forecast_eps=fwd, actual_eps=act,
                                index_close=index, date="2026-09-10",
                                available_from="2026-09-10T15:30:00+09:00",
                                known_at="2026-09-10T15:40:00+09:00", source_ref="test:proxy")
    price_sum = sum(closes_t[c] * FACTORS[c] for c in CODES)
    covered = [c for c in CODES if c != "1004"]
    plain = sum(fwd[c] * FACTORS[c] for c in covered)
    with_fallback = plain + act["1004"] * FACTORS["1004"]
    covered_price = sum(closes_t[c] * FACTORS[c] for c in covered)
    v = row["variants"]
    assert math.isclose(v["FORECAST_SIGNED"]["per"], price_sum / plain, rel_tol=1e-9)
    assert math.isclose(v["FORECAST_WITH_ACTUAL_FALLBACK"]["per"], price_sum / with_fallback, rel_tol=1e-9)
    assert math.isclose(v["FORECAST_COVERED_ONLY"]["per"], covered_price / plain, rel_tol=1e-9)
    assert v["FORECAST_SIGNED"]["per"] > v["FORECAST_WITH_ACTUAL_FALLBACK"]["per"]
    assert v["FORECAST_SIGNED"]["per"] > v["FORECAST_COVERED_ONLY"]["per"]
    assert row["coverage"]["missingForecastEps"] == ["1004"]
    assert row["coverage"]["actualEpsFallbackUsed"] == 1
    assert set(v) == set(proxy.EPS_VARIANTS)
    for name in proxy.EPS_VARIANTS:
        assert math.isclose(v[name]["indexEps"], index / v[name]["per"], rel_tol=1e-9)
