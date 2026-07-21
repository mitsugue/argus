import copy

import argus_foundation_jobs as foundation
import argus_research_benchmark as v1
import argus_research_benchmark_v2 as v2


def _master(code, market):
    return {"Code": code, "Mkt": market, "CoName": "Domestic Common"}


def _bar(code, date, adjusted, volume=100):
    return {"Code": code, "Date": date, "AdjC": adjusted, "Vo": volume}


def _axes(value=75):
    return {key: value for key in v2.QUALITY_WEIGHTS}


def _protocol():
    return {key: True for key in v2.PROTOCOL_GATES}


def _case_rows(run_id, cases, ratio_bias=0):
    rows = []
    for case in cases:
        order = v2.blind_order(run_id, case["caseId"])
        axes = {}
        for label, provider in order.items():
            axes[label] = _axes(80 + ratio_bias if provider == "argus" else 80)
        claims = {"gemini": [{"url": "https://example.com/g", "publishedAt":
                               case["allowedEvidenceCutoff"],
                               "sourceValidated": True}],
                  "argus": [{"url": "https://example.com/a", "publishedAt":
                              case["allowedEvidenceCutoff"],
                              "sourceValidated": True}]}
        rows.append(v2.score_case(run_id=run_id, case=case,
                                  axes_by_label=axes,
                                  claims_by_provider=claims,
                                  protocol_gates=_protocol()))
    return rows


def test_v2_pool_selection_is_frozen_stratified_and_disjoint_from_v1():
    manifest = v2.frozen_manifest("a" * 40)
    assert len(v2.candidate_pool()) == 36
    assert len(manifest["calibration"]) == 6
    assert len(manifest["holdout"]) == 12
    assert len(manifest["reserve"]) == 18
    assert manifest == v2.frozen_manifest("a" * 40)
    urls = {source["url"] for phase in ("calibration", "holdout")
            for case in manifest[phase]
            for source in case["primarySourceDocuments"]}
    check = v2.validate_manifest(
        manifest, v1_case_ids=[x["caseId"] for x in v1.FORMAL_DATASET],
        source_access={url: True for url in urls})
    assert check == {"valid": True, "errors": [], "validatedCaseCount": 18,
                     "datasetHash": manifest["datasetHash"]}


def test_v2_manifest_rejects_reused_v1_question_even_with_new_case_id():
    manifest = v2.frozen_manifest("f" * 40)
    manifest["calibration"][0]["ownerQuestion"] = v1.FORMAL_DATASET[0]["question"]
    selected = {phase: manifest[phase]
                for phase in ("calibration", "holdout", "reserve")}
    manifest["datasetHash"] = v2.digest({"name": v2.DATASET_NAME,
                                         "selected": selected})
    check = v2.validate_manifest(
        manifest,
        v1_case_ids=[row["caseId"] for row in v1.FORMAL_DATASET],
        v1_questions=[row["question"] for row in v1.FORMAL_DATASET])
    assert check["valid"] is False
    assert "v1_question_overlap" in check["errors"]


def test_v2_manifest_rejects_future_evidence_before_any_provider_call():
    manifest = v2.frozen_manifest("9" * 40)
    case = manifest["holdout"][0]
    case["primarySourceDocuments"][0]["availableFrom"] = \
        "2099-01-01T00:00:00Z"
    case["evidenceBundleHash"] = v2.digest(case["primarySourceDocuments"])
    selected = {phase: manifest[phase]
                for phase in ("calibration", "holdout", "reserve")}
    manifest["datasetHash"] = v2.digest({"name": v2.DATASET_NAME,
                                         "selected": selected})
    check = v2.validate_manifest(manifest)
    assert check["valid"] is False
    assert f"future_leakage:{case['caseId']}" in check["errors"]


def test_v2_quality_failure_is_scored_without_invalidating_protocol():
    case = v2.frozen_manifest("b" * 40)["calibration"][0]
    order = v2.blind_order("run", case["caseId"])
    axes = {label: _axes(10 if provider == "argus" else 90)
            for label, provider in order.items()}
    claims = {"gemini": [{"url": "https://example.com/g",
                           "publishedAt": case["allowedEvidenceCutoff"],
                           "sourceValidated": True}],
              "argus": [{"url": None,
                          "publishedAt": case["allowedEvidenceCutoff"],
                          "sourceValidated": False, "fabricated": True}]}
    row = v2.score_case(run_id="run", case=case, axes_by_label=axes,
                        claims_by_provider=claims, protocol_gates=_protocol())
    assert row["protocolValid"] is True
    assert row["argus"]["score"] == 0
    assert row["argus"]["criticalFabricationCount"] == 1


