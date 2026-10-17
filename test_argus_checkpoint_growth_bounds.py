"""Strict active-state growth bounds for Checkpoint V2 source sections."""
import argus_chart_intelligence as chart
import argus_market_ledger as market
import argus_market_replay as replay
import argus_today_intelligence as today


def test_market_ledger_retains_bounded_per_series_window():
    rows = [{"seriesId": "breadth.advancers",
             "periodEnd": f"{i:08d}",
             "revision": 0, "id": f"o-{i}"}
            for i in range(market.MAX_OBSERVATIONS_PER_SERIES + 9)]
    state = market.normalize_state({"observations": rows})
    assert len(state["observations"]) == market.MAX_OBSERVATIONS_PER_SERIES
    assert state["observations"][-1]["id"] == rows[-1]["id"]


def test_market_ledger_auxiliary_histories_are_bounded():
    state = market.normalize_state({
        "imports": [{"importId": str(i)}
                    for i in range(market.MAX_IMPORT_RECEIPTS + 5)],
        "backtests": [{"id": str(i)}
                      for i in range(market.MAX_BACKTESTS + 5)],
        "rolledBackImports": [str(i)
                              for i in range(market.MAX_IMPORT_RECEIPTS + 5)],
    })
    assert len(state["imports"]) == market.MAX_IMPORT_RECEIPTS
    assert len(state["backtests"]) == market.MAX_BACKTESTS
    assert len(state["rolledBackImports"]) == market.MAX_IMPORT_RECEIPTS


def test_chart_state_collections_are_bounded():
    rows = [{"id": str(i), "calculatedAt": f"{i:06d}"}
            for i in range(chart.STATE_LIMITS["snapshots"] + 5)]
    assert len(chart.normalize_state({"snapshots": rows})["snapshots"]) == \
        chart.STATE_LIMITS["snapshots"]


def test_today_state_collections_are_bounded():
    rows = [{"id": str(i), "asOf": f"{i:06d}"}
            for i in range(today.STATE_LIMITS["snapshots"] + 5)]
    assert len(today.normalize_state({"snapshots": rows})["snapshots"]) == \
        today.STATE_LIMITS["snapshots"]


def test_market_replay_compact_receipts_are_bounded():
    rows = [{"contextId": str(i), "asOf": f"{i:06d}"}
            for i in range(replay.MAX_CONTEXT_HISTORY + 5)]
    assert len(replay.normalize_state({
        "contextHistory": rows})["contextHistory"]) == replay.MAX_CONTEXT_HISTORY
