"""Same PIT rows and every feature/audit result, without discarded proof work."""
from copy import deepcopy
import pytest
import jp_market_engine as engine
import jp_market_features as features
from test_jp_market_features import prices


def data(case):
    rows=prices('VIX',90,start=15,change=.1)
    rows[6]['metadata']={'receipts':[{'kind':'synthetic','flags':[1,2]}]}
    if case=='late':rows[7]['knownAt']='2026-10-01T12:00:00Z'
    if case=='future':rows.append({**rows[7],'revision':1,'value':60,'knownAt':'2027-01-01T00:00:00Z'})
    if case=='revision':rows.append({**rows[7],'revision':1,'value':60,'knownAt':'2026-08-10T12:00:00Z'})
    if case=='malformed':rows.extend([{**rows[7],'availableFrom':'bad'}, {**rows[8],'revision':True}])
    return {'price_series':{'vix':rows,'nikkei':prices('NIKKEI_225_INDEX',90),
        'sp500':prices('SP500_INDEX',90),'topix':prices('TOPIX_INDEX',90),
        'usdjpy':prices('USDJPY',90),'jp10y':prices('JP10Y',90,start=-.2,change=.001,unit='PERCENT')},
        'valuation_loss':[{'instrumentId':'MARKET','seriesId':'credit.valuation_loss_pct',
            'date':'2026-08-01','availableFrom':'2026-08-02T00:00:00Z','value':5,
            'unit':'PERCENT','signConvention':'LOSS_POSITIVE'}]}


@pytest.mark.parametrize('case',['normal','late','future','revision','malformed'])
def test_entire_replay_matches_the_former_default_selector_path(case,monkeypatch):
    source=data(case);before=deepcopy(source)
    cutoffs=['2026-07-01T23:59:59Z','2026-08-01T23:59:59Z','2026-08-20T23:59:59Z','2026-09-01T23:59:59Z']
    actual=features.build_feature_history(cutoffs=cutoffs,**source)
    old=engine.point_in_time_rows
    def former(rows,cutoff,**unused):return old(rows,cutoff)
    with monkeypatch.context() as change:
        change.setattr(features,'point_in_time_rows',former)
        change.setattr(engine,'point_in_time_rows',former)
        expected=features.build_feature_history(cutoffs=cutoffs,**source)
    assert actual==expected
    assert source==before
    assert actual['actionAuthority'] is False and actual['historicalVintageVerified'] is False


def test_rejected_conflicting_revision_is_unchanged(monkeypatch):
    rows=prices('VIX',60);rows.append({**rows[-1],'value':999})
    with pytest.raises(ValueError,match='conflicting_row_revision'):
        features._history(rows,'VIX','2026-09-01T00:00:00Z')


def test_mutable_row_metadata_never_aliases_input_or_another_read():
    rows=data('normal')['price_series']['vix'];before=deepcopy(rows)
    first=features._history(rows,'VIX','2026-09-01T00:00:00Z')
    second=features._history(rows,'VIX','2026-09-01T00:00:00Z')
    first[6]['metadata']['receipts'][0]['flags'].append(3)
    assert second[6]['metadata']['receipts'][0]['flags']==[1,2]
    assert rows==before


def test_unused_proof_work_is_omitted_but_primary_proof_and_admission_stay(monkeypatch):
    rows=prices('VIX',60);cutoff='2026-09-01T00:00:00Z'
    count=[];old=engine._sha256
    def hashed(value):count.append(1);return old(value)
    monkeypatch.setattr(engine,'_sha256',hashed)
    old_rows,proof=engine.point_in_time_rows(rows,cutoff);with_proof=len(count);count.clear()
    actual=features._history(rows,'VIX',cutoff)
    assert len(actual)==len(old_rows)==60
    assert len(count)<with_proof and proof['datasetHash'] and proof['futureRowsAdmitted'] is False
    assert all({k:v for k,v in row.items() if k!='numericValue'}==old for row,old in zip(actual,old_rows))


def test_nonfinite_history_input_is_rejected_on_both_selector_paths(monkeypatch):
    source=data('normal');source['price_series']['vix'][9]['value']=float('inf')
    with pytest.raises(ValueError):
        features.build_feature_history(cutoffs=['2026-09-01T23:59:59Z'],**source)
    old=engine.point_in_time_rows
    def former(rows,cutoff,**unused):return old(rows,cutoff)
    monkeypatch.setattr(features,'point_in_time_rows',former)
    monkeypatch.setattr(engine,'point_in_time_rows',former)
    with pytest.raises(ValueError):
        features.build_feature_history(cutoffs=['2026-09-01T23:59:59Z'],**source)