def test_v2_calibration_freeze_and_one_time_holdout_formally_close_non_2x():
    manifest = v2.frozen_manifest("c" * 40)
    state = v2.default_state()
    state["manifest"] = manifest
    state = v2.close_v1(state, {
        "datasetHash": v1.DATASET_HASH, "benchmarkId": "v1-run",
        "resultClassification": "invalid", "twoXClaimAllowed": False},
        closed_at="2026-07-21T00:00:00Z")
    calibration = _case_rows("cal-run", manifest["calibration"])
    state = v2.record_calibration(
        state, run_id="cal-run", rows=calibration,
        completed_at="2026-07-21T00:01:00Z",
        models={"gemini": "gemini-3.1-pro-preview",
                "argus": "gpt-5.6-sol", "referee": "gpt-5.6-terra"},
        implementation_hash="d" * 64)
    assert state["frozenRun"]
    consumed = v2.consume_holdout(state, run_id="hold-run")
    assert consumed["allowed"]
    assert not v2.consume_holdout(consumed["state"],
                                  run_id="different")["allowed"]
    holdout = _case_rows("hold-run", manifest["holdout"])
    completed = v2.finalize(
        consumed["state"], run_id="hold-run", rows=holdout,
        models={"gemini": "gemini-3.1-pro-preview",
                "argus": "gpt-5.6-sol", "referee": "gpt-5.6-terra"},
        provider_proof={}, pricing={"version": "test"},
        actual_cost_jpy=100, completed_at="2026-07-21T00:02:00Z")
    assert completed["ok"] is True
    assert completed["status"] == "not_achieved"
    assert completed["result"]["formalDetermination"] == \
        "GEMINI 2X NOT ACHIEVED — FORMALLY CLOSED"
    assert completed["result"]["twoXClaimAllowed"] is False
    assert completed["result"]["qualityDimensions"]["argus"]
    assert sum(row["caseCount"] for row in
               completed["result"]["categoryBreakdown"].values()) == 12


def test_v1_closure_is_append_only_and_never_reopens_holdout():
    state = v2.close_v1(v2.default_state(), {
        "datasetHash": "hash", "benchmarkId": "run", "modelIds": {},
        "medianRatio": 1.2, "geometricMeanRatio": 1.1,
        "totalApiCostJpy": 10}, closed_at="2026-07-21T00:00:00Z")
    original = copy.deepcopy(state["v1Closure"])
    state = v2.close_v1(state, {"benchmarkId": "replacement"},
                        closed_at="2026-07-22T00:00:00Z")
    assert state["v1Closure"] == original
    assert state["v1Closure"]["status"] == "closed_invalid"
    assert state["v1Closure"]["rerunAllowed"] is False


def test_standard_breadth_uses_historical_first_section_then_prime():
    old = foundation.calculate_daily(
        date="2022-04-01",
        master_rows=[_master("11110", "0101"), _master("22220", "0102")],
        bar_rows=[_bar("11110", "2022-04-01", 110),
                  _bar("22220", "2022-04-01", 90)],
        previous_adjusted_closes={"11110": 100, "22220": 100})
    assert old["universes"]["tse_first_section_domestic_common"][
        "counts"]["advancers"] == 1
    assert old["universes"]["tse_prime_domestic_common"]["issueCount"] == 0
    old_series = {row["seriesId"] for row in foundation.ledger_candidates(
        old, calculated_at="2022-04-01T17:00:00+09:00")}
    assert any(series.startswith("breadth.first_section.") for series in old_series)
    assert not any(series.startswith("breadth.prime.") for series in old_series)
    new = foundation.calculate_daily(
        date="2022-04-04", master_rows=[_master("11110", "0111")],
        bar_rows=[_bar("11110", "2022-04-04", 111)],
        previous_adjusted_closes={"11110": 110})
    assert new["universes"]["tse_first_section_domestic_common"][
        "issueCount"] == 0
    assert new["universes"]["tse_prime_domestic_common"][
        "counts"]["advancers"] == 1
    new_series = {row["seriesId"] for row in foundation.ledger_candidates(
        new, calculated_at="2022-04-04T17:00:00+09:00")}
    assert any(series.startswith("breadth.prime.") for series in new_series)
    assert not any(series.startswith("breadth.first_section.")
                   for series in new_series)


def test_no_trade_and_missing_price_are_distinct_and_never_scored_as_zero():
    result = foundation.calculate_daily(
        date="2026-07-17",
        master_rows=[_master("11110", "0111"), _master("22220", "0111")],
        bar_rows=[_bar("11110", "2026-07-17", 100, volume=0),
                  _bar("22220", "2026-07-17", None, volume=100)],
        previous_adjusted_closes={"11110": 100, "22220": 100})
    prime = result["universes"]["tse_prime_domestic_common"]
    assert prime["counts"]["decliners"] == 0
    assert prime["counts"]["unavailable"] == 2
    assert prime["dataQuality"] == {"noTrade": 1, "missingPrice": 1}
    rows = foundation.ledger_candidates(
        result, calculated_at="2026-07-17T08:00:00Z")
    by_series = {row["seriesId"]: row for row in rows}
    assert by_series["breadth.prime.noTrade"]["value"] == 1
    assert by_series["breadth.prime.missingPrice"]["value"] == 1
    assert by_series["breadth.prime.advancers"]["metadata"]["plan"] == "standard"
    assert by_series["breadth.prime.advancers"]["metadata"][
        "entitlementStartDate"] == "2016-07-20"
    assert by_series["breadth.prime.advancers"]["metadata"][
        "contractScope"] == "rolling_10_years"
