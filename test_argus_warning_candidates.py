from copy import deepcopy
from datetime import date, timedelta

import pytest
from argus_warning_candidates import ratio_rule, eps_rule, earnings_rule, seal_candidates, _empty
from jp_market_level_map import EPS_BASIS

# Synthetic calendar, explicitly provided; production must use official sessions.
DAYS = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(40)]
AT = '2026-09-15T12:00:00Z'

def price(day, instrument, close, known=AT):
    return dict(date=day, instrumentId=instrument, close=close, availableFrom=known,
                priceBasis='JQUANTS_ADJUSTED_CLOSE')

def test_ratio_uses_cash_indices_prior_us_date_and_current_available_corrections():
    jp = [price(d, 'NIKKEI_225_INDEX', 40000) for d in DAYS]
    us = [price(d, 'SP500_INDEX', 5000) for d in DAYS]
    jp[-1]['close'] = 39000
    result = ratio_rule(sessions=DAYS,nikkei_rows=jp,sp500_rows=us,cutoff=AT)
    assert result['conditionMet'] is True and result['sampleCount'] == 25
    assert result['pairedDates'][-1]['usDate'] == DAYS[-2]
    assert result['knowledgeTime'] == '2026-09-15T12:00:00+00:00'
    # Today's US bar is future for this JP comparison, never used.
    us[-1]['close']=1
    assert ratio_rule(sessions=DAYS,nikkei_rows=jp,sp500_rows=us,cutoff=AT)==result
    us[-2]['instrumentId']='SPY'
    assert ratio_rule(sessions=DAYS,nikkei_rows=jp,sp500_rows=us,cutoff=AT)['pairedDates'][-1]['usDate']==DAYS[-3]
    assert ratio_rule(sessions=DAYS,nikkei_rows=jp[:-1],sp500_rows=us,cutoff=AT)['conditionMet'] is None
    assert not result['historicalVintageVerified'] and not result['actionAuthority']

def test_eps_exact_ten_sessions_basis_boundary_receipt_and_correction():
    rows=[dict(date=d,eps=4000,basis=EPS_BASIS,knownAt=AT) for d in DAYS]
    rows[-1]['eps']=3999
    result=eps_rule(sessions=DAYS,eps_rows=rows,cutoff=AT)
    assert result['conditionMet'] and result['comparisonDate']==DAYS[-11]
    correction={**rows[-1],'eps':5000,'knownAt':'2026-09-16T00:00:00Z'}
    assert eps_rule(sessions=DAYS,eps_rows=rows+[correction],cutoff=AT)==result
    rows[-11]['basis']='LEGACY_INDEX_PER'
    assert eps_rule(sessions=DAYS,eps_rows=rows,cutoff=AT)['state']=='DATA_GATED'
    rows[-11]['basis']=EPS_BASIS;rows[-1]['eps']=4000
    assert eps_rule(sessions=DAYS,eps_rows=rows,cutoff=AT)['conditionMet'] is False
    rows[-11]['receivedAt']='2026-09-16T00:00:00Z'
    assert eps_rule(sessions=DAYS,eps_rows=rows,cutoff=AT)['state']=='DATA_GATED'

def cohort():
    members=[str(1000+i) for i in range(225)]
    membership={d:members for d in DAYS[-10:]}
    coverage={d:dict(memberCodes=members,complete=True,knownAt=AT) for d in DAYS[-10:]}
    financial=[]; stocks={}; topix=[price(d,'TOPIX_INDEX',2000) for d in DAYS]
    for i,code in enumerate(members[:5]):
        for day,amount in ((DAYS[-20],100),(DAYS[-3],110)):
            financial.append(dict(summary=dict(Code=code,DiscDate=day,DiscNo=code+day,
                CurFYEn='2027-03-31',FOP=amount),knownAt=AT,
                publishedAt=day+'T07:00:00Z'))
        stocks[code]=[price(d,code,100 if d!=DAYS[-2] else 99 if i<3 else 101) for d in DAYS]
    return dict(sessions=DAYS,financial_rows=financial,membership_by_day=membership,
        coverage_by_day=coverage,stock_bars=stocks,topix_rows=topix,cutoff=AT)

