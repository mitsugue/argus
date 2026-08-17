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


def rehash_observation(row):
    material = copy.deepcopy(row)
    material.pop("observationId", None)
    row["observationId"] = "mdo-" + truth._sha(material)[:32]
    return row


def rehash_snapshot(row):
    material = copy.deepcopy(row)
    material.pop("snapshotId", None)
    material.pop("digest", None)
    row["digest"] = truth._sha(material)
    row["snapshotId"] = "mds-" + row["digest"][:32]
    return row


def rehash_pit_proof(row):
    material = copy.deepcopy(row)
    material.pop("proofDigest", None)
    row["proofDigest"] = truth._sha(material)
    return row


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

    def test_complete_requires_the_semantic_core_for_every_fact_type(self):
        cases = (
            ("QUOTE", {"price": 100.0}, {"volume": 1.0}, "JPY"),
            ("INDEX_PROXY", {"price": 100.0}, {"volume": 1.0}, "JPY"),
            ("RATE", {"rate": 4.25}, {"change": 0.1}, None),
            ("NAV", {"nav": 100.0}, {"changePct": 1.0}, "JPY"),
            ("OHLCV_BAR", {
                "open": 99.0, "high": 101.0, "low": 98.0,
                "close": 100.0, "volume": 1_000.0,
            }, {"close": 100.0}, "JPY"),
        )
        for fact_type, complete_values, false_complete, currency in cases:
            valid = observation(
                fact_type=fact_type, values=complete_values,
                currency=currency)
            self.assertTrue(
                truth.validate_observation(valid)[0], fact_type)
            with self.assertRaisesRegex(
                    ValueError, "complete_observation_missing_required_values"):
                observation(
                    fact_type=fact_type, values=false_complete,
                    currency=currency)

    def test_rehashed_complete_cannot_omit_any_required_fact_value(self):
        cases = (
            ("QUOTE", {"price": 100.0, "volume": 1.0}, ("price",), "JPY"),
            ("INDEX_PROXY", {"price": 100.0, "volume": 1.0},
             ("price",), "JPY"),
            ("RATE", {"rate": 4.25, "change": 0.1}, ("rate",), None),
            ("NAV", {"nav": 100.0, "changePct": 1.0}, ("nav",), "JPY"),
            ("OHLCV_BAR", {
                "open": 99.0, "high": 101.0, "low": 98.0,
                "close": 100.0, "volume": 1_000.0,
                "adjustedClose": 100.0,
            }, ("open", "high", "low", "close", "volume"), "JPY"),
        )
        for fact_type, values, required_fields, currency in cases:
            canonical = observation(
                fact_type=fact_type, values=values, currency=currency)
            for required in required_fields:
                hostile = copy.deepcopy(canonical)
                hostile["values"].pop(required)
                self.assertFalse(truth.validate_observation(
                    rehash_observation(hostile))[0],
                    f"{fact_type}:{required}")

    def test_partial_and_missing_shapes_must_declare_core_absence(self):
        with self.assertRaisesRegex(
                ValueError, "partial_observation_undeclared_required_missing"):
            observation(
                values={"volume": 1.0}, completeness="PARTIAL",
                missing_fields=("previousClose",))
        with self.assertRaisesRegex(
                ValueError, "missing_observation_requires_declared_core_absence"):
            truth.build_observation(
                instrument_id="JP:7203:EQUITY", symbol="7203", market="JP",
                asset_type="EQUITY", fact_type="QUOTE", values={},
                provider="moomoo", adapter="fixture.moomoo.v1",
                source_ref="missing-core", observed_at=None,
                received_at="2026-08-14T01:00:01Z",
                known_at="2026-08-14T01:00:02Z", freshness="UNAVAILABLE",
                completeness="MISSING", currency="JPY", missing_fields=())

        missing = truth.build_observation(
            instrument_id="JP:7203:EQUITY", symbol="7203", market="JP",
            asset_type="EQUITY", fact_type="QUOTE", values={},
            provider="moomoo", adapter="fixture.moomoo.v1",
            source_ref="missing-price", observed_at=None,
            received_at="2026-08-14T01:00:01Z",
            known_at="2026-08-14T01:00:02Z", freshness="UNAVAILABLE",
            completeness="MISSING", currency="JPY", missing_fields=("price",))
        missing["values"] = []
        self.assertFalse(truth.validate_observation(
            rehash_observation(missing))[0])

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

    def test_rehashed_unknown_fields_never_become_schema(self):
        mutations = []
        top = observation()
        top["providerPayload"] = {"admin": True}
        mutations.append(top)
        nested = observation()
        nested["instrument"]["venueSecret"] = "unknown"
        mutations.append(nested)
        source = observation()
        source["source"]["rawPayload"] = "unknown"
        mutations.append(source)
        session = observation()
        session["session"]["browserSaysOpen"] = True
        mutations.append(session)
        values = observation()
        values["values"]["arbitrarySignal"] = 999
        mutations.append(values)

        for row in mutations:
            self.assertFalse(truth.validate_observation(
                rehash_observation(row))[0])

    def test_rehashed_string_coercion_shapes_fail_closed(self):
        mutations = []

        numeric_symbol = observation()
        numeric_symbol["instrument"]["symbol"] = 7203
        mutations.append(numeric_symbol)

        numeric_instrument_id = observation()
        numeric_instrument_id["instrument"]["instrumentId"] = 7203
        mutations.append(numeric_instrument_id)

        object_market = observation()
        object_market["instrument"]["market"] = {"code": "JP"}
        mutations.append(object_market)

        numeric_asset_type = observation()
        numeric_asset_type["instrument"]["assetType"] = 1
        mutations.append(numeric_asset_type)

        numeric_adapter = observation()
        numeric_adapter["source"]["adapter"] = 123
        mutations.append(numeric_adapter)

        numeric_source_ref = observation()
        numeric_source_ref["source"]["sourceRef"] = 123
        mutations.append(numeric_source_ref)

        object_source_ref = observation()
        object_source_ref["source"]["sourceRef"] = {"request": "fixture"}
        mutations.append(object_source_ref)

        object_provider = observation()
        object_provider["source"]["provider"] = {"name": "moomoo"}
        # This is the exact pre-fix coercion result of str(dict) normalization.
        object_provider["source"]["providerKey"] = "name_moomoo"
        mutations.append(object_provider)

        numeric_provider = observation()
        numeric_provider["source"]["provider"] = 123
        numeric_provider["source"]["providerKey"] = "123"
        mutations.append(numeric_provider)

        numeric_provider_key = observation()
        numeric_provider_key["source"]["providerKey"] = 123
        mutations.append(numeric_provider_key)

        for row in mutations:
            self.assertFalse(truth.validate_observation(
                rehash_observation(row))[0])

    def test_rehashed_quality_enums_must_be_exact_canonical_strings(self):
        for field, malformed in (
                ("completeness", "COMPLETE "),
                ("freshness", "FRESH "),
                ("completeness", " complete"),
                ("freshness", "fresh")):
            row = observation()
            row[field] = malformed
            self.assertFalse(truth.validate_observation(
                rehash_observation(row))[0])

        missing = observation(
            values={}, missing_fields=("price",), observed_at=None,
            freshness="UNAVAILABLE", completeness="MISSING",
            fresh_until=None)
        missing["completeness"] = "MISSING "
        missing["freshness"] = "UNAVAILABLE "
        rehash_observation(missing)
        self.assertFalse(truth.validate_observation(missing)[0])
        with self.assertRaisesRegex(ValueError, "invalid_quality_types"):
            truth.select_truth(
                [missing], instrument_id="JP:7203:EQUITY", market="JP",
                fact_type="QUOTE", as_of=AS_OF,
                expected_currency="JPY")

    def test_rehashed_offset_timestamps_cannot_invert_provider_recency(self):
        newer = observation(
            price=200, observed_at="2026-08-16T01:00:00Z",
            received_at="2026-08-16T01:00:01Z",
            known_at="2026-08-16T01:00:02Z",
            fresh_until="2026-08-16T01:05:00Z")
        older = observation(
            price=100, observed_at="2026-08-16T00:00:00Z",
            received_at="2026-08-16T00:00:01Z",
            known_at="2026-08-16T00:00:02Z",
            fresh_until="2026-08-16T00:05:00Z")
        newer["observedAt"] = "2026-08-15T21:00:00-04:00"
        older["observedAt"] = "2026-08-16T09:00:00+09:00"
        rehash_observation(newer)
        rehash_observation(older)
        self.assertEqual(
            (False, "noncanonical_observation_time"),
            truth.validate_observation(newer))
        self.assertEqual(
            (False, "noncanonical_observation_time"),
            truth.validate_observation(older))
        with self.assertRaisesRegex(ValueError,
                                    "noncanonical_observation_time"):
            truth.select_truth(
                [newer, older], instrument_id="JP:7203:EQUITY",
                market="JP", fact_type="QUOTE",
                as_of="2026-08-16T01:01:00Z",
                expected_currency="JPY")
        with self.assertRaisesRegex(ValueError,
                                    "noncanonical_observation_time"):
            truth.build_decision_snapshot(
                [newer, older], requests=[{
                    "instrumentId": "JP:7203:EQUITY", "market": "JP",
                    "factType": "QUOTE", "currency": "JPY",
                    "required": True}],
                decision_at="2026-08-16T01:01:00Z",
                generated_at="2026-08-16T01:01:01Z",
                build_identity="a" * 40)

    def test_rehashed_fact_values_require_finite_numbers_not_json_scalars(self):
        for invalid in ("100.0", True, {"raw": 100.0}, [100.0]):
            row = observation()
            row["values"]["price"] = invalid
            self.assertFalse(truth.validate_observation(
                rehash_observation(row))[0], repr(invalid))

        valid = observation(values={"price": 100, "volume": 0.0})
        self.assertTrue(truth.validate_observation(valid)[0])

    def test_currency_is_null_or_canonical_string_for_every_fact(self):
        rate = observation(
            provider="fred", market="FX", fact_type="RATE",
            instrument_id="FX:US10Y:RATE", symbol="US10Y", currency=None,
            values={"rate": 4.25})
        self.assertTrue(truth.validate_observation(rate)[0])
        for invalid in (392, {"code": "USD"}, ["USD"]):
            damaged = copy.deepcopy(rate)
            damaged["instrument"]["currency"] = invalid
            self.assertFalse(truth.validate_observation(
                rehash_observation(damaged))[0], repr(invalid))

    def test_rehashed_session_boolean_lookalikes_are_not_booleans(self):
        hostile = (
            ("isTradingDay", 1), ("providerConflict", 0),
            ("market", {"code": "JP"}), ("session", 1),
            ("marketDate", 20260814), ("calendarVersion", ["v1"]),
            ("officialCalendar", {"name": "JPX_TSE"}),
            ("providerStatus", 1), ("providerRole", ["auxiliary_only"]),
        )
        for field, invalid in hostile:
            row = observation()
            row["session"][field] = invalid
            self.assertFalse(truth.validate_observation(
                rehash_observation(row))[0])

    def test_builder_rejects_wrong_identifier_and_value_types(self):
        common = {
            "instrument_id": "JP:7203:EQUITY", "symbol": "7203",
            "market": "JP", "asset_type": "EQUITY", "fact_type": "QUOTE",
            "values": {"price": 100.0}, "provider": "moomoo",
            "adapter": "fixture.moomoo.v1", "source_ref": "fixture:1",
            "observed_at": "2026-08-14T01:00:00Z",
            "received_at": "2026-08-14T01:00:01Z",
            "known_at": "2026-08-14T01:00:02Z", "freshness": "FRESH",
            "completeness": "COMPLETE",
            "fresh_until": "2026-08-14T01:05:00Z", "currency": "JPY",
        }
        hostile = (
            ("instrument_id", 7203), ("symbol", 7203),
            ("provider", {"name": "moomoo"}), ("adapter", 123),
            ("source_ref", {"request": 1}), ("currency", 392),
            ("values", {"price": "100.0"}),
        )
        for field, invalid in hostile:
            candidate = dict(common)
            candidate[field] = invalid
            with self.assertRaises((TypeError, ValueError), msg=field):
                truth.build_observation(**candidate)

    def test_provenance_is_the_only_typed_bounded_extension(self):
        row = observation()
        self.assertEqual(truth.PROVENANCE_SCHEMA_VERSION,
                         row["provenance"]["schemaVersion"])
        self.assertEqual("credential-free",
                         row["provenance"]["attributes"]["fixture"])

        nested = copy.deepcopy(row)
        nested["provenance"]["attributes"]["arbitrary"] = {"object": True}
        material = copy.deepcopy(nested)
        material.pop("observationId")
        nested["observationId"] = "mdo-" + truth._sha(material)[:32]
        self.assertFalse(truth.validate_observation(nested)[0])

        wrong_type = copy.deepcopy(row)
        wrong_type["provenance"]["attributes"] = "not-a-map"
        material = copy.deepcopy(wrong_type)
        material.pop("observationId")
        wrong_type["observationId"] = "mdo-" + truth._sha(material)[:32]
        self.assertFalse(truth.validate_observation(wrong_type)[0])

        with self.assertRaisesRegex(ValueError, "provenance_too_large"):
            truth.build_observation(
                instrument_id="JP:7203:EQUITY", symbol="7203", market="JP",
                asset_type="EQUITY", fact_type="QUOTE", values={"price": 100},
                provider="moomoo", adapter="fixture.moomoo.v1", source_ref="large",
                observed_at="2026-08-14T01:00:00Z",
                received_at="2026-08-14T01:00:01Z",
                known_at="2026-08-14T01:00:02Z", freshness="FRESH",
                completeness="COMPLETE", fresh_until="2026-08-14T01:05:00Z",
                currency="JPY", provenance={"metadata": ["x" * 256] * 16})


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

    def test_cross_market_instrument_id_cannot_enter_point_or_history_truth(self):
        hostile = observation(
            "moomoo", market="US", instrument_id="JP:7203:EQUITY",
            symbol="7203", currency="JPY")
        selected = truth.select_truth(
            [hostile], instrument_id="JP:7203:EQUITY", market="jp",
            fact_type="quote", as_of=AS_OF, expected_currency="JPY")
        self.assertIsNone(selected["selected"])
        self.assertEqual(0, selected["candidateCount"])
        self.assertEqual([], selected["candidates"])

        history = truth.select_history_as_of(
            [hostile], instrument_id="JP:7203:EQUITY", market="jp",
            fact_type="quote", as_of=AS_OF, expected_currency="JPY")
        self.assertEqual([], history)

    def test_expected_currency_never_coerces_falsy_json_to_no_constraint(self):
        row = observation()
        for invalid in (0, False, [], {}):
            with self.assertRaises(ValueError, msg=repr(invalid)):
                truth.select_truth(
                    [row], instrument_id="JP:7203:EQUITY", market="JP",
                    fact_type="QUOTE", as_of=AS_OF,
                    expected_currency=invalid)
            with self.assertRaises(ValueError, msg=repr(invalid)):
                truth.select_history_as_of(
                    [row], instrument_id="JP:7203:EQUITY", market="JP",
                    fact_type="QUOTE", as_of=AS_OF,
                    expected_currency=invalid)

        unconstrained = truth.select_truth(
            [row], instrument_id="JP:7203:EQUITY", market="JP",
            fact_type="QUOTE", as_of=AS_OF, expected_currency=None)
        constrained = truth.select_truth(
            [row], instrument_id="JP:7203:EQUITY", market="JP",
            fact_type="QUOTE", as_of=AS_OF, expected_currency="jpy")
        self.assertIsNotNone(unconstrained["selected"])
        self.assertEqual("JPY", constrained["expectedCurrency"])

    def test_point_and_history_selection_controls_are_exact_and_bounded(self):
        row = observation()

        def point(**controls):
            return truth.select_truth(
                [row], instrument_id="JP:7203:EQUITY", market="JP",
                fact_type="QUOTE", as_of=AS_OF, **controls)

        def history(**controls):
            return truth.select_history_as_of(
                [row], instrument_id="JP:7203:EQUITY", market="JP",
                fact_type="QUOTE", as_of=AS_OF, **controls)

        class IntLookalike(int):
            pass

        class FloatLookalike(float):
            pass

        for select in (point, history):
            for invalid in (
                    False, True, "1", 1.0, None, [], {}, IntLookalike(1),
                    -1, truth.MAX_ALTERNATES + 1):
                with self.assertRaisesRegex(
                        ValueError, "invalid_max_alternates",
                        msg=f"{select.__name__}:{invalid!r}"):
                    select(max_alternates=invalid)

            for invalid in (
                    False, True, "0.001", None, [], {},
                    FloatLookalike(0.001), float("nan"), float("inf"),
                    float("-inf"), -0.001, 1.001):
                with self.assertRaisesRegex(
                        ValueError, "invalid_relative_tolerance",
                        msg=f"{select.__name__}:{invalid!r}"):
                    select(relative_tolerance=invalid)

            zero = select(max_alternates=0, relative_tolerance=0)
            selected = zero if select is point else zero[0]
            self.assertEqual([], selected["alternates"])
            self.assertEqual(0,
                             selected["disagreement"]["relativeTolerance"])
            select(max_alternates=truth.MAX_ALTERNATES,
                   relative_tolerance=1.0)

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
                    "inputObservationIds": ["mdo-" + "f" * 32], "summary": {},
                }])

    def test_derived_evidence_cannot_bind_unrequested_visible_observation(self):
        requested = observation(
            "twelvedata", market="US", instrument_id="US:AAPL:EQUITY",
            symbol="AAPL", currency="USD")
        unrelated = observation(
            "twelvedata", market="US", instrument_id="US:MSFT:EQUITY",
            symbol="MSFT", currency="USD")
        request = [{"instrumentId": "US:AAPL:EQUITY", "market": "US",
                    "factType": "QUOTE", "currency": "USD"}]
        hostile = [{
            "evidenceId": "evidence.unrelated", "kind": "indicator",
            "knownAt": AS_OF, "methodVersion": "method.v1",
            "inputObservationIds": [unrelated["observationId"]],
            "summary": {},
        }]
        with self.assertRaisesRegex(ValueError,
                                    "evidence_input_not_visible"):
            truth.build_decision_snapshot(
                [requested, unrelated], requests=request,
                decision_at=AS_OF,
                generated_at="2026-08-14T01:00:04Z",
                build_identity="a" * 40, derived_evidence=hostile)
        valid = copy.deepcopy(hostile)
        valid[0]["inputObservationIds"] = [requested["observationId"]]
        snapshot = truth.build_decision_snapshot(
            [requested, unrelated], requests=request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z",
            build_identity="a" * 40, derived_evidence=valid)
        self.assertEqual((True, "ok"),
                         truth.verify_decision_snapshot(snapshot))

    def test_derived_evidence_inputs_and_summary_are_exact_json_types(self):
        row = observation()
        request = [{"instrumentId": "JP:7203:EQUITY", "market": "JP",
                    "factType": "QUOTE"}]
        base = {
            "evidenceId": "evidence.strict", "kind": "indicator",
            "knownAt": AS_OF, "methodVersion": "method.v1",
            "inputObservationIds": [row["observationId"]], "summary": {},
        }

        class StringLookalike:
            def __str__(self):
                return row["observationId"]

        for invalid_inputs in (
                [StringLookalike()], (row["observationId"],)):
            hostile = copy.deepcopy(base)
            hostile["inputObservationIds"] = invalid_inputs
            with self.assertRaisesRegex(ValueError,
                                        "invalid_evidence_inputs"):
                truth.build_decision_snapshot(
                    [row], requests=request, decision_at=AS_OF,
                    generated_at="2026-08-14T01:00:04Z",
                    build_identity="a" * 40,
                    derived_evidence=[hostile])
        hostile = copy.deepcopy(base)
        hostile["summary"] = False
        with self.assertRaisesRegex(ValueError,
                                    "invalid_derived_evidence_summary"):
            truth.build_decision_snapshot(
                [row], requests=request, decision_at=AS_OF,
                generated_at="2026-08-14T01:00:04Z",
                build_identity="a" * 40,
                derived_evidence=[hostile])

    def test_snapshot_verifier_rejects_equivalent_noncanonical_times(self):
        row = observation()
        snapshot = truth.build_decision_snapshot(
            [row], requests=[{
                "instrumentId": "JP:7203:EQUITY", "market": "JP",
                "factType": "QUOTE"}], decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z",
            build_identity="a" * 40)
        for field, offset_value in (
                ("decisionAt", "2026-08-14T10:00:03+09:00"),
                ("generatedAt", "2026-08-14T10:00:04+09:00")):
            forged = copy.deepcopy(snapshot)
            forged[field] = offset_value
            if field == "decisionAt":
                forged["selections"][0]["asOf"] = offset_value
            self.assertEqual(
                (False, "noncanonical_snapshot_time"),
                truth.verify_decision_snapshot(rehash_snapshot(forged)))

    def test_build_identity_is_an_exact_deployed_lowercase_sha_string(self):
        row = observation()
        request = [{
            "instrumentId": "JP:7203:EQUITY", "market": "JP",
            "factType": "QUOTE",
        }]

        class StringCoercible:
            def __str__(self):
                return "a" * 40

        class ShaString(str):
            pass

        hostile_builder_values = (
            int("1" * 40), False, True, StringCoercible(),
            ShaString("a" * 40), "A" * 40,
        )
        for invalid in hostile_builder_values:
            with self.assertRaisesRegex(
                    ValueError, "invalid_build_identity", msg=repr(invalid)):
                truth.build_decision_snapshot(
                    [row], requests=request, decision_at=AS_OF,
                    generated_at="2026-08-14T01:00:04Z",
                    build_identity=invalid)

        canonical = truth.build_decision_snapshot(
            [row], requests=request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z",
            build_identity="a" * 40)
        for invalid in (int("1" * 40), False, True,
                        ShaString("a" * 40), "A" * 40):
            hostile = copy.deepcopy(canonical)
            hostile["buildIdentity"] = invalid
            self.assertFalse(truth.verify_decision_snapshot(
                rehash_snapshot(hostile))[0], repr(invalid))

    def test_snapshot_build_and_verify_reject_cross_market_authority(self):
        hostile = observation(
            "moomoo", market="US", instrument_id="JP:7203:EQUITY",
            symbol="7203", currency="JPY")
        jp_request = [{
            "instrumentId": "JP:7203:EQUITY", "market": "JP",
            "factType": "QUOTE", "currency": "JPY", "required": True,
        }]
        snapshot = truth.build_decision_snapshot(
            [hostile], requests=jp_request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40)
        selection = snapshot["selections"][0]
        self.assertIsNone(selection["selected"])
        self.assertEqual(0, selection["candidateCount"])
        self.assertEqual(truth.MISSING,
                         snapshot["qualitySummary"]["completeness"])
        self.assertTrue(truth.verify_decision_snapshot(snapshot)[0])

        # Start from a valid US snapshot, then claim its US observation is a JP
        # selection and rehash every outer digest.  Digests authenticate bytes;
        # they cannot grant cross-market authority.
        forged = truth.build_decision_snapshot(
            [hostile], requests=[{
                "instrumentId": "JP:7203:EQUITY", "market": "US",
                "factType": "QUOTE", "currency": "JPY", "required": True,
            }], decision_at=AS_OF, generated_at="2026-08-14T01:00:04Z",
            build_identity="a" * 40)
        forged["selections"][0]["market"] = "JP"
        material = copy.deepcopy(forged)
        material.pop("snapshotId")
        material.pop("digest")
        forged["digest"] = truth._sha(material)
        forged["snapshotId"] = "mds-" + forged["digest"][:32]
        self.assertEqual(
            (False, "invalid_snapshot_candidate_observation"),
            truth.verify_decision_snapshot(forged))

    def test_snapshot_request_scalar_types_are_strict_at_build_and_verify(self):
        row = observation()
        base_request = {
            "instrumentId": "JP:7203:EQUITY", "market": "JP",
            "factType": "QUOTE", "currency": "JPY", "required": True,
        }
        hostile_build = []
        for invalid in (0, False, [], {}):
            hostile_build.append({**base_request, "currency": invalid})
        for field in ("market", "factType"):
            for invalid in (0, False, [], {}):
                hostile_build.append({**base_request, field: invalid})
        for invalid in (0, 1, "true", None, [], {}):
            hostile_build.append({**base_request, "required": invalid})
        for request in hostile_build:
            with self.assertRaises((TypeError, ValueError), msg=repr(request)):
                truth.build_decision_snapshot(
                    [row], requests=[request], decision_at=AS_OF,
                    generated_at="2026-08-14T01:00:04Z",
                    build_identity="a" * 40)

        # Missing/None currency are the two intentional unconstrained forms;
        # required=False is an actual boolean and remains valid.
        for request in (
                {"instrumentId": "JP:7203:EQUITY", "market": "JP",
                 "factType": "QUOTE", "required": False},
                {"instrumentId": "JP:7203:EQUITY", "market": "JP",
                 "factType": "QUOTE", "currency": None,
                 "required": False}):
            valid = truth.build_decision_snapshot(
                [row], requests=[request], decision_at=AS_OF,
                generated_at="2026-08-14T01:00:04Z",
                build_identity="a" * 40)
            self.assertTrue(truth.verify_decision_snapshot(valid)[0])

        canonical = truth.build_decision_snapshot(
            [row], requests=[base_request], decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40)
        hostile_verify = []
        for invalid in (0, False, [], {}):
            damaged = copy.deepcopy(canonical)
            damaged["selections"][0]["expectedCurrency"] = invalid
            hostile_verify.append(damaged)
        for field in ("market", "factType"):
            for invalid in (0, False, [], {}):
                damaged = copy.deepcopy(canonical)
                damaged["selections"][0][field] = invalid
                hostile_verify.append(damaged)
        for invalid in (0, 1, "true", None, [], {}):
            damaged = copy.deepcopy(canonical)
            damaged["selections"][0]["required"] = invalid
            hostile_verify.append(damaged)
        for damaged in hostile_verify:
            self.assertFalse(truth.verify_decision_snapshot(
                rehash_snapshot(damaged))[0])

    def test_rehashed_snapshot_bool_int_equality_never_preserves_validity(self):
        row = observation()
        request = [{
            "instrumentId": "JP:7203:EQUITY", "market": "JP",
            "factType": "QUOTE", "currency": "JPY", "required": True,
        }]
        canonical = truth.build_decision_snapshot(
            [row], requests=request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40)
        mutations = []

        candidate_count = copy.deepcopy(canonical)
        candidate_count["selections"][0]["candidateCount"] = True
        mutations.append(candidate_count)

        authority_rank = copy.deepcopy(canonical)
        authority_rank["selections"][0]["candidates"][0][
            "authorityRank"] = False
        mutations.append(authority_rank)

        required_count = copy.deepcopy(canonical)
        required_count["qualitySummary"]["requiredCount"] = True
        mutations.append(required_count)

        selection_count = copy.deepcopy(canonical)
        selection_count["bounds"]["selectionCount"] = True
        mutations.append(selection_count)

        for damaged in mutations:
            self.assertFalse(truth.verify_decision_snapshot(
                rehash_snapshot(damaged))[0])

    def test_rehashed_snapshot_unknown_top_and_nested_fields_are_rejected(self):
        row = observation()
        request = [{"instrumentId": "JP:7203:EQUITY", "market": "JP",
                    "factType": "QUOTE"}]
        snapshot = truth.build_decision_snapshot(
            [row], requests=request, decision_at=AS_OF,
            generated_at="2026-08-14T01:00:04Z", build_identity="a" * 40)

        def rehash(value):
            material = copy.deepcopy(value)
            material.pop("snapshotId", None)
            material.pop("digest", None)
            value["digest"] = truth._sha(material)
            value["snapshotId"] = "mds-" + value["digest"][:32]
            return value

        top = copy.deepcopy(snapshot)
        top["rawProviderPayload"] = {"trusted": False}
        self.assertEqual((False, "snapshot_schema_not_closed"),
                         truth.verify_decision_snapshot(rehash(top)))
        nested = copy.deepcopy(snapshot)
        nested["qualitySummary"]["unknownCount"] = 1
        self.assertFalse(truth.verify_decision_snapshot(rehash(nested))[0])


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

    def test_adapter_result_schema_rejects_unknown_top_and_nested_fields(self):
        spec = truth.AdapterSpec(
            adapter_id="fixture.closed.v1", provider="fixture_candidate",
            markets=("JP",), fact_types=("QUOTE",), schema_version="fixture-v1")

        unknown_top = truth.ProviderAdapterRegistry()
        unknown_top.register(spec, lambda _payload, _context: {
            "observations": [], "errors": [], "trustedBecauseHashed": True,
        })
        with self.assertRaisesRegex(ValueError, "invalid_adapter_outcome"):
            unknown_top.adapt("fixture.closed.v1", {}, {})

        unknown_nested = truth.ProviderAdapterRegistry()
        unknown_nested.register(spec, lambda _payload, _context: {
            "observations": [],
            "errors": [{"code": "provider_error", "retryable": False,
                        "rawProviderBody": {"arbitrary": True}}],
        })
        with self.assertRaisesRegex(ValueError, "invalid_adapter_error"):
            unknown_nested.adapt("fixture.closed.v1", {}, {})

    def test_adapter_outcome_collections_are_actual_lists(self):
        spec = truth.AdapterSpec(
            adapter_id="fixture.list-types.v1", provider="fixture_candidate",
            markets=("JP",), fact_types=("QUOTE",),
            schema_version="fixture-v1")
        for observations, errors in (((), []), ([], ())):
            registry = truth.ProviderAdapterRegistry()
            registry.register(spec, lambda _payload, _context,
                              o=observations, e=errors: {
                                  "observations": o, "errors": e})
            with self.assertRaisesRegex(
                    ValueError, "invalid_adapter_outcome_types"):
                registry.adapt("fixture.list-types.v1", {}, {})

    def test_adapter_error_identifiers_are_strings_without_coercion(self):
        spec = truth.AdapterSpec(
            adapter_id="fixture.error-types.v1", provider="fixture_candidate",
            markets=("JP",), fact_types=("QUOTE",),
            schema_version="fixture-v1")
        hostile_errors = (
            {"code": 404, "retryable": False},
            {"code": "provider_error", "instrumentId": 7203,
             "retryable": False},
            {"code": {"raw": "provider_error"}, "retryable": False},
        )
        for error in hostile_errors:
            registry = truth.ProviderAdapterRegistry()
            registry.register(spec, lambda _payload, _context, row=error: {
                "observations": [], "errors": [row]})
            with self.assertRaises(ValueError):
                registry.adapt("fixture.error-types.v1", {}, {})

        valid = truth.ProviderAdapterRegistry()
        valid.register(spec, lambda _payload, _context: {
            "observations": [],
            "errors": [{"code": "provider_error", "instrumentId": None,
                        "retryable": False}],
        })
        self.assertEqual(None, valid.adapt(
            "fixture.error-types.v1", {}, {})["errors"][0]["instrumentId"])


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

    def test_rehashed_pit_proof_is_closed_typed_and_count_reconciled(self):
        included, proof = truth.point_in_time_rows([{
            "date": "2026-08-13", "knownAt": "2026-08-13T12:00:00Z",
            "open": 100, "high": 101, "low": 99, "close": 100,
        }], AS_OF)
        self.assertEqual(1, len(included))
        self.assertEqual({"knownAt": 1, "availableFrom": 0},
                         proof["knowledgeTimeFields"])
        self.assertEqual((True, "ok"),
                         truth.verify_point_in_time_proof(proof))

        authority_extension = copy.deepcopy(proof)
        authority_extension["authorityGranted"] = True
        self.assertEqual(
            (False, "pit_proof_schema_not_closed"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(authority_extension)))

        bool_knowledge_count = copy.deepcopy(proof)
        bool_knowledge_count["knowledgeTimeFields"]["knownAt"] = True
        self.assertEqual(
            (False, "invalid_knowledge_time_counts"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(bool_knowledge_count)))

        numeric_dataset_digest = copy.deepcopy(proof)
        numeric_dataset_digest["admittedDatasetDigest"] = int("1" * 64)
        self.assertEqual(
            (False, "dataset_digest_missing"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(numeric_dataset_digest)))

        mismatched_counts = copy.deepcopy(proof)
        mismatched_counts["inputCount"] += 1
        self.assertEqual(
            (False, "invalid_filter_counts"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(mismatched_counts)))

        unknown_knowledge_field = copy.deepcopy(proof)
        unknown_knowledge_field["knowledgeTimeFields"][
            "providerReceivedAt"] = 0
        self.assertEqual(
            (False, "invalid_knowledge_time_counts"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(unknown_knowledge_field)))

        mismatched_knowledge_total = copy.deepcopy(proof)
        mismatched_knowledge_total["knowledgeTimeFields"]["knownAt"] = 0
        self.assertEqual(
            (False, "invalid_knowledge_time_counts"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(mismatched_knowledge_total)))

        missing_visible_maxima = copy.deepcopy(proof)
        missing_visible_maxima["maxKnownAt"] = None
        missing_visible_maxima["maxObservedAt"] = None
        self.assertEqual(
            (False, "missing_visible_time_maxima"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(missing_visible_maxima)))

        superseded_only = copy.deepcopy(proof)
        superseded_only["includedCount"] = 0
        superseded_only["supersededRevisionCount"] = 1
        self.assertEqual(
            (False, "invalid_revision_counts"),
            truth.verify_point_in_time_proof(
                rehash_pit_proof(superseded_only)))

    def test_empty_pit_proof_has_no_visible_time_maxima(self):
        included, proof = truth.point_in_time_rows([], AS_OF)
        self.assertEqual([], included)
        self.assertIsNone(proof["maxKnownAt"])
        self.assertIsNone(proof["maxObservedAt"])
        self.assertEqual((True, "ok"),
                         truth.verify_point_in_time_proof(proof))
        forged = copy.deepcopy(proof)
        forged["maxKnownAt"] = "2026-08-13T00:00:00Z"
        forged["maxObservedAt"] = "2026-08-13T00:00:00Z"
        self.assertEqual(
            (False, "unexpected_visible_time_maxima"),
            truth.verify_point_in_time_proof(rehash_pit_proof(forged)))

    def test_pit_proof_rejects_equivalent_noncanonical_times(self):
        _, proof = truth.point_in_time_rows([{
            "date": "2026-08-13", "knownAt": "2026-08-13T12:00:00Z",
            "open": 100, "high": 101, "low": 99, "close": 100,
        }], AS_OF)
        for field, offset_value in (
                ("cutoff", "2026-08-14T10:00:03+09:00"),
                ("maxKnownAt", "2026-08-13T21:00:00+09:00"),
                ("maxObservedAt", "2026-08-13T21:00:00+09:00")):
            forged = copy.deepcopy(proof)
            forged[field] = offset_value
            self.assertEqual(
                (False, "noncanonical_pit_time"),
                truth.verify_point_in_time_proof(
                    rehash_pit_proof(forged)))

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
