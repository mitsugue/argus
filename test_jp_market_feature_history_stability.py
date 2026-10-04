"""Feature-history stability across restarts and deploys (2026-10-02).

Same formulas and same inputs must not replay ten years after a restart; a
changed formula parameter must. Stamps that only record when a row was
received or calculated after the reuse boundary must not force a replay,
while any change visible to a reused cutoff still does.
"""
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import jp_market_features as features

ROOT = Path(__file__).resolve().parent
PINNED_VERSION = "jp-market-feature-method-v3"
PINNED_FIXTURE_RESULT = "a73614cc7917d199dd243192a8e2614d541e6b54fd8fa11ae94db164b5e10f13"
MODULES = ("jp_market_features.py", "jp_market_engine.py", "jp_market_dynamics.py",
           "jp_market_analogs.py", "jp_market_acquisition.py")


def day(i):
    return date(2026, 1, 1) + timedelta(days=i)


def vix(n, *, last_value=None):
    rows = [{'instrumentId': 'VIX', 'seriesId': 'close', 'date': str(day(i)),
             'availableFrom': str(day(i + 1)) + 'T00:00:00Z', 'value': 20 + (i % 7) * .5,
             'close': 20 + (i % 7) * .5, 'sourceRef': 'fixture:vix'} for i in range(n)]
    if last_value is not None:
        # A session still forming: same row replaced in place with a new
        # receipt; its availability bound stays at the next day.
        received = str(day(n)) + 'T03:00:00Z' if last_value == 'first' else str(day(n)) + 'T05:00:00Z'
        rows[-1] = {**rows[-1], 'value': 30.0 if last_value == 'first' else 31.5,
                    'close': 30.0 if last_value == 'first' else 31.5, 'knownAt': received,
                    'receivedAt': received, 'availabilityBasis': 'PROVISIONAL_SESSION_UPDATE'}
    return rows


def nikkei(n):
    return [{'instrumentId': 'NIKKEI_225_INDEX', 'field': 'close', 'date': str(day(i)),
             'availableFrom': str(day(i)) + 'T07:00:00Z', 'value': 38000 + (i % 11) * 40}
            for i in range(n)]


def sq(now):
    """Rule rows per calculation day plus the published row stamped with `now`."""
    rows = [{'eventId': 'jp-monthly-sq', 'calendarStatus': 'RULE_DERIVED', 'sqDate': '2026-04-10',
             'tradingSessionsUntil': 90 - i, 'date': str(day(i)),
             'calculatedAt': str(day(i)) + 'T00:00:00+09:00', 'knownAt': str(day(i)) + 'T00:00:00+09:00',
             'sourceRef': 'rule:fixture'} for i in range(1, 60)]
    rows.append({'eventId': 'jp-monthly-sq-2026-03', 'calendarStatus': 'VERIFIED', 'sqDate': '2026-03-13',
                 'tradingSessionsUntil': 10, 'calculatedAt': now,
                 'knownAt': '2025-12-01T00:00:00+00:00', 'sourceRef': 'official:fixture'})
    return rows


def cutoffs(n, now):
    return [str(day(i)) + 'T23:59:59Z' for i in range(n)] + [now]


def inputs(now, *, vix_rows=None, n=58):
    return {'price_series': {'vix': vix_rows if vix_rows is not None else vix(n),
                             'nikkei': nikkei(n)},
            'sq_events': sq(now)}


def saved(at, **kw):
    history = features.build_feature_history(cutoffs=at, **kw)
    return {**history, 'status': 'AVAILABLE', 'inputIdentity': 'a' * 64,
            'lastSuccessfulCalculationAt': at[-1]}


def same_values(actual, full):
    for key in ('features', 'conditions', 'firstCutoff', 'lastCutoff', 'cutoffCount',
                'evaluatedCutoffs', 'historicalVintageVerified', 'actionAuthority'):
        assert actual[key] == full[key], key
    assert actual['latest']['features'] == full['latest']['features']


NOW1 = str(day(57)) + 'T03:00:00Z'
NOW2 = str(day(57)) + 'T05:00:00Z'


# --- method identity ---------------------------------------------------------