def test_earnings_same_fiscal_revision_cohort_adjusted_topix_and_duplicate_originals():
    data=cohort();before=deepcopy(data)
    result=earnings_rule(**data)
    assert result['state']=='ACTIVE' and result['goodEarningsCount']==5
    assert result['underperformedCount']==3 and result['value']==.6
    assert data==before
    data['financial_rows'] += deepcopy(data['financial_rows'])
    assert earnings_rule(**data)==result
    data['stock_bars']['1000'][-2]['priceBasis']='UNADJUSTED'
    assert earnings_rule(**data)['state']=='DATA_GATED'

def test_earnings_missing_market_coverage_or_following_close_not_clear():
    data=cohort();data['coverage_by_day'].pop(DAYS[-1])
    assert earnings_rule(**data)['conditionMet'] is None
    data=cohort();data['financial_rows']=data['financial_rows'][:-2]
    assert earnings_rule(**data)['goodEarningsCount']==4
    data=cohort();data['financial_rows'][-1]['summary']['CurFYEn']='2028-03-31'
    assert earnings_rule(**data)['goodEarningsCount']==4
    assert earnings_rule(**data)['missingComparisonCases']==1
    data=cohort();data['coverage_by_day'][DAYS[-1]]['receivedAt']='2026-09-16T00:00:00Z'
    assert earnings_rule(**data)['conditionMet'] is None

def test_consolidated_and_nonconsolidated_equal_values_do_not_cross_lanes():
    data=cohort()
    # Equal current values must still compare to their own previous forecasts.
    first,second=data['financial_rows'][:2]
    first['summary'].update(FOP=200,FNCOP=100)
    second['summary'].update(FOP=110,FNCOP=110)
    assert earnings_rule(**data)['goodEarningsCount']==5

def test_signed_decimal_forecasts_are_not_silently_discarded():
    data=cohort()
    for row in data['financial_rows']:
        row['summary']['FOP']='-100.5' if row['summary']['DiscDate']==DAYS[-20] else '-50.5'
    assert earnings_rule(**data)['goodEarningsCount']==5

def test_five_measured_cases_cannot_hide_another_missing_original_forecast():
    data=cohort()
    missing={**data['financial_rows'][-1], 'summary':{**data['financial_rows'][-1]['summary'],
             'Code':'1005','DiscNo':'another-disclosure'}}
    data['financial_rows'].append(missing)
    result=earnings_rule(**data)
    assert result['goodEarningsCount']==5 and result['conditionMet'] is None
    assert result['missingComparisonCases']==1

def test_same_publication_conflicting_forecasts_are_ambiguous_not_last_row_wins():
    data=cohort()
    data['financial_rows'].append({**data['financial_rows'][1],
        'summary':{**data['financial_rows'][1]['summary'],'DiscNo':'correction','FOP':500}})
    assert earnings_rule(**data)['conditionMet'] is None

def historical_conflict(data, *, resolved):
    original=data['financial_rows'][0]
    day=DAYS[-25] if resolved else original['summary']['DiscDate']
    source={**original,'publishedAt':day+'T07:00:00Z',
            'summary':{**original['summary'],'DiscDate':day,'DiscNo':'old-first','FOP':90}}
    other={**source,'summary':{**source['summary'],'DiscNo':'old-second','FOP':95}}
    data['financial_rows'] += [source,other]


def test_resolved_old_conflict_does_not_gate_current_cohort_or_rewrite_inputs():
    data=cohort();expected=earnings_rule(**data)
    historical_conflict(data,resolved=True);before=deepcopy(data)
    assert earnings_rule(**data)==expected
    assert data==before
    data['financial_rows'].reverse()
    assert earnings_rule(**data)==expected


def test_unresolved_old_conflict_needed_by_current_revision_remains_gated():
    data=cohort();historical_conflict(data,resolved=False)
    result=earnings_rule(**data)
    assert result['state']=='DATA_GATED' and result['conditionMet'] is None
    assert '修正前' in result['reasonJa']
    data['financial_rows'].reverse()
    assert earnings_rule(**data)==result


