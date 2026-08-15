import copy
import unittest

import argus_market_data_truth as truth


AS_OF = "2026-08-14T01:00:03Z"


def observation(provider="moomoo", *, price=100.0, market="JP",
                fact_type="QUOTE", instrument_id="JP:7203:EQUITY",
                symbol="7203", currency="JPY", revision=0,
                observed_at="2026-08-14T01:00:00Z",
                received_at="2026-08-14T01:00:01Z",
                known_at="2026-08-14T01:00:02Z",
                fresh_until="2026-08-14T01:05:00Z",
                freshness="FRESH", completeness="COMPLETE",
                values=None, missing_fields=(), provider_session=None):
    return truth.build_observation(
        instrument_id=instrument_id,
        symbol=symbol,
        market=market,
        asset_type=("EQUITY" if market in {"JP", "US"} else
                    "FX_PAIR" if market == "FX" else "CRYPTO"),
        fact_type=fact_type,
        values={"price": price} if values is None else values,
        provider=provider,
        adapter=f"fixture.{truth.provider_key(provider)}.v1",
        source_ref=f"fixture:{provider}:{revision}",
        observed_at=observed_at,
        received_at=received_at,
        known_at=known_at,
        freshness=freshness,
        completeness=completeness,
        fresh_until=fresh_until,
        currency=currency,
        missing_fields=missing_fields,
        revision=revision,
        provider_session=provider_session,
        provenance={"fixture": "credential-free"},
    )


class ObservationContractTests(unittest.TestCase):
    def test_observation_is_deterministic_and_session_authority_is_official(self):
        first = observation(provider_session="CLOSED")
        second = observation(provider_session="CLOSED")
        self.assertEqual(first, second)
        self.assertTrue(truth.validate_observation(first)[0])
        self.assertEqual("MORNING_SESSION", first["session"]["session"])
        self.assertTrue(first["session"]["providerConflict"])
        self.assertEqual("auxiliary_only", first["session"]["providerRole"])

    def test_future_source_and_inverted_knowledge_timestamps_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "source_timestamp_future"):
            observation(observed_at="2026-08-14T01:00:02Z",
                        received_at="2026-08-14T01:00:01Z")
        with self.assertRaisesRegex(ValueError, "known_before_received"):
            observation(received_at="2026-08-14T01:00:02Z",
                        known_at="2026-08-14T01:00:01Z")
        with self.assertRaisesRegex(ValueError, "timezone_required"):
            observation(known_at="2026-08-14T01:00:02")

    def test_freshness_and_completeness_are_independent(self):
        partial = observation(
            freshness="live", completeness="PARTIAL",
            values={"price": 100.0, "volume": None},
            missing_fields=("volume",))
        self.assertEqual(truth.FRESH, partial["freshness"])
        self.assertEqual(truth.PARTIAL, partial["completeness"])
        self.assertEqual(truth.STALE, truth.freshness_at(
            partial, "2026-08-14T01:06:00Z"))
        missing = truth.build_observation(
            instrument_id="JP:7203:EQUITY", symbol="7203", market="JP",
            asset_type="EQUITY", fact_type="QUOTE", values={},
            provider="moomoo", adapter="fixture.moomoo.v1", source_ref="miss",
            observed_at=None, received_at="2026-08-14T01:00:01Z",
            known_at="2026-08-14T01:00:02Z", freshness="missing",
            completeness="MISSING", currency="JPY", missing_fields=("price",))
        self.assertEqual(truth.UNAVAILABLE, missing["freshness"])

    def test_digest_detects_mutation(self):
        row = observation()
        row["values"]["price"] = 101
        self.assertEqual((False, "observation_digest_mismatch"),
                         truth.validate_observation(row))

    def test_rehashed_future_source_timestamp_still_fails_semantics(self):
        row = observation()
        row["observedAt"] = "2026-08-14T02:00:00Z"
        material = copy.deepcopy(row)
        material.pop("observationId")
        row["observationId"] = "mdo-" + truth._sha(material)[:32]
        self.assertEqual((False, "invalid_observation_time_order"),
                         truth.validate_observation(row))