def _identity_in_subprocess(module_dir):
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(module_dir), str(ROOT)]),
           'PYTHONHASHSEED': '12345'}
    code = ('import jp_market_features as f, json; '
            'print(json.dumps([f.__file__, f.history_method_identity()]))')
    out = subprocess.run([sys.executable, '-c', code], env=env, cwd=str(module_dir),
                         capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _copy_modules(target, edit=None):
    for name in MODULES:
        text = (ROOT / name).read_text(encoding='utf-8')
        text += '\n# deploy without any formula change\n'
        if edit and name in edit:
            old, new = edit[name]
            assert old in text
            text = text.replace(old, new)
        (target / name).write_text(text, encoding='utf-8')


def test_identity_is_the_pinned_version_and_fixture_result():
    """Formula parity, checked separately from the identity value itself.

    If this fails after a change to a feature formula, threshold or window,
    advance FEATURE_HISTORY_METHOD_VERSION and record the new fixture result.
    Never update the digest without advancing the version.
    """
    assert features.FEATURE_HISTORY_METHOD_VERSION == PINNED_VERSION
    assert features.history_method_fingerprint() == PINNED_FIXTURE_RESULT


def test_canonical_fixture_exercises_every_feature_and_condition():
    from jp_market_analogs import FEATURE_DEFINITIONS
    snapshot = features.build_market_features(cutoff='2026-03-09T12:00:00+09:00',
                                              **features._canonical_fixture_inputs())
    assert snapshot['missingFeatures'] == [] and snapshot['staleFeatures'] == []
    assert {row['seriesId'] for row in snapshot['features']} == set(FEATURE_DEFINITIONS)
    assert {row['seriesId'] for row in snapshot['conditions']} == set(features.SIGN_CONDITION_IDS.values())


def test_redeploy_without_formula_change_keeps_identity():
    with tempfile.TemporaryDirectory() as root:
        target = Path(root)
        _copy_modules(target)
        loaded_from, identity = _identity_in_subprocess(target)
        assert Path(loaded_from).resolve().parent == target.resolve()
        assert identity == features.history_method_identity()


@pytest.mark.parametrize('edit', [
    {'jp_market_features.py': ('D04_INDEX_PER_THRESHOLD = 19', 'D04_INDEX_PER_THRESHOLD = 20')},
    {'jp_market_features.py': ('SIGN_CONDITION_LOOKBACK_DAYS = 200', 'SIGN_CONDITION_LOOKBACK_DAYS = 150')},
    {'jp_market_engine.py': ('ARGUS_MACD_BASELINE = (12, 26, 9)', 'ARGUS_MACD_BASELINE = (12, 26, 8)')},
    # A formula edit with no named parameter is caught by the fixture result.
    {'jp_market_features.py': ('emit("vix.change5", vix[-1]["numericValue"] - vix[-6]["numericValue"]',
                               'emit("vix.change5", vix[-1]["numericValue"] - vix[-5]["numericValue"]')},
])
def test_changed_formula_or_parameter_changes_identity(edit):
    with tempfile.TemporaryDirectory() as root:
        target = Path(root)
        _copy_modules(target, edit)
        _, identity = _identity_in_subprocess(target)
        assert identity != features.history_method_identity()


def test_version_advance_changes_identity():
    before = features.history_method_identity()
    with patch.object(features, 'FEATURE_HISTORY_METHOD_VERSION', 'jp-market-feature-method-v4'):
        assert features.history_method_identity() != before


# --- simulated restart -------------------------------------------------------

def test_restart_with_same_formulas_and_inputs_reuses_saved_history():
    at = cutoffs(57, NOW1)
    history = saved(at, **inputs(NOW1, vix_rows=vix(58, last_value='first')))
    method = features.history_method_identity()
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'jp_market_feature_cache.json'
        path.write_text(json.dumps(features.history_cache_envelope(history, method=method)))
        # Restart: fresh module state, identity recomputed from scratch.
        restarted = importlib.reload(features)
        try:
            restored = restarted.load_history_cache(path, method=restarted.history_method_identity(), now=NOW2)
            assert restored == history
            later = inputs(NOW2, vix_rows=vix(58, last_value='second'))
            with patch.object(restarted, 'build_market_features',
                              wraps=restarted.build_market_features) as compute:
                new = restarted.build_feature_history(cutoffs=cutoffs(57, NOW2),
                                                      previous_history=restored, **later)
            assert compute.call_count == 1  # only the replaced intraday endpoint
            assert new['calculationWork'] == {'reusedCutoffs': 57, 'evaluatedCutoffs': 1}
            assert new['reuseDecision']['reason'] == 'unchanged_known_inputs'
            assert new['reuseDecision']['boundedSources'] == ['price_series:vix', 'sq_events']
            same_values(new, restarted.build_feature_history(cutoffs=cutoffs(57, NOW2), **later))
        finally:
            importlib.reload(features)


def test_changed_formula_parameter_rejects_saved_history_and_replays():
    at = cutoffs(57, NOW1)
    history = saved(at, **inputs(NOW1))
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'cache.json'
        path.write_text(json.dumps(features.history_cache_envelope(
            history, method=features.history_method_identity())))
        features.history_method_fingerprint.cache_clear()
        try:
            with patch.object(features, 'D04_INDEX_PER_THRESHOLD', 20):
                changed = features.history_method_identity()
                assert features.load_history_cache(path, method=changed, now=NOW2) is None
                with patch.object(features, 'build_market_features',
                                  wraps=features.build_market_features) as compute:
                    new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=None,
                                                         **inputs(NOW2))
                assert compute.call_count == 58
                assert new['calculationWork'] == {'reusedCutoffs': 0, 'evaluatedCutoffs': 58}
        finally:
            features.history_method_fingerprint.cache_clear()
        # The file on disk is untouched by the rejection.
        assert json.loads(path.read_text())['history'] == history


