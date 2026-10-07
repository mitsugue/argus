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
