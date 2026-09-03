"""v13.5.38 — MARKET SIGNALS (SIG-01..07) owner-facing projection tests."""
from __future__ import annotations

import ast
import pathlib

import argus_market_signals as signals


def _row(status="AVAILABLE", condition=None):
    return {"status": status, "conditionMet": condition,
            "lineage": "SHO_ORIGINAL", "validationStatus": "UNVALIDATED"}


def test_seven_owner_facing_identities_are_fixed_and_ordered():
    assert signals.SIGNAL_IDS == (
        "SIG-01", "SIG-02", "SIG-03", "SIG-04", "SIG-05", "SIG-06", "SIG-07")
    assert signals.SIGNAL_TOTAL == 7
    assert [row["family"] for row in signals.SIGNAL_DEFINITIONS] == [
        "D01", "D02", "D03", "D04", "D05", "D06", "D07"]
    names = {row["id"]: row["nameEn"] for row in signals.SIGNAL_DEFINITIONS}
    assert names["SIG-01"] == "Margin / Credit Balance"
    assert names["SIG-02"] == "1570 / Supply-Demand"
    assert names["SIG-03"] == "Relative Strength"
    assert names["SIG-04"] == "Japan Earnings / Valuation"
    assert names["SIG-05"] == "Foreign Investor Flow"
    assert names["SIG-06"] == "VIX / MACD"
    assert names["SIG-07"] == "Earnings Reaction"
    # Owner-facing vocabulary never carries the legacy person-derived name.
    for row in signals.SIGNAL_DEFINITIONS:
        assert "SHO" not in row["nameEn"] and "SHO" not in row["nameJa"]


def test_numerator_counts_only_active_signals_and_is_not_hard_coded():
    none_active = signals.project_market_signals({
        f"D0{i}": _row(condition=False) for i in range(1, 8)})
    assert none_active["activeCount"] == 0 and none_active["countLabel"] == "0 / 7"
    three = signals.project_market_signals({
        "D01": _row(condition=True), "D02": _row(condition=True),
        "D03": _row(condition=True), "D04": _row("LICENSE_BLOCKED"),
        "D05": _row(condition=False), "D06": _row(condition=None),
        "D07": _row("MISSING")})
    assert three["activeCount"] == 3 and three["countLabel"] == "3 / 7"
    assert three["total"] == 7
    seven = signals.project_market_signals({
        f"D0{i}": _row(condition=True) for i in range(1, 8)})
    assert seven["activeCount"] == 7 and seven["countLabel"] == "7 / 7"
    assert "AVAILABLE and conditionMet true" in three["countRule"]


def test_each_signal_state_is_independent_and_truthful():
    projection = signals.project_market_signals({
        "D01": _row(condition=True), "D02": _row(condition=False),
        "D03": _row(condition=None), "D04": _row("LICENSE_BLOCKED"),
        "D05": _row("STALE"), "D06": _row("MISSING"),
        # D07 absent entirely: a missing provider is UNAVAILABLE, never zero/CLEAR
    })
    by_id = {row["id"]: row["state"] for row in projection["signals"]}
    assert by_id == {
        "SIG-01": "ACTIVE", "SIG-02": "CLEAR", "SIG-03": "DATA_GATED",
        "SIG-04": "LICENSE_BLOCKED", "SIG-05": "STALE",
        "SIG-06": "UNAVAILABLE", "SIG-07": "UNAVAILABLE",
    }
    assert projection["activeCount"] == 1
    assert projection["stateCounts"] == {
        "ACTIVE": 1, "CLEAR": 1, "DATA_GATED": 1, "STALE": 1,
        "LICENSE_BLOCKED": 1, "UNAVAILABLE": 2,
    }
    assert projection["actionAuthority"] is False
    assert projection["schemaVersion"] == "argus-market-signals-v1"


def test_missing_or_malformed_families_never_collapse_to_clear():
    assert signals.project_market_signals(None)["activeCount"] == 0
    states = {row["state"] for row in
              signals.project_market_signals(None)["signals"]}
    assert states == {"UNAVAILABLE"}
    assert signals.signal_state({"status": "AVAILABLE"}) == "DATA_GATED"
    assert signals.signal_state({"status": "PARTIAL", "conditionMet": True}) == "DATA_GATED"
    assert signals.signal_state("not a row") == "UNAVAILABLE"


def test_module_is_pure_and_carries_no_authority():
    source = pathlib.Path(signals.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "typing"}
    for forbidden in ("os", "time", "requests", "socket", "argus_providers",
                      "scanner", "argus_single_decision"):
        assert forbidden not in imported
    assert "order" not in source.lower().replace("display order", "")


def test_sho_projection_embeds_market_signals():
    import argus_sho as sho
    cutoff = "2026-09-03T02:00:00Z"
    projection = sho.project_today_sda_safe(cutoff=cutoff)
    assert projection["marketSignals"]["total"] == 7
    assert projection["marketSignals"]["activeCount"] == 0
    assert [row["id"] for row in projection["marketSignals"]["signals"]] == \
        list(signals.SIGNAL_IDS)
    assert projection["actionAuthority"] is False and projection["action"] is None