# --- volatile stamps ---------------------------------------------------------

def test_calculation_and_receipt_stamps_after_the_boundary_do_not_force_replay():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1, vix_rows=vix(58, last_value='first')))
    later = inputs(NOW2, vix_rows=vix(58, last_value='second'))
    new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=old, **later)
    assert new['calculationWork']['reusedCutoffs'] == 57
    same_values(new, features.build_feature_history(cutoffs=cutoffs(57, NOW2), **later))
    # Before 2026-10-02 the exact-prefix rule alone rejected this request.
    legacy = deepcopy(old)
    for source in legacy['sourceManifest'].values():
        source.pop('knownThrough')
    replay = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=legacy, **later)
    assert replay['calculationWork']['reusedCutoffs'] == 0
    assert replay['reuseDecision']['reason'] == 'source_prefix_changed'
    same_values(replay, new)


def test_change_visible_to_a_reused_cutoff_still_replays_everything():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1))
    for mutate in ('value', 'stamp', 'drop', 'sq'):
        later = inputs(NOW2)
        if mutate == 'value':
            later['price_series']['vix'][10]['value'] += 1
        elif mutate == 'stamp':  # a receipt on an already-known row is still compared
            later['price_series']['vix'][10]['receivedAt'] = NOW2
        elif mutate == 'drop':
            del later['price_series']['nikkei'][3]
        else:
            later['sq_events'][5]['tradingSessionsUntil'] += 1
        new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=old, **later)
        assert new['calculationWork']['reusedCutoffs'] == 0, mutate
        same_values(new, features.build_feature_history(cutoffs=cutoffs(57, NOW2), **later))


def test_backdated_correction_without_receipt_is_never_bounded():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1))
    later = inputs(NOW2)
    later['price_series']['vix'].append({**later['price_series']['vix'][4], 'value': 99, 'revision': 1,
                                         'availableFrom': NOW2})
    new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=old, **later)
    assert new['calculationWork']['reusedCutoffs'] == 0


def test_new_session_appends_after_bounded_reuse():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1, vix_rows=vix(58, last_value='first')))
    now3 = str(day(58)) + 'T03:00:00Z'
    later = inputs(now3, n=59)
    new = features.build_feature_history(cutoffs=cutoffs(58, now3), previous_history=old, **later)
    assert new['calculationWork'] == {'reusedCutoffs': 57, 'evaluatedCutoffs': 2}
    same_values(new, features.build_feature_history(cutoffs=cutoffs(58, now3), **later))


