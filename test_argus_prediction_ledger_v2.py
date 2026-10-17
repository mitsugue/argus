import copy

import pytest

import argus_decision_ledger as dl


ISSUED = "2026-08-10T15:00:00+00:00"
TARGET = "2026-08-11T20:00:00+00:00"
MATURE = "2026-08-11T20:05:00+00:00"
RECORDED = "2026-08-11T20:10:00+00:00"
EVALUATED = "2026-08-11T20:11:00+00:00"
SESSION = "XNYS:2026-08-11:regular"
CLASS_LABELS = [
    "downside_continuation",
    "sideways_stabilization",
    "rebound_attempt",
]


def _decision_truth(*, known_at=ISSUED):
    return dl.point_in_time_truth_ref(
        snapshot_id="truth-decision-001",
        source_id="market-truth-fabric",
        provider="provider-neutral-adapter",
        as_of=ISSUED,
        known_at=known_at,
        revision="r1",
        content_hash="a" * 64,
        observation_kind="decision_snapshot",
        observed_fields=["close", "freshness", "provenance"],
    )


def _maturity():
    return dl.session_maturity_contract(
        calendar_id="XNYS",
        target_session_id=SESSION,
        target_at=TARGET,
        maturity_at=MATURE,
        horizon="1d",
        session_kind="regular",
    )


def _distribution(*, labels=None, probabilities=None,
                  version="tactical-band-v1"):
    return dl.forecast_distribution(
        class_labels=labels or CLASS_LABELS,
        probabilities=probabilities or [0.3, 0.5, 0.2],
        class_order_version=version,
    )


def _prediction(*, mode="forward_live", action="BUY", truth=None,
                confidence=0.7, distribution=None):
    return dl.prediction_record_v2(
        mode=mode,
        symbol="AAPL",
        market="US",
        issued_at=ISSUED,
        horizon="1d",
        target_type="direction",
        forecast_value="up",
        confidence=confidence,
        candidate_action=action,
        target_ladder=[{"targetId": "up-2pct", "value": 2.0, "unit": "%"}],
        invalidation={"ruleId": "down-1pct", "value": -1.0, "unit": "%"},
        truth_ref=truth or _decision_truth(),
        maturity=_maturity(),
        engine_id="argus-decision-engine",
        engine_version="13.2.0",
        build_sha="b" * 40,
        evaluation_policy={"policyId": "direction-1d",
                           "policyVersion": "1"},
        evidence_refs=["evidence:price:001"],
        missing_evidence=[],
        dissent=["breadth confirmation incomplete"],
        forecast_distribution=distribution,
        replay_cutoff_at=ISSUED if mode == "historical_replay" else "",
        now_iso=(EVALUATED if mode == "historical_replay" else ISSUED),
    )


def _outcome_truth(*, known_at=MATURE, as_of=TARGET,
                   session=SESSION, fields=None,
                   kind="target_session_ohlc", digest="c" * 64):
    return dl.point_in_time_truth_ref(
        snapshot_id="truth-outcome-001",
        source_id="market-truth-fabric",
        provider="another-provider-adapter",
        as_of=as_of,
        known_at=known_at,
        revision="official-close-r1",
        content_hash=digest,
        observation_kind=kind,
        observed_fields=fields or ["open", "high", "low", "close"],
        target_session_id=session,
    )


def _metric(metric_type, family, value, *, unit="%", observation_ref="",
            target_ref="", missing_reason=""):
    return dl.evaluation_metric(
        metric_type=metric_type,
        family=family,
        value=value,
        unit=unit,
        metric_version="1",
        method_version="ohlc-path-v1",
        polarity="contextual",
        window="target_session",
        observed_at=TARGET if family != "missing" else "",
        first_observed_at=(TARGET if family in ("target", "invalidation")
                           else ""),
        observation_ref=observation_ref,
        target_ref=target_ref,
        evidence_refs=["truth-outcome-001"],
        missing_reason=missing_reason,
    )


def _observed_metrics(*, wait=False, target=True, invalidation=False,
                      target_bar="bar:2026-08-11",
                      invalidation_bar="bar:2026-08-11:later"):
    rows = [
        _metric("path.mfe_pct", "mfe", 4.5),
        _metric("path.mae_pct", "mae", -1.25),
        _metric("target.touch", "target", target, unit="boolean",
                observation_ref=target_bar, target_ref="up-2pct"),
        _metric("invalidation.touch", "invalidation", invalidation,
                unit="boolean", observation_ref=invalidation_bar,
                target_ref="down-1pct"),
        _metric("horizon.end_return_pct", "end", 1.75),
        _metric("benchmark.relative_return_pct", "benchmark", 0.4),
    ]
    if wait:
        rows.extend([
            _metric("opportunity.avoided_mae_pct", "opportunity", 1.25),
            _metric("opportunity.missed_mfe_pct", "opportunity", 4.5),
        ])
    return rows


