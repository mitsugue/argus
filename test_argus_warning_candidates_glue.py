"""Shared cached source glue: failures remain isolated, reads never acquire."""
from unittest.mock import Mock
import sqlite3
import pytest
import scanner
from test_argus_warning_candidates import DAYS, AT, price
from argus_warning_candidates import admitted_results
from jp_market_level_map import EPS_BASIS


def setup_inputs(monkeypatch,tmp_path):
    monkeypatch.setattr(scanner,'_N225_ANALOG_HISTORY',{'data':[price(d,'NIKKEI_225_INDEX',40000) for d in DAYS]})
    monkeypatch.setattr(scanner,'_jp_exchange_sessions',lambda *args:(DAYS,False))
    monkeypatch.setattr(scanner,'_JP_INDEX_PROXY',{'factors':{'factors':{str(1000+i):1 for i in range(225)}},'weightsAsOf':DAYS[0]})
    monkeypatch.setattr(scanner,'_nikkei225_constituent_changes',lambda:{'rows':[]})
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE',{'^GSPC':{'data':[price(d,'SP500_INDEX',5000) for d in DAYS],'acquiredAt':AT}})
    monkeypatch.setattr(scanner,'_LEVEL_MAP',{'eps':{d:dict(date=d,eps=4000,basis=EPS_BASIS,recordedAt=AT) for d in DAYS}})
    monkeypatch.setattr(scanner,'_JP_INTERNALS_CACHE',{'prices':{}})
    monkeypatch.setattr(scanner,'_TOPIX_HIST_CACHE',{'data':[]})
    request=Mock(side_effect=AssertionError('cache read cannot acquire'))
    monkeypatch.setattr(scanner.requests,'get',request)
    return request


def test_cached_rules_share_actual_sources_and_do_not_create_missing_stores(monkeypatch,tmp_path):
    request=setup_inputs(monkeypatch,tmp_path)
    artifact=scanner._jp_adopted_warning_rules({},AT)
    results=admitted_results(artifact,AT)
    assert results['D03']['state']=='CLEAR' and results['D04']['state']=='CLEAR'
    assert results['D07']['state']=='DATA_GATED'
    assert artifact['performanceStudy']['conditions']['D04']['validationStatus']=='UNVALIDATED'
    assert not list(tmp_path.iterdir())
    request.assert_not_called()


def test_corrupt_financial_store_does_not_hide_two_independent_conditions(monkeypatch,tmp_path):
    import argus_earnings_history
    request=setup_inputs(monkeypatch,tmp_path)
    monkeypatch.setattr(argus_earnings_history,'read',Mock(side_effect=sqlite3.DatabaseError('synthetic corruption')))
    results=admitted_results(scanner._jp_adopted_warning_rules({},AT),AT)
    assert results['D03']['state']=='CLEAR' and results['D04']['state']=='CLEAR'
    assert results['D07']['reasonJa']=='営業利益予想の保存原本を検証できません'
    request.assert_not_called()


def test_repeated_pagination_cannot_be_retained_as_complete_market_cohort(monkeypatch):
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','synthetic-test-key')
    request=Mock(side_effect=[Mock(status_code=200,json=Mock(return_value={'data':[],'pagination_key':'repeat'})),
                             Mock(status_code=200,json=Mock(return_value={'data':[],'pagination_key':'repeat'}))])
    monkeypatch.setattr(scanner.requests,'get',request)
    with pytest.raises(RuntimeError,match='repeated_pagination_cursor'):
        scanner._jquants_paginated('/fins/summary',{'date':'2026-09-01'})
    assert request.call_count==2