def test_known_through_manifest_survives_the_cache_envelope():
    history = saved(cutoffs(57, NOW1), **inputs(NOW1))
    manifest = history['sourceManifest']['sq_events']
    assert set(manifest['knownThrough']) == {cutoffs(57, NOW1)[-2], NOW1}
    doc = features.history_cache_envelope(history, method='b' * 64)
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'cache.json'
        path.write_text(json.dumps(doc))
        assert features.load_history_cache(path, method='b' * 64, now=NOW2) == history


# --- cold sources after a restart -------------------------------------------

def test_cold_source_keeps_verified_history_instead_of_replaying_without_it():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1))
    cold = inputs(NOW2)
    cold['price_series']['vix'] = []
    with patch.object(features, 'build_market_features', side_effect=AssertionError('replay')):
        kept = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=old, **cold)
    assert kept['sourceWarming'] == {'sources': ['price_series:vix'], 'retainedLastCutoff': NOW1}
    assert kept['reuseDecision'] == {'reason': 'source_warming', 'source': 'price_series:vix'}
    for key in ('features', 'conditions', 'latest', 'evaluatedCutoffs', 'sourceManifest', 'lastCutoff'):
        assert kept[key] == old[key]
    assert kept['actionAuthority'] is False and kept['historicalVintageVerified'] is False
    # The scanner stores it as the current history; it remains a valid cache.
    stored = {**kept, 'status': 'AVAILABLE', 'inputIdentity': 'c' * 64, 'lastSuccessfulCalculationAt': NOW2}
    features.history_cache_envelope(stored, method='b' * 64)
    # Once the source is back, only the endpoint is recalculated.
    warm = inputs(NOW2)
    new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=stored, **warm)
    assert new['calculationWork'] == {'reusedCutoffs': 57, 'evaluatedCutoffs': 1}
    same_values(new, features.build_feature_history(cutoffs=cutoffs(57, NOW2), **warm))


def test_short_fallback_counts_as_cold_but_a_rolling_trim_does_not():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1))
    half = inputs(NOW2)
    half['price_series']['vix'] = half['price_series']['vix'][-20:]
    assert features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=old,
                                          **half).get('sourceWarming')
    trimmed = inputs(NOW2)
    trimmed['price_series']['vix'] = trimmed['price_series']['vix'][1:]
    new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=old, **trimmed)
    assert 'sourceWarming' not in new and new['calculationWork']['reusedCutoffs'] == 0


def test_source_absent_beyond_the_bound_is_replayed_without_it():
    old = saved(cutoffs(57, NOW1), **inputs(NOW1))
    late = str(day(57 + 4)) + 'T03:00:00Z'
    cold = inputs(late)
    cold['price_series']['vix'] = []
    new = features.build_feature_history(cutoffs=cutoffs(57, late), previous_history=old, **cold)
    assert 'sourceWarming' not in new
    assert not any(row['seriesId'].startswith('vix.') for row in new['latest']['features'])


# --- provider re-sends and rolling windows ----------------------------------

import sqlite3  # noqa: E402

import jp_market_acquisition as acquisition  # noqa: E402


def topix(first, last, received):
    digest = hashlib.sha256(received.encode()).hexdigest()
    return [{'instrumentId': 'TOPIX_INDEX', 'seriesId': 'close', 'date': str(day(i)),
             'open': 2700 + i, 'high': 2710 + i, 'low': 2690 + i, 'close': 2705 + i,
             'unit': 'INDEX_POINTS', 'availableFrom': str(day(i)) + 'T09:00:00Z',
             'availabilityBasis': 'SCHEDULED_PUBLICATION', 'receivedAt': received,
             'publishedAt': None, 'historicalVintageVerified': False,
             'sourceRef': 'jquants:v2:indices/bars/daily/topix', 'sourceResponseSha256': digest}
            for i in range(first, last)]


