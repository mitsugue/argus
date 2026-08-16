import copy
import json

import pytest

import argus_calibration
import argus_decision_ledger as decision_ledger
import argus_market_data_truth as market_truth
from scripts import run_prediction_ledger as runner


PRODUCER_SHA = "a" * 40
RUNNER_SHA = "b" * 40
ISSUED = "2026-08-10T20:10:00Z"
TARGET = "2026-08-11T20:00:00Z"
TARGET_KNOWN = "2026-08-11T20:03:00Z"
MATURE = "2026-08-11T20:05:00Z"
RUN_AT = "2026-08-11T20:10:00Z"
SESSION = "NYSE_NASDAQ:calendar-v1:2026-08-11:regular"
INSTRUMENT = "US:AAPL"


def _decision_observation():
    return market_truth.build_observation(
        instrument_id=INSTRUMENT, symbol="AAPL", market="US",
        asset_type="EQUITY", fact_type="QUOTE",
        values={"price": 100.0, "changePct": 1.0},
        provider="twelvedata", adapter="test-quote-adapter-v1",
        source_ref="test:AAPL:decision", observed_at="2026-08-10T20:00:00Z",
        received_at="2026-08-10T20:05:00Z",
        known_at="2026-08-10T20:05:00Z",
        freshness=market_truth.FRESH, completeness=market_truth.COMPLETE,
        fresh_until="2026-08-10T20:20:00Z",
        currency="USD", revision=1,
    )


def _market_snapshot(observation=None, *, decision_at=ISSUED,
                     generated_at=None):
    observation = observation or _decision_observation()
    return market_truth.build_decision_snapshot(
        [observation], requests=[{
            "instrumentId": INSTRUMENT, "market": "US",
            "factType": "QUOTE", "currency": "USD", "required": True,
        }], decision_at=decision_at,
        generated_at=generated_at or decision_at,
        build_identity=PRODUCER_SHA,
    )


def _distribution():
    return decision_ledger.forecast_distribution(
        class_labels=list(argus_calibration.CLASSES),
        probabilities=[0.3, 0.5, 0.2],
        class_order_version=runner.SUPPORTED_CLASS_ORDER_VERSION,
    )


def _prediction(*, invalidation=False, action="BUY", mode="forward_live"):
    observation = _decision_observation()
    snapshot = _market_snapshot(observation)
    truth_ref = decision_ledger.point_in_time_truth_ref(
        snapshot_id=snapshot["snapshotId"],
        source_id=observation["observationId"],
        as_of=observation["observedAt"], known_at=observation["knownAt"],
        content_hash=observation["observationId"],
        observation_kind="decision_quote",
        observed_fields=sorted(observation["values"]),
        provider="twelvedata", revision="1",
    )
    maturity = decision_ledger.session_maturity_contract(
        calendar_id="NYSE_NASDAQ:calendar-v1",
        target_session_id=SESSION, target_at=TARGET,
        maturity_at=MATURE, horizon="1d", session_kind="regular",
    )
    ladder = [
        decision_ledger.target_ladder_entry(
            target_id=runner.SCENARIO_DOWNSIDE_TARGET_ID,
            value=-2.0, unit="%", comparator="<", target_at=TARGET),
        decision_ledger.target_ladder_entry(
            target_id=runner.SCENARIO_REBOUND_TARGET_ID,
            value=2.0, unit="%", comparator=">", target_at=TARGET),
    ]
    invalidation_rule = (decision_ledger.invalidation_rule(
        rule_id="risk.invalidated", value=-1.0, unit="%",
        comparator="<=", target_at=TARGET) if invalidation else None)
    prediction = decision_ledger.prediction_record_v2(
        mode=mode, symbol="AAPL", market="US", issued_at=ISSUED,
        horizon="1d", target_type="scenario",
        forecast_value="sideways_stabilization",
        forecast_distribution=_distribution(), confidence=0.5,
        candidate_action=action, target_ladder=ladder,
        invalidation=invalidation_rule, truth_ref=truth_ref,
        maturity=maturity, engine_id="argus-tactical-candidate",
        engine_version="ledger-v3-compat-projection",
        build_sha=PRODUCER_SHA,
        evaluation_policy=runner.scenario_evaluation_policy(
            band_pct=2.0, horizon="1d")[1],
        now_iso=ISSUED,
    )
    assert prediction and decision_ledger.verify_prediction_record_v2(prediction)
    return prediction, snapshot


def _reseal_prediction(prediction, **overrides):
    values = {
        "mode": prediction["mode"],
        "symbol": prediction["symbol"],
        "market": prediction["market"],
        "issued_at": prediction["issuedAt"],
        "horizon": prediction["forecastHorizon"],
        "target_type": prediction["targetType"],
        "forecast_value": prediction["forecastValue"],
        "forecast_distribution": prediction.get("forecastDistribution"),
        "confidence": prediction.get("confidence"),
        "candidate_action": prediction.get("candidateAction") or "",
        "target_ladder": prediction.get("targetLadder") or [],
        "invalidation": prediction.get("invalidation"),
        "truth_ref": prediction["truthRef"],
        "maturity": prediction["maturity"],
        "engine_id": prediction["engine"]["engineId"],
        "engine_version": prediction["engine"]["engineVersion"],
        "build_sha": prediction["engine"]["buildSha"],
        "evaluation_policy": prediction["evaluationPolicy"],
        "evidence_refs": prediction.get("evidenceRefs") or [],
        "missing_evidence": prediction.get("missingEvidence") or [],
        "dissent": prediction.get("dissent") or [],
        "now_iso": prediction["immutableCreatedAt"],
    }
    values.update(overrides)
    resealed = decision_ledger.prediction_record_v2(**values)
    assert resealed and decision_ledger.verify_prediction_record_v2(resealed)
    return resealed


def _outcome_bar(*, observed_at=TARGET, known_at=TARGET_KNOWN,
                 high=103.0, low=99.0, close=102.5):
    return market_truth.build_observation(
        instrument_id=INSTRUMENT, symbol="AAPL", market="US",
        asset_type="EQUITY", fact_type="OHLCV_BAR",
        values={"open": 100.0, "high": high, "low": low,
                "close": close, "volume": 1000},
        provider="twelvedata", adapter="test-history-adapter-v1",
        source_ref=f"test:AAPL:{observed_at}", observed_at=observed_at,
        received_at=known_at, known_at=known_at,
        freshness=market_truth.STALE, completeness=market_truth.COMPLETE,
        currency="USD", period_end=observed_at, revision=1,
    )


def _snapshot(*, as_of, decisions=None, outcomes=None, status="COMPLETE",
              mode="forward_live", market_snapshot=None,
              generated_at=None, projection_generated_at=None):
    generated_at = generated_at or as_of
    projection_generated_at = projection_generated_at or generated_at
    if market_snapshot is None:
        market_snapshot = _market_snapshot(
            decision_at=as_of, generated_at=projection_generated_at)
    projection = {
        "schemaVersion": decision_ledger.PREDICTION_LEDGER_V2_SCHEMA,
        "mode": mode,
        "authority": "PREDICTION_EVIDENCE_ONLY",
        "finalDecisionAuthorityActive": False,
        "marketTruthSchemaVersion": market_truth.SCHEMA_VERSION,
        "marketTruthSnapshot": market_snapshot,
        "issuedDecisions": list(decisions or []),
        "outcomeTruthObservations": list(outcomes or []),
        "status": status,
        "candidateCount": len(decisions or []),
        "issuedCount": len(decisions or []),
        "omittedCandidateCount": 0,
        "marketTruthSnapshotVerified": True,
        "truthQualityComplete": True,
        "decisionAt": as_of,
        "generatedAt": projection_generated_at,
        "producerBuildSha": PRODUCER_SHA,
    }
    return {
        "dateJst": as_of[:10], "asOf": as_of,
        "generatedAt": generated_at,
        "engineVersion": "ledger-v3",
        "canonicalPredictionLedger": projection,
    }


