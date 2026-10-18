"""Past release reactions: archived dates, fixed times, used only when better (2026-10-18)."""
from datetime import date, timedelta
import json

import pytest

import jp_market_analog_backtest as backtest
import jp_market_historical_releases as releases
import jp_market_material_reactions as material
from jp_market_session_reaction import measure, session_close, INSTRUMENT
from test_jp_market_analog_backtest import sessions, bars
from jp_market_price_paths import cached_index_comparison

RECEIVED = '2026-10-18T00:00:00+00:00'


def response(release_id, days):
    return json.dumps({'release_dates': [{'release_id': release_id, 'date': d} for d in days]}).encode()


def test_dates_become_events_at_the_fixed_release_time():
    nfp = releases.events('nfp', response(50, ['2015-12-04', '2016-11-04', '2026-10-02', '2026-11-06']), received_at=RECEIVED)
    assert [e['eventTime'] for e in nfp] == ['2016-11-04T12:30:00+00:00', '2026-10-02T12:30:00+00:00']
    jolts = releases.events('jolts', response(192, ['2026-01-07']), received_at=RECEIVED)
    assert jolts[0]['eventTime'] == '2026-01-07T15:00:00+00:00'   # 10:00 ET in winter
    assert nfp[0]['timeBasis'] == 'ARCHIVED_RELEASE_DATE_FIXED_TIME_RULE'
    assert nfp[0]['actualPublicationTimeVerified'] is False and len(nfp[0]['sourceSha256']) == 64
    assert 'api_key' not in json.dumps(nfp)
    with pytest.raises(ValueError):
        releases.events('nfp', response(10, ['2026-10-02']), received_at=RECEIVED)
    with pytest.raises(ValueError):
        releases.events('nfp', response(50, ['2026-10-02'] * (releases.MAX_DATES + 1)), received_at=RECEIVED)
    assert 'api_key' not in releases.request_params('cpi')


DAYS = sessions(40, start='2026-08-03')
CASH = [{'instrumentId': INSTRUMENT, 'date': d, 'close': 40000 + 10 * i, 'receivedAt': RECEIVED,
         'sourceSha256': 'a' * 64, 'sourceRef': 'yahoo:chart:^N225'} for i, d in enumerate(DAYS)]


def event(day, hhmm='12:30'):
    return {'eventId': f'hist-nfp-{day}', 'eventType': 'nfp', 'eventTime': f'{day}T{hhmm}:00+00:00',
            'timeBasis': releases.TIME_BASIS, 'sourceRef': releases.SOURCE, 'sourceSha256': 'b' * 64,
            'receivedAt': RECEIVED}


def test_research_rows_are_known_at_the_last_close_and_the_minute_does_not_matter():
    rows = measure(event=event('2026-09-04'), rows=CASH, sessions=DAYS, cutoff=RECEIVED, research_availability=True)
    five = next(r for r in rows if r['reactionWindowSessions'] == 5)
    assert five['baselineDate'] == '2026-09-04' and five['availableFrom'] == session_close(five['endpointDate']).isoformat()
    assert five['availabilityBasis'] == 'RESEARCH_KNOWN_AT_ENDPOINT_CLOSE'
    # 08:30, 10:00 or 14:00 ET on the same US date give the same Tokyo windows.
    for hhmm in ('12:30', '14:00', '18:00', '23:00'):
        again = measure(event=event('2026-09-04', hhmm), rows=CASH, sessions=DAYS, cutoff=RECEIVED, research_availability=True)
        assert [(r['baselineDate'], r['endpointDate'], r['value']) for r in again] == \
               [(r['baselineDate'], r['endpointDate'], r['value']) for r in rows]
    with pytest.raises(ValueError):
        measure(event=event('2026-09-04'), rows=CASH, sessions=DAYS, cutoff=RECEIVED)
    with pytest.raises(ValueError):
        measure(event={**event('2026-09-04'), 'timeBasis': 'OFFICIAL_EMBARGO_BOUNDARY'}, rows=CASH,
                sessions=DAYS, cutoff=RECEIVED, research_availability=True)


def test_evidenced_records_take_precedence_and_the_bound_holds():
    out = material.historical_reactions([event('2026-09-04'), event('2026-08-07')], rows=CASH, sessions=DAYS,
                                        cutoff=RECEIVED, exclude={('material_reaction.nfp.1', '2026-09-07')})
    keys = {(r['seriesId'], r['date']) for r in out['rows']}
    assert ('material_reaction.nfp.1', '2026-09-07') not in keys and len(out['rows']) == 5
    assert out['diagnostics']['gatedReasonCounts']['evidenced_record_takes_precedence'] == 1
    assert out['diagnostics']['availabilityBasis'] == 'RESEARCH_KNOWN_AT_ENDPOINT_CLOSE'
    with pytest.raises(ValueError):
        material.historical_reactions([event('2026-09-04')] * (material.MAX_HISTORICAL_EVENTS + 1),
                                      rows=CASH, sessions=DAYS, cutoff=RECEIVED)


