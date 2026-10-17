"""Synthetic annual observations; no production statistics or predictive validation."""
from copy import deepcopy
import pytest
import argus_jp_fiscal_monitor as f

AT = '2026-09-16T04:00:00Z'


def rows(g=3., r=1., pb=-5., b=200., year=2025, revision='one'):
    common = dict(country='JP', priceBasis='NOMINAL', periodBasis='FISCAL_YEAR',
        frequency='ANNUAL', year=year, unit='PERCENT', estimateType='ACTUAL',
        governmentScope='CENTRAL_AND_LOCAL', balanceCoverage='MATCHED_GROSS',
        debtDefinition='GROSS_PUBLIC_DEBT', accountingBasis='MATCHED_CASH',
        sourceUrl='https://example.invalid/fiscal', sourceRevision=revision,
        sourceHash='a'*64, knownAt=AT, acquiredAt=AT, publishedAt=None,
        roundingHalfWidth=0.05, acquisitionStatus='AVAILABLE')
    result = {metric:dict(common, metric=metric,value=value,id=metric+revision)
        for metric,value in zip(f.METRICS,(g,r,pb,b))}
    result['nominal_growth']['rateBasis']='YEAR_OVER_YEAR'
    result['effective_rate']['rateBasis']='INTEREST_OVER_START_DEBT'
    result['primary_balance']['ratioBasis']='SURPLUS_OVER_CURRENT_GDP'
    result['debt_ratio'].update(year=year-1,ratioBasis='END_DEBT_OVER_SAME_YEAR_GDP')
    return result


def test_growth_exceeds_rate_but_primary_deficit_increases_debt_ratio():
    d=f.calculate(rows(),as_of=AT)
    assert d['status']=='AVAILABLE'
    assert d['values']['spreadPoints']==2
    assert d['values']['interestGrowthEffectPoints']==pytest.approx(-3.8834951456)
    assert d['values']['pressurePoints']==pytest.approx(1.1165048544)
    assert d['warningLevel']=='WATCH' and not d['actionAuthority'] and d['probability'] is None


def test_rate_exceeds_growth_but_sufficient_primary_surplus_reduces_ratio():
    d=f.calculate(rows(g=1,r=3,pb=5),as_of=AT)
    assert d['values']['spreadPoints']==-2
    assert d['values']['pressurePoints'] < 0
    assert d['warningLevel']=='NO_TRIGGER'  # No trigger is explicitly not a safety verdict.


@pytest.mark.parametrize('metric,field,value',[
    ('nominal_growth','priceBasis','REAL'), ('nominal_growth','country','US'),
    ('nominal_growth','rateBasis','QUARTER_ON_QUARTER_ANNUALIZED'),
    ('nominal_growth','periodBasis','CALENDAR_YEAR'),
    ('effective_rate','rateBasis','MARKET_10Y_YIELD'),
    ('effective_rate','rateBasis','INTEREST_OVER_AVERAGE_DEBT'),
    ('primary_balance','governmentScope','GENERAL_GOVERNMENT'),
    ('primary_balance','ratioBasis','DEFICIT_OVER_CURRENT_GDP'),
    ('debt_ratio','debtDefinition','NET_DEBT'),
    ('debt_ratio','year',2025), ('nominal_growth','value',None),
    ('nominal_growth','value',float('nan')), ('nominal_growth','value',-100),
    ('nominal_growth','acquisitionStatus','UPDATE_DUE'),
    ('nominal_growth','acquisitionStatus','FAILED'),
    ('nominal_growth','knownAt','2026-09-17T04:00:00Z'),
    ('nominal_growth','sourceRevision',''),
])
def test_mixed_unknown_or_unavailable_data_is_not_normal(metric,field,value):
    d=rows();d[metric][field]=value
    result=f.calculate(d,as_of=AT)
    assert result['status']=='DATA_GATED'
    assert result['warningLevel']=='UNKNOWN'
    assert result['values'] is None


