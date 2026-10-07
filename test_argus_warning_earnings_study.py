import pytest
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


def test_explicit_reconstruction_is_separate_from_real_vintage_and_preserves_originals():
    data = inputs()
    for row in data['financial_rows']:
        row['receivedAt'] = data['cutoff']
    for row in data['coverage_by_day'].values():
        row['receivedAt'] = data['cutoff']
    for rows in [data['topix_rows'],*data['stock_bars'].values()]:
        for row in rows:
            row['receivedAt'] = data['cutoff']
    before = deepcopy(data)
    assert study(**data)['condition']['inputDays'] == 0
    report = study(**data,reconstruct=True)
    assert report['condition']['inputDays'] == 2
    assert report['availabilityBasis'] == 'RECONSTRUCTED_PUBLICATION_18JST_NOT_ARCHIVED_VINTAGE'
    assert report['historicalVintageVerified'] is False and report['validationStatus'] == 'UNVALIDATED'
    assert not report['tenYearOriginalCoverageComplete']
    assert data == before
    for row in data['financial_rows']:
        row['receivedAt'] = '2030-01-01T00:00:00Z'
    assert study(**data,reconstruct=True)['condition']['inputDays'] == 0


def test_conflicting_same_receipt_originals_are_not_first_row_wins():
    data = inputs()
    row = data['financial_rows'][1]
    data['financial_rows'].append({**row,'summary':{**row['summary'],'FOP':999}})
    with pytest.raises(ValueError,match='ambiguous_original'):
        study(**data,reconstruct=True)