def walk(hits_pattern, n=400):
    records = []
    for i in range(n):
        up = hits_pattern(i)
        records.append({'anchorDate': (date(2018, 1, 1) + timedelta(days=i)).isoformat(),
                        'horizons': {'5': {'forecast': 102, 'lower': 99, 'upper': 104, 'realized': 103 if up else 97}}})
    return {'step': 1, 'records': records}


def test_reactions_are_adopted_only_when_the_decision_period_is_better():
    worse, better = walk(lambda i: i % 2 == 0), walk(lambda i: i % 3 != 0)
    result = backtest.compare_material_reactions(worse, better)
    assert result['adopted'] and result['reason'] == 'better_hit_rate_in_decision_period'
    assert result['decision']['with']['hitRate'] > result['decision']['without']['hitRate']
    assert result['heldOut']['with']['directionalEvaluations'] > 0
    assert not backtest.compare_material_reactions(better, worse)['adopted']
    assert backtest.compare_material_reactions(better, better)['adopted'] is False
    # A slightly higher rate that chance explains is not adopted.
    near = backtest.compare_material_reactions(walk(lambda i: i % 2 == 0), walk(lambda i: i % 2 == 0 or i % 37 == 1))
    assert not near['adopted'] and near['reason'] == 'difference_within_chance'
    assert near['pairedOnlyWithRight'] > 0 and near['pairedOnlyWithoutRight'] == 0 and near['pairedOneSidedPValue'] >= .05
    assert result['pairedOneSidedPValue'] < .05
    few = backtest.compare_material_reactions(walk(lambda i: False, 40), walk(lambda i: True, 40))
    assert few['reason'] == 'too_few_decision_evaluations' and not few['adopted']


def comparison_inputs():
    days = sessions(900)
    closes, value, seed = [], 30000.0, 11
    for _ in days:
        seed = (seed * 1103515245 + 12345) % 2**31
        value *= 1 + ((seed / 2**31) - 0.5) * 0.02
        closes.append(round(value, 2))
    cash = [{'instrumentId': INSTRUMENT, 'date': d, 'close': c, 'receivedAt': RECEIVED,
             'sourceSha256': 'a' * 64, 'sourceRef': 'yahoo:chart:^N225'} for d, c in zip(days, closes)]
    fridays = [d for d in days if date.fromisoformat(d).weekday() == 4 and int(d[8:]) <= 7]
    research = material.historical_reactions([event(d) for d in fridays], rows=cash, sessions=days, cutoff=RECEIVED)
    return days, bars(days, closes), research['rows']


def test_comparison_reports_both_and_keeps_the_base_unless_better(monkeypatch):
    days, rows, research = comparison_inputs()
    assert research
    cache = {}
    doc = cached_index_comparison(rows, cutoff=days[-1] + 'T08:00:00Z', session_dates=days, horizon_sessions=5,
                                  backtest_cache=cache, research_reaction_rows=research)
    block = doc['comparison']['forecast']['materialReactionResearch']
    assert block['researchReactionRows'] == len(research) and block['candidatesWithReactions'] > 0
    assert block['adopted'] is cache['materialReactionResearch']['adopted']
    assert block['availabilityBasis'] == 'RESEARCH_KNOWN_AT_ENDPOINT_CLOSE' and block['predictiveProbabilities'] is None
    base = cached_index_comparison(rows, cutoff=days[-1] + 'T08:00:00Z', session_dates=days, horizon_sessions=5,
                                   backtest_cache={})
    assert 'materialReactionResearch' not in base['comparison']['forecast']
    # Forced adoption: the selection then reads the sealed set with reactions.
    monkeypatch.setattr(backtest, 'compare_material_reactions', lambda a, b: {'adopted': True, 'reason': 'forced'})
    forced = cached_index_comparison(rows, cutoff=days[-1] + 'T08:00:00Z', session_dates=days, horizon_sessions=5,
                                     backtest_cache={}, research_reaction_rows=research)
    assert forced['comparison']['forecast']['materialReactionResearch']['adopted'] is True
    assert any('materialReaction' not in c['missingGroups'] for c in forced['comparison']['candidates'])
    if not block['adopted']:
        assert all('materialReaction' in c['missingGroups'] for c in doc['comparison']['candidates'])