def test_reaction_scope_reads_market_originals_without_network_and_rotates_twenty(monkeypatch,tmp_path):
    from test_argus_warning_candidates import cohort
    import argus_earnings_history
    setup_inputs(monkeypatch,tmp_path);data=cohort()
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:AT)
    monkeypatch.setattr(argus_earnings_history,'read',lambda *a,**k:data['financial_rows'])
    assert scanner._jp_earnings_reaction_codes()==[str(1000+i) for i in range(5)]
    monkeypatch.setattr(argus_earnings_history,'read',Mock(side_effect=sqlite3.DatabaseError('synthetic')))
    assert scanner._jp_earnings_reaction_codes()==[]


# ━━━ 2026-10-15: reuse while the visible inputs are unchanged ━━━

def _count_rule_runs(monkeypatch):
    import argus_warning_candidates as rules
    runs = []
    original = rules.ratio_rule
    monkeypatch.setattr(rules, 'ratio_rule', lambda **k: runs.append(k['cutoff']) or original(**k))
    return runs


def test_unchanged_visible_inputs_reuse_results_and_seal_at_the_new_cutoff(monkeypatch, tmp_path):
    setup_inputs(monkeypatch, tmp_path)
    runs = _count_rule_runs(monkeypatch)
    first = scanner._jp_adopted_warning_rules({}, AT)
    later = '2026-09-15T12:02:00Z'
    second = scanner._jp_adopted_warning_rules({}, later)
    assert runs == [AT]                                   # computed once
    assert second['informationCutoff'] == later and second['artifactId'] != first['artifactId']
    assert admitted_results(second, later) == admitted_results(first, AT)
    assert second['performanceStudy'] == first['performanceStudy']


def test_a_row_that_becomes_visible_or_arrives_forces_a_recomputation(monkeypatch, tmp_path):
    from test_argus_warning_candidates import price
    setup_inputs(monkeypatch, tmp_path)
    runs = _count_rule_runs(monkeypatch)
    rows = scanner._N225_ANALOG_HISTORY['data']
    # Present already, visible only from 12:01.
    rows[-1] = price(rows[-1]['date'], 'NIKKEI_225_INDEX', 40100, known='2026-09-15T12:01:00Z')
    scanner._jp_adopted_warning_rules({}, AT)
    scanner._jp_adopted_warning_rules({}, '2026-09-15T12:00:30Z')     # still invisible: reused
    scanner._jp_adopted_warning_rules({}, '2026-09-15T12:02:00Z')     # now visible: recomputed
    assert len(runs) == 2
    rows.append(price('2026-09-10', 'NIKKEI_225_INDEX', 40200))        # a new row arrives
    scanner._jp_adopted_warning_rules({}, '2026-09-15T12:03:00Z')
    assert len(runs) == 3


def test_reuse_expires_after_one_hour(monkeypatch, tmp_path):
    setup_inputs(monkeypatch, tmp_path)
    runs = _count_rule_runs(monkeypatch)
    scanner._jp_adopted_warning_rules({}, AT)
    scanner._JP_ADOPTED_RULES_MEMO['at'] -= scanner._JP_ADOPTED_RULES_MAX_AGE_SEC + 1
    scanner._jp_adopted_warning_rules({}, '2026-09-15T12:02:00Z')
    assert len(runs) == 2


def test_only_a_financial_change_in_the_shared_store_forces_a_recomputation(monkeypatch, tmp_path):
    import argus_earnings_history
    import jp_market_acquisition
    from test_argus_earnings_history import row
    setup_inputs(monkeypatch, tmp_path)
    path = tmp_path / 'jp_market_source_history.sqlite3'
    argus_earnings_history.retain(path, [{**row(), 'DiscDate': '2026-09-01'}], received_at='2026-09-01T10:00:00Z',
                                  member_codes=['1000'], query_date='2026-09-01')
    runs = _count_rule_runs(monkeypatch)
    scanner._jp_adopted_warning_rules({}, AT)
    db = jp_market_acquisition.connect(path)            # an unrelated source writes
    with db:
        db.execute("INSERT INTO raw_sources VALUES('other','https://example.test','x','2026-09-15T12:00:30Z',X'00')")
        db.execute("INSERT INTO observations(source_id,session,raw_id,body) VALUES('vix','2026-09-15','other','{}')")
    db.close()
    scanner._jp_adopted_warning_rules({}, '2026-09-15T12:01:00Z')
    assert len(runs) == 1
    added = argus_earnings_history.retain(path, [{**row(), 'DiscDate': '2026-09-15', 'DiscTime': '09:00:00', 'DiscNo': '101'}],
                                  received_at='2026-09-15T12:01:30Z',
                                  member_codes=['1000'])
    assert added['newObservations'] == 1
    scanner._jp_adopted_warning_rules({}, '2026-09-15T12:02:00Z')
    assert len(runs) == 2


