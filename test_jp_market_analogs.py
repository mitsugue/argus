import copy
import math
import unittest
import weakref
from datetime import date, timedelta
from unittest.mock import patch

from jp_market_analogs import (AnalogPolicy, FEATURE_DEFINITIONS, INSTRUMENT,
                               build_episode, reference_path, reference_paths, select_episodes)

POLICY = AnalogPolicy(lookback_sessions=5, minimum_separation_sessions=6)
DAYS = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(120)]


def bars(start, end, scale=1):
    return [{"instrumentId": INSTRUMENT, "field": "OHLCV_BAR", "date": DAYS[i],
             "availableFrom": DAYS[i] + "T07:00:00Z", "close": scale * (100 + i % 6),
             "sourceRef": "test:daily-index", "revision": 0} for i in range(start, end)]


def fact(field, value, index, unit, **extra):
    return {"instrumentId": INSTRUMENT, "field": field, "date": DAYS[index],
            "availableFrom": DAYS[index] + "T08:00:00Z", "value": value,
            "unit": unit, "revision": 0, **extra}


def episode(index, *, full=False, changes=None, price_rows=None):
    states = [fact(key, 1, index, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()] if full else []
    conditions = [fact("vix_cross", 1, index - 3, "DIRECTION"),
                  fact("price_recovery", 1, index - 1, "DIRECTION")] if full else []
    reactions = [fact("policy_reaction", 1, index, "PERCENT", eventId="test-event-" + str(index),
                      eventType="MONETARY_POLICY", reactionWindowSessions=1)] if full else []
    args = {"cutoff": DAYS[index] + "T23:00:00Z", "bars": price_rows if price_rows is not None else bars(0, index + 1),
            "state_rows": states, "condition_rows": conditions, "reaction_rows": reactions, "policy": POLICY}
    args.update(changes or {})
    return build_episode(**args)


class AnalogSelectionTest(unittest.TestCase):
    def test_past_outcome_changes_do_not_change_selection(self):
        before = bars(0, 18)
        after = copy.deepcopy(before)
        for row in after[12:]:
            row["close"] *= 7
        first = episode(11, full=True, price_rows=before)
        changed = episode(11, full=True, price_rows=after)
        self.assertEqual(first, changed)
        current = episode(83, full=True)
        result = select_episodes(current, [first], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result, select_episodes(current, [changed], session_dates=DAYS, policy=POLICY))
        original_path = reference_path(first, later_bars=before, display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        changed_path = reference_path(changed, later_bars=after, display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        self.assertNotEqual(original_path["subsequentReference"], changed_path["subsequentReference"])
        self.assertFalse(result["outcomesUsedForSelection"])

    def test_partial_price_comparison_is_not_full_market_analog(self):
        result = select_episodes(episode(83), [episode(11), episode(23)], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "PARTIAL_COMPARISONS_ONLY")
        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(result["selected"][0]["similarityReasons"], ["priceShape"])
        self.assertIn("materialReaction", result["selected"][0]["missingGroups"])
        self.assertIsNone(result["predictiveProbability"])
        self.assertFalse(result["actionAuthority"])

    def test_full_comparison_reports_independent_components_and_differences(self):
        result = select_episodes(episode(83, full=True), [episode(11, full=True)], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "MARKET_ANALOGS_AVAILABLE")
        row = result["selected"][0]
        self.assertEqual(set(row["componentDistances"]), {"priceShape", "marketState", "conditionOrder", "materialReaction"})
        self.assertEqual(row["missingFeatures"], [])
        self.assertFalse(row["historicalVintageVerified"])
        self.assertEqual(result["validationStatus"], "UNVALIDATED")

    def test_sequence_order_changes_distance_but_same_day_is_simultaneous(self):
        current, past = episode(83, full=True), episode(11, full=True)
        reversed_order = episode(11, full=True, changes={"condition_rows": [
            fact("price_recovery", 1, 8, "DIRECTION"), fact("vix_cross", 1, 10, "DIRECTION")]})
        left = select_episodes(current, [past], session_dates=DAYS, policy=POLICY)
        right = select_episodes(current, [reversed_order], session_dates=DAYS, policy=POLICY)
        self.assertLess(left["selected"][0]["componentDistances"]["conditionOrder"],
                        right["selected"][0]["componentDistances"]["conditionOrder"])
        simultaneous = [fact("price_recovery", 1, 10, "DIRECTION"), fact("vix_cross", 1, 10, "DIRECTION")]
        a = episode(11, full=True, changes={"condition_rows": simultaneous})
        b = episode(11, full=True, changes={"condition_rows": simultaneous[::-1]})
        self.assertEqual(a, b)

    def test_future_revision_and_wrong_instrument_do_not_enter_features(self):
        base = episode(11, full=True)
        future = fact("vix.level", 500, 11, "INDEX_POINTS", knownAt=DAYS[20] + "T00:00:00Z", revision=1)
        states = [fact(key, 1, 11, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()]
        wrong = fact("vix.level", 999, 11, "INDEX_POINTS", instrumentId="1321")
        changed = episode(11, full=True, changes={"state_rows": states + [future, wrong]})
        self.assertEqual(base, changed)

    def test_nearby_episodes_are_not_independent_samples(self):
        result = select_episodes(episode(83), [episode(11), episode(12), episode(23)], session_dates=DAYS, policy=POLICY)
        anchors = [row["anchorDate"] for row in result["selected"]]
        self.assertIn(DAYS[11], anchors)
        self.assertNotIn(DAYS[12], anchors)
        self.assertIn(DAYS[23], anchors)

    def test_year_audit_explains_search_without_changing_selection(self):
        result = select_episodes(episode(83), [episode(11), episode(12), episode(23)],
                                 session_dates=DAYS, policy=POLICY)
        year = DAYS[11][:4]
        audit = result["yearAudit"][year]
        self.assertEqual(audit["candidateCount"], 3)
        self.assertEqual(audit["admittedCount"], 2)
        self.assertEqual(audit["selectedCount"], 2)
        self.assertEqual(audit["closest"]["status"], "SELECTED")
        self.assertEqual(audit["closest"]["rank"], 1)

    def test_year_audit_records_distance_rejection(self):
        extreme = bars(0, 12)
        extreme[-6]["close"] = 10000
        result = select_episodes(episode(83), [episode(11, price_rows=extreme)],
                                 session_dates=DAYS, policy=POLICY)
        audit = result["yearAudit"][DAYS[11][:4]]
        self.assertEqual(audit["admittedCount"], 0)
        self.assertEqual(audit["closest"]["status"], "DISTANCE_ABOVE_THRESHOLD")
        self.assertIsNone(audit["closest"]["rank"])

    def test_no_strong_analog_and_stale_snapshot_are_explicit(self):
        extreme = bars(0, 12)
        extreme[-6]["close"] = 10000
        result = select_episodes(episode(83), [episode(11, price_rows=extreme)], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "NO_STRONG_ANALOG")
        late = episode(11, changes={"cutoff": DAYS[30] + "T23:00:00Z"})
        self.assertEqual(select_episodes(episode(83), [late], session_dates=DAYS, policy=POLICY)["selected"], [])

    def test_tampered_snapshot_and_missing_exchange_session_rejected(self):
        tampered = episode(11)
        tampered["window"][-1]["close"] = 500
        with self.assertRaisesRegex(ValueError, "episode_content_changed"):
            select_episodes(episode(83), [tampered], session_dates=DAYS, policy=POLICY)
        incomplete = episode(11, price_rows=[r for r in bars(0, 12) if r["date"] != DAYS[8]])
        self.assertEqual(select_episodes(episode(83), [incomplete], session_dates=DAYS, policy=POLICY)["selected"], [])

    def test_unit_mismatch_is_missing_not_silently_scaled(self):
        current = episode(83, full=True)
        states = [fact(key, 1, 11, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()]
        states[0]["unit"] = "JPY"
        past = episode(11, full=True, changes={"state_rows": states})
        result = select_episodes(current, [past], session_dates=DAYS, policy=POLICY)
        self.assertEqual(result["status"], "PARTIAL_COMPARISONS_ONLY")
        self.assertIn("credit.ratio", result["selected"][0]["missingFeatures"])

    def test_existing_ohlcv_shape_without_explicit_field_is_supported(self):
        values = bars(0, 12)
        for row in values:
            row.pop("field")
            row.update(open=row["close"], high=row["close"], low=row["close"], volume=0)
        self.assertEqual(episode(11, price_rows=values)["status"], "AVAILABLE")

    def test_stale_daily_feature_is_excluded_and_missing_price_is_not_bridged(self):
        current = episode(83, full=True)
        states = [fact(key, 1, 11, definition[0]) for key, definition in FEATURE_DEFINITIONS.items()]
        next(row for row in states if row["field"] == "vix.level")["date"] = DAYS[0]
        past = episode(11, full=True, changes={"state_rows": states})
        result = select_episodes(current, [past], session_dates=DAYS, policy=POLICY)
        self.assertIn("vix.level", result["selected"][0]["missingFeatures"])
        incomplete = bars(0, 18)
        incomplete = [row for row in incomplete if row["date"] != DAYS[14]]
        path = reference_path(episode(11), later_bars=incomplete, display_cutoff=DAYS[18] + "T00:00:00Z",
                              session_dates=DAYS, policy=POLICY)
        self.assertEqual(path["status"], "PARTIAL")
        self.assertEqual(path["subsequentReference"][-1]["date"], DAYS[13])

    def test_actual_past_and_subsequent_paths_share_anchor_without_becoming_forecast(self):
        past = episode(11)
        path = reference_path(past, later_bars=bars(0, 18), display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        self.assertEqual(path["status"], "AVAILABLE")
        self.assertEqual(path["comparison"][-1]["value"], 100)
        self.assertEqual(path["subsequentReference"][0]["value"], 100)
        self.assertFalse(path["subsequentReferenceIsPrediction"])
        partial = reference_path(past, later_bars=bars(0, 14), display_cutoff=DAYS[18] + "T00:00:00Z", session_dates=DAYS, policy=POLICY)
        self.assertEqual(partial["status"], "PARTIAL")


class DistanceArithmeticParityTest(unittest.TestCase):
    def test_scaled_weighted_components_keep_exact_arithmetic_and_inputs(self):
        import copy
        import math
        from dataclasses import asdict
        from jp_market_analogs import component_distances
        policy = AnalogPolicy(state_scales=(("credit.ratio", 2.0),),
            component_weights=(("priceShape", 1.0), ("marketState", 2.0),
                               ("conditionOrder", 0.0)))
        current = {"states": {"credit.ratio": {"value": 6}}, "reactions": {}}
        past = {"states": {"credit.ratio": {"value": 2}}, "reactions": {}}
        before = copy.deepcopy((current, past, asdict(policy)))
        result = component_distances(current, past, policy,
            current_shape=[100, 102], candidate_shape=[100, 100],
            current_order=[("rise",)], candidate_order=[("rise",)])
        self.assertEqual(result["distances"], {"priceShape": math.sqrt(2) / 5,
            "marketState": 2.0, "conditionOrder": 0.0, "materialReaction": None})
        self.assertEqual(result["distance"], (math.sqrt(2) / 5 + 4) / 3)
        self.assertEqual(before, (current, past, asdict(policy)))

    def test_custom_policy_lookups_remain_authoritative(self):
        from jp_market_analogs import component_distances, weighted_distance
        class CustomPolicy(AnalogPolicy):
            def scale_for(self, key):
                return 4.0
            def weight_for(self, key):
                return 3.0 if key == "marketState" else 1.0
        policy = CustomPolicy(component_weights=(("marketState", 2.0),))
        result = component_distances(
            {"states": {"credit.ratio": {"value": 6}}, "reactions": {}},
            {"states": {"credit.ratio": {"value": 2}}, "reactions": {}}, policy,
            current_shape=[100], candidate_shape=[100], current_order=[], candidate_order=[])
        self.assertEqual(result["stateDeltas"], {"credit.ratio": 1.0})
        self.assertEqual(weighted_distance({"priceShape": 0.0, "marketState": 1.0}, policy), 0.75)

    def test_condition_order_still_distinguishes_insertions_and_reversals(self):
        from jp_market_analogs import _edit_distance
        self.assertEqual(_edit_distance([], []), 0.0)
        self.assertEqual(_edit_distance([("up",)], [("up",)]), 0.0)
        self.assertEqual(_edit_distance([("up",)], [("up",), ("down",)]), 0.5)
        self.assertEqual(_edit_distance([("up",), ("down",)], [("down",), ("up",)]), 1.0)


class EpisodeOwnershipTest(unittest.TestCase):
    def test_source_update_after_admission_cannot_change_retained_receipt(self):
        import jp_market_analogs as analogs
        price = bars(0, 84)
        price[-1]['source'] = {'refs': ['admitted']}
        receipt = analogs._receipt
        changed = False

        def after_admission(row):
            nonlocal changed
            if not changed:
                price[-1]['source']['refs'].append('after-admission')
                changed = True
            return receipt(row)

        with patch.object(analogs, '_receipt', side_effect=after_admission):
            result = episode(83, price_rows=price)
        self.assertEqual(price[-1]['source']['refs'], ['admitted', 'after-admission'])
        self.assertEqual(result['window'][-1]['source']['refs'], ['admitted'])

    def test_optimized_read_keeps_default_pit_admission_and_conflict_checks(self):
        import jp_market_engine as engine
        original = fact('vix.level', 20, 60, 'INDEX_POINTS')
        correction = {**original, 'value': 22, 'revision': 1,
                      'knownAt': DAYS[62] + 'T08:00:00Z'}
        rows = [original, correction,
                {**original, 'field': 'future', 'date': DAYS[90]},
                {**original, 'field': 'malformed', 'date': 'not-a-date'},
                {**original, 'field': 'missing-receipt', 'availableFrom': None},
                {**original, 'field': 'missing-revision-receipt', 'revision': 1},
                {**original, 'field': 'not-json', 'value': float('nan')}]
        for day in (61, 62, 90):
            cutoff = DAYS[day] + 'T23:00:00Z'
            with self.subTest(day=day):
                expected, proof = engine.point_in_time_rows(rows, cutoff)
                actual, unused = engine.point_in_time_rows(rows, cutoff,
                    _reuse_immutable_scalars=True, _include_proof=False)
                self.assertEqual(actual, expected)
                self.assertTrue(proof['proofId'])
                self.assertEqual(unused, {})
        conflict = {**original, 'value': 999}
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                with self.assertRaisesRegex(ValueError, 'conflicting_row_revision'):
                    engine.point_in_time_rows([original, correction, conflict],
                        DAYS[90] + 'T23:00:00Z', _reuse_immutable_scalars=optimized,
                        _include_proof=not optimized)

    def test_episode_owns_nested_receipts_and_reaction_identity(self):
        price = bars(0, 84)
        price[-1]['source'] = {'refs': ['price']}
        state = fact('vix.level', 22, 83, 'INDEX_POINTS', source={'refs': ['state']})
        condition = fact('cross', 1, 82, 'DIRECTION', source={'refs': ['condition']})
        reaction = fact('reaction', 1, 83, 'PERCENT', source={'refs': ['reaction']},
                        eventId={'refs': ['event']}, eventType='POLICY', reactionWindowSessions=1)
        args = dict(cutoff=DAYS[83] + 'T23:00:00Z', bars=price, state_rows=[state],
                    condition_rows=[condition], reaction_rows=[reaction], policy=POLICY)
        first = build_episode(**args)
        saved = copy.deepcopy(first)
        for row in (price[-1], state, condition, reaction):
            row['source']['refs'].append('later-source-change')
        reaction['eventId']['refs'].append('later-event-change')
        self.assertEqual(first, saved)
        second = build_episode(**args)
        self.assertNotEqual(second['snapshotId'], first['snapshotId'])
        before = copy.deepcopy(args)
        first['window'][-1]['source']['refs'].append('output-change')
        first['states']['vix.level']['source']['refs'].append('output-change')
        first['conditions'][0]['source']['refs'].append('output-change')
        first['reactions']['POLICY:1']['source']['refs'].append('output-change')
        first['reactions']['POLICY:1']['eventId']['refs'].append('output-change')
        self.assertEqual(args, before)

    def test_newest_invalid_state_does_not_erase_previous_valid_observation(self):
        states = [fact('vix.level', 20, 80, 'INDEX_POINTS'),
                  fact('vix.level', 999, 83, 'WRONG_UNIT')]
        result = episode(83, changes={'state_rows': states})
        self.assertEqual(result['states']['vix.level']['value'], 20)
        self.assertEqual(result['states']['vix.level']['date'], DAYS[80])

    def test_default_pit_returns_owned_rows_and_unchanged_proof(self):
        import jp_market_engine as engine
        row = fact('vix.level', 20, 80, 'INDEX_POINTS', source={'refs': ['original']})
        result, proof = engine.point_in_time_rows([row], DAYS[83] + 'T23:00:00Z')
        row['source']['refs'].append('changed')
        self.assertEqual(result[0]['source'], {'refs': ['original']})
        self.assertEqual(proof['includedCount'], 1)
        self.assertEqual(proof['excludedMalformedCount'], 0)
        self.assertFalse(proof['futureRowsAdmitted'])


class ReferenceBatchTest(unittest.TestCase):
    def invoke(self, episodes=None, rows=None, cutoff=None, horizon=5):
        return reference_paths(episodes if episodes is not None else [episode(11), episode(23)],
            later_bars=rows if rows is not None else bars(0, 84),
            display_cutoff=cutoff or DAYS[83] + "T23:00:00Z", session_dates=DAYS,
            horizon_sessions=horizon, policy=POLICY)

    def test_all_horizons_keep_exact_paths_and_check_full_prices_once(self):
        import jp_market_analogs as analogs
        past, rows = [episode(11), episode(23)], bars(0, 84)
        original = copy.deepcopy((past, rows))
        for horizon in (1, 5, 10, 20):
            with self.subTest(horizon=horizon):
                with patch.object(analogs, 'point_in_time_rows', wraps=analogs.point_in_time_rows) as verify:
                    paths = self.invoke(past, rows, horizon=horizon)
                self.assertEqual(verify.call_count, 1)
                for index, anchor in enumerate((11, 23)):
                    path = paths[index]
                    self.assertEqual(path['snapshotId'], past[index]['snapshotId'])
                    self.assertEqual(path['status'], 'AVAILABLE')
                    self.assertEqual(path['subsequentReference'], [
                        {'offsetSessions': offset, 'date': DAYS[anchor + offset],
                         'value': (100 + (anchor + offset) % 6) / (100 + anchor % 6) * 100}
                        for offset in range(horizon + 1)])
                    self.assertEqual(path, reference_path(past[index], later_bars=rows,
                        display_cutoff=DAYS[83] + 'T23:00:00Z', session_dates=DAYS,
                        horizon_sessions=horizon, policy=POLICY))
        self.assertEqual((past, rows), original)

    def test_later_episode_is_verified_even_after_prices_are_admitted(self):
        past = [episode(11), episode(23)]
        past[1]['window'][-1]['close'] *= 2
        with self.assertRaisesRegex(ValueError, '^episode_content_changed$'):
            self.invoke(past)

    def test_conflicting_prices_outside_selected_paths_still_fail(self):
        rows = bars(0, 84)
        rows.append({**rows[-1], 'close': rows[-1]['close'] * 2})
        with self.assertRaisesRegex(ValueError, '^conflicting_row_revision:'):
            self.invoke(rows=rows)

    def test_future_receipt_and_missing_session_cannot_fill_path(self):
        rows = bars(0, 84)
        rows[13]['availableFrom'] = DAYS[90] + 'T07:00:00Z'
        result = self.invoke(rows=rows)[0]
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual([row['date'] for row in result['subsequentReference']], DAYS[11:13])

    def test_next_batch_admits_correction_only_at_its_new_cutoff(self):
        rows = bars(0, 84)
        rows.append({**rows[13], 'revision': 1, 'close': 777,
                     'knownAt': DAYS[90] + 'T07:00:00Z'})
        before = self.invoke(rows=rows)[0]
        after = self.invoke(rows=rows, cutoff=DAYS[91] + 'T07:00:00Z')[0]
        self.assertEqual(before['subsequentReference'][2]['value'], 101 / 105 * 100)
        self.assertEqual(after['subsequentReference'][2]['value'], 777 / 105 * 100)
        self.assertEqual(before['snapshotId'], after['snapshotId'])

    def test_unavailable_and_empty_batches_do_not_read_prices(self):
        import jp_market_analogs as analogs
        unavailable = build_episode(cutoff=DAYS[1] + 'T23:00:00Z', bars=bars(0, 2), policy=POLICY)
        with patch.object(analogs, 'point_in_time_rows', side_effect=AssertionError('unexpected read')):
            self.assertEqual(self.invoke([]), [])
            self.assertEqual(self.invoke([unavailable]),
                             [{'status': 'UNAVAILABLE', 'comparison': [], 'subsequentReference': []}])

    def test_admitted_scale_rows_are_released_before_candidate_selection(self):
        import jp_market_engine as engine
        import jp_market_analogs as analogs
        from jp_market_price_paths import cached_index_comparison
        admitted = []
        original = engine.point_in_time_rows
        select = analogs.select_episodes

        class ScaleRows(list):
            pass

        def visible(rows, cutoff):
            data, proof = original(rows, cutoff)
            if rows and rows[0].get('field') == 'credit.loss_pct':
                data = ScaleRows(data)
                admitted.append(weakref.ref(data))
            return data, proof

        def selection(*args, **kwargs):
            self.assertEqual(len(admitted), 1)
            self.assertIsNone(admitted[0]())
            return select(*args, **kwargs)

        with patch.object(engine, 'point_in_time_rows', new=visible), \
                patch.object(analogs, 'select_episodes', new=selection):
            result = cached_index_comparison(bars(0, 84), cutoff=DAYS[83] + 'T23:00:00Z',
                session_dates=DAYS, policy=POLICY,
                state_rows=[fact('credit.loss_pct', -1, 60, 'PERCENT')])
        self.assertEqual(result['status'], 'available')


if __name__ == "__main__":
    unittest.main()