def test_resent_observations_keep_first_receipt_and_fixed_origin():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'jp_market_source_history.sqlite3'
        first = acquisition.retain_first_receipts(topix(0, 50, NOW1), path=path, source_id='topix',
                                                  received_at=NOW1)
        assert first == topix(0, 50, NOW1)
        # Later the window moved by one session and every row carries a new
        # receipt and response digest.
        later = str(day(58)) + 'T03:00:00Z'
        again = acquisition.retain_first_receipts(topix(1, 51, later), path=path, source_id='topix',
                                                  received_at=later)
        assert again[:50] == first  # origin and receipts unchanged
        assert again[50] == topix(50, 51, later)[0]
        # Restart with a cold provider cache: the recorded selection returns.
        assert acquisition.retain_first_receipts([], path=path, source_id='topix', received_at=later) == again
        # A changed observation still replaces the selection.
        corrected = topix(1, 51, later)
        corrected[9]['close'] += 1
        changed = acquisition.retain_first_receipts(corrected, path=path, source_id='topix', received_at=later)
        assert changed[10] == corrected[9]
        # Nothing recorded is deleted: 50 + 1 new session + 1 correction.
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM selected_feature_inputs').fetchone()[0] == 52


def test_forming_session_is_returned_but_not_recorded():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'store.sqlite3'
        rows = topix(0, 3, NOW1)
        rows.append({**topix(3, 4, NOW1)[0], 'availableFrom': '2099-01-01T00:00:00Z'})
        out = acquisition.retain_first_receipts(rows, path=path, source_id='topix', received_at=NOW1)
        assert out == rows
        assert acquisition.retain_first_receipts([], path=path, source_id='topix', received_at=NOW1) == rows[:3]


def test_retention_rejects_unknown_source_and_passes_through_without_store():
    with pytest.raises(ValueError):
        acquisition.retain_first_receipts([], path='x', source_id='nikkei', received_at=NOW1)
    rows = topix(0, 3, NOW1)
    assert acquisition.retain_first_receipts(rows, path=None, source_id='topix', received_at=NOW1) == rows


def test_topix_refetch_and_restart_reuse_the_feature_history():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / 'store.sqlite3'

        def with_topix(now, rows):
            base = inputs(now)
            return {**base, 'price_series': {**base['price_series'], 'topix': rows}}

        selected = acquisition.retain_first_receipts(topix(0, 57, NOW1), path=path, source_id='topix',
                                                     received_at=NOW1)
        first = saved(cutoffs(57, NOW1), **with_topix(NOW1, selected))
        # Without retention the re-sent rows differ before the boundary.
        replay = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=first,
                                                **with_topix(NOW2, topix(1, 57, NOW2)))
        assert replay['calculationWork']['reusedCutoffs'] == 0
        assert replay['reuseDecision']['source'] == 'price_series:topix'
        selected = acquisition.retain_first_receipts(topix(1, 57, NOW2), path=path, source_id='topix',
                                                     received_at=NOW2)
        series = with_topix(NOW2, selected)
        new = features.build_feature_history(cutoffs=cutoffs(57, NOW2), previous_history=first, **series)
        assert new['calculationWork'] == {'reusedCutoffs': 57, 'evaluatedCutoffs': 1}
        same_values(new, features.build_feature_history(cutoffs=cutoffs(57, NOW2), **series))