def test_revision_and_annual_change_are_not_confused():
    old=f.calculate(rows(),as_of=AT)
    revised=f.calculate(rows(g=2,revision='two'),as_of=AT,previous=old)
    assert revised['comparison']['kind']=='REVISION'
    assert 'GROWTH_RATE_GAP_NARROWED' in revised['reasons']
    next_year=f.calculate(rows(g=2,year=2026),as_of=AT,previous=old)
    assert next_year['comparison']['kind']=='ANNUAL_CHANGE'
    other=f.calculate(rows(year=2028),as_of=AT,previous=old)
    assert other['comparison']['status']=='UNAVAILABLE'


def test_forecast_revision_keeps_case_and_signs():
    before=rows()
    for row in before.values():row.update(estimateType='FORECAST',scenario='case_a')
    old=f.calculate(before,as_of=AT)
    after=deepcopy(before)
    after['nominal_growth'].update(value=2,id='g-new')
    after['effective_rate'].update(value=2,id='r-new')
    d=f.calculate(after,as_of=AT,previous=old)
    assert 'GROWTH_FORECAST_REVISED_DOWN' in d['reasons']
    assert 'EFFECTIVE_RATE_FORECAST_REVISED_UP' in d['reasons']
    after['effective_rate']['scenario']='case_b'
    assert f.calculate(after,as_of=AT)['status']=='DATA_GATED'


def test_scenario_does_not_modify_source_or_create_official_notification():
    source=rows(); unchanged=deepcopy(source)
    simulated=f.scenario(source,as_of=AT,growth_pct=0,effective_rate_pct=4)
    assert simulated['values']['pressurePoints']==13
    assert source==unchanged
    assert simulated['recordKind']=='HYPOTHETICAL_SCENARIO'
    assert not simulated['officialHistoryWriteAllowed']
    assert f.transition(None,simulated)['event'] is None


def test_duplicate_suppression_failure_holds_and_evidence_based_release():
    d=f.calculate(rows(),as_of=AT)
    first=f.transition(None,d)
    assert first['event']['kind']=='NEW_WATCH'
    assert f.transition(d,d)['event'] is None
    missing=f.calculate({},as_of=AT)
    failed=f.transition(d,missing)
    assert failed['effectiveState']==d and not failed['releaseAllowed'] and failed['event'] is None
    improved=f.calculate(rows(g=4,pb=2,revision='two'),as_of=AT,previous=d)
    cleared=f.transition(d,improved)
    assert cleared['event']['kind']=='RELEASED'
    assert cleared['releaseAllowed']
    assert not cleared['event']['deliveryConfirmed']


def test_retrieval_timestamp_alone_does_not_create_new_identity():
    first=f.calculate(rows(),as_of=AT)
    again=rows()
    for row in again.values():row['acquiredAt']='2026-09-16T04:30:00Z'
    second=f.calculate(again,as_of='2026-09-16T04:30:00Z')
    assert first['id']==second['id']


def test_unrelated_period_or_scope_cannot_release_warning():
    old=f.calculate(rows(),as_of=AT)
    unrelated=f.calculate(rows(year=2030,g=4,pb=2),as_of=AT,previous=old)
    result=f.transition(old,unrelated)
    assert result['event'] is None and result['effectiveState']==old
    assert result['assessmentStatus']=='NOT_COMPARABLE'


def test_rounding_indeterminate_is_neither_new_warning_nor_release():
    old=f.calculate(rows(),as_of=AT)
    zero=f.calculate(rows(g=1,r=1,pb=0,revision='two'),as_of=AT,previous=old)
    assert zero['values']['pressurePoints']==0
    assert zero['uncertainty']['pressurePointsRange'][0]<0<zero['uncertainty']['pressurePointsRange'][1]
    assert f.transition(old,zero)['releaseAllowed'] is False


def market_rows():
    result=[]
    for series in ('jp.market.jgb.10y','jp.market.jgb.20y','jp.market.jgb.30y','jp.market.jgb.40y','fx.usdjpy'):
        for i, day in enumerate(('2026-09-08','2026-09-09','2026-09-10','2026-09-11','2026-09-14','2026-09-15')):
            result.append(dict(seriesId=series,sessionDate=day,knownAt=AT,id=series+day,
                value=100+i,roundingHalfWidth=.0005,acquisitionStatus='AVAILABLE',
                unit='JPY_PER_USD' if series=='fx.usdjpy' else 'PERCENT',
                rateBasis='FX_SPOT' if series=='fx.usdjpy' else 'MARKET_YIELD',
                sourceUrl='https://example.invalid/market', instrument='synthetic', compounding='same'))
    return result