def test_historical_ambiguity_is_not_resolved_by_equal_third_variant():
    data=cohort();historical_conflict(data,resolved=False)
    row=data['financial_rows'][-1]
    data['financial_rows'].append({**row,'summary':{**row['summary'],'DiscNo':'old-third'}})
    assert earnings_rule(**data)['conditionMet'] is None


def test_conflicts_outside_dated_cohort_do_not_gate_current_members():
    data=cohort();expected=earnings_rule(**data)
    first=data['financial_rows'][1]
    data['financial_rows'] += [{**first,'summary':{**first['summary'],'Code':'9999','DiscNo':'other-a','FOP':90}},
                             {**first,'summary':{**first['summary'],'Code':'9999','DiscNo':'other-b','FOP':95}}]
    assert earnings_rule(**data)==expected


def test_adopted_projection_preserves_old_evidence_and_rejects_corruption():
    from test_argus_warning_conditions import evidence
    from argus_warning_conditions import project_warning_conditions
    from jp_market_engine import _sha256
    rows={f:_empty(f,'missing') for f in ('D03','D04','D07')}
    rows['D07']=earnings_rule(**cohort())
    original=evidence();before=deepcopy(original)
    sealed=seal_candidates(cutoff=AT,results=rows)
    # Evidence must be sealed for the same cutoff, not a different day's facts.
    original['informationCutoff']=AT;original.pop('artifactId')
    original['artifactId']='jp-market-engine-evidence-'+_sha256(original)
    before=deepcopy(original)
    result=project_warning_conditions(original,cutoff=AT,adopted_rules=sealed)
    assert result['schemaVersion']=='jp-warning-conditions-v3'
    assert result['signals'][6]['state']=='ACTIVE'
    assert result['signals'][6]['performance']['evaluated']==0 and original==before
    assert result['signals'][0]['ruleId'].startswith('jp-warning-conditions-v2.')
    sealed['results']['D07']['conditionMet']=False
    assert project_warning_conditions(original,cutoff=AT,adopted_rules=sealed)['schemaVersion']=='jp-warning-conditions-v2'
    sealed.pop('artifactId');sealed['artifactId']='argus-adopted-warning-'+_sha256(sealed)
    assert project_warning_conditions(original,cutoff=AT,adopted_rules=sealed)['schemaVersion']=='jp-warning-conditions-v2'

@pytest.mark.parametrize('bad',[True,float('inf'),10**400])
def test_nonfinite_or_boolean_values_are_missing(bad):
    rows=[dict(date=d,eps=4000,basis=EPS_BASIS,knownAt=AT) for d in DAYS]
    rows[-1]['eps']=bad
    assert eps_rule(sessions=DAYS,eps_rows=rows,cutoff=AT)['conditionMet'] is None

def test_seal_is_separate_and_zero_authority():
    rows={f:_empty(f,'missing') for f in ('D03','D04','D07')}
    sealed=seal_candidates(cutoff=AT,results=rows)
    assert sealed['validationStatus']=='UNVALIDATED' and sealed['probability'] is None
    with pytest.raises(ValueError):seal_candidates(cutoff=AT,results={'D03':rows['D03']})


def test_price_reaction_scope_is_dated_and_is_not_a_warning_or_current_watchlist():
    from argus_warning_candidates import reaction_instruments
    data=cohort();before=deepcopy(data)
    args={key:data[key] for key in ('sessions','financial_rows','membership_by_day','cutoff')}
    assert reaction_instruments(**args)==[str(1000+i) for i in range(5)]
    assert data==before
    # A recent forecast is an acquisition candidate even before it is a proven
    # good-earnings revision. Never count that price scope as a lit condition.
    args['financial_rows']=[data['financial_rows'][-1]]
    assert reaction_instruments(**args)==['1004']
    args['financial_rows']=[{**data['financial_rows'][-1],'knownAt':'2026-09-16T00:00:00Z'}]
    assert reaction_instruments(**args)==[]
    args['financial_rows']=[data['financial_rows'][0]]
    assert reaction_instruments(**args)==[]
    args['financial_rows']=[data['financial_rows'][-1]]
    args['membership_by_day']={}
    assert reaction_instruments(**args)==[]