def _run(snapshot, root, run_id):
    return runner.run_prediction_ledger(
        snapshot, ledger_root=root, expected_mode="forward_live",
        run_id=run_id, runner_build_sha=RUNNER_SHA)


def _read(path):
    return json.loads(path.read_text())


def _write_canonical(path, value):
    path.write_bytes(runner._canonical_bytes(value) + b"\n")


def _manifest(root):
    return _read(root / "manifest.json")


def _index(root):
    manifest = _manifest(root)
    return _read(root / manifest["index"]["path"])


def _aggregate(root):
    manifest = _manifest(root)
    return _read(root / manifest["aggregate"]["path"])


def _inventory(root):
    manifest = _manifest(root)
    return _read(root / manifest["inventory"]["path"])


def _reseal(value):
    material = copy.deepcopy(value)
    material.pop("digest", None)
    return runner._sealed_document(material)


def _replace_inventory_and_manifest(root, inventory, *, head=None):
    manifest_path = root / "manifest.json"
    manifest = _manifest(root)
    inventory = _reseal(inventory)
    _write_canonical(root / manifest["inventory"]["path"], inventory)
    manifest["inventory"].update({
        "digest": inventory["digest"],
        "segmentCount": inventory["segmentCount"],
        "historyRoot": inventory["historyRoot"],
    })
    if head is not None:
        manifest["head"] = copy.deepcopy(head)
    _write_canonical(manifest_path, _reseal(manifest))


def _build_deep_history(root):
    prediction, market_snapshot = _prediction()
    runs = [_run(_snapshot(
        as_of=ISSUED, decisions=[prediction],
        market_snapshot=market_snapshot), root, "history-issue")]
    runs.append(_run(_snapshot(as_of="2026-08-12T20:10:00Z"),
                     root, "history-unscorable"))
    runs.append(_run(_snapshot(
        as_of="2026-08-12T20:20:00Z", outcomes=[_outcome_bar()]),
        root, "history-resolve"))
    runs.append(_run(_snapshot(as_of="2026-08-12T20:21:00Z"),
                     root, "history-tail-1"))
    runs.append(_run(_snapshot(as_of="2026-08-12T20:22:00Z"),
                     root, "history-tail-2"))
    return runs


def _metric(event, metric_type):
    return next(row for row in event["metrics"]
                if row["metricType"] == metric_type)


def test_runner_appends_chain_and_scores_exact_ohlc_without_scans(tmp_path):
    prediction, market_snapshot = _prediction()
    first = _run(_snapshot(
        as_of=ISSUED, decisions=[prediction],
        market_snapshot=market_snapshot), tmp_path, "run-1")
    assert first == {
        "ok": True, "idempotent": False,
        "segmentPath": "segments/2026-08-10/run-1.json",
        "segmentId": first["segmentId"],
        "issued": 1, "outcomes": 0, "evaluations": 0,
        "pending": 1, "identityCount": 1,
        "aggregateEvaluationCount": 0,
    }

    second_snapshot = _snapshot(
        as_of=RUN_AT, outcomes=[_outcome_bar()])
    second = _run(second_snapshot, tmp_path, "run-2")
    assert second["issued"] == 0
    assert second["outcomes"] == second["evaluations"] == 1
    assert second["pending"] == 0

    segment = _read(tmp_path / second["segmentPath"])
    first_segment = _read(tmp_path / first["segmentPath"])
    assert segment["previousSegment"]["digest"] == first_segment["digest"]
    outcome = segment["outcomeResolutions"][0]
    evaluation = segment["evaluationEvents"][0]
    assert outcome["status"] == "OBSERVED"
    assert _metric(outcome, "path.mfe_pct")["value"] == 3.0
    assert _metric(outcome, "path.mae_pct")["value"] == -1.0
    assert _metric(outcome, "horizon.end_return_pct")["value"] == 2.5
    assert _metric(evaluation, "score.brier_raw_sum")["value"] == 0.98
    assert decision_ledger.verify_outcome_resolution_event(outcome, prediction)
    assert decision_ledger.verify_evaluation_event(
        evaluation, prediction, outcome)

    aggregate = _aggregate(tmp_path)
    assert aggregate["mode"] == "forward_live"
    assert aggregate["purpose"] == "calibration"
    assert aggregate["evaluationCount"] == 1
    assert {row["metricType"] for row in aggregate["metrics"]} == {
        "score.argmax_hit", "score.brier_normalized_mean",
        "score.brier_raw_sum", "score.rps_normalized", "score.rps_raw",
    }
    repeated = _run(second_snapshot, tmp_path, "run-2")
    assert repeated["idempotent"] is True
    assert _read(tmp_path / second["segmentPath"]) == segment


def test_latest_or_wrong_session_is_unscorable_then_exact_retry_appends(tmp_path):
    prediction, market_snapshot = _prediction()
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "issue")
    later = "2026-08-12T20:00:00Z"
    later_known = "2026-08-12T20:03:00Z"
    wrong_bar = _outcome_bar(observed_at=later, known_at=later_known)
    first_retry_at = "2026-08-12T20:10:00Z"
    missing_run = _run(_snapshot(
        as_of=first_retry_at, outcomes=[wrong_bar]),
        tmp_path, "missing-target")
    missing_segment = _read(tmp_path / missing_run["segmentPath"])
    first_outcome = missing_segment["outcomeResolutions"][0]
    assert first_outcome["status"] == "UNSCORABLE"
    assert first_outcome["sequence"] == 1
    assert first_outcome["truthRef"]["targetSessionId"] == SESSION
    assert first_outcome["truthRef"]["asOf"] == TARGET
    assert missing_run["pending"] == 1

    retry_at = "2026-08-12T20:20:00Z"
    resolved_run = _run(_snapshot(
        as_of=retry_at, outcomes=[wrong_bar, _outcome_bar()]),
        tmp_path, "exact-retry")
    resolved_segment = _read(tmp_path / resolved_run["segmentPath"])
    second_outcome = resolved_segment["outcomeResolutions"][0]
    assert second_outcome["status"] == "OBSERVED"
    assert second_outcome["sequence"] == 2
    assert second_outcome["previousEventId"] == first_outcome["id"]
    assert resolved_run["pending"] == 0
    aggregate = _aggregate(tmp_path)
    assert aggregate["evaluationCount"] == 2
    assert aggregate["unscorableCount"] == 1


@pytest.mark.parametrize("mutation", [
    "sequence_mismatch", "initial_state_after_retry", "latest_missing",
    "attempts_exhausted", "latest_identity_unknown",
])
def test_unreachable_pending_retry_state_fails_closed(tmp_path, mutation):
    prediction, market_snapshot = _prediction()
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "state-issue")
    retry_at = "2026-08-12T20:10:00Z"
    _run(_snapshot(as_of=retry_at), tmp_path, "state-retry")
    index = _index(tmp_path)
    row = index["pending"][0]
    if mutation == "sequence_mismatch":
        row["sequence"] = 0
    elif mutation == "initial_state_after_retry":
        row["state"] = "pending_maturity"
    elif mutation == "latest_missing":
        row["latestOutcomeEventId"] = None
        row["latestOutcomeIntegrityHash"] = None
    elif mutation == "attempts_exhausted":
        row["attempts"] = runner.MAX_RESOLUTION_ATTEMPTS
        row["sequence"] = runner.MAX_RESOLUTION_ATTEMPTS
    else:
        row["latestOutcomeEventId"] = "or-unknown"
    index.pop("digest")
    hostile = runner._sealed_document(index)
    with pytest.raises(
            runner.LedgerRunError,
            match="invalid_pending_sequence|invalid_pending_state|"
                  "invalid_pending_retry_identity"):
        runner._decode_index(hostile)