def _outcome(prediction, *, status="OBSERVED", metrics=None,
             truth=None, recorded_at=RECORDED, sequence=1,
             previous_event_id="", missing_reasons=None):
    return dl.outcome_resolution_event(
        prediction=prediction,
        recorded_at=recorded_at,
        truth_ref=truth or _outcome_truth(),
        status=status,
        metrics=metrics or _observed_metrics(
            wait=prediction.get("candidateAction") == "WAIT"),
        method_version="target-session-resolution-v1",
        sequence=sequence,
        previous_event_id=previous_event_id,
        missing_reasons=missing_reasons or [],
    )


def _score_metric(value=0.09):
    return dl.evaluation_metric(
        metric_type="score.brier",
        family="score",
        value=value,
        unit="score",
        metric_version="1",
        method_version="argus-calibration-brier-v1",
        polarity="lower_better",
        window="1d",
        evidence_refs=["outcome-resolution"],
    )


def _evaluation(prediction, outcome, *, metrics=None):
    return dl.evaluation_event_record(
        prediction=prediction,
        outcome=outcome,
        evaluated_at=EVALUATED,
        metrics=metrics or [_score_metric()],
        scoring_policy={"policyId": "direction-brier",
                        "policyVersion": "1"},
        evaluator_id="argus-calibration",
        evaluator_version="1",
        build_sha="d" * 40,
    )


def _missing_metric(metric_type="truth.target_session_missing"):
    return _metric(metric_type, "missing", None, unit="status",
                   missing_reason="target_session_truth_missing")


def test_all_canonical_modes_are_hash_bound_and_distinct():
    records = [_prediction(mode=mode) for mode in dl.PREDICTION_MODES]
    assert all(records)
    assert len({row["id"] for row in records}) == 3
    for mode, row in zip(dl.PREDICTION_MODES, records):
        assert row["mode"] == mode
        assert dl.verify_prediction_record_v2(row)
        assert dl.prediction_mode(row) == mode


@pytest.mark.parametrize("path,value", [
    (("mode",), "shadow"),
    (("truthRef", "contentHash"), "tampered"),
    (("engine", "buildSha"), "tampered"),
    (("candidateAction",), "WAIT"),
    (("maturity", "targetSessionId"), "XNYS:wrong"),
])
def test_issued_decision_mutation_breaks_integrity(path, value):
    record = _prediction()
    changed = copy.deepcopy(record)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert dl.verify_prediction_record_v2(record)
    assert not dl.verify_prediction_record_v2(changed)


def test_categorical_distribution_is_optional_bounded_and_hash_bound():
    without_distribution = _prediction()
    assert "forecastDistribution" not in without_distribution
    assert dl.verify_prediction_record_v2(without_distribution)

    distribution = _distribution()
    record = _prediction(distribution=distribution)
    assert record["forecastDistribution"] == distribution
    assert record["id"] != without_distribution["id"]
    assert dl.verify_prediction_record_v2(record)

    reordered = _distribution(
        labels=list(reversed(CLASS_LABELS)),
        probabilities=[0.2, 0.5, 0.3])
    reordered_record = _prediction(distribution=reordered)
    assert reordered_record["id"] != record["id"]

    changed = copy.deepcopy(record)
    changed["forecastDistribution"]["probabilities"][0] = 0.31
    assert changed["id"] == record["id"]
    assert not dl.verify_prediction_record_v2(changed)


@pytest.mark.parametrize("labels,probabilities,version", [
    (CLASS_LABELS, [0.3, 0.5, float("nan")], "tactical-band-v1"),
    (CLASS_LABELS, [0.3, 0.5, float("inf")], "tactical-band-v1"),
    (CLASS_LABELS, [0.3, 0.5, -0.2], "tactical-band-v1"),
    (CLASS_LABELS, [0.3, 0.5, 1.2], "tactical-band-v1"),
    (CLASS_LABELS, [0.3, 0.5, 0.19], "tactical-band-v1"),
    (CLASS_LABELS, [0.3, 0.5], "tactical-band-v1"),
    (["duplicate", "duplicate"], [0.5, 0.5], "tactical-band-v1"),
    (["valid", "bad label"], [0.5, 0.5], "tactical-band-v1"),
    (["valid", "other"], [True, 0.0], "tactical-band-v1"),
    (["valid", "other"], [0.5, 0.5], ""),
])
def test_categorical_distribution_rejects_hostile_shapes(
        labels, probabilities, version):
    assert dl.forecast_distribution(
        class_labels=labels,
        probabilities=probabilities,
        class_order_version=version) is None