def test_known_incomplete_eps_cannot_light_or_clear_the_rule_before_complete_correction():
    rows=[dict(date=d,eps=4000,basis=EPS_BASIS,knownAt=AT,
               coverage={'members':225,'missingMarketCap':0}) for d in DAYS]
    partial={**rows[-1],'eps':5000,'coverage':{'members':225,'missingMarketCap':200}}
    before=deepcopy(partial)
    assert eps_rule(sessions=DAYS,eps_rows=rows[:-1]+[partial],cutoff=AT)['conditionMet'] is None
    complete={**rows[-1],'eps':3999}
    result=eps_rule(sessions=DAYS,eps_rows=rows[:-1]+[partial,complete],cutoff=AT)
    assert result['conditionMet'] is True and partial==before
    rows[-11]['coverage']['missingMarketCap']=1
    assert eps_rule(sessions=DAYS,eps_rows=rows[:-1]+[partial,complete],cutoff=AT)['conditionMet'] is None


@pytest.mark.parametrize('count',[0,1,4])
def test_complete_cohort_below_minimum_is_clear_without_unused_reaction_prices(count):
    data=cohort()
    data['financial_rows']=data['financial_rows'][:2*count]
    data['stock_bars']={};data['topix_rows']=[]
    before=deepcopy(data)
    result=earnings_rule(**data)
    assert result['status']=='AVAILABLE' and result['state']=='CLEAR'
    assert result['conditionMet'] is False and result['goodEarningsCount']==count
    assert result['underperformedCount'] is None
    assert result['threshold']=={'value':5,'operator':'>=','unit':'CASES'}
    assert result['value']==count and result['knowledgeTime']=='2026-09-15T12:00:00+00:00'
    assert result['validationStatus']=='UNVALIDATED' and result['probability'] is None
    assert data==before


def test_below_minimum_never_hides_missing_cohort_or_prior_forecast():
    data=cohort();data['financial_rows']=data['financial_rows'][:8]
    data['coverage_by_day'].pop(DAYS[-1])
    assert earnings_rule(**data)['conditionMet'] is None
    data=cohort();data['financial_rows']=data['financial_rows'][:8]
    data['financial_rows'].pop(0)
    result=earnings_rule(**data)
    assert result['state']=='DATA_GATED' and result['missingComparisonCases']==1


def test_complete_low_count_reaction_is_not_used_as_false_underperformance():
    data=cohort();data['financial_rows']=data['financial_rows'][:8]
    for rows in data['stock_bars'].values():
        rows[-2]['close']=1
    result=earnings_rule(**data)
    assert result['conditionMet'] is False and result['value']==4
    assert result['underperformedCount'] is None


def test_complete_low_count_is_admitted_to_v3_and_tampered_count_is_rejected():
    from argus_warning_candidates import admitted_results
    from jp_market_engine import _sha256
    data=cohort();data['financial_rows']=data['financial_rows'][:8]
    rows={f:_empty(f,'missing') for f in ('D03','D04','D07')}
    rows['D07']=earnings_rule(**data)
    sealed=seal_candidates(cutoff=AT,results=rows)
    assert admitted_results(sealed,AT)['D07']['state']=='CLEAR'
    for change in ({'value':3},{'goodEarningsCount':True},{'underperformedCount':0},
                   {'threshold':{'value':4,'operator':'>=','unit':'CASES'}},
                   {'threshold':{'value':5,'operator':'>=','unit':'FRACTION'}},
                   {'state':'ACTIVE','conditionMet':True}):
        bad=deepcopy(sealed);bad['results']['D07'].update(change);bad.pop('artifactId')
        bad['artifactId']='argus-adopted-warning-'+_sha256(bad)
        assert admitted_results(bad,AT) is None
    from test_argus_warning_conditions import evidence
    from argus_warning_conditions import project_warning_conditions
    original=evidence();original['informationCutoff']=AT;original.pop('artifactId')
    original['artifactId']='jp-market-engine-evidence-'+_sha256(original)
    projected=project_warning_conditions(original,cutoff=AT,adopted_rules=sealed)
    assert projected['schemaVersion']=='jp-warning-conditions-v3'
    assert projected['signals'][6]['state']=='CLEAR'
    assert projected['signals'][6]['distance']['unit']=='CASES'

