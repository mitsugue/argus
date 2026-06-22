"""Tests for argus_ai_cost — the AI cost ledger + hard budget stops (v10.50)."""
import datetime as dt
import argus_ai_cost as c


def test_estimate_cost_basic():
    # 1M input @ $1.25 + 1M output @ $10 = $11.25
    assert c.estimate_cost("gpt-5.5", 1_000_000, 1_000_000) == 11.25
    assert c.estimate_cost("gpt-5.5", 0, 0) == 0.0


def test_estimate_cost_grounding_and_unknown_model():
    base = c.estimate_cost("gemini-2.5-pro", 1000, 500)
    withg = c.estimate_cost("gemini-2.5-pro", 1000, 500, grounding=True, grounding_usd=0.035)
    assert round(withg - base, 6) == 0.035
    assert c.estimate_cost("nonexistent-model", 9_999_999, 9_999_999) == 0.0   # honest 0, not fabricated


def test_estimate_cost_bad_inputs_safe():
    assert c.estimate_cost("gpt-5.5", None, "x") == 0.0
    assert c.estimate_cost("gpt-5.5", True, False) == 0.0          # bools are not token counts


def test_budget_check_under_allows():
    ok, why, reserve = c.budget_check(1.0, 10.0, 5.0, 80.0, 2.0)
    assert ok and why is None and reserve is False


def test_budget_check_daily_stop():
    ok, why, _ = c.budget_check(5.0, 10.0, 5.0, 80.0)
    assert not ok and "daily" in why


def test_budget_check_monthly_stop_and_reserve():
    ok, why, _ = c.budget_check(1.0, 80.0, 5.0, 80.0, 2.0)
    assert not ok and "monthly" in why
    # force dips into the reserve up to budget+reserve
    ok2, _, used = c.budget_check(1.0, 80.5, 5.0, 80.0, 2.0, force=True)
    assert ok2 and used is True
    # reserve exhausted → still blocked even with force
    ok3, _, _ = c.budget_check(1.0, 82.0, 5.0, 80.0, 2.0, force=True)
    assert not ok3


def test_budget_zero_is_unlimited():
    ok, why, _ = c.budget_check(999.0, 9999.0, 0, 0)
    assert ok and why is None


def test_keys():
    d = dt.datetime(2026, 6, 22, 16, 5)
    assert c.month_key(d) == "2026-06"
    assert c.day_key(d) == "2026-06-22"