def test_categorical_distribution_rejects_unknown_keys_and_tampered_order():
    distribution = _distribution()
    with_unknown = copy.deepcopy(distribution)
    with_unknown["scoringRule"] = "brier"
    assert _prediction(distribution=with_unknown) is None

    record = _prediction(distribution=distribution)
    changed = copy.deepcopy(record)
    changed["forecastDistribution"]["classLabels"].reverse()
    assert not dl.verify_prediction_record_v2(changed)


def test_prediction_rejects_future_truth_outcome_fields_and_nonfinite_confidence():
    future_truth = _decision_truth(known_at="2026-08-10T15:01:00+00:00")
    assert _prediction(truth=future_truth) is None
    assert _prediction(confidence=float("nan")) is None
    base = dict(
        mode="forward_live", symbol="AAPL", market="US", issued_at=ISSUED,
        horizon="1d", target_type="direction", forecast_value="up",
        truth_ref=_decision_truth(), maturity=_maturity(),
        engine_id="engine", engine_version="1", build_sha="b" * 40,
        evaluation_policy={"policyId": "p", "policyVersion": "1"},
        now_iso=ISSUED,
    )
    assert dl.prediction_record_v2(**base, endPrice=123.0) is None


def test_legacy_v1_origin_is_never_upgraded_to_a_sealed_mode():
    legacy = dl.forecast_record(
        symbol="AAPL", market="US", issued_at=ISSUED, horizon="1d",
        target_type="direction", forecast_value="up", now_iso=ISSUED)
    legacy["origin"] = "forward_live"
    assert dl.verify_forecast_integrity(legacy)  # preserved v1 compatibility
    classified = dl.classify_prediction_record(legacy)
    assert classified["recordClass"] == "legacy_v1"
    assert classified["mode"] == "unknown_legacy"
    assert classified["modeSealed"] is False


def test_target_session_and_independent_maturity_are_exact_not_latest():
    prediction = _prediction()
    metrics = _observed_metrics()
    assert _outcome(prediction, recorded_at=TARGET, metrics=metrics) is None
    assert _outcome(
        prediction, metrics=metrics,
        truth=_outcome_truth(session="XNYS:2026-08-12:regular")) is None
    assert _outcome(
        prediction, metrics=metrics,
        truth=_outcome_truth(as_of=RECORDED,
                             known_at="2026-08-11T20:12:00+00:00")) is None


def test_observed_mfe_mae_require_actual_target_session_ohlc():
    prediction = _prediction()
    close_only = _outcome_truth(fields=["close"])
    assert _outcome(prediction, truth=close_only,
                    metrics=_observed_metrics()) is None
    event = _outcome(prediction)
    assert event and dl.verify_outcome_resolution_event(event, prediction)
    families = {row["family"] for row in event["metrics"]}
    assert {"mfe", "mae", "end"}.issubset(families)


def test_same_bar_target_and_invalidation_is_ambiguous_and_not_scoreable():
    prediction = _prediction()
    metrics = _observed_metrics(
        target=True, invalidation=True,
        target_bar="bar:collision", invalidation_bar="bar:collision")
    assert _outcome(prediction, status="OBSERVED", metrics=metrics) is None
    ambiguous = _outcome(prediction, status="AMBIGUOUS", metrics=metrics)
    assert ambiguous and dl.verify_outcome_resolution_event(ambiguous, prediction)
    assert _evaluation(prediction, ambiguous) is None
    missing_eval = _evaluation(prediction, ambiguous,
                               metrics=[_missing_metric("score.ambiguous_path")])
    assert missing_eval and missing_eval["evaluationStatus"] == "UNSCORABLE"


def test_wait_requires_avoided_mae_and_missed_mfe_opportunity_metrics():
    prediction = _prediction(action="WAIT")
    assert _outcome(prediction, metrics=_observed_metrics(wait=False)) is None
    event = _outcome(prediction, metrics=_observed_metrics(wait=True))
    assert event and dl.verify_outcome_resolution_event(event, prediction)
    types = {row["metricType"] for row in event["metrics"]}
    assert {"opportunity.avoided_mae_pct",
            "opportunity.missed_mfe_pct"}.issubset(types)