class SelectionTests(unittest.TestCase):
    def test_repo_precedence_selected_alternate_and_disagreement_are_preserved(self):
        selected = observation("moomoo", price=100)
        alternate = observation("jquants", price=101)
        result = truth.select_truth(
            [alternate, selected], instrument_id="JP:7203:EQUITY",
            market="JP", fact_type="QUOTE", as_of=AS_OF,
            expected_currency="JPY")
        self.assertEqual(selected["observationId"], result["selectedObservationId"])
        self.assertEqual("jquants", result["alternates"][0]["observation"]
                         ["source"]["providerKey"])
        self.assertEqual("PRESENT", result["disagreement"]["status"])
        self.assertEqual(truth.AUTHORITY_POLICY_ID, result["policyId"])
        self.assertEqual(truth.PIT_POLICY_ID, result["pitPolicyId"])

    def test_fresh_lower_priority_beats_stale_higher_priority(self):
        stale = observation("moomoo", price=100,
                            fresh_until="2026-08-14T01:00:02Z")
        delayed = observation("jquants", price=101, freshness="DELAYED")
        result = truth.select_truth(
            [stale, delayed], instrument_id="JP:7203:EQUITY",
            market="JP", fact_type="QUOTE", as_of=AS_OF)
        self.assertEqual("jquants", result["selected"]["observation"]
                         ["source"]["providerKey"])
        self.assertEqual("DELAYED", result["freshness"])

    def test_repository_priorities_cover_us_fx_and_crypto(self):
        cases = [
            ("US", "US:SPY:ETF", "SPY", "USD", "moomoo", "twelvedata"),
            ("FX", "FX:USDJPY:FX_PAIR", "USDJPY", "JPY", "yahoo", "fred"),
            ("CRYPTO", "CRYPTO:BTC:CRYPTO", "BTC", "USD", "coingecko", "coinbase"),
        ]
        for market, instrument_id, symbol, currency, first, second in cases:
            rows = [
                observation(second, price=101, market=market,
                            instrument_id=instrument_id, symbol=symbol,
                            currency=currency),
                observation(first, price=100, market=market,
                            instrument_id=instrument_id, symbol=symbol,
                            currency=currency),
            ]
            result = truth.select_truth(
                rows, instrument_id=instrument_id, market=market,
                fact_type="QUOTE", as_of=AS_OF, expected_currency=currency)
            self.assertEqual(first, result["selected"]["observation"]
                             ["source"]["providerKey"])

    def test_future_known_revision_is_invisible_until_cutoff(self):
        original = observation("moomoo", price=100, revision=0)
        revision = observation(
            "moomoo", price=102, revision=1,
            received_at="2026-08-14T01:02:59Z",
            known_at="2026-08-14T01:03:00Z")
        before = truth.select_truth(
            [revision, original], instrument_id="JP:7203:EQUITY",
            market="JP", fact_type="QUOTE", as_of=AS_OF)
        after = truth.select_truth(
            [revision, original], instrument_id="JP:7203:EQUITY",
            market="JP", fact_type="QUOTE", as_of="2026-08-14T01:03:01Z")
        self.assertEqual(100, before["selected"]["observation"]["values"]["price"])
        self.assertEqual(102, after["selected"]["observation"]["values"]["price"])

    def test_future_observed_fact_is_invisible_even_if_forged_known_earlier(self):
        # Builder rejects this shape before selection, proving a future bar can
        # never be normalized as an age-zero/live observation.
        with self.assertRaisesRegex(ValueError, "source_timestamp_future"):
            observation(observed_at="2026-08-14T02:00:00Z")

    def test_conflicting_same_provider_revision_fails_closed(self):
        first = observation("moomoo", price=100)
        conflicting = observation("moomoo", price=101)
        with self.assertRaisesRegex(ValueError, "conflicting_revision"):
            truth.observations_as_of([first, conflicting], AS_OF)

    def test_unknown_registered_provider_never_gains_authority(self):
        unknown = observation("fixture_candidate", price=99)
        result = truth.select_truth(
            [unknown], instrument_id="JP:7203:EQUITY", market="JP",
            fact_type="QUOTE", as_of=AS_OF)
        self.assertIsNone(result["selected"])
        self.assertEqual("provider_not_authoritative",
                         result["candidates"][0]["rejectionReason"])


