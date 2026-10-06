"""Initial-card source truth: current levels, distinct source scopes, bounded owner coverage."""
from datetime import datetime, timezone
import math
import scanner
import argus_supply_demand as sd


def test_one_current_week_is_available_without_inventing_a_previous_change(monkeypatch):
    now = datetime(2026, 10, 7, 1, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(scanner.time, 'time', lambda: now)
    monkeypatch.setattr(scanner, '_flow_evidence_for', lambda *a: {})
    monkeypatch.setattr(scanner, '_JQ_MARGIN_CACHE', {'1001': {'expires': now+100,
        'data': [{'date':'2026-10-02', 'longVol':800, 'shortVol':100}]}})
    monkeypatch.setattr(scanner, '_JQ_HISTORY_CACHE', {})
    monkeypatch.setattr(scanner, '_JSF_CACHE', {})
    sig = scanner._supply_demand_signal_for('1001')
    assert sig['evidence']['marginBuyingBalance'] == 800
    assert sig['ratios']['margin'] == 8 and sig['sourceDates']['weeklyMargin'] == '2026-10-02'
    assert sig['evidence']['marginBalanceChange'] is None
    assert sig['direction'] == 'unknown' and sig['sourceDates']['previousWeeklyMargin'] is None
    # Stale / future source dates are still excluded.
    scanner._JQ_MARGIN_CACHE['1001']['data'][0]['date'] = '2026-10-09'
    assert scanner._supply_demand_signal_for('1001')['supplyDemandRank'] == 'Unknown'


def test_market_credit_and_jsf_ratios_are_separate_and_heavy_credit_stays_capped():
    sig = sd.classify('1001','JP', {'marginBuying':1200, 'marginSelling':100,
        'marginBuyingPrev':1400, 'jsfLoan':50, 'jsfLending':100,
        'marginDate':'2026-10-02', 'jsfDate':'2026/10/06', 'avgDailyVolume':1000,
        'changePct':2, 'volumeRatio':1.5}, '2026-10-07T01:00:00Z')
    assert sig['ratios'] == {'margin':12.0, 'jsf':0.5, 'usedSource':'JSF'}
    assert sig['supplyDemandLevel'] == 'very_heavy' and sig['supplyDemandRank'] not in ('S','A','B')
    assert '日証金の貸借倍率' in sig['ownerReadableWhyJa']


def test_invalid_or_partial_balances_cannot_mint_direct_s_rank():
    for value in (math.nan, math.inf, -1, True):
        sig = sd.classify('1001','JP', {'marginBuying':value, 'marginSelling':value,
            'jsfLoan':value, 'jsfLending':value, 'changePct':2}, '2026-10-07T01:00:00Z')
        assert sig['supplyDemandRank'] == 'Unknown' and sig['directness'] != 'direct_data'
    assert sd.recent_margin_rows([{'date':'a','longVol':1},{'date':'a','longVol':2}], lambda _:True) == []


def test_all_saved_owner_registrations_are_read_while_unknown_extras_remain_bounded(monkeypatch):
    members = [{'market':'JP','symbol':str(7000+i),'enabled':True} for i in range(40)]
    monkeypatch.setattr(scanner, '_OWNER_OVERVIEW_MEMBERSHIP', {'members':members})
    monkeypatch.setattr(scanner, '_supply_demand_list', lambda cap: [])
    monkeypatch.setattr(scanner, '_sd_register_extra', lambda *a: None)
    monkeypatch.setattr(scanner, '_quote_cached_only', lambda *a: {})
    monkeypatch.setattr(scanner, '_supply_demand_signal_for', lambda sym,mkt: {'symbol':sym, 'market':mkt})
    def read(codes):
        return scanner.app.test_client().get('/api/argus/supply-demand', query_string={'symbols':','.join(codes)}).get_json()['signals']
    assert len(read([m['symbol'] for m in members])) == 40
    assert len(read([str(8000+i) for i in range(40)])) == 10
