from scripts.audit_breadth_probability_truth import (
    ai_added_value,
    breadth_reconciliation,
    build_report,
)


def _point(date, direction, suffix):
    return {
        "id": f"tp-{suffix}",
        "ruleId": "BREADTH_TURN",
        "effectiveFrom": date,
        "direction": direction,
    }


def test_reconciliation_deduplicates_by_date_universe_rule():
    market = {
        "turningPoints": [
            _point("2026-01-05", "prime:short_above_medium", "a"),
            _point("2026-01-05", "prime:short_above_medium", "duplicate"),
            _point("2026-01-06", "all:ratio6_over_120", "b"),
        ],
        "backtests": [],
    }
    canonical = [
        _point("2026-01-05", "prime:short_above_medium", "c"),
        _point("2026-01-06", "all:ratio6_over_120", "d"),
        _point("2026-01-07", "first_section:short_below_medium", "e"),
    ]
    result = breadth_reconciliation(
        market,
        as_of="2026-01-08T00:00:00Z",
        detected_at="2026-01-08T00:00:00Z",
        detector=lambda *_: canonical,
    )
    assert result["persistedCount"] == 3
    assert result["persistedUniquePartitionCount"] == 2
    assert result["persistedDuplicateExtraRows"] == 1
    assert result["canonicalCount"] == 3
    assert result["canonicalMissingFromPersisted"] == [{
        "date": "2026-01-07",
        "universe": "first_section",
        "rule": "short_below_medium",
    }]
    assert result["migrationExecuted"] is False


def test_ai_audit_does_not_mistake_power_score_for_predictive_rps():
    snapshot = {
        "forecasts": [{
            "id": "fc-1",
            "modelEpoch": "gemini:test",
            "ruleAction": None,
            "aiFinalAction": None,
        }],
        "outcomes": [{"forecastId": "fc-1", "status": "unresolved"}],
        "rpsHistory": [{"epochId": "gemini:test", "argusScore": 80}],
    }
    result = ai_added_value(snapshot)
    assert result["actualForecastRuns"] == 1
    assert result["resolvedOutcomes"] == 0
    assert result["researchPowerScoreRecords"] == 1
    assert result["researchPowerScoreIsPredictiveRps"] is False
    assert result["conclusion"] == "SECOND_OPINION_ONLY"


def test_directional_lean_population_excludes_breadth_turning_point_sets():
    report = build_report(
        {"marketLedger": {"observations": [], "turningPoints": [], "backtests": []}},
        generated_at="2026-07-27T00:00:00Z",
    )
    population = report["probabilityDisplayAudit"]["directionalLeanPopulation"]
    assert population["breadthTurningPointsUsed"] is False
    assert population["persisted4509TurningPointsUsed"] is False
    assert population["canonical4061TurningPointsUsed"] is False
    assert "price-bar episodes" in population["source"]