def test_missing_or_malformed_truth_is_unscorable_never_zero_scored():
    prediction = _prediction()
    missing_truth = _outcome_truth(
        fields=["fetch_status"], kind="target_session_missing")
    missing_metric = _missing_metric()
    assert _outcome(prediction, status="MISSING", metrics=[missing_metric],
                    truth=missing_truth,
                    missing_reasons=["provider_timeout"]) is None
    assert _outcome(prediction, status="OBSERVED", metrics=[missing_metric],
                    truth=missing_truth) is None
    event = _outcome(
        prediction, status="UNSCORABLE", metrics=[missing_metric],
        truth=missing_truth, missing_reasons=["provider_timeout"])
    assert event and event["status"] == "UNSCORABLE"
    assert all(row["value"] is None for row in event["metrics"])
    assert dl.verify_outcome_resolution_event(event, prediction)


def test_wait_unscorable_still_names_both_opportunity_metrics():
    prediction = _prediction(action="WAIT")
    missing_truth = _outcome_truth(
        fields=["fetch_status"], kind="target_session_missing")
    one = [_missing_metric("opportunity.avoided_mae_pct")]
    assert _outcome(prediction, status="UNSCORABLE", metrics=one,
                    truth=missing_truth, missing_reasons=["missing_ohlc"]) is None
    both = one + [_missing_metric("opportunity.missed_mfe_pct")]
    event = _outcome(prediction, status="UNSCORABLE", metrics=both,
                     truth=missing_truth, missing_reasons=["missing_ohlc"])
    assert event and dl.verify_outcome_resolution_event(event, prediction)


def test_resolution_retry_is_a_new_append_only_event_not_a_mutation():
    prediction = _prediction()
    first = _outcome(prediction)
    frozen = copy.deepcopy(first)
    later_truth = _outcome_truth(
        known_at="2026-08-11T20:12:00+00:00", digest="e" * 64)
    second = _outcome(
        prediction, truth=later_truth,
        recorded_at="2026-08-11T20:12:00+00:00",
        sequence=2, previous_event_id=first["id"])
    assert first == frozen
    assert second and second["id"] != first["id"]
    assert second["previousEventId"] == first["id"]
    assert dl.verify_outcome_resolution_event(first, prediction)
    assert dl.verify_outcome_resolution_event(second, prediction)


def test_evaluation_is_append_only_cross_bound_and_tamper_evident():
    prediction = _prediction()
    outcome = _outcome(prediction)
    evaluation = _evaluation(prediction, outcome)
    assert evaluation and dl.verify_evaluation_event(
        evaluation, prediction, outcome)
    changed = copy.deepcopy(evaluation)
    changed["metrics"][0]["value"] = 0.99
    assert not dl.verify_evaluation_event(changed, prediction, outcome)
    other = _prediction(mode="shadow")
    assert not dl.verify_evaluation_event(evaluation, other, outcome)


def test_metric_contract_is_typed_extensible_and_rejects_nonfinite():
    custom = _metric("opportunity.cash_yield_delta_pct", "opportunity", 0.35)
    assert custom["metricType"] == "opportunity.cash_yield_delta_pct"
    assert _metric("UPPERCASE", "opportunity", 1.0) is None
    assert _metric("path.mfe_pct", "mfe", float("inf")) is None
    assert _metric("missing.price", "missing", 0.0,
                   missing_reason="missing") is None


def test_mode_scoped_aggregate_never_mixes_modes_and_calibration_is_live_only():
    live_prediction = _prediction(mode="forward_live")
    live_outcome = _outcome(live_prediction)
    live_eval = _evaluation(live_prediction, live_outcome)
    shadow_prediction = _prediction(mode="shadow")
    shadow_outcome = _outcome(shadow_prediction)
    shadow_eval = _evaluation(shadow_prediction, shadow_outcome,
                              metrics=[_score_metric(0.25)])
    live = dl.aggregate_evaluation_events(
        [live_eval, shadow_eval], mode="forward_live", purpose="calibration")
    assert live["evaluationCount"] == 1
    assert live["excludedOtherMode"] == 1
    assert live["calibrationEligible"] is True
    assert live["metrics"][0]["mean"] == 0.09
    shadow = dl.aggregate_evaluation_events(
        [live_eval, shadow_eval], mode="shadow")
    assert shadow["evaluationCount"] == 1
    assert shadow["metrics"][0]["mean"] == 0.25
    with pytest.raises(ValueError):
        dl.aggregate_evaluation_events([shadow_eval], mode="shadow",
                                       purpose="calibration")
    with pytest.raises(ValueError):
        dl.aggregate_evaluation_events([live_eval], mode="unknown_legacy")


def test_aggregate_rejects_unbounded_history_instead_of_implicitly_scanning_it():
    prediction = _prediction()
    event = _evaluation(prediction, _outcome(prediction))
    with pytest.raises(ValueError):
        dl.aggregate_evaluation_events(
            [event] * (dl._V2_MAX_AGGREGATE_EVENTS + 1),
            mode="forward_live")
