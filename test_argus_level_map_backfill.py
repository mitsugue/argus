"""2026-10-21 (owner): the EPS backfill keeps its position and sets aside dates that never fill."""
import json

import argus_level_map_backfill as b

T0 = '2026-10-21T00:00:00Z'


def test_three_identical_results_set_a_date_aside_and_a_different_one_resets():
    state = b.empty()
    sign = b.signature('INPUT_INCOMPLETE', {'missingMarketCap': 1, 'missingEarnings': 0})
    assert not b.note(state, '2026-08-12', sign, T0)
    assert not b.note(state, '2026-08-12', sign, T0)
    other = b.signature('INPUT_INCOMPLETE', {'missingMarketCap': 0, 'missingEarnings': 2})
    assert not b.note(state, '2026-08-12', other, T0)               # a changed result starts over
    assert not b.note(state, '2026-08-12', other, T0)
    assert b.note(state, '2026-08-12', other, T0)
    assert b.set_aside(state, T0) == {'2026-08-12'}
    assert b.summary(state)['setAsideBySignature'] == {other: 1}


def test_the_latest_session_is_never_skipped_and_others_are():
    assert b.wanted_without_set_aside(['2026-10-20', '2026-08-12', '2026-08-11'], {'2026-08-12', '2026-10-20'},
                                      '2026-10-20') == ['2026-10-20', '2026-08-11']


def test_a_set_aside_date_gets_one_more_try_after_thirty_days():
    state = b.empty()
    sign = b.signature('NO_VALUATION_ROWS')
    for _ in range(3):
        b.note(state, '2026-07-14', sign, T0)
    assert b.set_aside(state, '2026-11-19T00:00:00Z') == {'2026-07-14'}
    assert b.set_aside(state, '2026-11-21T00:00:00Z') == set()       # due again
    assert b.note(state, '2026-07-14', sign, '2026-11-21T00:00:00Z')  # the same again: set aside at once


def test_a_success_clears_the_date():
    state = b.empty()
    for _ in range(3):
        b.note(state, '2026-07-14', 'x', T0)
    b.clear(state, '2026-07-14')
    assert b.set_aside(state, T0) == set() and b.summary(state)['attemptsTracked'] == 0


def test_the_saved_state_round_trips_and_a_bad_file_starts_empty():
    state = b.empty(); state['cursor'] = '2026-07-14'
    b.note(state, '2026-07-14', 'x', T0)
    assert b.parse(json.loads(json.dumps(state))) == state
    assert b.parse({'schemaVersion': 'other'}) == b.empty()
    assert b.parse({'schemaVersion': b.SCHEMA, 'cursor': 'not-a-day', 'attempts': {'bad': {}}})['cursor'] is None


def test_the_position_survives_a_restart(tmp_path, monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setitem(scanner._DURABILITY_PATHS, "root", str(tmp_path))
    monkeypatch.setattr(scanner, "_LEVEL_MAP_BACKFILL", {"state": None, "lastSaveError": None})
    monkeypatch.setitem(scanner._LEVEL_MAP, "epsBackfillCursor", "2026-07-14")
    state = scanner._level_map_backfill_state()
    b.note(state, '2026-08-12', 'x', T0)
    scanner._level_map_backfill_save()
    assert scanner._LEVEL_MAP_BACKFILL["lastSaveError"] is None
    monkeypatch.setattr(scanner, "_LEVEL_MAP_BACKFILL", {"state": None, "lastSaveError": None})   # a restart
    again = scanner._level_map_backfill_state()
    assert again['cursor'] == '2026-07-14' and again['attempts']['2026-08-12']['count'] == 1