class SnapshotTests(unittest.TestCase):
    def test_snapshot_binds_candidates_quality_policy_and_digest(self):
        rows = [observation("moomoo", price=100),
                observation("jquants", price=101)]
        request = [{"instrumentId": "JP:7203:EQUITY", "market": "JP",
                    "factType": "QUOTE", "currency": "JPY", "required": True}]
        first = truth.build_decision_snapshot(
            rows, requests=request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40)
        second = truth.build_decision_snapshot(
            rows, requests=request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40)
        self.assertEqual(first, second)
        self.assertEqual(truth.COMPLETE, first["qualitySummary"]["completeness"])
        self.assertEqual(2, first["bounds"]["candidateObservationCount"])
        self.assertTrue(truth.verify_decision_snapshot(first)[0])
        damaged = copy.deepcopy(first)
        damaged["selections"][0]["freshness"] = truth.STALE
        self.assertFalse(truth.verify_decision_snapshot(damaged)[0])

        forged = copy.deepcopy(first)
        selection = forged["selections"][0]
        selection["selected"] = copy.deepcopy(selection["alternates"][0])
        selection["selectedObservationId"] = selection["selected"][
            "observation"]["observationId"]
        selection["freshness"] = selection["selected"]["qualityAtAsOf"][
            "freshness"]
        selection["completeness"] = selection["selected"][
            "qualityAtAsOf"]["completeness"]
        material = copy.deepcopy(forged)
        material.pop("snapshotId")
        material.pop("digest")
        forged["digest"] = truth._sha(material)
        forged["snapshotId"] = "mds-" + forged["digest"][:32]
        self.assertEqual((False, "snapshot_selection_mismatch"),
                         truth.verify_decision_snapshot(forged))

    def test_snapshot_rejects_future_cutoff_and_unseen_derived_inputs(self):
        row = observation()
        request = [{"instrumentId": "JP:7203:EQUITY", "market": "JP",
                    "factType": "QUOTE"}]
        with self.assertRaisesRegex(ValueError, "future_decision_at"):
            truth.build_decision_snapshot(
                [row], requests=request, decision_at="2026-08-14T02:00:00Z",
                generated_at="2026-08-14T01:00:00Z", build_identity="a" * 40)
        with self.assertRaisesRegex(ValueError, "invalid_build_identity"):
            truth.build_decision_snapshot(
                [row], requests=request, decision_at=AS_OF,
                generated_at="2026-08-14T01:00:04Z",
                build_identity="sha-placeholder")
        with self.assertRaisesRegex(ValueError, "evidence_input_not_visible"):
            truth.build_decision_snapshot(
                [row], requests=request, decision_at=AS_OF,
                generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40,
                derived_evidence=[{
                    "evidenceId": "evidence.1", "kind": "indicator",
                    "knownAt": AS_OF, "methodVersion": "method.v1",
                    "inputObservationIds": ["mdo-not-visible"], "summary": {},
                }])