def test_pending_retry_latest_outcome_must_exist_in_its_source_segment(tmp_path):
    prediction, market_snapshot = _prediction()
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "source-issue")
    retry_at = "2026-08-12T20:10:00Z"
    _run(_snapshot(as_of=retry_at), tmp_path, "source-retry")
    manifest_path = tmp_path / "manifest.json"
    manifest = _read(manifest_path)
    index_path = tmp_path / manifest["index"]["path"]
    index = _read(index_path)
    pending = index["pending"][0]
    latest_id = pending["latestOutcomeEventId"]
    latest_identity = next(
        row for row in index["identities"] if row["id"] == latest_id)
    latest_identity["sourceSegment"] = pending["sourceSegment"]
    index.pop("digest")
    index = runner._sealed_document(index)
    _write_canonical(index_path, index)
    manifest["index"]["digest"] = index["digest"]
    manifest.pop("digest")
    manifest = runner._sealed_document(manifest)
    _write_canonical(manifest_path, manifest)

    with pytest.raises(
                runner.LedgerRunError,
                match="pending_source_outcome_mismatch|"
                      "index_canonical_source_mismatch|manifest_projection_mismatch|"
                      "committed_projection_witness_mismatch"):
        _run(_snapshot(as_of="2026-08-12T20:11:00Z"),
             tmp_path, "after-source-tamper")


def test_same_bar_target_and_invalidation_is_ambiguous(tmp_path):
    prediction, market_snapshot = _prediction(invalidation=True)
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "issue")
    result = _run(_snapshot(
        as_of=RUN_AT,
        outcomes=[_outcome_bar(high=103.0, low=98.5, close=100.0)]),
        tmp_path, "ambiguous")
    segment = _read(tmp_path / result["segmentPath"])
    outcome = segment["outcomeResolutions"][0]
    evaluation = segment["evaluationEvents"][0]
    assert outcome["status"] == "AMBIGUOUS"
    assert evaluation["evaluationStatus"] == "UNSCORABLE"
    assert _metric(evaluation, "score.ambiguous_same_bar")["value"] is None
    assert result["pending"] == 1


def test_wait_emits_explicit_avoided_mae_and_missed_mfe(tmp_path):
    prediction, market_snapshot = _prediction(action="WAIT")
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "wait-issue")
    result = _run(_snapshot(
        as_of=RUN_AT, outcomes=[_outcome_bar()]),
        tmp_path, "wait-resolve")
    outcome = _read(tmp_path / result["segmentPath"])[
        "outcomeResolutions"][0]
    assert _metric(outcome, "opportunity.avoided_mae_pct")["value"] == 1.0
    assert _metric(outcome, "opportunity.missed_mfe_pct")["value"] == 3.0


@pytest.mark.parametrize("mode,sha,error", [
    ("shadow", RUNNER_SHA, "canonical_projection_mode_or_schema_mismatch"),
    ("forward_live", "short", "runner_build_sha_must_be_exact"),
])
def test_mode_separation_and_exact_runner_identity_fail_closed(
        tmp_path, mode, sha, error):
    prediction, market_snapshot = _prediction()
    snapshot = _snapshot(as_of=ISSUED, decisions=[prediction], mode=mode,
                         market_snapshot=market_snapshot)
    with pytest.raises(runner.LedgerRunError, match=error):
        runner.run_prediction_ledger(
            snapshot, ledger_root=tmp_path, expected_mode="forward_live",
            run_id="hostile", runner_build_sha=sha)
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize("field,value", [
    ("status", "UNKNOWN"),
    ("omittedCandidateCount", -1),
    ("candidateCount", 0),
    ("issuedCount", 0),
])
def test_malformed_projection_status_and_counts_fail_before_write(
        tmp_path, field, value):
    prediction, market_snapshot = _prediction()
    snapshot = _snapshot(as_of=ISSUED, decisions=[prediction],
                         market_snapshot=market_snapshot)
    snapshot["canonicalPredictionLedger"][field] = value
    with pytest.raises(runner.LedgerRunError,
                       match="canonical_projection_incomplete"):
        _run(snapshot, tmp_path, f"incomplete-{field}")
    assert not (tmp_path / "manifest.json").exists()


def test_mixed_partial_projection_admits_only_complete_record_and_resolves(
        tmp_path):
    prediction, market_snapshot = _prediction()
    partial_issue = _snapshot(
        as_of=ISSUED, decisions=[prediction], status="INCOMPLETE",
        market_snapshot=market_snapshot)
    projection = partial_issue["canonicalPredictionLedger"]
    projection.update({
        "candidateCount": 2, "issuedCount": 1,
        "omittedCandidateCount": 1,
        "marketTruthSnapshotVerified": False,
        "truthQualityComplete": False,
    })
    issued = _run(partial_issue, tmp_path, "scheduled-partial-issue")
    assert issued["issued"] == 1
    partial_resolve = _snapshot(
        as_of=RUN_AT, outcomes=[_outcome_bar()], status="INCOMPLETE")
    partial_resolve["canonicalPredictionLedger"].update({
        "candidateCount": 1, "omittedCandidateCount": 1,
        "marketTruthSnapshotVerified": False,
        "truthQualityComplete": False,
    })
    resolved = _run(
        partial_resolve, tmp_path, "scheduled-partial-resolve")
    assert resolved["outcomes"] == resolved["evaluations"] == 1
    assert resolved["pending"] == 0


def test_outer_generated_at_is_exact_run_time_and_rejects_inversion(tmp_path):
    prediction, market_snapshot = _prediction()
    before = "2026-08-10T20:09:59Z"
    inverted = _snapshot(
        as_of=ISSUED, generated_at=before, decisions=[prediction],
        market_snapshot=market_snapshot)
    with pytest.raises(runner.LedgerRunError, match="snapshot_time_inversion"):
        _run(inverted, tmp_path, "time-inversion")
    assert not (tmp_path / "manifest.json").exists()


def test_market_truth_cutoff_must_equal_outer_decision_cutoff(tmp_path):
    _, old_market_snapshot = _prediction()
    later_cutoff = "2026-08-10T20:11:00Z"
    mismatched = _snapshot(
        as_of=later_cutoff, generated_at=later_cutoff,
        market_snapshot=old_market_snapshot)
    with pytest.raises(
            runner.LedgerRunError,
            match="market_truth_decision_cutoff_mismatch"):
        _run(mismatched, tmp_path, "cutoff-mismatch")
    assert not (tmp_path / "manifest.json").exists()


def test_missing_outer_generated_at_is_rejected(tmp_path):
    snapshot = _snapshot(as_of=ISSUED)
    snapshot.pop("generatedAt")
    with pytest.raises(runner.LedgerRunError,
                       match="invalid_snapshot_generated_at"):
        _run(snapshot, tmp_path, "missing-generated-at")


