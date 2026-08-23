import copy
import json
import os
import time

import pytest

import argus_causal_event_memory as cem


T0 = "2026-07-20T02:34:00Z"
T1 = "2026-08-05T03:00:00Z"
T2 = "2026-08-18T03:00:00Z"
BEFORE_T0 = "2026-07-19T02:34:00Z"
SHA = "a" * 40


def news(event_id="nie-iran-1", *, event_type="IRAN", severity="WATCH",
         processed=T0, received="2026-07-20T02:33:00Z", headline="Iran tension rises",
         themes=None, entities=None, backfill=False, facts=None):
    return {
        "schemaVersion": "argus-news-event-v1",
        "eventId": event_id,
        "revision": 1,
        "source": "Nikkei",
        "sourceFamily": "NIKKEI",
        "sourceTier": "trusted_subscription",
        "sourceFingerprint": "fp-" + event_id,
        "sourceReceivedAt": received,
        "sourcePublishedAt": None,
        "processedAt": processed,
        "headlineJa": headline,
        "eventType": event_type,
        "themeTags": themes or ["ENERGY", "LONG_DURATION_GROWTH"],
        "facts": facts or ["tension increased"],
        "entities": entities or ["IRAN"],
        "sourceUrl": "https://example.test/source",
        "severity": severity,
        "severityReasons": ["family_" + event_type.lower()],
        "dataInput": False,
        "authority": "NEWS_RISK_EVIDENCE",
        "sdaAuthority": False,
        "backfill": backfill,
    }


def build_event(raw=None, *, existing=(), prior=None, known=T0, origin="FORWARD_LIVE",
                regime=None, readings=None, episode=None):
    raw = raw or news()
    ep = episode or cem.choose_episode(
        existing, event_id=raw["eventId"], event_type=raw["eventType"],
        themes=raw.get("themeTags") or [], entities=raw.get("entities") or [],
        countries=[], known_at=known)
    context = []
    for row in readings or []:
        context.append({**row, "knownAt": row.get("knownAt") or known,
                        "sourceRef": row.get("sourceRef") or "truth:test"})
    return cem.build_event_revision(
        news_event=raw, known_at=known, origin=origin, code_identity=SHA,
        episode=ep, market_context=context, regime_context=regime or {},
        prior_event=prior)


def ledger_state(tmp_path, *payloads):
    path = tmp_path / "events.jsonl"
    for payload in payloads:
        cem.append_record(str(path), payload)
    loaded = cem.read_ledger(str(path))
    assert loaded["status"] == "VERIFIED"
    return str(path), cem.fold_records(loaded["records"])


def test_low_value_and_info_mail_do_not_pollute_memory():
    ok, reason = cem.event_memory_eligible(news(severity="INFO"))
    assert not ok and reason == "info_not_material"
    ok, reason = cem.event_memory_eligible(news(
        headline="Subscription Change Confirmation", facts=["subscription changed"]))
    assert not ok and reason == "administrative_mail"
    ok, reason = cem.event_memory_eligible(news())
    assert ok and reason == "eligible"


def test_point_in_time_contract_rejects_future_market_and_source_data():
    with pytest.raises(ValueError, match="future_market_context"):
        build_event(readings=[{"key": "oil", "value": 90, "change": 3,
                               "knownAt": T1}])
    raw = news()
    raw["sourcePublishedAt"] = T1
    with pytest.raises(ValueError, match="future_published_at"):
        build_event(raw)