def test_an_unreadable_store_identity_keeps_d03_d04_and_a_read_failure_is_not_kept(monkeypatch, tmp_path):
    """Audit 2026-10-17: the identity read ran outside the financial guard, so
    its failure removed every condition; and a failed read was reused for an hour."""
    import argus_earnings_history
    setup_inputs(monkeypatch, tmp_path)
    monkeypatch.setattr(argus_earnings_history, 'store_identity',
                        Mock(side_effect=sqlite3.DatabaseError('synthetic corruption')))
    monkeypatch.setattr(argus_earnings_history, 'read', Mock(side_effect=sqlite3.DatabaseError('synthetic')))
    runs = _count_rule_runs(monkeypatch)
    results = admitted_results(scanner._jp_adopted_warning_rules({}, AT), AT)
    assert results['D03']['state'] == 'CLEAR' and results['D04']['state'] == 'CLEAR'
    assert results['D07']['reasonJa'] == '営業利益予想の保存原本を検証できません'
    scanner._jp_adopted_warning_rules({}, AT)
    assert len(runs) == 2                                 # retried, not reused


def test_the_first_read_after_a_start_verifies_the_originals_in_the_background(monkeypatch, tmp_path):
    """2026-10-17: the once-per-start verification took 60-150 s inside the
    first request after each deploy. It now runs once in the background; D07
    says it is being checked, D03/D04 stay available, and nothing is reused."""
    import threading
    import argus_earnings_history
    setup_inputs(monkeypatch, tmp_path)
    (tmp_path / 'jp_market_source_history.sqlite3').write_bytes(b'')
    release = threading.Event()
    reads = []
    def slow_read(*a, **k):
        reads.append(threading.current_thread().name)
        release.wait(5)
        return []
    monkeypatch.setattr(argus_earnings_history, 'store_identity', lambda path: 'identity')
    monkeypatch.setattr(argus_earnings_history, 'read', slow_read)
    monkeypatch.setattr(argus_earnings_history, 'read_coverage', lambda *a, **k: {})
    monkeypatch.setattr(argus_earnings_history, 'read_company_coverage', lambda *a, **k: {})
    monkeypatch.setitem(scanner._JP_FINANCIAL_VERIFY, 'state', 'NOT_STARTED')
    runs = _count_rule_runs(monkeypatch)
    results = admitted_results(scanner._jp_adopted_warning_rules({}, AT), AT)
    assert results['D03']['state'] == 'CLEAR' and results['D04']['state'] == 'CLEAR'
    assert results['D07']['reasonJa'].startswith('営業利益予想の保存原本を確認中')
    assert reads == ['jp-financial-verify']                      # only the background thread read
    scanner._jp_adopted_warning_rules({}, AT)
    assert len(runs) == 2 and reads == ['jp-financial-verify']   # not reused, no second start
    release.set()
    for _ in range(100):
        if scanner._JP_FINANCIAL_VERIFY['state'] == 'DONE':
            break
        threading.Event().wait(0.02)
    assert scanner._JP_FINANCIAL_VERIFY['state'] == 'DONE'
    results = admitted_results(scanner._jp_adopted_warning_rules({}, AT), AT)
    assert 'reasonJa' not in results['D07'] or '確認中' not in results['D07'].get('reasonJa', '')