def test_pending_overflow_fails_without_segment_or_eviction(tmp_path, monkeypatch):
    prediction, market_snapshot = _prediction()
    monkeypatch.setattr(runner, "MAX_PENDING_RECORDS", 0)
    with pytest.raises(runner.LedgerRunError, match="pending_index_overflow"):
        _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                       market_snapshot=market_snapshot), tmp_path, "overflow")
    assert not (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "segments/2026-08-10/overflow.json").exists()


def test_self_consistent_identity_collision_fails_closed(tmp_path):
    prediction, market_snapshot = _prediction()
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "initial")
    manifest_path = tmp_path / "manifest.json"
    manifest = _read(manifest_path)
    index_path = tmp_path / manifest["index"]["path"]
    index = _read(index_path)
    index["identities"][0]["integrityHash"] = "f" * 64
    index.pop("digest")
    index = runner._sealed_document(index)
    _write_canonical(index_path, index)
    manifest["index"]["digest"] = index["digest"]
    manifest.pop("digest")
    manifest = runner._sealed_document(manifest)
    _write_canonical(manifest_path, manifest)

    with pytest.raises(
            runner.LedgerRunError,
            match="record_id_collision|pending_identity_binding_mismatch"):
        _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                       market_snapshot=market_snapshot), tmp_path, "collision")


def test_run_id_is_immutable_and_same_input_is_idempotent(tmp_path):
    prediction, market_snapshot = _prediction()
    original = _snapshot(as_of=ISSUED, decisions=[prediction],
                         market_snapshot=market_snapshot)
    first = _run(original, tmp_path, "fixed-run")
    assert _run(original, tmp_path, "fixed-run")["idempotent"] is True
    changed = copy.deepcopy(original)
    changed["canonicalPredictionLedger"]["sourceCandidateCount"] = 1
    with pytest.raises(runner.LedgerRunError,
                       match="immutable_document_collision"):
        _run(changed, tmp_path, "fixed-run")
    assert _read(tmp_path / first["segmentPath"])["inputDigest"] == \
        runner._digest({
            "asOf": original["asOf"],
            "generatedAt": original["generatedAt"],
            "canonicalPredictionLedger": original[
                "canonicalPredictionLedger"],
        })


def test_future_outcome_truth_is_rejected_before_any_write(tmp_path):
    prediction, market_snapshot = _prediction()
    future_bar = _outcome_bar()
    snapshot = _snapshot(as_of=ISSUED, decisions=[prediction],
                         outcomes=[future_bar], market_snapshot=market_snapshot)
    with pytest.raises(runner.LedgerRunError, match="future_outcome_truth"):
        _run(snapshot, tmp_path, "lookahead")
    assert not (tmp_path / "manifest.json").exists()


def test_policy_binding_rejects_hash_or_ladder_semantic_drift(tmp_path):
    prediction, market_snapshot = _prediction()
    bad_policy = copy.deepcopy(prediction["evaluationPolicy"])
    bad_policy["parametersHash"] = "f" * 64
    policy_drift = _reseal_prediction(
        prediction, evaluation_policy=bad_policy)
    with pytest.raises(runner.LedgerRunError,
                       match="evaluation_policy_mismatch"):
        _run(_snapshot(as_of=ISSUED, decisions=[policy_drift],
                       market_snapshot=market_snapshot),
             tmp_path, "policy-drift")

    inclusive_ladder = copy.deepcopy(prediction["targetLadder"])
    inclusive_ladder[0] = decision_ledger.target_ladder_entry(
        target_id=runner.SCENARIO_DOWNSIDE_TARGET_ID, value=-2.0,
        unit="%", comparator="<=", target_at=TARGET)
    comparator_drift = _reseal_prediction(
        prediction, target_ladder=inclusive_ladder)
    with pytest.raises(runner.LedgerRunError,
                       match="scenario_boundaries_missing"):
        _run(_snapshot(as_of=ISSUED, decisions=[comparator_drift],
                       market_snapshot=market_snapshot),
             tmp_path, "comparator-drift")

    extra_ladder = copy.deepcopy(prediction["targetLadder"])
    extra_ladder.append(decision_ledger.target_ladder_entry(
        target_id="scenario.extra", value=4.0, unit="%",
        comparator=">", target_at=TARGET))
    extra_target = _reseal_prediction(
        prediction, target_ladder=extra_ladder)
    with pytest.raises(runner.LedgerRunError,
                       match="noncanonical_scenario_targets"):
        _run(_snapshot(as_of=ISSUED, decisions=[extra_target],
                       market_snapshot=market_snapshot),
             tmp_path, "extra-target")
    assert not (tmp_path / "manifest.json").exists()


def test_truth_ref_must_bind_exact_selected_authoritative_observation(tmp_path):
    selected = _decision_observation()
    rejected = market_truth.build_observation(
        instrument_id=INSTRUMENT, symbol="AAPL", market="US",
        asset_type="EQUITY", fact_type="QUOTE",
        values={"price": 999.0, "changePct": 9.0},
        provider="unapproved-provider", adapter="hostile-adapter-v1",
        source_ref="hostile:AAPL:decision",
        observed_at="2026-08-10T20:00:00Z",
        received_at="2026-08-10T20:05:00Z",
        known_at="2026-08-10T20:05:00Z",
        freshness=market_truth.FRESH,
        completeness=market_truth.COMPLETE,
        fresh_until="2026-08-10T20:20:00Z", currency="USD", revision=1)
    snapshot = market_truth.build_decision_snapshot(
        [selected, rejected], requests=[{
            "instrumentId": INSTRUMENT, "market": "US",
            "factType": "QUOTE", "currency": "USD", "required": True,
        }], decision_at=ISSUED, generated_at=ISSUED,
        build_identity=PRODUCER_SHA)
    assert snapshot["selections"][0]["selectedObservationId"] == \
        selected["observationId"]
    prediction, _ = _prediction()
    rejected_ref = decision_ledger.point_in_time_truth_ref(
        snapshot_id=snapshot["snapshotId"],
        source_id=rejected["observationId"],
        as_of=rejected["observedAt"], known_at=rejected["knownAt"],
        content_hash=rejected["observationId"],
        observation_kind="decision_quote",
        observed_fields=sorted(rejected["values"]),
        provider=rejected["source"]["providerKey"], revision="1")
    hostile = _reseal_prediction(prediction, truth_ref=rejected_ref)
    with pytest.raises(runner.LedgerRunError,
                       match="prediction_decision_price_unbound"):
        _run(_snapshot(as_of=ISSUED, decisions=[hostile],
                       market_snapshot=snapshot), tmp_path, "rejected-source")
    assert not (tmp_path / "manifest.json").exists()


def test_selected_truth_quality_and_missing_evidence_are_rederived(tmp_path):
    prediction, market_snapshot = _prediction()
    missing = _reseal_prediction(
        prediction, missing_evidence=["freshness:STALE"])
    with pytest.raises(runner.LedgerRunError,
                       match="prediction_selected_truth_incomplete"):
        _run(_snapshot(as_of=ISSUED, decisions=[missing],
                       market_snapshot=market_snapshot),
             tmp_path, "missing-evidence")

    stale_observation = copy.deepcopy(_decision_observation())
    stale_observation.pop("observationId")
    stale_observation["freshness"] = market_truth.STALE
    stale_observation["freshUntil"] = None
    stale_observation["observationId"] = "mdo-" + market_truth._sha(
        stale_observation)[:32]
    stale_snapshot = _market_snapshot(stale_observation)
    stale_ref = decision_ledger.point_in_time_truth_ref(
        snapshot_id=stale_snapshot["snapshotId"],
        source_id=stale_observation["observationId"],
        as_of=stale_observation["observedAt"],
        known_at=stale_observation["knownAt"],
        content_hash=stale_observation["observationId"],
        observation_kind="decision_quote",
        observed_fields=sorted(stale_observation["values"]),
        provider=stale_observation["source"]["providerKey"], revision="1")
    stale_prediction = _reseal_prediction(prediction, truth_ref=stale_ref)
    with pytest.raises(runner.LedgerRunError,
                       match="prediction_selected_truth_incomplete"):
        _run(_snapshot(as_of=ISSUED, decisions=[stale_prediction],
                       market_snapshot=stale_snapshot),
             tmp_path, "stale-selected")