@pytest.mark.parametrize('fault,field,text', [
    ('membership', 'missingMembershipDays', '日付別の225構成が不足'),
    ('receipt', 'missingReceiptDays', '全体取得の受領記録が不足'),
    ('partial', 'incompleteReceiptDays', '全体取得が未完了'),
    ('scope', 'scopeMismatchDays', '取得範囲と対象構成が不一致'),
    ('future', 'unavailableReceiptDays', '利用時点までの受領を確認できない'),
])
def test_earnings_coverage_failure_identifies_stage_without_exposing_company_inputs(fault, field, text):
    data = cohort(); day = DAYS[-3]
    if fault == 'membership': data['membership_by_day'].pop(day)
    elif fault == 'receipt': data['coverage_by_day'].pop(day)
    elif fault == 'partial': data['coverage_by_day'][day]['complete'] = False
    elif fault == 'scope': data['coverage_by_day'][day]['memberCodes'] = ['9999'] * 225
    else: data['coverage_by_day'][day]['receivedAt'] = '2026-09-16T00:00:00Z'
    before = deepcopy(data)
    result = earnings_rule(**data)
    assert result['state'] == 'DATA_GATED' and result['conditionMet'] is None
    assert result['value'] is None and result['probability'] is None and result['actionAuthority'] is False
    assert text in result['reasonJa']
    diagnostic = result['inputCoverage']
    assert diagnostic[field] == [day] and diagnostic['verifiedSessionCount'] == 9
    assert diagnostic['requiredSessionCount'] == 10
    assert set(diagnostic) == {'requiredSessionCount', 'verifiedSessionCount', 'missingMembershipDays',
        'missingReceiptDays', 'incompleteReceiptDays', 'scopeMismatchDays', 'unavailableReceiptDays'}
    assert data == before


def test_earnings_dated_coverage_lists_all_missing_days_in_calendar_order():
    data = cohort()
    for day in (DAYS[-2], DAYS[-8]): data['coverage_by_day'].pop(day)
    data['membership_by_day'].pop(DAYS[-5])
    result = earnings_rule(**data)
    assert result['inputCoverage']['missingReceiptDays'] == [DAYS[-8], DAYS[-2]]
    assert result['inputCoverage']['missingMembershipDays'] == [DAYS[-5]]
    assert result['inputCoverage']['verifiedSessionCount'] == 7
    assert '2日' in result['reasonJa'] and '1日' in result['reasonJa']
    data['coverage_by_day'] = dict(reversed(list(data['coverage_by_day'].items())))
    assert earnings_rule(**data) == result


def test_earnings_short_calendar_is_distinct_from_forecasts_and_reaction_prices():
    data = cohort(); data['sessions'] = DAYS[-10:]
    result = earnings_rule(**data)
    assert result['conditionMet'] is None and '営業日履歴が不足' in result['reasonJa']
    data = cohort(); data['stock_bars'] = {}
    result = earnings_rule(**data)
    assert result['reasonJa'] == '発表翌営業日の調整済み株価とTOPIXが不足'
    assert 'inputCoverage' not in result


def test_earnings_coverage_diagnostic_survives_existing_sealed_display_projection():
    from test_argus_warning_conditions import evidence
    from argus_warning_conditions import project_warning_conditions
    from jp_market_engine import _sha256
    data = cohort(); data['coverage_by_day'].pop(DAYS[-1])
    rows = {family: _empty(family, 'missing') for family in ('D03', 'D04', 'D07')}
    rows['D07'] = earnings_rule(**data)
    original = evidence(); original['informationCutoff'] = AT; original.pop('artifactId')
    original['artifactId'] = 'jp-market-engine-evidence-' + _sha256(original)
    result = project_warning_conditions(original, cutoff=AT,
        adopted_rules=seal_candidates(cutoff=AT, results=rows))
    signal = result['signals'][6]
    assert signal['reasonJa'] == '全体取得の受領記録が不足（1日）'
    assert signal['inputCoverage']['verifiedSessionCount'] == 9
    assert signal['state'] == 'DATA_GATED' and signal['conditionMet'] is None
    assert signal['performance']['evaluated'] == 0 and result['actionAuthority'] is False
