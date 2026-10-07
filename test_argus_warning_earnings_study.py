from copy import deepcopy

from argus_warning_earnings_study import study
from test_argus_warning_candidates import cohort


def inputs():
    data = cohort()
    # Actual receipt times, not recently fetched history rewritten as old.
    for row in data['financial_rows']:
        row['knownAt'] = row['publishedAt']
    members = data['membership_by_day'][data['sessions'][-1]]
    data['membership_by_day'] = {day:list(members) for day in data['sessions']}
    data['coverage_by_day'] = {day:dict(memberCodes=list(members), complete=True,
                                     knownAt=day+'T08:00:00Z') for day in data['sessions']}
    for rows in [data['topix_rows'], *data['stock_bars'].values()]:
        for row in rows:
            row['availableFrom'] = row['date'] + 'T07:00:00Z'
    data['nikkei_rows'] = [dict(date=day, instrumentId='NIKKEI_225_INDEX', close=40000,
                              availableFrom=day+'T07:00:00Z') for day in data['sessions']]
    return data


def test_original_replay_keeps_missing_cohort_and_next_reaction_gated():
    data = inputs(); before = deepcopy(data)
    result = study(**data)
    # The last two closes can observe the five revisions' next-session bars.
    assert result['condition']['inputDays'] == 2
    assert result['condition']['inputStart'] == data['sessions'][-2]
    assert result['condition']['evaluated'] == 0
    assert result['condition']['gatedDays'] == 28
    assert result['availabilityBasis'] == 'ACTUAL_RETAINED_RECEIPTS_AT_DAILY_18JST'
    assert result['validationStatus'] == 'UNVALIDATED'
    assert not result['tenYearOriginalCoverageComplete']
    assert result['providerCalls'] == 0 and result['automaticAiCalls'] == 0
    assert data == before


def test_later_downloads_and_incomplete_scope_never_become_past_observations():
    data = inputs()
    for row in data['financial_rows']:
        row['receivedAt'] = data['cutoff']
    assert study(**data)['condition']['inputDays'] == 0
    data = inputs()
    data['coverage_by_day'][data['sessions'][-1]]['memberCodes'] = ['1000']
    result = study(**data)
    assert result['condition']['inputDays'] == 1
    assert result['condition']['evaluated'] == 0


def test_missing_adjusted_price_cannot_create_a_market_clear_state():
    data = inputs()
    data['stock_bars']['1000'][-2]['priceBasis'] = 'UNADJUSTED'
    assert study(**data)['condition']['inputDays'] == 0
