"""2026-11-10 cost decision: subject explanations are not rewritten on every market edition."""
import argus_overview_refresh as refresh


def ctx(*facts):
    return {'facts': list(facts)}


NEWS = {'source': 'subject_news_metadata', 'materialInput': {'url': 'https://example.test/a', 'title': 'A',
        'publishedAt': '2026-11-09T00:00:00Z', 'updatedAt': None, 'receivedAt': '2026-11-09T01:00:00Z'}}
MARKET = {'source': 'trusted_mail', 'text': '市場の材料'}


def test_boundary_is_latest_friday_1600_jst():
    # Tue 2026-11-10 -> Fri 2026-11-06 16:00 JST, before and after the old daily time
    assert refresh.refresh_boundary('2026-11-10T06:59:00Z').isoformat() == '2026-11-06T07:00:00+00:00'
    assert refresh.refresh_boundary('2026-11-10T07:00:00Z').isoformat() == '2026-11-06T07:00:00+00:00'
    # Friday 15:59 JST is still the previous week; 16:00 is the new one.
    assert refresh.refresh_boundary('2026-11-13T06:59:00Z').isoformat() == '2026-11-06T07:00:00+00:00'
    assert refresh.refresh_boundary('2026-11-13T07:00:00Z').isoformat() == '2026-11-13T07:00:00+00:00'
    # Sunday and the following Monday -> Friday 16:00 JST
    assert refresh.refresh_boundary('2026-11-15T03:00:00Z').isoformat() == '2026-11-13T07:00:00+00:00'
    assert refresh.refresh_boundary('2026-11-16T08:00:00Z').isoformat() == '2026-11-13T07:00:00+00:00'


def test_market_change_alone_is_not_due_within_the_day():
    policy = refresh.RefreshPolicy()
    due, reason = policy.decide(subject=('JP', '7203', 5), previous_context=ctx(MARKET, NEWS),
        previous_completed_at='2026-11-10T07:30:00Z', context=ctx({**MARKET, 'text': '新しい版'}, NEWS),
        now='2026-11-10T12:00:00Z')
    assert (due, reason) == (False, 'REFRESH_NOT_DUE')


def test_weekly_refresh_after_friday_close():
    policy = refresh.RefreshPolicy()
    args = dict(subject=('JP', '7203', 5), previous_context=ctx(NEWS),
                previous_completed_at='2026-11-09T08:00:00Z', context=ctx(NEWS))
    # Weekdays after the written one do not rewrite it any more.
    for moment in ('2026-11-10T07:05:00Z', '2026-11-12T07:05:00Z', '2026-11-13T06:59:00Z'):
        assert policy.decide(**args, now=moment) == (False, 'REFRESH_NOT_DUE')
    assert policy.decide(**args, now='2026-11-13T07:05:00Z') == (True, 'WEEKLY_REFRESH')


def test_refetch_of_the_same_news_is_not_a_change():
    again = {**NEWS, 'materialInput': {**NEWS['materialInput'], 'receivedAt': '2026-11-10T03:00:00Z'}}
    assert refresh.material_key(ctx(NEWS)) == refresh.material_key(ctx(again))


def test_own_material_change_after_an_hour():
    policy = refresh.RefreshPolicy()
    new = {**NEWS, 'materialInput': {**NEWS['materialInput'], 'url': 'https://example.test/b'}}
    args = dict(subject=('JP', '7203', 5), previous_context=ctx(NEWS), context=ctx(new),
                previous_completed_at='2026-11-10T07:30:00Z')
    assert policy.decide(**args, now='2026-11-10T08:00:00Z') == (False, 'SUBJECT_MATERIAL_TOO_RECENT')
    assert policy.decide(**args, now='2026-11-10T08:31:00Z') == (True, 'SUBJECT_MATERIAL_CHANGED')


def test_starts_per_subject_and_day_are_bounded():
    policy = refresh.RefreshPolicy(max_starts=2)
    subject = ('JP', '7203', 5)
    for _ in range(2):
        policy.started(subject=subject, now='2026-11-10T08:00:00Z')
    due, reason = policy.decide(subject=subject, previous_context=ctx(NEWS),
        previous_completed_at='2026-11-01T00:00:00Z', context=ctx(NEWS), now='2026-11-10T09:00:00Z')
    assert (due, reason) == (False, 'DAILY_START_LIMIT')
    # The next JST day starts a new count.
    assert policy.decide(subject=subject, previous_context=ctx(NEWS),
        previous_completed_at='2026-11-01T00:00:00Z', context=ctx(NEWS), now='2026-11-11T08:00:00Z')[0]


def test_next_refresh_is_the_next_friday():
    assert refresh.RefreshPolicy().next_refresh_at('2026-11-13T08:00:00Z') == '2026-11-20T07:00:00+00:00'
    assert refresh.RefreshPolicy().next_refresh_at('2026-11-10T01:00:00Z') == '2026-11-13T07:00:00+00:00'


def test_registered_refresh_waits_for_the_weekly_time_after_a_new_market_edition(tmp_path):
    import copy
    import time
    from flask import Flask
    import argus_owner_dialogue_api as api
    import argus_owner_dialogue_store as store
    import argus_market_brief as brief_module
    from test_argus_owner_dialogue import market_brief, answer
    path = tmp_path / 'owner.sqlite3'
    clock = ['2026-11-10T01:00:00Z']   # Tue 10:00 JST
    current = [market_brief()]
    calls = []
    controls = api.register(Flask(__name__), authorize=lambda token: (True, None, 200),
        storage_path=lambda: str(path), market_brief=lambda: current[0], now=lambda: clock[0],
        generate=lambda user, **kw: (calls.append(user), answer())[1],
        generation_policy=lambda: {'model': 'test', 'ruleVersion': 'v1'},
        subject_materials=lambda **kw: [],
        registered_subjects=lambda: [{'market': 'JP', 'symbol': '5803', 'enabled': True}],
        refresh_policy=refresh.RefreshPolicy())

    def finish():
        for _ in range(200):
            items = store.history(path, controls['bootId'])['items']
            if items and items[0]['status'] != 'RUNNING':
                return items[0]
            time.sleep(.01)
        raise AssertionError('worker did not complete')

    assert controls['refreshSubjectOverviews']()['status'] == 'STARTED'
    assert finish()['status'] == 'SUCCEEDED' and len(calls) == 1
    # A new market edition the same afternoon: the saved explanation is kept.
    edition = copy.deepcopy(current[0])
    edition['facts'] = edition['facts'] + [{'text': '新しい市場の材料。', 'source': 'trusted_mail',
        'priority': 'P1', 'verification': 'UNCONFIRMED'}]
    edition['unifiedContext'] = brief_module.unified_context(edition)
    current[0] = edition
    for moment in ('2026-11-10T03:00:00Z', '2026-11-10T07:01:00Z', '2026-11-12T07:01:00Z',
                   '2026-11-13T06:59:00Z'):
        clock[0] = moment
        current_state = controls['refreshSubjectOverviews']()
        assert current_state['status'] == 'CURRENT', (moment, current_state)
    assert len(calls) == 1
    # After Friday 16:00 JST the changed market facts are written once.
    clock[0] = '2026-11-13T07:01:00Z'
    assert controls['refreshSubjectOverviews']()['status'] == 'STARTED'
    assert finish()['status'] == 'SUCCEEDED' and len(calls) == 2
    assert controls['refreshSubjectOverviews']()['status'] == 'CURRENT' and len(calls) == 2
