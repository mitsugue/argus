import ast
import copy
import hashlib
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import argus_research_compute as research
import argus_risk_discipline as risk
import argus_sho as sho


ROOT = Path(__file__).resolve().parent
RUNNER_PATH = ROOT / "scripts" / "run_round2_research.py"
_SPEC = importlib.util.spec_from_file_location("run_round2_research", RUNNER_PATH)
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


def _canonical_dataset_payload(rows):
    """Model the deterministic, hash-verified files used by unit fixtures."""
    return research.canonical_bytes(sorted(rows, key=research.canonical_bytes))


def _ranges():
    return [
        {"name": "DEVELOPMENT", "startDate": "2026-01-01",
         "endDate": "2026-04-30"},
        {"name": "EMBARGO", "startDate": "2026-05-01",
         "endDate": "2026-05-20"},
        {"name": "HOLDOUT", "startDate": "2026-05-21",
         "endDate": "2026-06-20"},
        {"name": "EMBARGO", "startDate": "2026-06-21",
         "endDate": "2026-07-20"},
        {"name": "GOLDEN", "startDate": "2026-07-21",
         "endDate": "2026-08-31"},
    ]


def _draft_manifest(*, datasets=None, horizon_40=False):
    horizons = [1, 5, 10, 20] + ([40] if horizon_40 else [])
    if datasets is None:
        bars_payload = _canonical_dataset_payload(_bars())
        events_payload = _canonical_dataset_payload(_events())
        golden_bars_payload = _canonical_dataset_payload([
            row for row in _bars(include_golden=True)
            if row["datasetId"] == "fixture-golden-bars-v1"])
        golden_events_payload = _canonical_dataset_payload([
            row for row in _events(include_golden=True)
            if row["datasetId"] == "fixture-golden-events-v1"])
        datasets = [
            {"datasetId": "fixture-bars-v1", "kind": "bars",
             "partitionScope": "NON_GOLDEN",
             "path": "bars.json",
             "sha256": hashlib.sha256(bars_payload).hexdigest(),
             "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
            {"datasetId": "fixture-events-v1", "kind": "events",
             "partitionScope": "NON_GOLDEN",
             "path": "events.json",
             "sha256": hashlib.sha256(events_payload).hexdigest(),
             "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
            {"datasetId": "fixture-golden-bars-v1", "kind": "bars",
             "partitionScope": "GOLDEN", "path": "golden-bars.json",
             "sha256": hashlib.sha256(golden_bars_payload).hexdigest(),
             "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
            {"datasetId": "fixture-golden-events-v1", "kind": "events",
             "partitionScope": "GOLDEN", "path": "golden-events.json",
             "sha256": hashlib.sha256(golden_events_payload).hexdigest(),
             "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
        ]
    return {
        "schemaVersion": research.MANIFEST_SCHEMA,
        "researchId": "round2-synthetic-contract-v1",
        "datasetVersion": "synthetic-bars-events-v1",
        "datasets": datasets,
        "informationCutoffAt": "2026-09-01T00:00:00Z",
        "pitPolicyId": research.PIT_POLICY_ID,
        "propositionRegistryVersion": "sho-registry-fixture-v1",
        "policyVersion": "round2-policy-fixture-v1",
        "parameterVersion": "round2-parameters-fixture-v1",
        "buildSha": "c" * 40,
        "calendarVersion": "fixture-daily-calendar-v1",
        "adjustmentPolicy": "split-adjusted-fixture-v1",
        "executionPolicy": "next_session_open",
        "costBps": 5.0,
        "slippageBps": 5.0,
        "seed": 17,
        "horizons": horizons,
        "horizon40Preregistered": horizon_40,
        "horizon40PreregistrationId": (
            "round2-fixture-40d-prereg-v1" if horizon_40 else None),
        "partitionPolicy": {
            "schemaVersion": research.PARTITION_POLICY_SCHEMA,
            "policyId": "round2-fixed-date-partitions-v1",
            "embargoSessions": 40 if horizon_40 else 20,
            "ranges": _ranges(),
            "walkForwardFolds": [{
                "foldId": "wf-1",
                "trainStartDate": "2026-01-01",
                "trainEndDate": "2026-02-15",
                "validationStartDate": "2026-02-16",
                "validationEndDate": "2026-03-15",
                "forwardStartDate": "2026-03-16",
                "forwardEndDate": "2026-04-15",
            }],
        },
        "goldenPolicy": {
            "caseId": "jp-late-july-august-2026-reversal-v1",
            "expectedEventId": "golden-reversal",
            "expectedInstrumentId": "JP:1321:ETF",
            "access": "SEALED", "openedAt": None,
            "openedForPolicyIdentity": None,
            "openedForResearchDataIdentity": None,
        },
        "freeze": {
            "status": "DRAFT", "policyIdentity": None, "frozenAt": None,
            "holdoutStatus": "UNTOUCHED", "holdoutResultDigest": None,
            "holdoutRecordedAt": None, "researchDataIdentity": None,
        },
        "retune": {"priorPolicyIdentity": None, "reason": None},
        "parameters": {
            "targetPct": 3.0, "invalidationPct": -3.0,
            "newLowLookback": 20, "rallyThresholdPct": 3.0,
            "reversalThresholdPct": 2.0, "waitFailureThresholdPct": 3.0,
            "counterfactualHorizon": 20,
            "turtle": {
                "entryLookbacks": [20, 55], "exitLookbacks": [10, 20],
                "atrPeriod": 20, "entryRule": "20_or_55_day_high_break",
                "exitRule": "10_or_20_day_low_break", "shadowOnly": True,
                "hardVeto": False,
            },
        },
    }


def _frozen_manifest(**kwargs):
    return research.freeze_manifest(
        _draft_manifest(**kwargs), frozen_at="2026-05-01T00:00:00Z")


def _bars(*, include_golden=False):
    start = date(2026, 1, 1)
    end = date(2026, 8, 31) if include_golden else date(2026, 7, 20)
    rows = []
    index = 0
    day = start
    while day <= end:
        # Rising fixture produces deterministic Turtle breakouts. Periodic dips
        # exercise MAE, drawdown, reversal, and new-low metrics.
        trend = 100.0 + index * 0.22
        dip = -4.0 if index % 37 == 0 and index else 0.0
        close = trend + dip
        signals = {}
        if index % 29 == 2:
            signals["shoReversal"] = True
        if index % 31 == 3:
            signals["vixDecreasingConfirmation"] = True
        if index % 41 == 4:
            signals["sarFlip"] = True
        if index % 43 == 5:
            signals["macdGoldenCross"] = True
        if index % 47 == 6:
            signals["ma25Reclaim"] = True
        rows.append({
            "datasetId": ("fixture-golden-bars-v1"
                          if day >= date(2026, 7, 21)
                          else "fixture-bars-v1"),
            "instrumentId": "JP:1321:ETF",
            "date": day.isoformat(), "availableFrom": day.isoformat() + "T20:00:00Z",
            "decisionCutoffAt": day.isoformat() + "T20:30:00Z",
            "revision": 0, "sourceId": "fixture:" + day.isoformat(),
            "open": close - 0.2, "high": close + 1.2, "low": close - 1.1,
            "close": close, "volume": 1000 + index, "signals": signals,
        })
        day += timedelta(days=1)
        index += 1
    return rows


def _golden_risk_kernel():
    observed_at = "2026-07-23T20:30:00Z"
    return risk.build_risk_kernel({
        "schemaVersion": "argus-risk-discipline-input-v1",
        "subject": {
            "kind": "ASSET", "instrumentId": "JP:1321:ETF", "market": "JP"},
        "asOf": observed_at,
        "informationCutoffAt": observed_at,
        "policy": {
            "policyId": "round2-golden-risk-sufficiency-v1",
            "policySha256": "c" * 64,
        },
        "contributions": [{
            "evidenceRef": "market:golden-selloff-risk",
            "primitiveFactorId": "market.selloff_risk",
            "sourceKind": "MARKET", "constraint": "REDUCE_RISK",
            "status": "ACTIVE", "severity": "HIGH",
            "confidenceCapBps": 6000, "observedAt": observed_at,
        }],
    })


def _golden_sho_reversal():
    cutoff = "2026-07-25T20:30:00Z"
    source = [row for row in _bars(include_golden=True)
              if row["date"] <= "2026-07-25"]

    def as_instrument(row, instrument, scale=1.0):
        return {
            "instrumentId": instrument, "date": row["date"],
            "availableFrom": row["availableFrom"], "revision": 0,
            "sourceId": "fixture-sho:" + instrument + ":" + row["date"],
            "open": row["open"] * scale, "high": row["high"] * scale,
            "low": row["low"] * scale, "close": row["close"] * scale,
            "volume": row["volume"],
        }

    return sho.build_reversal_engine(
        cutoff=cutoff, analysis_instrument="JP:1321:ETF",
        downside_background="SELL_OFF_ACTIVE",
        nikkei_rows=[as_instrument(row, "NIKKEI_225_INDEX") for row in source],
        vix_rows=[as_instrument(row, "VIX", 0.2) for row in source],
    )


def _events(*, include_golden=False):
    rows = [
        ("fixture-events-v1", "dev-validation", "2026-03-01", "calm",
         ["credit"]),
        ("fixture-events-v1", "dev-forward", "2026-03-20", "risk_off",
         ["vix", "credit"]),
        ("fixture-events-v1", "holdout-one", "2026-05-25", "risk_off",
         ["credit"]),
    ]
    if include_golden:
        rows.append(("fixture-golden-events-v1", "golden-reversal",
                     "2026-07-25", "reversal", ["golden"]))
    return [{
        "datasetId": dataset_id, "eventId": event_id,
        "instrumentId": "JP:1321:ETF",
        "signalDate": day, "availableFrom": day + "T20:30:00Z",
        "decisionCutoffAt": day + "T20:30:00Z",
        "expectedDirection": "UP", "probability": 0.65,
        "targetPct": 3.0, "invalidationPct": -3.0, "regime": regime,
        "ablationTags": tags, "validatedReversal": True,
        "evidenceRefs": ["fixture:" + event_id],
        **({
            "riskKernelArtifact": _golden_risk_kernel(),
            "shoReversalArtifact": _golden_sho_reversal(),
        } if event_id == "golden-reversal" else {}),
    } for dataset_id, event_id, day, regime, tags in rows]


def _rows_by_dataset(manifest, bars, events):
    descriptors = manifest["datasets"]
    result = {row["datasetId"]: [] for row in descriptors}
    bar_ids = {row["datasetId"] for row in descriptors
               if row["kind"] == "bars"}
    event_ids = [row["datasetId"] for row in descriptors
                 if row["kind"] == "events"]
    for row in bars:
        dataset_id = row.get("datasetId")
        if dataset_id not in bar_ids:
            raise AssertionError("bar fixture lacks a declared dataset")
        result[dataset_id].append(row)
    for row in events:
        dataset_id = row.get("datasetId")
        if dataset_id is None and len(event_ids) == 1:
            dataset_id = event_ids[0]
        if dataset_id not in event_ids:
            raise AssertionError("event fixture lacks an unambiguous dataset")
        result[dataset_id].append(row)
    return result


def _manifest_for_inputs(manifest, bars, events):
    prepared = copy.deepcopy(manifest)
    rows_by_dataset = _rows_by_dataset(prepared, bars, events)
    for descriptor in prepared["datasets"]:
        rows = rows_by_dataset[descriptor["datasetId"]]
        if descriptor["partitionScope"] == "GOLDEN" and not rows:
            continue
        payload = _canonical_dataset_payload(
            rows)
        descriptor["sha256"] = hashlib.sha256(payload).hexdigest()
    return prepared


def _dataset_payloads(manifest, bars, events):
    rows_by_dataset = _rows_by_dataset(manifest, bars, events)
    payloads = {}
    golden_open = manifest["goldenPolicy"]["access"] == "OPEN"
    for descriptor in research.validate_manifest(manifest)["datasets"]:
        if descriptor["partitionScope"] == "GOLDEN" and not golden_open:
            continue
        rows = rows_by_dataset[descriptor["datasetId"]]
        payload = _canonical_dataset_payload(rows)
        digest = hashlib.sha256(payload).hexdigest()
        assert digest == descriptor["sha256"]
        payloads[descriptor["datasetId"]] = payload
    return payloads


def _verified_artifact(manifest, bars, events):
    bars = list(bars)
    events = list(events)
    return research.build_verified_research_artifact(
        manifest, _dataset_payloads(manifest, bars, events))


def _artifact(manifest=None):
    return _verified_artifact(
        manifest or _frozen_manifest(), _bars(), _events())


def test_manifest_freeze_binds_exact_policy_and_research_identities():
    draft = _draft_manifest()
    normalized = research.validate_manifest(draft)
    assert normalized["freeze"]["status"] == "DRAFT"
    frozen = research.freeze_manifest(draft, frozen_at="2026-05-01T00:00:00Z")
    bound = research.validate_manifest(frozen)
    assert frozen["freeze"]["policyIdentity"] == bound["policyIdentity"]
    assert bound["policyIdentity"].startswith("rp-")
    assert bound["researchIdentity"].startswith("rr-")
    assert research.policy_identity(draft) == research.policy_identity(frozen)


def test_freeze_precommits_data_and_precedes_holdout_isolation():
    draft = _draft_manifest()
    with pytest.raises(research.ResearchContractError,
                       match="policy_frozen_after_holdout_isolation"):
        research.freeze_manifest(
            draft, frozen_at="2026-05-01T00:00:01Z")
    frozen = research.freeze_manifest(
        draft, frozen_at="2026-05-01T00:00:00Z")
    assert frozen["freeze"]["researchDataIdentity"] == \
        research.research_data_identity(frozen)
    changed = copy.deepcopy(frozen)
    changed["datasets"][0]["sha256"] = "9" * 64
    with pytest.raises(research.ResearchContractError,
                       match="frozen_data_identity_mismatch"):
        research.validate_manifest(changed)


def test_partition_roles_are_chronological_and_draft_cannot_open_holdout():
    malformed = _draft_manifest()
    malformed["partitionPolicy"]["ranges"][0]["name"] = "HOLDOUT"
    malformed["partitionPolicy"]["ranges"][2]["name"] = "DEVELOPMENT"
    with pytest.raises(research.ResearchContractError,
                       match="invalid_partition_sequence"):
        research.validate_manifest(malformed)
    with pytest.raises(research.ResearchContractError,
                       match="holdout_requires_frozen_policy"):
        research.build_research_artifact(
            _draft_manifest(), _bars(), _events())


def test_same_identity_and_reordered_inputs_produce_identical_canonical_bytes():
    manifest = _frozen_manifest()
    first = _verified_artifact(manifest, _bars(), _events())
    second = _verified_artifact(
        copy.deepcopy(manifest), list(reversed(_bars())),
        list(reversed(_events())))
    assert research.canonical_bytes(first) == research.canonical_bytes(second)
    assert research.verify_research_artifact(first)


def test_verifier_rejects_direct_unbound_builder_output():
    unbound = research.build_research_artifact(
        _frozen_manifest(), _bars(), _events())
    assert "inputReceipt" not in unbound
    assert research.verify_research_artifact(unbound) is False


def test_verifier_accepts_coherent_hash_bound_draft_artifact():
    bars = [row for row in _bars()
            if not "2026-05-21" <= row["date"] <= "2026-06-20"]
    events = [row for row in _events()
              if row["signalDate"] <= "2026-04-30"]
    manifest = _manifest_for_inputs(_draft_manifest(), bars, events)
    artifact = _verified_artifact(manifest, bars, events)
    assert artifact["inputReceipt"]["authority"] == \
        "HASH_VERIFIED_OFFLINE_INPUT"
    assert artifact["validationProtocol"]["policyFrozen"] is False
    assert artifact["partitions"]["HOLDOUT"]["eventCount"] == 0
    assert artifact["holdoutProof"]["eligibleForPass"] is False
    assert research.verify_research_artifact(artifact)


def test_verifier_accepts_coherent_event_detail_truncation():
    template = _events()[0]
    events = []
    for index in range(research.MAX_EVENT_DETAILS + 1):
        event = copy.deepcopy(template)
        event["eventId"] = f"development-bulk-{index:03d}"
        event["evidenceRefs"] = [f"fixture:development-bulk-{index:03d}"]
        events.append(event)
    manifest = _manifest_for_inputs(_draft_manifest(), _bars(), events)
    manifest = research.freeze_manifest(
        manifest, frozen_at="2026-05-01T00:00:00Z")
    artifact = _verified_artifact(manifest, _bars(), events)
    assert artifact["eventDetailsTruncated"] is True
    assert len(artifact["eventDetails"]) == research.MAX_EVENT_DETAILS
    assert artifact["counterfactuals"]["perEventTruncated"] is True
    assert len(artifact["counterfactuals"]["perEvent"]) == \
        research.MAX_EVENT_DETAILS
    assert artifact["partitions"]["DEVELOPMENT"]["eventCount"] == \
        research.MAX_EVENT_DETAILS + 1
    assert research.verify_research_artifact(artifact)


def test_truncation_retains_golden_then_holdout_audit_details():
    template = _events()[0]
    development = []
    for index in range(research.MAX_EVENT_DETAILS + 1):
        event = copy.deepcopy(template)
        event["eventId"] = f"development-priority-{index:03d}"
        event["evidenceRefs"] = [
            f"fixture:development-priority-{index:03d}"]
        development.append(event)
    non_golden_events = development + [_events()[2]]
    all_events = non_golden_events + [
        _events(include_golden=True)[-1]]
    all_bars = _bars(include_golden=True)
    draft = _manifest_for_inputs(
        _draft_manifest(), all_bars, all_events)
    frozen = research.freeze_manifest(
        draft, frozen_at="2026-05-01T00:00:00Z")
    sealed = _verified_artifact(
        frozen, _bars(), non_golden_events)
    passed = research.record_holdout_result(
        frozen, status="PASSED", dataset_payloads=_dataset_payloads(
            frozen, _bars(), non_golden_events),
        recorded_at="2026-07-21T00:00:00Z")
    opened = research.open_golden(
        passed, opened_at="2026-07-21T00:00:01Z")
    artifact = _verified_artifact(opened, all_bars, all_events)
    assert artifact["eventDetailsTruncated"] is True
    assert [row["partition"] for row in artifact["eventDetails"][:2]] == [
        "GOLDEN", "HOLDOUT"]
    assert artifact["partitionProofs"]["GOLDEN"][
        "retainedEventDetailCount"] == 1
    assert artifact["partitionProofs"]["HOLDOUT"][
        "retainedEventDetailCount"] == 1
    assert artifact["counterfactuals"]["perEvent"][0]["eventId"] == \
        "golden-reversal"
    assert research.verify_research_artifact(artifact)


def test_research_identity_binds_freeze_holdout_and_golden_lifecycle():
    sealed = _frozen_manifest()
    sealed_artifact = _verified_artifact(
        sealed, _bars(), _events())
    passed = research.record_holdout_result(
        sealed, status="PASSED",
        dataset_payloads=_dataset_payloads(sealed, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    opened = research.open_golden(
        passed, opened_at="2026-07-21T00:00:01Z")
    opened_artifact = _verified_artifact(
        opened, _bars(include_golden=True),
        _events(include_golden=True))
    assert research.research_identity(sealed) != \
        research.research_identity(passed)
    assert research.research_identity(passed) != \
        research.research_identity(opened)
    assert sealed_artifact["identity"]["researchDataIdentity"] == \
        opened_artifact["identity"]["researchDataIdentity"]
    assert sealed_artifact["dataIdentity"]["declaredDatasets"] == \
        opened_artifact["dataIdentity"]["declaredDatasets"]
    assert sealed_artifact["dataIdentity"]["barDatasetHash"] != \
        opened_artifact["dataIdentity"]["barDatasetHash"]
    assert research.canonical_bytes(sealed_artifact) != \
        research.canonical_bytes(opened_artifact)


def test_recorded_holdout_digest_must_match_recomputed_holdout():
    sealed = _frozen_manifest()
    sealed_artifact = _verified_artifact(
        sealed, _bars(), _events())
    passed = research.record_holdout_result(
        sealed, status="PASSED",
        dataset_payloads=_dataset_payloads(sealed, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    changed = _bars()
    holdout = next(row for row in changed if row["date"] == "2026-05-25")
    holdout["close"] += 9.0
    holdout["high"] += 9.0
    holdout["low"] += 9.0
    holdout["open"] += 9.0
    with pytest.raises(research.ResearchContractError,
                       match="recorded_holdout_digest_mismatch"):
        research.build_research_artifact(passed, changed, _events())

    changed = _bars()
    holdout = next(row for row in changed if row["date"] == "2026-05-25")
    holdout["signals"] = {"shoReversal": True}
    with pytest.raises(research.ResearchContractError,
                       match="recorded_holdout_digest_mismatch"):
        research.build_research_artifact(passed, changed, _events())


def test_point_in_time_excludes_future_revision_and_binds_highest_visible_revision():
    manifest = _frozen_manifest()
    baseline = _artifact(manifest)
    rows = _bars()
    future = copy.deepcopy(rows[40])
    future.update({"revision": 9, "knownAt": "2026-09-02T00:00:00Z",
                   "close": 9999.0, "high": 10000.0, "low": 9998.0,
                   "open": 9998.5})
    hostile = research.build_research_artifact(manifest, rows + [future], _events())
    assert hostile["dataIdentity"]["barDatasetHash"] == baseline[
        "dataIdentity"]["barDatasetHash"]
    assert hostile["pointInTimeProof"]["bars"]["excludedFutureCount"] == 1
    assert hostile["pointInTimeProof"]["futureInputAdmitted"] is False


def test_late_known_bar_revision_cannot_backdate_a_historical_trigger():
    manifest = _frozen_manifest()
    rows = _bars()
    original = copy.deepcopy(rows[59])
    original["signals"] = {}
    rows[59] = original
    baseline = research.build_research_artifact(manifest, rows, _events())
    late = copy.deepcopy(original)
    late.update({
        "revision": 1,
        "knownAt": "2026-07-01T00:00:00Z",
        "signals": {"shoReversal": True},
    })
    hostile = research.build_research_artifact(
        manifest, rows + [late], _events())
    assert hostile["dataIdentity"]["barDatasetHash"] == baseline[
        "dataIdentity"]["barDatasetHash"]
    assert hostile["counterfactuals"] == baseline["counterfactuals"]
    assert hostile["pointInTimeProof"]["bars"][
        "excludedAfterDecisionCutoffCount"] == 1

    missing_known_at = copy.deepcopy(original)
    missing_known_at.update({
        "revision": 1,
        "signals": {"shoReversal": True},
    })
    with pytest.raises(research.ResearchContractError,
                       match="revision_known_at_required"):
        research.build_research_artifact(
            manifest, rows + [missing_known_at], _events())

    changed_cutoff = copy.deepcopy(original)
    changed_cutoff.update({
        "revision": 1,
        "knownAt": original["date"] + "T20:45:00Z",
        "decisionCutoffAt": original["date"] + "T21:00:00Z",
        "signals": {"shoReversal": True},
    })
    with pytest.raises(research.ResearchContractError,
                       match="bar_decision_cutoff_changed"):
        research.build_research_artifact(
            manifest, rows + [changed_cutoff], _events())


def test_bar_decision_cutoff_is_same_session_and_after_source_availability():
    rows = _bars()
    rows[0]["decisionCutoffAt"] = "2026-07-01T00:00:00Z"
    with pytest.raises(research.ResearchContractError,
                       match="bar_decision_cutoff_outside_session"):
        research.build_research_artifact(
            _frozen_manifest(), rows, _events())


def test_each_event_binds_its_own_decision_cutoff_and_cannot_be_backdated():
    hostile = _events()
    hostile[0]["decisionCutoffAt"] = "2026-03-01T20:29:59Z"
    with pytest.raises(research.ResearchContractError,
                       match="event_available_after_decision_cutoff"):
        research.build_research_artifact(
            _frozen_manifest(), _bars(), hostile)
    artifact = _artifact()
    event = next(row for row in artifact["eventDetails"]
                 if row["eventId"] == "dev-validation")
    assert event["decisionCutoffAt"] == "2026-03-01T20:30:00Z"

    hostile = _events()
    hostile[0]["availableFrom"] = "2026-07-01T20:00:00Z"
    hostile[0]["decisionCutoffAt"] = "2026-07-01T20:30:00Z"
    with pytest.raises(
            research.ResearchContractError,
            match="event_decision_cutoff_outside_signal_session"):
        research.build_research_artifact(
            _frozen_manifest(), _bars(), hostile)


def test_complete_ohlc_and_same_revision_conflicts_fail_closed():
    rows = _bars()
    rows[0].pop("low")
    with pytest.raises(research.ResearchContractError,
                       match="invalid_bar_fields"):
        research.build_research_artifact(_frozen_manifest(), rows, _events())
    rows = _bars()
    conflict = copy.deepcopy(rows[0])
    conflict["close"] += 0.5
    conflict["high"] += 0.5
    with pytest.raises(research.ResearchContractError,
                       match="conflicting_same_revision_bar"):
        research.build_research_artifact(
            _frozen_manifest(), rows + [conflict], _events())


def test_overlapping_bar_sources_and_event_dataset_as_bars_fail_closed():
    rows = _bars()
    overlap = copy.deepcopy(rows[0])
    overlap["datasetId"] = "second-bars-v1"
    with pytest.raises(research.ResearchContractError,
                       match="overlapping_bar_sources"):
        research.normalize_point_in_time_bars(
            rows + [overlap], cutoff_at="2026-09-01T00:00:00Z")
    rows = _bars()
    rows[0]["datasetId"] = "fixture-events-v1"
    with pytest.raises(research.ResearchContractError,
                       match="undeclared_bar_dataset"):
        research.build_research_artifact(
            _frozen_manifest(), rows, _events())


def test_partition_scoped_datasets_cannot_launder_golden_or_non_golden_rows():
    bars = _bars()
    bars[0]["datasetId"] = "fixture-golden-bars-v1"
    with pytest.raises(research.ResearchContractError,
                       match="bar_dataset_partition_scope_mismatch"):
        research.build_research_artifact(
            _frozen_manifest(), bars, _events())
    events = _events()
    events[0]["datasetId"] = "fixture-golden-events-v1"
    with pytest.raises(research.ResearchContractError,
                       match="event_dataset_partition_scope_mismatch"):
        research.build_research_artifact(
            _frozen_manifest(), _bars(), events)


def test_direct_iterables_abort_at_bound_before_unbounded_materialization(
        monkeypatch):
    monkeypatch.setattr(research, "MAX_EVENTS", 2)
    source = (row for row in _events()[:3])
    with pytest.raises(research.ResearchContractError,
                       match="event_bound_exceeded"):
        research.normalize_point_in_time_events(
            source, cutoff_at="2026-09-01T00:00:00Z",
            partition_policy=_draft_manifest()["partitionPolicy"])


def test_protocol_has_walk_forward_holdout_embargo_and_full_required_metrics():
    artifact = _artifact()
    assert artifact["validationProtocol"]["horizons"] == [1, 5, 10, 20]
    assert artifact["coverage"]["excludedEventCounts"]["EMBARGO"] == 0
    assert artifact["partitions"]["GOLDEN"] == {
        "access": "SEALED", "eventCount": 0, "metrics": None}
    assert artifact["partitions"]["HOLDOUT"]["eventCount"] == 1
    metrics = artifact["partitions"]["DEVELOPMENT"]["metrics"]["10"]
    assert {"returnMeanPct", "medianReturnPct", "winRate", "mfeMeanPct",
            "maeMeanPct", "maxDrawdownMeanPct", "newLowRate",
            "targetHitRate", "targetBreakRate", "falsePositiveRate",
            "falseRallyRate", "falseReversalRate", "rallyRate",
            "reversalRate", "missedOpportunityRate",
            "brierMean", "logLossMean", "calibration", "regimes",
            "ablations", "sampleCount", "winRateCi95Wilson"}.issubset(metrics)
    event = next(row for row in artifact["eventDetails"]
                 if row["eventId"] == "holdout-one")
    for outcome in event["horizons"].values():
        if outcome["status"] in {"OBSERVED", "AMBIGUOUS"}:
            assert outcome["falseRally"] == bool(
                outcome["rally"] and outcome["falsePositive"])
            assert outcome["falseReversal"] == bool(
                outcome["falsePositive"])
    folds = artifact["validationProtocol"]["walkForward"]
    assert [row["foldId"] for row in folds] == ["wf-1"]
    assert folds[0]["stages"]["VALIDATION"]["eventCount"] == 1
    assert folds[0]["stages"]["FORWARD"]["eventCount"] == 1
    assert folds[0]["stages"]["VALIDATION"]["metrics"]["1"][
        "scoreableCount"] == 1
    assert folds[0]["stages"]["VALIDATION"]["metrics"]["20"][
        "scoreableCount"] == 0
    assert artifact["counterfactuals"]["assumptions"] == {
        "costBps": 5.0,
        "executionPolicy": "next_session_open",
        "roundTripCostAndSlippagePct": 0.2,
        "slippageBps": 5.0,
    }


def test_declared_embargo_width_and_actual_bar_sessions_are_enforced():
    manifest = _draft_manifest()
    manifest["partitionPolicy"]["ranges"][1]["endDate"] = "2026-05-01"
    manifest["partitionPolicy"]["ranges"][2]["startDate"] = "2026-05-02"
    with pytest.raises(research.ResearchContractError,
                       match="insufficient_embargo_calendar_span"):
        research.validate_manifest(manifest)

    bars = [row for row in _bars() if row["date"] != "2026-05-01"]
    with pytest.raises(research.ResearchContractError,
                       match="insufficient_embargo_bar_sessions"):
        research.build_research_artifact(
            _frozen_manifest(), bars, _events())


def test_same_close_execution_is_rejected_without_pre_close_time_proof():
    manifest = _draft_manifest()
    manifest["executionPolicy"] = "signal_close"
    with pytest.raises(
            research.ResearchContractError,
            match="execution_policy_requires_next_session_open"):
        research.validate_manifest(manifest)


def test_40_day_horizon_requires_explicit_preregistration_and_larger_embargo():
    manifest = _draft_manifest()
    manifest["horizons"].append(40)
    with pytest.raises(research.ResearchContractError,
                       match="horizon_40_not_preregistered"):
        research.validate_manifest(manifest)
    manifest = _draft_manifest(horizon_40=True)
    with pytest.raises(research.ResearchContractError,
                       match="insufficient_embargo_calendar_span"):
        research.validate_manifest(manifest)
    manifest["partitionPolicy"]["ranges"] = [
        {"name": "DEVELOPMENT", "startDate": "2026-01-01",
         "endDate": "2026-03-31"},
        {"name": "EMBARGO", "startDate": "2026-04-01",
         "endDate": "2026-05-10"},
        {"name": "HOLDOUT", "startDate": "2026-05-11",
         "endDate": "2026-06-10"},
        {"name": "EMBARGO", "startDate": "2026-06-11",
         "endDate": "2026-07-20"},
        {"name": "GOLDEN", "startDate": "2026-07-21",
         "endDate": "2026-08-31"},
    ]
    manifest["partitionPolicy"]["walkForwardFolds"] = [{
        "foldId": "wf-40",
        "trainStartDate": "2026-01-01",
        "trainEndDate": "2026-02-01",
        "validationStartDate": "2026-02-02",
        "validationEndDate": "2026-03-01",
        "forwardStartDate": "2026-03-02",
        "forwardEndDate": "2026-03-31",
    }]
    valid = research.validate_manifest(manifest)
    assert valid["horizons"] == [1, 5, 10, 20, 40]
    assert valid["partitionPolicy"]["embargoSessions"] == 40


def test_failed_holdout_cannot_be_retuned_under_same_policy_identity():
    frozen = _frozen_manifest()
    sealed_artifact = _verified_artifact(
        frozen, _bars(), _events())
    failed = research.record_holdout_result(
        frozen, status="FAILED", dataset_payloads=_dataset_payloads(
            frozen, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    with pytest.raises(research.ResearchContractError,
                       match="failed_holdout_requires_new_policy_identity"):
        research.validate_retune(failed, frozen)
    next_draft = _draft_manifest()
    next_draft["parameterVersion"] = "round2-parameters-fixture-v2"
    next_draft["retune"] = {
        "priorPolicyIdentity": research.policy_identity(failed),
        "reason": "failed untouched holdout; preregistered corrective identity",
    }
    proof = research.validate_retune(failed, next_draft)
    assert proof["changed"] is True


def test_holdout_result_is_append_once_and_golden_opens_only_after_pass():
    frozen = _frozen_manifest()
    with pytest.raises(research.ResearchContractError,
                       match="golden_requires_passed_frozen_holdout"):
        research.open_golden(frozen, opened_at="2026-07-21T00:00:01Z")
    sealed_artifact = _verified_artifact(
        frozen, _bars(), _events())
    passed = research.record_holdout_result(
        frozen, status="PASSED",
        dataset_payloads=_dataset_payloads(frozen, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    with pytest.raises(research.ResearchContractError,
                       match="holdout_result_is_immutable"):
        research.record_holdout_result(
            passed, status="FAILED", dataset_payloads=_dataset_payloads(
                passed, _bars(), _events()),
            recorded_at="2026-07-21T00:00:01Z")
    opened = research.open_golden(
        passed, opened_at="2026-07-21T00:00:01Z")
    assert opened["goldenPolicy"]["openedForPolicyIdentity"] == \
        research.policy_identity(opened)
    assert opened["goldenPolicy"]["openedForResearchDataIdentity"] == \
        research.research_data_identity(opened)


def test_lifecycle_timestamps_holdout_eligibility_and_golden_data_are_bound():
    frozen = _frozen_manifest()
    artifact = _verified_artifact(
        frozen, _bars(), _events())
    with pytest.raises(research.ResearchContractError,
                       match="holdout_recorded_before_latest_input"):
        research.record_holdout_result(
            frozen, status="PASSED", dataset_payloads=_dataset_payloads(
                frozen, _bars(), _events()),
            recorded_at="2026-04-30T23:59:59Z")
    with pytest.raises(research.ResearchContractError,
                       match="holdout_recorded_before_latest_input"):
        research.record_holdout_result(
            frozen, status="PASSED", dataset_payloads=_dataset_payloads(
                frozen, _bars(), _events()),
            recorded_at="2026-05-02T00:00:00Z")

    no_holdout_events = [row for row in _events()
                         if row["eventId"] != "holdout-one"]
    no_holdout_draft = _manifest_for_inputs(
        _draft_manifest(), _bars(), no_holdout_events)
    no_holdout_frozen = research.freeze_manifest(
        no_holdout_draft, frozen_at="2026-05-01T00:00:00Z")
    no_holdout = _verified_artifact(
        no_holdout_frozen, _bars(), no_holdout_events)
    assert no_holdout["holdoutProof"]["eligibleForPass"] is False
    with pytest.raises(research.ResearchContractError,
                       match="holdout_not_eligible_for_pass"):
        research.record_holdout_result(
            no_holdout_frozen, status="PASSED",
            dataset_payloads=_dataset_payloads(
                no_holdout_frozen, _bars(), no_holdout_events),
            recorded_at="2026-07-21T00:00:00Z")

    passed = research.record_holdout_result(
        frozen, status="PASSED", dataset_payloads=_dataset_payloads(
            frozen, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    with pytest.raises(research.ResearchContractError,
                       match="golden_opened_before_holdout_result"):
        research.open_golden(
            passed, opened_at="2026-07-20T23:59:59Z")
    with pytest.raises(research.ResearchContractError,
                       match="golden_opened_before_holdout_result"):
        research.open_golden(
            passed, opened_at="2026-07-20T22:00:00Z")
    opened = research.open_golden(
        passed, opened_at="2026-07-21T00:00:01Z")
    changed_data = copy.deepcopy(opened)
    changed_data["datasetVersion"] = "synthetic-bars-events-v2"
    changed_data["datasets"][0]["sha256"] = "9" * 64
    with pytest.raises(research.ResearchContractError,
                       match="frozen_data_identity_mismatch"):
        research.validate_manifest(changed_data)


def test_sealed_golden_rejects_raw_input_and_open_golden_evaluates_last():
    sealed = _frozen_manifest()
    with pytest.raises(research.ResearchContractError,
                       match="sealed_golden_input_forbidden"):
        research.build_research_artifact(
            sealed, _bars(include_golden=True), _events(include_golden=True))
    sealed_artifact = _verified_artifact(
        sealed, _bars(), _events())
    passed = research.record_holdout_result(
        sealed, status="PASSED",
        dataset_payloads=_dataset_payloads(sealed, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    opened = research.open_golden(
        passed, opened_at="2026-07-21T00:00:01Z")
    artifact = _verified_artifact(
        opened, _bars(include_golden=True), _events(include_golden=True))
    assert artifact["goldenCase"]["access"] == "OPEN"
    assert artifact["goldenCase"]["evaluatedEventCount"] == 1
    assert artifact["partitions"]["GOLDEN"]["eventCount"] == 1
    checks = artifact["goldenCase"]["acceptanceChecks"]
    assert checks["evaluationStatus"] == "EVALUATED"
    assert checks["riskOffSufficient"] is True
    assert checks["riskOffFirstObservedDate"] == "2026-07-23"
    sho_artifact = _golden_sho_reversal()
    band = sho_artifact["evidence"]["bandWalkEnding"]
    assert checks["bandWalkEndingDetected"] is (
        band["conditionMet"] is True)
    assert checks["bandWalkEndingFirstObservedDate"] == (
        band["evidenceDate"] if band["conditionMet"] is True else None)
    assert checks["riskKernelArtifactId"] == _golden_risk_kernel()[
        "riskKernelId"]
    assert checks["shoReversalArtifactId"] == sho_artifact["artifactId"]
    assert checks["waitMissedOpportunityMeasured"] is True

    missing_artifacts = _events(include_golden=True)
    missing_artifacts[-1].pop("riskKernelArtifact")
    missing_artifacts[-1].pop("shoReversalArtifact")
    with pytest.raises(research.ResearchContractError,
                       match="golden_case_not_fully_evaluable"):
        research.build_research_artifact(
            opened, _bars(include_golden=True), missing_artifacts)

    tampered = _events(include_golden=True)
    tampered[-1]["riskKernelArtifact"]["constraint"] = "NONE"
    with pytest.raises(research.ResearchContractError,
                       match="invalid_golden_risk_kernel"):
        research.build_research_artifact(
            opened, _bars(include_golden=True), tampered)

    wrong_market = _events(include_golden=True)
    kernel = wrong_market[-1]["riskKernelArtifact"]
    kernel["subject"]["market"] = "US"
    kernel["riskKernelId"] = risk.compute_risk_kernel_id(kernel)
    with pytest.raises(research.ResearchContractError,
                       match="golden_risk_subject_mismatch"):
        research.build_research_artifact(
            opened, _bars(include_golden=True), wrong_market)


def test_counterfactuals_share_path_charge_costs_and_penalize_wait():
    artifact = _artifact()
    event = next(row for row in artifact["counterfactuals"]["perEvent"]
                 if row["eventId"] == "dev-forward")
    assert [row["strategy"] for row in event["strategies"]] == list(
        research.COUNTERFACTUAL_STRATEGIES)
    assert all(row["ownerPnl"] is False for row in event["strategies"])
    buy_now = event["strategies"][0]
    wait = event["strategies"][-1]
    assert buy_now["terminalReturnPct"] < (
        (_bars()[98]["close"] / _bars()[78]["close"] - 1) * 100)
    assert wait["cashReturnAssumptionPct"] == 0.0
    assert wait["missedMfePct"] == buy_now["mfePct"]
    assert wait["terminalStatus"] == "MISSED_VALIDATED_REVERSAL"
    assert wait["failure"] is True


def test_wait_failure_does_not_require_a_later_confirmation_trigger():
    bars, _ = research.normalize_point_in_time_bars(
        [{**row, "signals": {}} for row in _bars()],
        cutoff_at="2026-09-01T00:00:00Z")
    events, _ = research.normalize_point_in_time_events(
        _events(), cutoff_at="2026-09-01T00:00:00Z",
        partition_policy=_draft_manifest()["partitionPolicy"])
    event = next(row for row in events if row["eventId"] == "dev-validation")
    comparison = research._counterfactual_for_event(
        event, [row for row in bars if row["instrumentId"] == event[
            "instrumentId"]], {}, _draft_manifest()["parameters"],
        "next_session_open", 5.0, 5.0)
    wait = next(row for row in comparison["strategies"]
                if row["strategy"] == "WAIT")
    assert wait["missedMfePct"] >= 3.0
    assert wait["failure"] is True
    assert wait["terminalStatus"] == "MISSED_VALIDATED_REVERSAL"


def test_down_direction_drawdown_is_not_the_profitable_price_decline():
    events = _events()
    events[0]["expectedDirection"] = "DOWN"
    bars = _bars()
    anchor = next(index for index, row in enumerate(bars)
                  if row["date"] == events[0]["signalDate"])
    start = bars[anchor]["close"]
    for offset, row in enumerate(bars[anchor + 1:anchor + 21], 1):
        close = start - offset
        row.update({"open": close + 0.2, "high": close + 0.4,
                    "low": close - 0.4, "close": close})
    artifact = research.build_research_artifact(
        _frozen_manifest(), bars, events)
    event = next(row for row in artifact["eventDetails"]
                 if row["eventId"] == "dev-validation")
    outcome = event["horizons"]["20"]
    assert outcome["endReturnPct"] > 0
    assert outcome["mfePct"] > 0
    assert outcome["maxDrawdownPct"] > -5


def test_next_session_open_includes_entry_day_path_and_turtle_applies_exit():
    next_open = _draft_manifest()
    next_open = research.freeze_manifest(
        next_open, frozen_at="2026-05-01T00:00:00Z")
    artifact = research.build_research_artifact(
        next_open, _bars(), _events())
    event = next(row for row in artifact["counterfactuals"]["perEvent"]
                 if row["eventId"] == "dev-validation")
    buy_now = next(row for row in event["strategies"]
                   if row["strategy"] == "BUY_NOW")
    bars = _bars()
    entry = next(row for row in bars if row["date"] == buy_now["entryDate"])
    entry_day_mfe = (entry["high"] / entry["open"] - 1.0) * 100.0
    assert buy_now["mfePct"] >= round(entry_day_mfe, 6)

    bars = _bars()
    anchor = next(index for index, row in enumerate(bars)
                  if row["date"] == "2026-03-01")
    crash = bars[anchor + 2]
    prior_low = min(row["low"] for row in bars[anchor - 20:anchor + 2])
    crash.update({"open": prior_low - 0.5, "high": prior_low - 0.1,
                  "low": prior_low - 2.0, "close": prior_low - 1.0})
    artifact = research.build_research_artifact(
        _frozen_manifest(), bars, _events())
    event = next(row for row in artifact["counterfactuals"]["perEvent"]
                 if row["eventId"] == "dev-validation")
    turtle = next(row for row in event["strategies"]
                  if row["strategy"] == "BUY_ON_TURTLE_CONFIRMATION")
    assert turtle["exitRule"] == "20_DAY_LOW_EXIT"
    assert turtle["exitDate"] == bars[anchor + 3]["date"]

    bars = _bars()
    anchor = next(index for index, row in enumerate(bars)
                  if row["date"] == "2026-03-01")
    entry = bars[anchor + 1]
    prior_low = min(row["low"] for row in bars[anchor - 19:anchor + 1])
    entry.update({"open": prior_low + 1.0, "high": prior_low + 2.0,
                  "low": prior_low - 2.0, "close": prior_low + 0.5})
    artifact = research.build_research_artifact(
        _frozen_manifest(), bars, _events())
    event = next(row for row in artifact["counterfactuals"]["perEvent"]
                 if row["eventId"] == "dev-validation")
    turtle = next(row for row in event["strategies"]
                  if row["strategy"] == "BUY_ON_TURTLE_CONFIRMATION")
    assert turtle["entryDate"] == entry["date"]
    assert turtle["exitRule"] == "20_DAY_LOW_EXIT"
    assert turtle["exitDate"] == bars[anchor + 2]["date"]
    assert turtle["terminalStatus"] == "20_DAY_LOW_EXIT"


def test_turtle_is_exact_parameterized_shadow_and_never_a_hard_veto():
    turtle = _artifact()["turtleShadow"]
    assert turtle["parameters"] == {
        "atrPeriod": 20, "entryLookbacks": [20, 55],
        "exitLookbacks": [10, 20]}
    assert turtle["signalCounts"]["entry20"] > 0
    assert turtle["signalCounts"]["entry55"] > 0
    assert turtle["signalDayCount"] == len(turtle["signals"])
    assert turtle["signalsTruncated"] is False
    assert any(row["atrN"] is not None for row in turtle["signals"])
    assert turtle["shadowOnly"] is True
    assert turtle["hardVeto"] is False
    assert turtle["validationStatus"].startswith("UNVALIDATED")


def test_compact_event_details_bind_interpretation_and_dataset_provenance():
    event = next(row for row in _artifact()["eventDetails"]
                 if row["eventId"] == "dev-validation")
    assert event["datasetId"] == "fixture-events-v1"
    assert event["expectedDirection"] == "UP"
    assert event["targetPct"] == 3.0
    assert event["invalidationPct"] == -3.0
    assert event["validatedReversal"] is True


def test_artifact_is_compact_content_addressed_and_contains_no_raw_history():
    artifact = _artifact()
    payload = research.canonical_bytes(artifact)
    assert len(payload) < research.MAX_ARTIFACT_BYTES
    assert research.verify_research_artifact(artifact)
    def contains_ohlc(node):
        if isinstance(node, dict):
            if {"open", "high", "low", "close"}.issubset(node):
                return True
            return any(contains_ohlc(value) for value in node.values())
        if isinstance(node, list):
            return any(contains_ohlc(value) for value in node)
        return False
    assert contains_ohlc(artifact) is False
    assert b'"rawBars"' not in payload
    assert artifact["eventDetailsTruncated"] is False


def test_verifier_rejects_resealed_artifact_that_embeds_raw_ohlc():
    hostile = copy.deepcopy(_artifact())
    hostile["eventDetails"] = [{
        "date": "2026-03-01", "open": 100.0, "high": 101.0,
        "low": 99.0, "close": 100.5,
    }]
    hostile.pop("artifactDigest")
    hostile.pop("artifactId")
    digest = research.sha256_hex(hostile)
    hostile["artifactDigest"] = digest
    hostile["artifactId"] = "ra-" + digest[:32]
    assert research.sha256_hex({
        key: value for key, value in hostile.items()
        if key not in ("artifactDigest", "artifactId")
    }) == digest
    assert research.verify_research_artifact(hostile) is False


def test_verifier_rejects_rehashed_semantically_impossible_authority():
    hostile = copy.deepcopy(_artifact())
    hostile["goldenCase"].update({
        "access": "OPEN", "evaluatedEventCount": 999,
        "openedForPolicyIdentity": "rp-" + "f" * 64,
        "openedForResearchDataIdentity": "rd-" + "e" * 64,
    })
    hostile["partitions"]["GOLDEN"] = {
        "access": "OPEN", "eventCount": 999, "metrics": None}
    hostile["pointInTimeProof"]["futureInputAdmitted"] = True
    hostile["pointInTimeProof"]["bars"]["futureRowsAdmitted"] = True
    hostile["holdoutResultDigest"] = "0" * 64
    hostile["identity"] = {"researchIdentity": "rr-FORGED"}
    hostile.pop("artifactDigest")
    hostile.pop("artifactId")
    digest = research.sha256_hex(hostile)
    hostile["artifactDigest"] = digest
    hostile["artifactId"] = "ra-" + digest[:32]
    assert research.verify_research_artifact(hostile) is False


def test_verifier_rejects_resealed_count_and_nested_schema_forgery():
    def reseal(value):
        value.pop("artifactDigest")
        value.pop("artifactId")
        digest = research.sha256_hex(value)
        value["artifactDigest"] = digest
        value["artifactId"] = "ra-" + digest[:32]
        return value

    mutations = []
    hostile = copy.deepcopy(_artifact())
    hostile["coverage"]["excludedEventCounts"]["EMBARGO"] = 999
    mutations.append(hostile)
    hostile = copy.deepcopy(_artifact())
    hostile["pointInTimeProof"]["bars"]["duplicateRowCount"] = 999
    mutations.append(hostile)
    hostile = copy.deepcopy(_artifact())
    hostile["pointInTimeProof"]["events"]["duplicateEventCount"] = 999
    mutations.append(hostile)
    hostile = copy.deepcopy(_artifact())
    hostile["validationProtocol"]["walkForward"][0][
        "rawCloseHistory"] = [100.0] * 5000
    mutations.append(hostile)
    hostile = copy.deepcopy(_artifact())
    hostile["counterfactuals"]["strategies"][0][
        "rawCloseHistory"] = [100.0] * 5000
    mutations.append(hostile)
    assert all(research.verify_research_artifact(reseal(row)) is False
               for row in mutations)


def test_verifier_rejects_resealed_pit_execution_and_golden_contradictions():
    def reseal(value):
        value.pop("artifactDigest")
        value.pop("artifactId")
        digest = research.sha256_hex(value)
        value["artifactDigest"] = digest
        value["artifactId"] = "ra-" + digest[:32]
        return value

    hostile = copy.deepcopy(_artifact())
    dev_event = next(row for row in hostile["eventDetails"]
                     if row["eventId"] == "dev-validation")
    dev_comparison = next(row for row in hostile["counterfactuals"]["perEvent"]
                          if row["eventId"] == "dev-validation")
    buy_now = next(row for row in dev_comparison["strategies"]
                   if row["strategy"] == "BUY_NOW")
    buy_now["entryDate"] = "2099-12-31"
    buy_now["delaySessions"] = 1
    development_comparisons = [
        row for row in hostile["counterfactuals"]["perEvent"]
        if next(detail["partition"] for detail in hostile["eventDetails"]
                if detail["eventId"] == row["eventId"]) == "DEVELOPMENT"]
    hostile["partitionProofs"]["DEVELOPMENT"][
        "counterfactualDigest"] = research.sha256_hex(
            development_comparisons)
    assert research.verify_research_artifact(reseal(hostile)) is False

    hostile = copy.deepcopy(_artifact())
    dev_event = next(row for row in hostile["eventDetails"]
                     if row["eventId"] == "dev-validation")
    dev_event["availableFrom"] = "2026-03-01T23:00:00Z"
    dev_event["decisionCutoffAt"] = "1900-01-01T00:00:00Z"
    development_details = [
        row for row in hostile["eventDetails"]
        if row["partition"] == "DEVELOPMENT"]
    hostile["partitionProofs"]["DEVELOPMENT"][
        "eventDetailsDigest"] = research.sha256_hex(development_details)
    assert research.verify_research_artifact(reseal(hostile)) is False

    sealed = _frozen_manifest()
    passed = research.record_holdout_result(
        sealed, status="PASSED",
        dataset_payloads=_dataset_payloads(sealed, _bars(), _events()),
        recorded_at="2026-07-21T00:00:00Z")
    opened = research.open_golden(
        passed, opened_at="2026-07-21T00:00:01Z")
    hostile = copy.deepcopy(_verified_artifact(
        opened, _bars(include_golden=True), _events(include_golden=True)))
    checks = hostile["goldenCase"]["acceptanceChecks"]
    checks["vixDecreasingConfirmationDetected"] = not checks[
        "vixDecreasingConfirmationDetected"]
    checks["riskOffFirstObservedDate"] = "1900-01-01"
    assert research.verify_research_artifact(reseal(hostile)) is False


def test_module_and_runner_have_no_network_env_backend_or_implicit_now_dependency():
    forbidden_imports = {"os", "requests", "socket", "urllib", "http",
                         "scanner"}
    for path in (ROOT / "argus_research_compute.py", RUNNER_PATH):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0]
                               for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today", "time"}
        assert not (imports & forbidden_imports)


def test_runner_verifies_hashes_is_idempotent_and_never_embeds_input_rows(tmp_path):
    bars_payload = research.canonical_bytes(_bars())
    events_payload = research.canonical_bytes(_events())
    (tmp_path / "bars.json").write_bytes(bars_payload)
    (tmp_path / "events.json").write_bytes(events_payload)
    datasets = [
        {"datasetId": "fixture-bars-v1", "kind": "bars",
         "partitionScope": "NON_GOLDEN",
         "path": "bars.json", "sha256": hashlib.sha256(bars_payload).hexdigest(),
         "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
        {"datasetId": "fixture-events-v1", "kind": "events",
         "partitionScope": "NON_GOLDEN",
         "path": "events.json", "sha256": hashlib.sha256(events_payload).hexdigest(),
         "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
    ]
    manifest = _frozen_manifest(datasets=datasets)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(research.canonical_bytes(manifest))
    output = tmp_path / "out" / "artifact.json"
    first = runner.run(
        manifest_path=manifest_path, dataset_root=tmp_path,
        output_path=output,
        expected_research_identity=research.research_identity(manifest))
    first_bytes = output.read_bytes()
    second = runner.run(
        manifest_path=manifest_path, dataset_root=tmp_path,
        output_path=output,
        expected_research_identity=research.research_identity(manifest))
    assert first == second
    assert output.read_bytes() == first_bytes
    assert first["inputReceipt"]["totalBytes"] == len(bars_payload) + len(events_payload)
    assert b'"open"' not in first_bytes
    assert research.verify_research_artifact(first)

    hostile = copy.deepcopy(manifest)
    hostile["datasets"][0]["sha256"] = "0" * 64
    hostile["freeze"]["researchDataIdentity"] = \
        research.research_data_identity(hostile)
    hostile_path = tmp_path / "hostile.json"
    hostile_path.write_bytes(research.canonical_bytes(hostile))
    with pytest.raises(runner.RunnerError, match="dataset_sha256_mismatch"):
        runner.run(manifest_path=hostile_path, dataset_root=tmp_path,
                   output_path=tmp_path / "never.json")


def test_runner_keeps_precommitted_golden_files_unread_and_protected(tmp_path):
    bars_payload = _canonical_dataset_payload(_bars())
    events_payload = _canonical_dataset_payload(_events())
    (tmp_path / "bars.json").write_bytes(bars_payload)
    (tmp_path / "events.json").write_bytes(events_payload)
    manifest = _frozen_manifest()
    manifest_path = tmp_path / "sealed-manifest.json"
    manifest_path.write_bytes(research.canonical_bytes(manifest))
    artifact = runner.run(
        manifest_path=manifest_path, dataset_root=tmp_path,
        output_path=tmp_path / "sealed-artifact.json",
        expected_research_identity=research.research_identity(manifest))
    assert artifact["inputReceipt"]["datasetCount"] == 2
    assert len(artifact["inputReceipt"]["sealedCommitments"]) == 2
    assert not (tmp_path / "golden-bars.json").exists()
    assert not (tmp_path / "golden-events.json").exists()
    with pytest.raises(runner.RunnerError,
                       match="output_may_not_replace_input"):
        runner.run(
            manifest_path=manifest_path, dataset_root=tmp_path,
            output_path=tmp_path / "golden-bars.json")
    assert not (tmp_path / "golden-bars.json").exists()


def test_committed_coverage_artifact_is_sealed_and_honestly_data_gated():
    path = ROOT / "artifacts" / "round2-research-coverage-v1.json"
    coverage = json.loads(path.read_text(encoding="utf-8"))
    assert research.verify_coverage_artifact(coverage)
    assert coverage["overallStatus"] == "DATA_GATED"
    assert coverage["productionExpectancyValidated"] is False
    assert coverage["syntheticFixturesAreProductionEvidence"] is False
    assert coverage["committedData"][0]["rowCount"] == 2434
    assert coverage["committedData"][0]["sha256"] == \
        "50c57ae35762d90f5123f4fc40614c85954c7dee417ff249fc688b9130ee37cb"
    assert coverage["committedData"][0]["firstPeriod"] == "2002-08-02"
    assert coverage["committedData"][0]["lastPeriod"] == "2026-07-10"