@pytest.mark.parametrize(
    "failure_phase", [
        "index", "aggregate", "inventory", "segment_stage",
        "manifest_commit", "commit_head", "manifest",
    ])
def test_crash_safe_publication_recovers_same_run_without_orphan_collision(
        tmp_path, monkeypatch, failure_phase):
    prediction, market_snapshot = _prediction()
    snapshot = _snapshot(as_of=ISSUED, decisions=[prediction],
                         market_snapshot=market_snapshot)
    original_install = runner._install_immutable_or_verify
    original_atomic = runner._atomic_write
    calls = {"install": 0}

    def flaky_install(*args, **kwargs):
        calls["install"] += 1
        phase = {
            1: "index", 2: "aggregate", 3: "inventory",
            4: "segment_stage", 5: "manifest_commit",
        }.get(calls["install"])
        if phase == failure_phase:
            raise runner.LedgerRunError(f"injected_{phase}_failure")
        return original_install(*args, **kwargs)

    def flaky_atomic(*args, **kwargs):
        path = args[0] if args else kwargs.get("path")
        if failure_phase == "commit_head" and path.name == "commit-head.json":
            raise runner.LedgerRunError("injected_commit_head_failure")
        if failure_phase == "manifest" and path.name == "manifest.json":
            raise runner.LedgerRunError("injected_manifest_failure")
        return original_atomic(*args, **kwargs)

    monkeypatch.setattr(runner, "_install_immutable_or_verify", flaky_install)
    monkeypatch.setattr(runner, "_atomic_write", flaky_atomic)
    with pytest.raises(runner.LedgerRunError, match="injected_"):
        _run(snapshot, tmp_path, "recoverable-run")
    assert not (tmp_path / "manifest.json").exists()

    monkeypatch.setattr(runner, "_install_immutable_or_verify", original_install)
    monkeypatch.setattr(runner, "_atomic_write", original_atomic)
    recovered = _run(snapshot, tmp_path, "recoverable-run")
    # The immutable commit marker precedes the mutable manifest projection.
    # A failure in that final projection therefore recovers as an already
    # committed idempotent run; earlier failures remain uncommitted orphans.
    assert recovered["idempotent"] is (
        failure_phase in {"commit_head", "manifest"})
    assert _run(snapshot, tmp_path, "recoverable-run")["idempotent"] is True
    assert len(list(tmp_path.glob("segments/*/recoverable-run.json"))) == 1


def test_missing_committed_manifest_version_fails_closed(tmp_path):
    result = _run(_snapshot(as_of=ISSUED), tmp_path, "manifest-version-1")
    (tmp_path / f"manifests/versions/{result['segmentId']}.json").unlink()
    with pytest.raises(runner.LedgerRunError,
                       match="unmanifested_segment_authority"):
        runner._load_state(tmp_path)


@pytest.mark.parametrize("suffix_count", [1, 2, 4])
def test_commit_head_rejects_deleted_committed_segment_suffix(
        tmp_path, suffix_count):
    runs = _build_deep_history(tmp_path)
    for offset in range(suffix_count):
        (tmp_path / runs[-1 - offset]["segmentPath"]).unlink()
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_missing"):
        runner._load_state(tmp_path)


def test_stale_commit_head_is_repaired_forward_without_rollback(tmp_path):
    _run(_snapshot(as_of=ISSUED), tmp_path, "stale-head-1")
    prior_head = (tmp_path / "commit-head.json").read_bytes()
    prior_manifest = (tmp_path / "manifest.json").read_bytes()
    second = _run(_snapshot(as_of="2026-08-10T20:11:00Z"),
                  tmp_path, "stale-head-2")
    (tmp_path / "commit-head.json").write_bytes(prior_head)
    (tmp_path / "manifest.json").write_bytes(prior_manifest)

    _, _, manifest, inventory, _, marker = runner._load_state(tmp_path)
    assert marker["generation"] == 2
    assert inventory["segmentCount"] == 2
    assert manifest["head"]["path"] == second["segmentPath"]

    third = _run(_snapshot(as_of="2026-08-10T20:12:00Z"),
                 tmp_path, "stale-head-3")
    repaired = _read(tmp_path / "commit-head.json")
    assert repaired["generation"] == 3
    assert _manifest(tmp_path)["head"]["path"] == third["segmentPath"]


@pytest.mark.parametrize("tamper", ["missing", "corrupt"])
def test_manifest_head_requires_exact_direct_predecessor(tmp_path, tamper):
    prediction, market_snapshot = _prediction()
    first = _run(_snapshot(
        as_of=ISSUED, decisions=[prediction],
        market_snapshot=market_snapshot), tmp_path, "predecessor")
    later = "2026-08-10T20:11:00Z"
    _run(_snapshot(as_of=ISSUED, generated_at=later),
         tmp_path, "head")
    predecessor = tmp_path / first["segmentPath"]
    if tamper == "missing":
        predecessor.unlink()
    else:
        predecessor.write_text("{}")
    with pytest.raises(runner.LedgerRunError,
                       match="manifest_predecessor|invalid_immutable|"
                             "retained_segment"):
        _run(_snapshot(
            as_of=ISSUED, generated_at="2026-08-10T20:12:00Z"),
            tmp_path, "after-tamper")


@pytest.mark.parametrize("position", [0, 1, 2])
def test_complete_inventory_rejects_deleted_issue_outcome_or_evaluation_segment(
        tmp_path, position):
    runs = _build_deep_history(tmp_path)
    (tmp_path / runs[position]["segmentPath"]).unlink()
    with pytest.raises(runner.LedgerRunError,
                       match="retained_segment_file_missing"):
        runner._load_state(tmp_path)


@pytest.mark.parametrize("positions", [(0, 1), (0, 2)])
def test_complete_inventory_rejects_multiple_missing_segments(
        tmp_path, positions):
    runs = _build_deep_history(tmp_path)
    for position in positions:
        (tmp_path / runs[position]["segmentPath"]).unlink()
    with pytest.raises(runner.LedgerRunError,
                       match="retained_segment_file_missing"):
        runner._load_state(tmp_path)


def test_complete_inventory_rejects_swapped_or_reordered_segments(tmp_path):
    runs = _build_deep_history(tmp_path)
    left = tmp_path / runs[1]["segmentPath"]
    right = tmp_path / runs[2]["segmentPath"]
    left_bytes, right_bytes = left.read_bytes(), right.read_bytes()
    left.write_bytes(right_bytes)
    right.write_bytes(left_bytes)
    with pytest.raises(runner.LedgerRunError,
                       match="retained_segment_mismatch"):
        runner._load_state(tmp_path)

    left.write_bytes(left_bytes)
    right.write_bytes(right_bytes)
    inventory = _inventory(tmp_path)
    inventory["segments"][1], inventory["segments"][2] = (
        inventory["segments"][2], inventory["segments"][1])
    inventory["historyRoot"] = runner._history_root(inventory["segments"])
    inventory["head"] = copy.deepcopy(inventory["segments"][-1])
    _replace_inventory_and_manifest(tmp_path, inventory)
    with pytest.raises(runner.LedgerRunError,
                       match="retained_segment_chain_mismatch|"
                             "manifest_projection_mismatch|"
                             "committed_manifest_mismatch"):
        runner._load_state(tmp_path)