def test_event_revision_preserves_initial_state_and_hypotheses(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    raw2 = news(processed=T1, received="2026-08-05T02:59:00Z", severity="HIGH",
                headline="Iran supply risk escalates")
    second = build_event(raw2, prior=state["events"][first["eventId"]], known=T1,
                         episode={"episodeId": first["episodeId"], "linked": True,
                                  "relatedEventId": None})
    assert second["eventVersion"] == 2
    assert second["initialSeverity"] == "WATCH"
    assert second["causalHypotheses"] == first["causalHypotheses"]
    _, state2 = ledger_state(tmp_path / "next", first, second)
    assert len(state2["events"][first["eventId"]]["revisions"]) == 2


def test_revision_cannot_change_episode_origin_or_backdate(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    prior = state["events"][first["eventId"]]
    later = news(processed=T1, received="2026-08-05T02:59:00Z")
    with pytest.raises(ValueError, match="episode_mutation"):
        build_event(later, prior=prior, known=T1,
                    episode={"episodeId": "cep-different", "linked": False,
                             "relatedEventId": None})
    with pytest.raises(ValueError, match="origin_mutation"):
        build_event(later, prior=prior, known=T1, origin="BACKFILL",
                    episode={"episodeId": first["episodeId"], "linked": False,
                             "relatedEventId": None})
    backdated = news(processed=BEFORE_T0, received="2026-07-19T02:33:00Z")
    with pytest.raises(ValueError, match="backdating"):
        build_event(backdated, prior=prior, known=BEFORE_T0,
                    episode={"episodeId": first["episodeId"], "linked": False,
                             "relatedEventId": None})


def test_logical_history_mutation_is_rejected_even_if_new_record_is_valid(tmp_path):
    first = build_event()
    bad = copy.deepcopy(first)
    bad["eventVersion"] = 2
    bad["knownAt"] = bad["eventDecisionCutoff"] = T1
    bad["normalizedAt"] = bad["immutableCreatedAt"] = T1
    bad["initialSeverity"] = "CRITICAL"
    path = tmp_path / "mutated.jsonl"
    r1 = cem.append_record(str(path), first)
    r2 = cem.append_record(str(path), bad)
    state = cem.empty_state()
    cem.apply_record(state, r1)
    with pytest.raises(ValueError, match="history_mutation"):
        cem.apply_record(state, r2)


def test_hash_chained_fsynced_ledger_detects_corruption(tmp_path):
    first = build_event()
    path, _ = ledger_state(tmp_path, first)
    with open(path, "rb") as handle:
        row = json.loads(handle.readline())
    row["payload"]["headline"] = "rewritten hindsight"
    with open(path, "wb") as handle:
        handle.write(json.dumps(row).encode() + b"\n")
    loaded = cem.read_ledger(path)
    assert loaded["status"] == "CORRUPT"
    assert loaded["corruptLine"] == 1
    with pytest.raises(RuntimeError, match="invalid_tail"):
        cem.append_record(path, first)


def test_ledger_enforces_record_bound_before_append(tmp_path, monkeypatch):
    monkeypatch.setattr(cem, "MAX_LEDGER_RECORDS", 1)
    path = tmp_path / "bounded.jsonl"
    cem.append_record(str(path), build_event())
    with pytest.raises(RuntimeError, match="record_bound"):
        cem.append_record(str(path), build_event(news(event_id="second")))


def test_iran_flag_recovery_requires_intermediate_chain(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = state["events"][first["eventId"]]
    hypothesis = first["causalHypotheses"][0]
    observations = cem.market_observations([
        {"key": "oil", "value": 96, "change": 4.2, "asOf": "2026-08-18"},
        {"key": "us30y", "value": 5.30, "change": 8.0, "state": "HIGH",
         "asOf": "2026-08-18"},
        {"key": "qqq", "value": 590, "change": -2.2, "asOf": "2026-08-18"},
    ], known_at=T2)
    evidence = cem.evidence_for_hypothesis(
        hypothesis, observations, event_support_ref="causal-event:nie-sanctions",
        event_supporting=True)
    assessment = cem.build_assessment(
        event={**cem.event_view(event), "assessments": event["assessments"]},
        hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T2,
        evidence=evidence, code_identity=SHA)
    assert assessment["status"] == "CONFIRMED"
    assert assessment["flagRecovery"] is True
    assert assessment["causalLanguage"] == "CONSISTENT_WITH"
    assert assessment["requirementsCovered"] == [
        "long_duration_growth", "long_end_yields", "oil_price"]


def test_old_watch_with_deescalation_is_invalidated(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    hypothesis = event["causalHypotheses"][0]
    assessment = cem.build_assessment(
        event=event, hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T2,
        evidence=[{"variable": "event_escalation", "relation": "CONTRADICTING",
                   "observedDirection": "DOWN", "expectedDirection": "UP",
                   "knownAt": T2, "sourceRef": "official:ceasefire",
                   "noteCode": "DEESCALATION_CONFIRMED"}])
    assert assessment["status"] == "INVALIDATED"
    assert assessment["eventStatus"] in ("WEAKENED", "WATCHING")
    assert assessment["flagRecovery"] is False


def test_unrelated_fiscal_yield_move_does_not_recover_old_inflation_flag(tmp_path):
    first = build_event(news(event_id="nie-cpi", event_type="INFLATION",
                             themes=["LONG_DURATION_GROWTH"], entities=["BLS"]))
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    hypothesis = event["causalHypotheses"][0]
    assessment = cem.build_assessment(
        event=event, hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T2,
        evidence=[{"variable": "long_end_yields", "relation": "SUPPORTING",
                   "observedDirection": "UP", "expectedDirection": "UP",
                   "knownAt": T2, "sourceRef": "truth:dgs30",
                   "noteCode": "FISCAL_AUCTION_SHOCK"}],
        attribution_mode="ATTRIBUTION_UNCERTAIN",
        competing_event_refs=["causal-event:fiscal-auction"])
    assert assessment["status"] == "PARTIALLY_CONFIRMED"
    assert assessment["flagRecovery"] is False
    assert assessment["attributionMode"] == "ATTRIBUTION_UNCERTAIN"


def test_market_falls_but_intermediate_evidence_contradicts_no_confirmation(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    hypothesis = event["causalHypotheses"][0]
    assessment = cem.build_assessment(
        event=event, hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T2,
        evidence=[
            {"variable": "long_duration_growth", "relation": "SUPPORTING",
             "observedDirection": "DOWN", "expectedDirection": "DOWN",
             "knownAt": T2, "sourceRef": "truth:qqq", "noteCode": "EARNINGS_SHOCK"},
            {"variable": "oil_price", "relation": "CONTRADICTING",
             "observedDirection": "DOWN", "expectedDirection": "UP",
             "knownAt": T2, "sourceRef": "truth:wti", "noteCode": "MARKET_OBSERVATION"},
            {"variable": "long_end_yields", "relation": "CONTRADICTING",
             "observedDirection": "DOWN", "expectedDirection": "UP",
             "knownAt": T2, "sourceRef": "truth:dgs30", "noteCode": "MARKET_OBSERVATION"},
        ], attribution_mode="ATTRIBUTION_UNCERTAIN",
        competing_event_refs=["causal-event:earnings"])
    assert assessment["status"] == "WEAKENED"
    assert assessment["flagRecovery"] is False


def test_multi_causal_is_explicit_and_never_monocausal_language(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    h = event["causalHypotheses"][0]
    evidence = [{"variable": variable, "relation": "SUPPORTING",
                 "observedDirection": h["expectedDirections"][variable],
                 "expectedDirection": h["expectedDirections"][variable],
                 "knownAt": T2, "sourceRef": "truth:" + variable,
                 "noteCode": "MARKET_OBSERVATION"}
                for variable in h["confirmationRequirements"]]
    assessment = cem.build_assessment(
        event=event, hypothesis_id=h["hypothesisId"], evaluated_at=T2,
        evidence=evidence, attribution_mode="MULTI_CAUSAL",
        competing_event_refs=["event:auction", "event:fed-speech"])
    assert assessment["status"] == "CONFIRMED"
    assert assessment["attributionMode"] == "MULTI_CAUSAL"
    assert assessment["causalLanguage"] == "CONSISTENT_WITH"


def test_no_outcome_data_is_unscorable_not_zero(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    outcome = cem.build_outcome_window(
        event=event, hypothesis_id=event["causalHypotheses"][0]["hypothesisId"],
        horizon="5D", target_at=T1, observed_at=T1, known_at=T1,
        metrics=None, truth_refs=None, missing_reasons=["price_history_missing"])
    assert outcome["status"] == "UNSCORABLE"
    assert outcome["metrics"] == [] and outcome["truthRefs"] == []
    assert outcome["forwardLiveCalibrationEvidence"] is False
    assert outcome["policyInfluence"] is False
    with pytest.raises(ValueError, match="time_contract"):
        cem.build_outcome_window(
            event=event, hypothesis_id=event["causalHypotheses"][0]["hypothesisId"],
            horizon="5D", target_at=T1, observed_at=T0, known_at=T1,
            metrics=None, truth_refs=None, missing_reasons=["missing"])


def test_scheduled_macro_distinguishes_expected_from_verified_surprise():
    raw = news(event_type="INFLATION")
    raw["sourceFamily"] = "BLS"
    expected = build_event(raw)
    assert expected["scheduledEvent"] is True
    assert expected["eventInformationType"] == "EXPECTED_EVENT"
    assert expected["surpriseInformation"] is None
    raw["surpriseInformation"] = {
        "actual": 3.1, "consensus": 2.9, "unit": "%", "knownAt": T0,
        "sourceRef": "bls:cpi:2026-07"}
    surprise = build_event(raw)
    assert surprise["eventInformationType"] == "SURPRISE_INFORMATION"
    assert surprise["surpriseInformation"]["actual"] == 3.1
    assert surprise["japanTransmissionPaths"]


def test_replay_backfill_and_forward_live_remain_separate(tmp_path):
    payloads = []
    for idx, origin in enumerate(cem.ORIGINS):
        at = f"2026-07-{10 + idx:02d}T02:34:00Z"
        raw = news(event_id=f"nie-{origin.lower()}", processed=at,
                   received=f"2026-07-{10 + idx:02d}T02:33:00Z")
        payloads.append(build_event(raw, known=at, origin=origin))
    _, state = ledger_state(tmp_path, *payloads)
    view = cem.compact_public_view(state, as_of=T2)
    assert view["maturity"]["forwardLiveIndependentEpisodes"] == 1
    assert view["calibrationMode"] == "SHADOW"
    assert view["automaticCalibrationEnabled"] is False
    assert view["maturity"]["minimumTradingDaySpan"] == 120
    assert "minimumCalendarSpanDays" not in view["maturity"]


def test_maturity_span_counts_weekdays_not_calendar_days(tmp_path):
    first_at = "2026-01-01T02:34:00Z"
    last_at = "2026-01-05T02:34:00Z"
    first = build_event(news(event_id="span-first", processed=first_at,
                             received="2026-01-01T02:33:00Z"), known=first_at)
    last = build_event(news(event_id="span-last", processed=last_at,
                            received="2026-01-05T02:33:00Z"), known=last_at)
    _, state = ledger_state(tmp_path, first, last)
    result = cem.maturity(state, as_of=T2)
    assert result["forwardLiveCalendarSpanDays"] == 5
    assert result["forwardLiveTradingDaySpan"] == 3
    assert result["maturity"] == "INSUFFICIENT"


def test_episode_clustering_links_related_events_but_not_other_families(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    views = cem.all_event_views(state)
    linked = cem.choose_episode(
        views, event_id="nie-hormuz-2", event_type="HORMUZ", themes=["ENERGY"],
        entities=["IRAN"], countries=[], known_at=T1)
    assert linked["linked"] and linked["episodeId"] == first["episodeId"]
    unrelated = cem.choose_episode(
        views, event_id="nie-ai", event_type="AI_DATACENTER", themes=["AI"],
        entities=["NVIDIA"], countries=[], known_at=T1)
    assert not unrelated["linked"] and unrelated["episodeId"] != first["episodeId"]
    isolated = cem.choose_episode(
        views, event_id="nie-replay", event_type="HORMUZ", themes=["ENERGY"],
        entities=["IRAN"], countries=[], known_at=T1, origin="HISTORICAL_REPLAY")
    assert not isolated["linked"] and isolated["episodeId"] != first["episodeId"]


def _analog_event(event_id, known, regime, *, episode_id=None, origin="FORWARD_LIVE"):
    raw = news(event_id=event_id, processed=known,
               received=known.replace(":00Z", ":00Z"), headline="same headline")
    episode = {"episodeId": episode_id or f"cep-{event_id}", "linked": False,
               "relatedEventId": None}
    return build_event(raw, known=known, regime=regime, origin=origin, episode=episode)


def test_analog_ranking_is_structured_regime_aware_and_episode_independent(tmp_path):
    similar = _analog_event("prior-similar", "2026-06-01T02:34:00Z",
                            {"ratesRegime": "HIGH", "equityVolatility": "HIGH"},
                            episode_id="cep-duplicate")
    duplicate = _analog_event("prior-duplicate", "2026-06-02T02:34:00Z",
                              {"ratesRegime": "HIGH", "equityVolatility": "HIGH"},
                              episode_id="cep-duplicate")
    different = _analog_event("prior-different", "2026-06-03T02:34:00Z",
                              {"ratesRegime": "LOW", "equityVolatility": "LOW"})
    current = _analog_event("current", T2,
                            {"ratesRegime": "HIGH", "equityVolatility": "HIGH"})
    _, state = ledger_state(tmp_path, similar, duplicate, different, current)
    result = cem.retrieve_analogs(state, event_id="current", as_of=T2)
    assert result["independentEpisodeCount"] == 2
    assert result["analogs"][0]["episodeId"] == "cep-duplicate"
    assert result["analogs"][0]["regimeSimilarity"] > \
        result["analogs"][1]["regimeSimilarity"]
    assert result["selectionUsesOutcomes"] is False
    assert result["insufficientEvidence"] is True
    assert result["calibratedProbability"] is None


def test_future_outcome_cannot_enter_analog_result_at_original_cutoff(tmp_path):
    prior = _analog_event("prior", "2026-06-01T02:34:00Z",
                          {"ratesRegime": "HIGH"})
    current = _analog_event("current", T1, {"ratesRegime": "HIGH"})
    _, base = ledger_state(tmp_path / "base", prior, current)
    prior_view = cem.event_view(base["events"]["prior"])
    outcome = cem.build_outcome_window(
        event=prior_view,
        hypothesis_id=prior_view["causalHypotheses"][0]["hypothesisId"],
        horizon="20D", target_at="2026-07-01T02:34:00Z",
        observed_at="2026-07-01T02:34:00Z", known_at=T2,
        metrics=[{"metric": "RETURN", "instrument": "QQQ", "value": -3.2,
                  "unit": "%"}], truth_refs=["truth:qqq:2026-07-01"])
    hypothesis = prior_view["causalHypotheses"][0]
    future_assessment = cem.build_assessment(
        event=prior_view, hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T2,
        evidence=[{
            "variable": variable, "relation": "SUPPORTING",
            "observedDirection": hypothesis["expectedDirections"][variable],
            "expectedDirection": hypothesis["expectedDirections"][variable],
            "knownAt": T2, "sourceRef": "truth:" + variable,
            "noteCode": "MARKET_OBSERVATION",
        } for variable in hypothesis["confirmationRequirements"]])
    _, with_future = ledger_state(
        tmp_path / "future", prior, current, outcome, future_assessment)
    before = cem.retrieve_analogs(base, event_id="current", as_of=T1)
    after = cem.retrieve_analogs(with_future, event_id="current", as_of=T1)
    assert before["analogs"] == after["analogs"]
    assert after["scoredEpisodeCount"] == 0


def test_analog_statistics_are_origin_separated_and_cached(tmp_path):
    forward = _analog_event("prior-forward", "2026-06-01T02:34:00Z",
                            {"ratesRegime": "HIGH"})
    replay = _analog_event("prior-replay", "2026-06-02T02:34:00Z",
                           {"ratesRegime": "HIGH"}, origin="HISTORICAL_REPLAY")
    current = _analog_event("current", T2, {"ratesRegime": "HIGH"})
    _, base = ledger_state(tmp_path / "base", forward, replay, current)
    forward_view = cem.event_view(base["events"]["prior-forward"])
    replay_view = cem.event_view(base["events"]["prior-replay"])
    outcomes = [cem.build_outcome_window(
        event=view, hypothesis_id=view["causalHypotheses"][0]["hypothesisId"],
        horizon="5D", target_at="2026-06-10T02:34:00Z",
        observed_at="2026-06-10T02:34:00Z", known_at="2026-06-10T02:34:00Z",
        metrics=[{"metric": "RETURN", "instrument": "QQQ", "value": value,
                  "unit": "%"}], truth_refs=[f"truth:qqq:{value}"])
        for view, value in ((forward_view, -3.0), (replay_view, -7.0))]
    _, state = ledger_state(tmp_path / "scored", forward, replay, current, *outcomes)
    before = cem.analog_cache_metrics()["hits"]
    result = cem.retrieve_analogs(state, event_id="current", as_of=T2)
    again = cem.retrieve_analogs(state, event_id="current", as_of=T2)
    assert result == again
    assert cem.analog_cache_metrics()["hits"] == before + 1
    by_origin = result["outcomeStatisticsByOrigin"]
    assert by_origin["FORWARD_LIVE"][0]["median"] == -3.0
    assert by_origin["HISTORICAL_REPLAY"][0]["median"] == -7.0


def test_learning_counts_one_independent_episode_not_email_volume(tmp_path):
    first = build_event()
    second = build_event(news(event_id="nie-hormuz", event_type="HORMUZ",
                              processed=T1, received="2026-08-05T02:59:00Z"),
                         known=T1, episode={"episodeId": first["episodeId"],
                                            "linked": True,
                                            "relatedEventId": first["eventId"]})
    _, state = ledger_state(tmp_path, first, second)
    observations = cem.learning_observations(state)
    assert len(observations) == 1
    assert observations[0]["episodeId"] == first["episodeId"]


def test_prediction_linkage_refs_are_bounded_and_evidence_only(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    refs = cem.active_evidence_refs(state)
    assert refs[0] == "causal-event:" + first["eventId"]
    assert refs[1].startswith("causal-hypothesis:")
    assert len(refs) <= 8
    replay = build_event(news(event_id="replay-active"), origin="HISTORICAL_REPLAY")
    _, isolated = ledger_state(tmp_path / "isolated", replay)
    assert cem.active_evidence_refs(isolated) == []


def test_missed_event_and_false_alert_reviews_append_without_rewrite(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    missed = cem.build_review(
        event=event, review_type="MISSED_MATERIAL_EVENT", finding_at=T2,
        reason_codes=["INFO_CLASSIFICATION_TOO_LOW"], policy_change_warranted=True,
        regression_fixture_ref="fixture:missed-iran")
    false = cem.build_review(
        event=event, review_type="FALSE_ALERT_REVIEW", finding_at=T2,
        reason_codes=["NO_INTERMEDIATE_CONFIRMATION"], policy_change_warranted=False)
    assert missed["historyMutated"] is False and false["historyMutated"] is False
    assert missed["policyInfluence"] is False and false["policyInfluence"] is False
    _, reviewed = ledger_state(tmp_path / "reviewed", first, missed, false)
    metrics = cem.event_intelligence_metrics(reviewed)
    assert metrics["missedMaterialEventReviews"] == 1
    assert metrics["falseAlertReviews"] == 1
    assert metrics["predictionLedgerOutcomeEffect"] == "NOT_YET_MEASURED"


def test_owner_portfolio_private_fields_are_rejected():
    first = build_event()
    private = copy.deepcopy(first)
    private["ownerPortfolio"] = {"quantity": 100, "costBasis": 900}
    with pytest.raises(ValueError, match="privacy"):
        cem.validate_event_revision(private)


def test_analog_retrieval_cost_is_bounded(tmp_path):
    payloads = []
    for idx in range(160):
        day = (idx % 27) + 1
        month = 1 + (idx // 27)
        known = f"2026-{month:02d}-{day:02d}T02:34:00Z"
        payloads.append(_analog_event(
            f"event-{idx}", known, {"ratesRegime": "HIGH"},
            episode_id=f"episode-{idx}"))
    current = _analog_event("current", T2, {"ratesRegime": "HIGH"})
    _, state = ledger_state(tmp_path, *payloads, current)
    started = time.perf_counter()
    result = cem.retrieve_analogs(state, event_id="current", as_of=T2)
    elapsed = time.perf_counter() - started
    assert result["sampleSize"] == cem.MAX_ANALOG_RESULTS
    assert elapsed < 0.5


# ━━━ v13.5.22 — symmetric INVALIDATED automation (external review item D) ━━━

T3 = "2026-08-22T03:00:00Z"     # 4 days after T2 — beyond the 3-day streak floor


def _all_contradicting_evidence(at):
    return [
        {"variable": "oil_price", "relation": "CONTRADICTING",
         "observedDirection": "DOWN", "expectedDirection": "UP",
         "knownAt": at, "sourceRef": "truth:wti", "noteCode": "MARKET_OBSERVATION"},
        {"variable": "long_end_yields", "relation": "CONTRADICTING",
         "observedDirection": "DOWN", "expectedDirection": "UP",
         "knownAt": at, "sourceRef": "truth:dgs30", "noteCode": "MARKET_OBSERVATION"},
    ]


def _weakened_event(tmp_path):
    first = build_event()
    _, state = ledger_state(tmp_path, first)
    event = cem.event_view(state["events"][first["eventId"]])
    hypothesis = event["causalHypotheses"][0]
    weakened = cem.build_assessment(
        event=event, hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T2,
        evidence=_all_contradicting_evidence(T2),
        attribution_mode="ATTRIBUTION_UNCERTAIN", code_identity=SHA)
    assert weakened["status"] == "WEAKENED"
    path, state = ledger_state(tmp_path, first, weakened)
    event = cem.event_view(state["events"][first["eventId"]])
    return {**event, "assessments":
            state["events"][first["eventId"]]["assessments"]}, hypothesis


def test_sustained_contradiction_reaches_invalidated(tmp_path):
    """WEAKENED for >= 3 days + still fully contradicted → the streak note is
    emitted and the assessment lands on INVALIDATED. The negative side of the
    memory is reachable from production evidence — confirmation bias closed."""
    event, hypothesis = _weakened_event(tmp_path)
    evidence = _all_contradicting_evidence(T3)
    note = cem.sustained_contradiction_note(
        event, hypothesis["hypothesisId"], evidence, T3)
    assert note is not None
    assert note["noteCode"] == cem.CONTRADICTION_STREAK_CRITERION
    assessment = cem.build_assessment(
        event=event, hypothesis_id=hypothesis["hypothesisId"], evaluated_at=T3,
        evidence=evidence + [note],
        attribution_mode="ATTRIBUTION_UNCERTAIN", code_identity=SHA)
    assert assessment["status"] == "INVALIDATED"
    assert assessment["previousStatus"] == "WEAKENED"


def test_streak_note_never_fires_on_mixed_young_or_healthy_states(tmp_path):
    """One adverse read never invalidates: the note refuses mixed evidence,
    contradiction younger than 3 days, and hypotheses not already WEAKENED."""
    event, hypothesis = _weakened_event(tmp_path)
    # Mixed evidence (any support) → None.
    mixed = _all_contradicting_evidence(T3) + [{
        "variable": "long_duration_growth", "relation": "SUPPORTING",
        "observedDirection": "DOWN", "expectedDirection": "DOWN",
        "knownAt": T3, "sourceRef": "truth:qqq", "noteCode": "MARKET_OBSERVATION"}]
    assert cem.sustained_contradiction_note(
        event, hypothesis["hypothesisId"], mixed, T3) is None
    # Only one contradicting variable → None.
    assert cem.sustained_contradiction_note(
        event, hypothesis["hypothesisId"],
        _all_contradicting_evidence(T3)[:1], T3) is None
    # Same-day contradiction (streak too young) → None.
    assert cem.sustained_contradiction_note(
        event, hypothesis["hypothesisId"],
        _all_contradicting_evidence(T2), T2) is None
    # A hypothesis that is not WEAKENED (no standing assessments) → None.
    assert cem.sustained_contradiction_note(
        {"assessments": []}, hypothesis["hypothesisId"],
        _all_contradicting_evidence(T3), T3) is None
