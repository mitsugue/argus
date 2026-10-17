"""Nikkei 225 contributions from recovered or owner-entered factors (2026-10-17)."""
from decimal import Decimal

import jp_index_contribution as ic

DIVISOR = Decimal("2.5")
FACTORS = {"1001": 1.0, "1002": 0.5, "1003": 2.0}
START = {"1001": 1000, "1002": 4000, "1003": 300}
END = {"1001": 1100, "1002": 3900, "1003": 330}


def official(prices, factors=FACTORS, divisor=DIVISOR):
    total = sum(Decimal(str(prices[c])) * Decimal(str(f)) for c, f in factors.items())
    return float((total / divisor).quantize(Decimal("0.01")))


def run(**kw):
    args = dict(start="2026-10-14", end="2026-10-15", members_start=FACTORS, members_end=FACTORS,
                closes={"2026-10-14": START, "2026-10-15": END},
                index_close={"2026-10-14": official(START), "2026-10-15": official(END)},
                derived_factors=FACTORS, names={"1001": "甲", "1002": "乙", "1003": "丙"})
    args.update(kw)
    return ic.period(**args)


def test_points_add_up_to_the_index_move():
    result = run()
    assert result["status"] == "AVAILABLE" and result["members"] == 3
    assert result["impliedDivisor"] == 2.5 and abs(result["residualPoints"]) <= 0.02
    points = {row["code"]: row["points"] for row in result["top"]}
    assert points == {"1001": 40.0, "1003": 24.0, "1002": -20.0}
    assert result["top"][0]["nameJa"] == "甲" and result["bottom"][0]["code"] == "1002"
    assert result["sumOfContributionsPoints"] == result["indexDeltaPoints"] == 44.0


def test_a_large_unseen_factor_change_shows_no_member_values():
    # The real factor of 1003 became 0.2 (a big split); the derived 2.0 is far off.
    actual = {**FACTORS, "1003": 0.2}
    result = run(index_close={"2026-10-14": official(START), "2026-10-15": official(END, actual)})
    assert result["status"] == "SUM_MISMATCH" and "top" not in result


def test_a_new_member_is_counted_with_factor_one_and_marked_as_an_estimate():
    """Owner 2026-10-17: fully automatic; an estimate within a small error is fine."""
    derived = {"1001": 1.0, "1002": 0.5}               # 1003 joined after the weight table
    exact = run(derived_factors=derived, index_close={"2026-10-14": official(START, {**FACTORS, "1003": 1.0}),
                                                      "2026-10-15": official(END, {**FACTORS, "1003": 1.0})})
    assert exact["status"] == "AVAILABLE" and exact["assumedFactorCodes"] == ["1003"] and exact["estimate"] is True
    near = run(derived_factors=derived)                # the real factor is 2.0: the error is 15 points
    assert near["status"] == "SUM_MISMATCH" or abs(near["residualPoints"]) <= max(1.0, 0.03 * abs(near["indexDeltaPoints"]))


def test_a_small_residual_is_shown_as_an_estimate_and_a_large_one_is_hidden():
    exact = run()
    assert exact["status"] == "AVAILABLE" and exact["estimate"] is False
    slightly = run(index_close={"2026-10-14": official(START), "2026-10-15": official(END) + 0.5})
    assert slightly["status"] == "AVAILABLE" and slightly["estimate"] is True
    far = run(index_close={"2026-10-14": official(START), "2026-10-15": official(END) + 5})
    assert far["status"] == "SUM_MISMATCH"


def test_changes_inside_the_period_are_refused():
    assert run(members_end={"1001", "1002"})["reason"] == "constituents_changed_in_period"
    assert run(closes={"2026-10-14": START, "2026-10-15": {"1001": 1100}})["reason"] == "member_closes_missing"
    assert run(index_close={"2026-10-14": official(START)})["reason"] == "index_close_missing"


def test_scanner_keeps_member_closes_and_computes_from_cached_inputs_only(monkeypatch):
    import scanner
    from unittest.mock import Mock
    monkeypatch.setattr(scanner.requests, "get", Mock(side_effect=AssertionError("no fetch")))
    monkeypatch.setattr(scanner, "_JP_INDEX_PROXY", {"factors": {"factors": dict(FACTORS)}, "weightsAsOf": "2026-09-30",
                                                     "memberCloses": {}})
    monkeypatch.setattr(scanner, "_nikkei225_constituent_changes", lambda: {"rows": []})
    monkeypatch.setattr(scanner, "_jq_name_for", lambda code, **kw: {"1001": "甲"}.get(code))
    for day, prices in (("2026-10-14", START), ("2026-10-15", END)):
        bars = {code + "0": {"C": price} for code, price in prices.items()}
        bars["99990"] = {"C": 1}                                     # not a member: not kept
        scanner._jp_index_keep_member_closes(day, bars, scanner._JP_INDEX_PROXY["factors"])
    assert set(scanner._JP_INDEX_PROXY["memberCloses"]["2026-10-14"]) == set(FACTORS)
    rows = [{"date": "2026-10-14", "close": official(START)}, {"date": "2026-10-15", "close": official(END)}]
    result = scanner._jp_index_contribution_for("2026-10-14", "2026-10-15", rows)
    assert result["status"] == "AVAILABLE" and result["top"][0]["nameJa"] == "甲"
    monkeypatch.setitem(scanner._JP_INDEX_PROXY, "factors", {})
    assert scanner._jp_index_contribution_for("2026-10-14", "2026-10-15", rows)["reason"] == "weight_table_not_configured"


def test_the_market_snapshot_carries_the_contributions_and_names_the_movers():
    import jp_market_internals as mi
    import test_jp_market_internals as base
    calls = []
    def contributions(horizon, start, end):
        calls.append((horizon, start, end))
        return {"status": "AVAILABLE", "top": [{"code": "8035", "nameJa": "東京エレクトロン", "points": 120.5, "pricePct": 3.1}],
                "bottom": [{"code": "9984", "nameJa": "ソフトバンクグループ", "points": -80.25, "pricePct": -2.0}]}
    p, m = base.snapshot()
    snapshot = mi.build_snapshot(session_dates=base.DATES, cutoff=base.AT, prices=p, symbols=["1234"],
                                 classifications=m, index_contributions=contributions)
    assert calls and snapshot["periods"]["1"]["indexContributions"]["status"] == "AVAILABLE"
    text = mi.explanation_facts(snapshot)[0]["text"]
    assert "押し上げ上位: 8035東京エレクトロン +120.50円" in text and "押し下げ上位: 9984ソフトバンクグループ -80.25円" in text