class AdapterContractTests(unittest.TestCase):
    def test_credential_free_fixture_maps_fields_session_and_errors(self):
        registry = truth.ProviderAdapterRegistry()

        def normalize(payload, context):
            return {
                "observations": [truth.build_observation(
                    instrument_id=context["instrumentId"], symbol=payload["ticker"],
                    market="JP", asset_type="EQUITY", fact_type="QUOTE",
                    values={"price": payload["last"]}, provider="fixture_candidate",
                    adapter="fixture.jp.quote.v1", source_ref=payload["requestId"],
                    observed_at=payload["exchangeTime"],
                    received_at=context["receivedAt"], known_at=context["knownAt"],
                    freshness=payload["quality"], completeness="COMPLETE",
                    fresh_until=context["freshUntil"], currency=payload["currency"],
                    provider_session=payload["providerSession"], revision=0,
                    provenance={"payloadSchema": "fixture-v1"})],
                "errors": [{"code": "fixture_partial_batch",
                            "instrumentId": "JP:9999:EQUITY", "retryable": True}],
            }

        registry.register(truth.AdapterSpec(
            adapter_id="fixture.jp.quote.v1", provider="fixture_candidate",
            markets=("JP",), fact_types=("QUOTE",), schema_version="fixture-v1"),
            normalize)
        description = registry.describe()[0]
        self.assertFalse(description["registrationGrantsAuthority"])
        self.assertFalse(description["scopes"][0]["authority"])
        outcome = registry.adapt("fixture.jp.quote.v1", {
            "ticker": "7203", "last": 100.5, "currency": "JPY",
            "exchangeTime": "2026-08-14T01:00:00Z", "quality": "live",
            "providerSession": "CLOSED", "requestId": "fixture-request-1",
        }, {
            "instrumentId": "JP:7203:EQUITY",
            "receivedAt": "2026-08-14T01:00:01Z",
            "knownAt": "2026-08-14T01:00:02Z",
            "freshUntil": "2026-08-14T01:05:00Z",
        })
        row = outcome["observations"][0]
        self.assertEqual("2026-08-14T01:00:00Z", row["observedAt"])
        self.assertEqual("2026-08-14T01:00:02Z", row["knownAt"])
        self.assertEqual("MORNING_SESSION", row["session"]["session"])
        self.assertEqual("fixture_partial_batch", outcome["errors"][0]["code"])
        selection = truth.select_truth(
            outcome["observations"], instrument_id="JP:7203:EQUITY",
            market="JP", fact_type="QUOTE", as_of=AS_OF)
        self.assertIsNone(selection["selected"])

    def test_adapter_outcomes_are_bounded_and_retryability_is_typed(self):
        registry = truth.ProviderAdapterRegistry()
        spec = truth.AdapterSpec(
            adapter_id="fixture.bounds.v1", provider="fixture_candidate",
            markets=("JP",), fact_types=("QUOTE",), schema_version="fixture-v1")
        registry.register(spec, lambda _payload, _context: {
            "observations": [],
            "errors": [{"code": "bad_retryable", "retryable": "false"}],
        })
        with self.assertRaisesRegex(ValueError, "invalid_adapter_retryable"):
            registry.adapt("fixture.bounds.v1", {}, {})

        too_many = truth.ProviderAdapterRegistry()
        too_many.register(spec, lambda _payload, _context: {
            "observations": [],
            "errors": [{"code": f"error_{index}", "retryable": False}
                       for index in range(truth.MAX_ADAPTER_ERRORS + 1)],
        })
        with self.assertRaisesRegex(ValueError, "adapter_outcome_unbounded"):
            too_many.adapt("fixture.bounds.v1", {}, {})


class LegacyPointInTimeTests(unittest.TestCase):
    def test_future_unknown_and_malformed_rows_are_excluded_with_proof(self):
        rows = [
            {"date": "2026-08-13", "availableFrom": "2026-08-13",
             "open": 100, "high": 101, "low": 99, "close": 100},
            {"date": "2026-08-14", "knownAt": "2026-08-14T02:00:00Z",
             "open": 100, "high": 101, "low": 99, "close": 100},
            {"date": "2026-08-12", "open": 100, "high": 101,
             "low": 99, "close": 100},
            {"date": "bad", "knownAt": "also-bad"},
        ]
        included, proof = truth.point_in_time_rows(
            rows, "2026-08-14T01:00:00Z")
        self.assertEqual(["2026-08-13"], [row["date"] for row in included])
        self.assertEqual(1, proof["excludedFutureCount"])
        self.assertEqual(1, proof["excludedUnknownKnowledgeTimeCount"])
        self.assertEqual(1, proof["excludedMalformedCount"])
        self.assertFalse(proof["futureRowsAdmitted"])
        self.assertEqual("PASS", proof["status"])
        self.assertEqual((True, "ok"), truth.verify_point_in_time_proof(proof))

    def test_revision_without_exact_known_at_is_never_backdated(self):
        rows = [{
            "date": "2026-08-13", "availableFrom": "2026-08-13",
            "revision": 1, "open": 100, "high": 101, "low": 99,
            "close": 100,
        }]
        included, proof = truth.point_in_time_rows(
            rows, "2026-08-14T23:59:59.999999Z")
        self.assertEqual([], included)
        self.assertEqual(1, proof["excludedUnknownKnowledgeTimeCount"])
        self.assertEqual((True, "ok"), truth.verify_point_in_time_proof(proof))
        damaged = copy.deepcopy(proof)
        damaged["futureRowsAdmitted"] = True
        self.assertFalse(truth.verify_point_in_time_proof(damaged)[0])

    def test_global_input_bound_is_enforced_before_processing(self):
        row = {"date": "2026-08-13", "availableFrom": "2026-08-13"}
        with self.assertRaisesRegex(ValueError, "too_many_rows"):
            truth.point_in_time_rows(
                [row] * (truth.MAX_INPUT_OBSERVATIONS + 1), AS_OF)


if __name__ == "__main__":
    unittest.main()