def test_runtime_refresh_reads_four_series_once_and_never_keeps_the_key(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_FRED_API_KEY', 'k' * 32)
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    monkeypatch.setattr(scanner, '_JP_HISTORICAL_RELEASES', {'events': [], 'status': 'NOT_ACQUIRED', 'lastAttemptAt': None,
                        'lastSuccessAt': None, 'lastAttemptMonotonic': None, 'releases': {}})
    calls = []
    class Response:
        status_code = 200
        def __init__(self, rid): self.content = response(rid, ['2026-09-04', '2026-10-02'])
    def get(url, params=None, **kw):
        calls.append(params)
        return Response(params['release_id'])
    monkeypatch.setattr(scanner.requests, 'get', get)
    scanner._jp_historical_release_refresh()
    assert len(calls) == 4 and {c['release_id'] for c in calls} == {50, 10, 46, 192}
    assert scanner._JP_HISTORICAL_RELEASES['status'] == 'AVAILABLE'
    assert len(scanner._JP_HISTORICAL_RELEASES['events']) == 8
    assert 'k' * 32 not in json.dumps(scanner._JP_HISTORICAL_RELEASES) + json.dumps(scanner._jp_historical_release_status())
    scanner._jp_historical_release_refresh()
    assert len(calls) == 4   # not due again within the day
    def fail(url, params=None, **kw):
        raise OSError('down')
    monkeypatch.setattr(scanner.requests, 'get', fail)
    scanner._JP_HISTORICAL_RELEASES['lastAttemptMonotonic'] = None
    scanner._jp_historical_release_refresh()
    assert len(scanner._JP_HISTORICAL_RELEASES['events']) == 8          # previous dates are kept
    assert scanner._jp_historical_release_status()['errors'] == {c: 'OSError' for c in releases.RELEASES}


def test_reactions_alone_are_reread_and_equal_a_full_rebuild():
    from jp_market_analogs import build_episode, with_reactions
    days, rows, research = comparison_inputs()
    at = days[400] + 'T23:59:59Z'
    window = rows[380:401]
    base = build_episode(cutoff=at, bars=window, reaction_rows=())
    full = build_episode(cutoff=at, bars=window, reaction_rows=research)
    assert full['reactions'] and with_reactions(base, research) == full
    assert with_reactions(full, ()) == base


def test_one_build_serves_every_horizon_and_equals_a_fresh_build(monkeypatch):
    import jp_market_analogs
    import jp_market_price_paths as paths
    days, rows, research = comparison_inputs()
    builds = []
    original = jp_market_analogs.build_episode
    def counted(**kw):
        builds.append(1)
        return original(**kw)
    monkeypatch.setattr(jp_market_analogs, 'build_episode', counted)
    cache = {}
    first = {h: paths.cached_index_comparison(rows, cutoff=days[-1] + 'T08:00:00Z', session_dates=days,
                                              horizon_sessions=h, backtest_cache=cache,
                                              research_reaction_rows=research) for h in (1, 5, 10, 20)}
    one_build = len(builds)
    assert one_build < 2 * len(days)              # candidates were built once, not four times
    for h in (20,):   # the last horizon read the reused candidates; one full rebuild is enough
        fresh = paths.cached_index_comparison(rows, cutoff=days[-1] + 'T08:00:00Z', session_dates=days,
                                              horizon_sessions=h, backtest_cache={}, research_reaction_rows=research)
        assert fresh == first[h]
    changed = [dict(r) for r in rows]; changed[-30]['close'] = changed[-30]['close'] * 1.01
    key = cache['sealedCandidates']['key']
    before = len(builds)
    paths.cached_index_comparison(changed, cutoff=days[-1] + 'T08:00:00Z', session_dates=days,
                                  horizon_sessions=5, backtest_cache=cache, research_reaction_rows=research)
    assert cache['sealedCandidates']['key'] != key and len(builds) > before   # a changed bar rebuilds


def test_private_runtime_diagnostics_carry_the_research_counts(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_JP_MATERIAL_RESEARCH_LAST', {'historicalEvents': 520, 'research': {'status': 'AVAILABLE'}})
    monkeypatch.setattr(scanner, '_JP_ANALOG_BACKTEST_CACHE', {'materialReactionResearch': {
        'adopted': False, 'reason': 'difference_within_chance', 'commonEvaluationDates': 400,
        'decision': {'with': {'hitRate': .55, 'directionalEvaluations': 120}, 'without': {'hitRate': .53, 'directionalEvaluations': 118}},
        'heldOut': {'with': {'hitRate': .5, 'directionalEvaluations': 40}, 'without': {'hitRate': .52, 'directionalEvaluations': 41}},
        'pairedOneSidedPValue': .3}})
    out = scanner._material_research_diagnostics()
    assert out['lastCalculation']['historicalEvents'] == 520
    assert out['decision']['adopted'] is False and out['decision']['heldOutWith']['hitRate'] == .5
    assert set(out['source']) >= {'status', 'events', 'errors'}