def test_backfilled_foreign_flow_is_known_from_its_official_publication():
    """2026-10-03: the ten-year investor-type backfill was stamped knownAt = its
    import (2026-09-30), so no past cutoff could see any past week and D05 had
    one event in ten years. An original row is known from its PubDate; the
    import stays as receivedAt; a correction keeps its own receipt."""
    original = {"instrumentId": "MARKET", "seriesId": "flow.foreign", "periodEnd": "2018-03-02",
                "value": 1.0e11, "unit": "JPY", "availableFrom": "2018-03-08T18:00:00+09:00",
                "publishedAt": "2018-03-08T18:00:00+09:00", "knownAt": "2026-09-30T05:00:00Z"}
    correction = {**original, "revision": 1, "value": 2.0e11, "knownAt": "2026-09-30T05:00:00Z"}
    other = {**original, "seriesId": "credit.short_balance"}
    out = features._flow_publication_availability([original, correction, other])
    assert out[0]["knownAt"] == "2018-03-08T18:00:00+09:00"
    assert out[0]["receivedAt"] == "2026-09-30T05:00:00Z"
    assert out[0]["availabilityBasis"] == "OFFICIAL_PUBLICATION_DATE"
    assert out[1] == correction and out[2] == other
    assert original["knownAt"] == "2026-09-30T05:00:00Z"          # not mutated
    assert features._flow_publication_availability(out) == out      # idempotent

    weeks = [{**original, "periodEnd": f"2018-0{m}-{d:02d}",
              "availableFrom": f"2018-0{m}-{d + 6:02d}T18:00:00+09:00",
              "publishedAt": f"2018-0{m}-{d + 6:02d}T18:00:00+09:00",
              "value": (1 if i % 2 else -1) * 1.0e11}
             for i, (m, d) in enumerate([(3, 2), (3, 9), (3, 16), (4, 6), (4, 13), (4, 20)])]
    snapshot = features.build_market_features(cutoff="2018-05-01T00:00:00Z",
                                              price_series={}, foreign_flow=weeks)
    d05 = [c for c in snapshot["conditions"] if c["seriesId"] == features.SIGN_CONDITION_IDS["D05"]]
    assert d05, "past cutoffs must see the published weeks"


def test_daily_1570_balances_are_read_as_week_final_rows():
    """J-Quants margin-interest became daily from the 2026-09-25 application
    date. Weekly consumers keep each week's last date; the open week waits
    for its Friday; a holiday Friday's Thursday counts once a later week exists."""
    from jp_market_dynamics import week_final_rows
    def rows(*days):
        return [{"seriesId": "margin.long_balance", "periodEnd": d, "value": 1.0} for d in days]
    daily = rows("2026-09-18", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01")
    assert [r["periodEnd"] for r in week_final_rows(daily)] == ["2026-09-18", "2026-09-25"]
    closed = week_final_rows(daily + rows("2026-10-02"))
    assert [r["periodEnd"] for r in closed] == ["2026-09-18", "2026-09-25", "2026-10-02"]
    holiday = week_final_rows(rows("2026-11-19", "2026-11-26", "2026-11-30"))   # Thursday then next week
    assert [r["periodEnd"] for r in holiday] == ["2026-11-19", "2026-11-26"]
    weekly_era = rows("2016-10-14", "2016-10-21", "2016-10-28")
    assert week_final_rows(weekly_era) == weekly_era
    source = rows("2026-09-25")
    week_final_rows(source)[0]["value"] = 9.0
    assert source[0]["value"] == 1.0                                             # not mutated


def test_ten_year_vix_macd_lists_bounded_references():
    """2026-10-04: the VIX MACD over ten years listed 2,821 input rows (1.3 MB);
    the market brief reached 4.9 MB and timed out on the phone, and its
    history record exceeded 2 MB. sourceRef still binds every input."""
    from datetime import date as _date, timedelta as _timedelta
    start = _date(2016, 10, 3)
    vix = [{"instrumentId": "VIX", "seriesId": "close", "value": 15 + (i % 17) * 0.5, "close": 15 + (i % 17) * 0.5,
            "date": (start + _timedelta(days=i)).isoformat(),
            "availableFrom": (start + _timedelta(days=i + 1)).isoformat() + "T00:00:00Z", "sourceRef": "test:vix"}
           for i in range(3650)]
    snapshot = features.build_market_features(cutoff="2026-10-01T00:00:00Z", price_series={"vix": vix})
    row = next(r for r in snapshot["features"] if r["seriesId"] == "vix.macd_histogram")
    assert len(row["inputReferences"]) == features.INPUT_REFERENCE_LIMIT
    assert row["inputReferenceCount"] == 3650 and row["firstInputDate"] == "2016-10-03"
    assert row["inputReferences"][-1]["date"] == vix[-1]["date"]
    assert len(json.dumps(snapshot, ensure_ascii=False)) < 200_000
    short = next(r for r in snapshot["features"] if r["seriesId"] == "vix.change5")
    assert len(short["inputReferences"]) == 6 and "inputReferenceCount" not in short