def test_yield_tenors_are_one_group_not_four_independent_confirmations():
    result=f.market_assessment(market_rows(),expected_session='2026-09-15',as_of=AT)
    assert result['status']=='AVAILABLE'
    assert result['adverseGroups']==['FX','JGB']
    assert not result['causalityConfirmed'] and not result['actionAuthority']
    assert result['auctionStatus']=='NOT_CONNECTED'


def test_one_day_jump_is_not_a_persistent_market_watch():
    source=market_rows()
    for row in source:row['value']=105 if row['sessionDate']=='2026-09-15' else 100
    result=f.market_assessment(source,expected_session='2026-09-15',as_of=AT)
    assert result['warningLevel']=='NO_TRIGGER'
    assert result['adverseGroups']==[]


def test_stale_or_missing_market_cannot_become_clear():
    source=market_rows()
    old=f.market_assessment(source,expected_session='2026-09-16',as_of=AT)
    assert old['warningLevel']=='UNKNOWN'
    assert all(row['status']=='UPDATE_DUE' for row in old['series'].values())
    for row in source:
        if row['sessionDate']=='2026-09-15':row.update(value=None,acquisitionStatus='MISSING')
    assert f.market_assessment(source,expected_session='2026-09-15',as_of=AT)['warningLevel']=='UNKNOWN'


def test_market_rounding_boundary_does_not_trigger_from_binary_float_noise():
    assert not f.exceeds(2.988-2.987,.001)


def test_source_publication_date_prevents_backdated_knowledge():
    source=rows()
    source['nominal_growth']['publishedDate']='2026-09-17'
    result=f.calculate(source,as_of=AT)
    assert result['status']=='DATA_GATED'


def test_fiscal_and_market_confluence_explains_categories_not_crisis():
    fiscal=f.calculate(rows(),as_of=AT)
    market=f.market_assessment(market_rows(),expected_session='2026-09-15',as_of=AT)
    env=f.environment_assessment(fiscal,market)
    assert env['warningLevel']=='WARNING'
    assert set(env['currentReasons'])=={'FISCAL:POSITIVE_MECHANICAL_PRESSURE','MARKET:JGB','MARKET:FX'}
    assert not env['actionAuthority'] and env['probability'] is None
    assert env['notificationCandidate']['kind']=='NEW_WATCH'
    assert f.environment_assessment(fiscal,market,previous=env)['notificationCandidate'] is None


def test_collection_failure_retains_warning_then_real_release_has_a_reason():
    old=f.calculate(rows(),as_of=AT)
    market=f.market_assessment(market_rows(),expected_session='2026-09-15',as_of=AT)
    prior=f.environment_assessment(old,market)
    unavailable=f.calculate({},as_of=AT)
    missing_market=f.market_assessment([],expected_session='2026-09-15',as_of=AT)
    failed=f.environment_assessment(unavailable,missing_market,previous=prior)
    assert failed['warningLevel']=='WARNING' and failed['previousWarningRetained']
    assert failed['notificationCandidate'] is None
    assert failed['dataCompleteness']=='INCOMPLETE'
    # Compare to the last successful fiscal record, not the failed acquisition.
    changed=f.calculate(rows(g=4,pb=1,revision='new'),as_of=AT,previous=old)
    easing=market_rows()
    for row in easing: row['value']=-row['value']
    clear=f.market_assessment(easing,expected_session='2026-09-15',as_of=AT)
    released=f.environment_assessment(changed,clear,previous=failed)
    assert released['notificationCandidate']['kind']=='RELEASED'
    assert released['releaseConditions']


def test_fiscal_scenario_cannot_notify_even_when_market_watch_is_present():
    hypothetical=f.scenario(rows(),as_of=AT,growth_pct=-3)
    market=f.market_assessment(market_rows(),expected_session='2026-09-15',as_of=AT)
    env=f.environment_assessment(hypothetical,market)
    assert env['notificationCandidate'] is None
    assert not env['officialHistoryWriteAllowed']