@pytest.mark.parametrize("mutation", ["bytes", "truncate"])
def test_complete_inventory_rejects_altered_historical_bytes(
        tmp_path, mutation):
    runs = _build_deep_history(tmp_path)
    path = tmp_path / runs[1]["segmentPath"]
    payload = path.read_bytes()
    if mutation == "bytes":
        path.write_bytes(payload + b" ")
    else:
        path.write_bytes(payload[:len(payload) // 2])
    with pytest.raises(runner.LedgerRunError,
                       match="invalid_immutable"):
        runner._load_state(tmp_path)


def test_self_consistent_inventory_truncation_is_rejected_at_genesis(tmp_path):
    _build_deep_history(tmp_path)
    inventory = _inventory(tmp_path)
    inventory["segments"] = inventory["segments"][1:]
    inventory["segmentCount"] = len(inventory["segments"])
    inventory["head"] = copy.deepcopy(inventory["segments"][-1])
    inventory["historyRoot"] = runner._history_root(inventory["segments"])
    _replace_inventory_and_manifest(tmp_path, inventory)
    with pytest.raises(runner.LedgerRunError,
                       match="retained_history_truncated|"
                             "manifest_projection_mismatch|"
                             "invalid_inventory_authority_generation"):
        runner._load_state(tmp_path)


def test_stale_manifest_projection_cannot_bypass_commit_authority(tmp_path):
    runs = _build_deep_history(tmp_path)
    inventory = _inventory(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(tmp_path)
    manifest["head"] = copy.deepcopy(inventory["segments"][-2])
    _write_canonical(manifest_path, _reseal(manifest))
    _, _, authoritative_manifest, authoritative_inventory, _, marker = \
        runner._load_state(tmp_path)
    assert authoritative_manifest["head"] == inventory["segments"][-1]
    assert authoritative_inventory["head"] == inventory["segments"][-1]
    assert authoritative_manifest["head"]["path"] == runs[-1]["segmentPath"]
    assert marker["generation"] == len(runs)


def test_stale_index_cannot_survive_canonical_source_history(tmp_path):
    _build_deep_history(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(tmp_path)
    index_path = tmp_path / manifest["index"]["path"]
    index = _read(index_path)
    removed = len(index["identities"])
    index["identities"] = []
    index["counts"]["identityCount"] = 0
    index["retention"]["evictedIdentityCount"] += removed
    index = _reseal(index)
    _write_canonical(index_path, index)
    manifest["index"].update({
        "digest": index["digest"], "identityCount": 0,
        "pendingCount": index["counts"]["pendingCount"],
    })
    _write_canonical(manifest_path, _reseal(manifest))
    with pytest.raises(runner.LedgerRunError,
                       match="index_canonical_source_mismatch|"
                             "manifest_projection_mismatch|"
                             "committed_projection_witness_mismatch"):
        runner._load_state(tmp_path)


def test_stale_calibration_aggregate_cannot_survive_source_evaluations(
        tmp_path):
    _build_deep_history(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(tmp_path)
    aggregate_path = tmp_path / manifest["aggregate"]["path"]
    aggregate = runner._empty_aggregate()
    aggregate.pop("digest")
    aggregate["updatedAt"] = manifest["updatedAt"]
    aggregate = runner._sealed_document(aggregate)
    _write_canonical(aggregate_path, aggregate)
    manifest["aggregate"].update({
        "digest": aggregate["digest"], "evaluationCount": 0,
        "unscorableCount": 0,
    })
    _write_canonical(manifest_path, _reseal(manifest))
    with pytest.raises(runner.LedgerRunError,
                       match="calibration_canonical_source_mismatch|"
                             "manifest_projection_mismatch|"
                             "committed_projection_witness_mismatch"):
        runner._load_state(tmp_path)


def test_prior_committed_manifest_cannot_roll_back_complete_history(tmp_path):
    prediction, market_snapshot = _prediction()
    first = _run(_snapshot(
        as_of=ISSUED, decisions=[prediction],
        market_snapshot=market_snapshot), tmp_path, "rollback-1")
    _run(_snapshot(as_of="2026-08-12T20:10:00Z"),
         tmp_path, "rollback-2")
    prior_manifest = (tmp_path / "manifest.json").read_bytes()
    third = _run(_snapshot(
        as_of="2026-08-12T20:20:00Z", outcomes=[_outcome_bar()]),
        tmp_path, "rollback-3")
    latest_manifest = _manifest(tmp_path)

    # Restore a complete, formerly valid older mutable pointer while leaving
    # the newer committed immutable marker and authority files intact.
    (tmp_path / "manifest.json").write_bytes(prior_manifest)
    _, aggregate, manifest, inventory, _, marker = runner._load_state(tmp_path)
    assert inventory["segmentCount"] == 3
    assert manifest["head"]["path"] == third["segmentPath"]
    assert aggregate["evaluationCount"] == 2
    assert marker["generation"] == 3

    appended = _run(_snapshot(as_of="2026-08-12T20:21:00Z"),
                    tmp_path, "rollback-4")
    assert appended["idempotent"] is False
    repaired = _manifest(tmp_path)
    assert repaired["generation"] == 4
    assert repaired["head"]["path"] == appended["segmentPath"]
    assert repaired["head"]["path"] != first["segmentPath"]
    assert repaired["inventory"]["segmentCount"] == 4
    assert repaired["generation"] > latest_manifest["generation"]


def test_deleted_manifest_projection_cannot_create_second_genesis(tmp_path):
    first = _run(_snapshot(as_of=ISSUED), tmp_path, "delete-pointer-1")
    (tmp_path / "manifest.json").unlink()
    _, _, manifest, inventory, _, marker = runner._load_state(tmp_path)
    assert manifest["head"]["path"] == first["segmentPath"]
    assert inventory["segmentCount"] == 1
    assert marker["generation"] == 1

    second = _run(_snapshot(as_of="2026-08-10T20:11:00Z"),
                  tmp_path, "delete-pointer-2")
    repaired = _manifest(tmp_path)
    assert repaired["generation"] == 2
    assert repaired["inventory"]["segmentCount"] == 2
    assert repaired["head"]["path"] == second["segmentPath"]
    assert (tmp_path / first["segmentPath"]).is_file()


def test_restored_old_projections_and_deleted_segment_suffix_cannot_rollback(
        tmp_path):
    first = _run(_snapshot(as_of=ISSUED), tmp_path, "coordinated-rollback-1")
    old_manifest = (tmp_path / "manifest.json").read_bytes()
    old_head = (tmp_path / "commit-head.json").read_bytes()
    second = _run(_snapshot(as_of="2026-08-10T20:11:00Z"),
                  tmp_path, "coordinated-rollback-2")
    third = _run(_snapshot(as_of="2026-08-10T20:12:00Z"),
                 tmp_path, "coordinated-rollback-3")

    (tmp_path / "manifest.json").write_bytes(old_manifest)
    (tmp_path / "commit-head.json").write_bytes(old_head)
    (tmp_path / second["segmentPath"]).unlink()
    (tmp_path / third["segmentPath"]).unlink()
    assert (tmp_path / first["segmentPath"]).is_file()
    assert (tmp_path / f"manifests/versions/{second['segmentId']}.json").is_file()
    assert (tmp_path / f"manifests/versions/{third['segmentId']}.json").is_file()
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_missing"):
        runner._load_state(tmp_path)
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_missing"):
        _run(_snapshot(as_of="2026-08-10T20:13:00Z"),
             tmp_path, "coordinated-rollback-4")


def test_unmanifested_crash_tail_requires_exact_same_run_retry(
        tmp_path, monkeypatch):
    snapshot = _snapshot(as_of=ISSUED)
    original_install = runner._install_immutable_or_verify
    calls = {"count": 0}

    def fail_manifest_commit(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 5:
            raise runner.LedgerRunError("injected_manifest_commit_failure")
        return original_install(*args, **kwargs)

    monkeypatch.setattr(
        runner, "_install_immutable_or_verify", fail_manifest_commit)
    with pytest.raises(runner.LedgerRunError,
                       match="injected_manifest_commit_failure"):
        _run(snapshot, tmp_path, "exact-crash-retry")
    monkeypatch.setattr(
        runner, "_install_immutable_or_verify", original_install)

    with pytest.raises(runner.LedgerRunError,
                       match="unmanifested_segment_authority"):
        runner._load_state(tmp_path)
    with pytest.raises(runner.LedgerRunError,
                       match="unmanifested_segment_authority"):
        _run(_snapshot(as_of="2026-08-10T20:11:00Z"),
             tmp_path, "different-run-cannot-adopt")
    with pytest.raises(runner.LedgerRunError,
                       match="unmanifested_segment_authority"):
        _run(_snapshot(as_of="2026-08-11T20:10:00Z"),
             tmp_path, "exact-crash-retry")
    assert len(list(tmp_path.glob(
        "segments/*/exact-crash-retry.json"))) == 1
    recovered = _run(snapshot, tmp_path, "exact-crash-retry")
    assert recovered["idempotent"] is False
    assert _manifest(tmp_path)["generation"] == 1


def test_committed_run_id_cannot_be_reused_on_another_date(tmp_path):
    first = _run(_snapshot(as_of=ISSUED), tmp_path, "date-bound-run")
    manifest_before = (tmp_path / "manifest.json").read_bytes()
    with pytest.raises(runner.LedgerRunError, match="duplicate_run_id"):
        _run(_snapshot(as_of="2026-08-11T20:10:00Z"),
             tmp_path, "date-bound-run")
    assert (tmp_path / "manifest.json").read_bytes() == manifest_before
    assert (tmp_path / first["segmentPath"]).is_file()
    assert not (tmp_path /
                "segments/2026-08-11/date-bound-run.json").exists()


@pytest.mark.parametrize("head_mode", ["missing", "stale"])
def test_public_manifest_witness_rejects_paired_committed_suffix_deletion(
        tmp_path, head_mode):
    runs = _build_deep_history(tmp_path)
    stale_head = runner._commit_head_document(
        _read(tmp_path /
              f"manifests/versions/{runs[1]['segmentId']}.json"),
        manifest_path=(
            f"manifests/versions/{runs[1]['segmentId']}.json"))
    for run in runs[2:]:
        (tmp_path / run["segmentPath"]).unlink()
        (tmp_path /
         f"manifests/versions/{run['segmentId']}.json").unlink()
    if head_mode == "missing":
        (tmp_path / "commit-head.json").unlink()
    else:
        _write_canonical(tmp_path / "commit-head.json", stale_head)
    # The latest valid public manifest was installed only after its immutable
    # generation, so it is a durable monotonic witness of the deleted suffix.
    assert _manifest(tmp_path)["generation"] == len(runs)
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_suffix_missing"):
        runner._load_state(tmp_path)
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_suffix_missing"):
        _run(_snapshot(as_of="2026-08-12T20:30:00Z"),
             tmp_path, "cannot-fork-truncated-history")


def test_immutable_projection_witnesses_reject_full_authority_suffix_rollback(
        tmp_path):
    runs = _build_deep_history(tmp_path)
    retained_manifest = _read(
        tmp_path / f"manifests/versions/{runs[1]['segmentId']}.json")
    retained_head = runner._commit_head_document(
        retained_manifest,
        manifest_path=(
            f"manifests/versions/{runs[1]['segmentId']}.json"))
    for run in runs[2:]:
        (tmp_path / run["segmentPath"]).unlink()
        (tmp_path /
         f"manifests/versions/{run['segmentId']}.json").unlink()
        (tmp_path /
         f"inventories/versions/{run['segmentId']}.json").unlink()
    _write_canonical(tmp_path / "manifest.json", retained_manifest)
    _write_canonical(tmp_path / "commit-head.json", retained_head)

    # The immutable index/aggregate generations are installed before commit.
    # Their surviving ids are bounded monotonic witnesses of the removed
    # canonical suffix and may not be ignored to create a shorter journal.
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_suffix_missing"):
        runner._load_state(tmp_path)
    with pytest.raises(runner.LedgerRunError,
                       match="committed_segment_suffix_missing"):
        _run(_snapshot(as_of="2026-08-12T20:30:00Z"),
             tmp_path, "projection-witness-cannot-fork")


def test_prepared_inventory_is_bound_to_exact_deterministic_segment(
        tmp_path, monkeypatch):
    original_install = runner._install_immutable_or_verify
    calls = {"count": 0}

    def fail_segment_stage(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 4:
            raise runner.LedgerRunError("injected_segment_stage_failure")
        return original_install(*args, **kwargs)

    snapshot = _snapshot(as_of=ISSUED)
    monkeypatch.setattr(
        runner, "_install_immutable_or_verify", fail_segment_stage)
    with pytest.raises(runner.LedgerRunError,
                       match="injected_segment_stage_failure"):
        _run(snapshot, tmp_path, "prepared-exact-segment")
    monkeypatch.setattr(
        runner, "_install_immutable_or_verify", original_install)
    witness_names = tuple(sorted(
        path.name for path in (tmp_path / "inventories/versions").iterdir()))

    with pytest.raises(runner.LedgerRunError,
                       match="prepared_segment_identity_mismatch"):
        _run(_snapshot(as_of=ISSUED, status="INCOMPLETE"),
             tmp_path, "prepared-exact-segment")
    assert tuple(sorted(
        path.name for path in
        (tmp_path / "inventories/versions").iterdir())) == witness_names
    assert _run(snapshot, tmp_path,
                "prepared-exact-segment")["idempotent"] is False


def test_exact_prepared_retry_counts_each_existing_witness_once(
        tmp_path, monkeypatch):
    main = tmp_path / "main"
    reference = tmp_path / "reference"
    base = _snapshot(as_of=ISSUED)
    tail = _snapshot(as_of="2026-08-10T20:11:00Z")
    _run(base, reference, "prepared-cap-base")
    reference_tail = _run(tail, reference, "prepared-cap-tail")
    new_segment_size = (
        reference / reference_tail["segmentPath"]).stat().st_size
    new_manifest_size = (
        reference / "manifests/versions" /
        f"{reference_tail['segmentId']}.json").stat().st_size

    _run(base, main, "prepared-cap-base")
    original_install = runner._install_immutable_or_verify
    calls = {"count": 0}

    def fail_segment_stage(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 4:
            raise runner.LedgerRunError("injected_prepared_cap_failure")
        return original_install(*args, **kwargs)

    monkeypatch.setattr(
        runner, "_install_immutable_or_verify", fail_segment_stage)
    with pytest.raises(runner.LedgerRunError,
                       match="injected_prepared_cap_failure"):
        _run(tail, main, "prepared-cap-tail")
    monkeypatch.setattr(
        runner, "_install_immutable_or_verify", original_install)

    retained_paths = []
    for pattern in (
            "segments/*/*.json", "manifests/versions/*.json",
            "inventories/versions/*.json", "indexes/versions/*.json",
            "aggregates/versions/*.json"):
        retained_paths.extend(main.glob(pattern))
    retained_bytes = sum(path.stat().st_size for path in retained_paths)
    exact_retry_cap = retained_bytes + new_segment_size + \
        new_manifest_size + 100
    monkeypatch.setattr(
        runner, "MAX_RETAINED_AUTHORITY_BYTES", exact_retry_cap)

    recovered = _run(tail, main, "prepared-cap-tail")
    assert recovered["idempotent"] is False
    actual_bytes = 0
    for pattern in (
            "segments/*/*.json", "manifests/versions/*.json",
            "inventories/versions/*.json", "indexes/versions/*.json",
            "aggregates/versions/*.json"):
        actual_bytes += sum(path.stat().st_size for path in main.glob(pattern))
    assert retained_bytes < actual_bytes <= exact_retry_cap


def test_retained_byte_bound_precedes_any_segment_json_verification(
        tmp_path, monkeypatch):
    runs = _build_deep_history(tmp_path)
    smallest = min((tmp_path / run["segmentPath"]).stat().st_size
                   for run in runs)
    calls = {"verified": 0}
    original = runner._verify_segment

    def counted(value):
        calls["verified"] += 1
        return original(value)

    monkeypatch.setattr(runner, "_verify_segment", counted)
    monkeypatch.setattr(
        runner, "MAX_RETAINED_AUTHORITY_BYTES", smallest - 1)
    with pytest.raises(runner.LedgerRunError,
                       match="retained_authority_byte_bound_exceeded"):
        runner._load_state(tmp_path)
    assert calls["verified"] == 0


def test_append_fails_before_publication_after_deep_history_damage(tmp_path):
    runs = _build_deep_history(tmp_path)
    manifest_before = (tmp_path / "manifest.json").read_bytes()
    (tmp_path / runs[0]["segmentPath"]).unlink()
    append_path = tmp_path / "segments/2026-08-12/append-after-damage.json"
    with pytest.raises(runner.LedgerRunError,
                       match="retained_segment_file_missing"):
        _run(_snapshot(as_of="2026-08-12T20:23:00Z"),
             tmp_path, "append-after-damage")
    assert (tmp_path / "manifest.json").read_bytes() == manifest_before
    assert not append_path.exists()


def test_retained_inventory_bound_fails_before_install(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_RETAINED_SEGMENTS", 1)
    _run(_snapshot(as_of=ISSUED), tmp_path, "bounded-history-1")
    with pytest.raises(runner.LedgerRunError,
                       match="retained_segment_bound_exceeded"):
        _run(_snapshot(as_of="2026-08-10T20:11:00Z"),
             tmp_path, "bounded-history-2")
    assert not (tmp_path / "segments/2026-08-10/bounded-history-2.json").exists()


def test_prospective_retained_byte_bound_fails_before_any_publication(
        tmp_path, monkeypatch):
    first = _run(_snapshot(as_of=ISSUED), tmp_path, "byte-bound-1")
    first_segment = tmp_path / first["segmentPath"]
    retained_bytes = first_segment.stat().st_size
    manifest_path = tmp_path / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    version_directories = (
        tmp_path / "indexes/versions",
        tmp_path / "aggregates/versions",
        tmp_path / "inventories/versions",
    )
    versions_before = {
        directory: tuple(sorted(path.name for path in directory.iterdir()))
        for directory in version_directories
    }
    monkeypatch.setattr(
        runner, "MAX_RETAINED_AUTHORITY_BYTES", retained_bytes)

    with pytest.raises(runner.LedgerRunError,
                       match="retained_authority_byte_bound_exceeded"):
        _run(_snapshot(as_of="2026-08-10T20:11:00Z"),
             tmp_path, "byte-bound-2")

    assert manifest_path.read_bytes() == manifest_before
    assert not (tmp_path / "segments/2026-08-10/byte-bound-2.json").exists()
    for directory, expected in versions_before.items():
        assert tuple(sorted(path.name for path in directory.iterdir())) == expected


def test_index_byte_bound_fails_before_any_immutable_install(tmp_path, monkeypatch):
    prediction, market_snapshot = _prediction()
    monkeypatch.setattr(runner, "MAX_INDEX_BYTES", 128)
    with pytest.raises(runner.LedgerRunError, match="index_too_large"):
        _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                       market_snapshot=market_snapshot),
             tmp_path, "index-byte-overflow")
    assert not (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "segments/2026-08-10/index-byte-overflow.json").exists()


def test_per_run_issued_decision_cap_is_exact_and_prewrite(tmp_path, monkeypatch):
    assert runner.MAX_ISSUED_DECISIONS == 64 * 3
    prediction, market_snapshot = _prediction()
    monkeypatch.setattr(runner, "MAX_ISSUED_DECISIONS", 0)
    with pytest.raises(runner.LedgerRunError,
                       match="issued_decision_input_overflow"):
        _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                       market_snapshot=market_snapshot),
             tmp_path, "issued-cap")
    assert not (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "segments/2026-08-10/issued-cap.json").exists()


def test_bounded_identity_retention_has_monotonic_replay_guard(
        tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_IDENTITY_RECORDS", 2)
    prediction, market_snapshot = _prediction()
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "bounded-issue")
    _run(_snapshot(as_of=RUN_AT, outcomes=[_outcome_bar()]),
         tmp_path, "bounded-resolve")
    index = _index(tmp_path)
    assert index["counts"]["identityCount"] == 2
    assert index["retention"]["evictedIdentityCount"] == 1
    replay_at = "2026-08-11T20:20:00Z"
    replay = _snapshot(
        as_of=ISSUED, generated_at=replay_at,
        projection_generated_at=ISSUED, decisions=[prediction],
        market_snapshot=market_snapshot)
    with pytest.raises(runner.LedgerRunError,
                       match="stale_prediction_replay"):
        _run(replay, tmp_path, "evicted-replay")


@pytest.mark.parametrize("mutation", [
    "negative_evaluations", "unscorable_exceeds_total",
    "metric_components", "metric_exceeds_scored", "metric_mean",
])
def test_self_consistent_but_impossible_aggregate_state_fails_closed(
        tmp_path, mutation):
    prediction, market_snapshot = _prediction()
    _run(_snapshot(as_of=ISSUED, decisions=[prediction],
                   market_snapshot=market_snapshot), tmp_path, "agg-issue")
    _run(_snapshot(as_of=RUN_AT, outcomes=[_outcome_bar()]),
         tmp_path, "agg-resolve")
    aggregate = _aggregate(tmp_path)
    aggregate.pop("digest")
    if mutation == "negative_evaluations":
        aggregate["evaluationCount"] = -7
    elif mutation == "unscorable_exceeds_total":
        aggregate["unscorableCount"] = aggregate["evaluationCount"] + 1
    elif mutation == "metric_components":
        aggregate["metrics"][0]["numericCount"] += 1
    elif mutation == "metric_exceeds_scored":
        aggregate["unscorableCount"] = aggregate["evaluationCount"]
    else:
        aggregate["metrics"][0]["mean"] = 999.0
    hostile = runner._sealed_document(aggregate)
    with pytest.raises(
            runner.LedgerRunError,
            match="invalid_aggregate_counts|invalid_aggregate_metric"):
        runner._validate_aggregate(hostile)
