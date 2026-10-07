from datetime import date,timedelta
from copy import deepcopy
import pytest

from argus_warning_candidates_history import study,performance_for
from jp_market_level_map import EPS_BASIS

def inputs():
    days=[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(900)]
    cutoff='2023-01-01T00:00:00Z'
    prices=[dict(date=d,instrumentId='NIKKEI_225_INDEX',close=40000+i,
                 availableFrom=d+'T07:00:00Z') for i,d in enumerate(days)]
    us=[dict(date=d,instrumentId='SP500_INDEX',close=4000+i%31,
             availableFrom=d+'T22:00:00Z') for i,d in enumerate(days)]
    # Recorded recently, reconstructed explicitly; not falsely dated as an original vintage.
    eps=[dict(date=d,eps=4000 if i%30<15 else 3900,basis=EPS_BASIS,
              recordedAt='2022-12-01T00:00:00Z') for i,d in enumerate(days)]
    return dict(sessions=days,nikkei_rows=prices,sp500_rows=us,eps_rows=eps,cutoff=cutoff)

def test_current_basis_rules_reconstructed_separately_and_not_predictively_validated():
    args=inputs();before=deepcopy(args);result=study(**args)
    assert result['conditions']['D04']['evaluated']>=20
    assert result['conditions']['D04']['status']=='NOT_ABOVE_BASELINE'
    assert result['conditions']['D04']['horizons']['5']['falls']==0
    assert result['conditions']['D04']['inputDays']==890
    assert result['conditions']['D07']['status']=='NOT_EVALUABLE'
    assert result['historicalVintageVerified'] is False and result['validationStatus']=='UNVALIDATED'
    assert not result['legacySupportResultsReused'] and result['predictiveProbabilities'] is None
    assert args==before and performance_for(result,'D04',args['cutoff'])['evaluated']>=20
    result['conditions']['D04']['evaluated']=999
    assert performance_for(result,'D04',args['cutoff']) is None

def test_future_receipts_old_basis_and_conflicting_corrections_never_enter_the_study():
    args=inputs();args['eps_rows']=[{**r,'recordedAt':'2024-01-01T00:00:00Z'} for r in args['eps_rows']]
    assert study(**args)['conditions']['D04']['inputDays']==0
    args=inputs();args['eps_rows']=[{**r,'basis':'ARGUS_PROXY_INDEX_BASED_PER'} for r in args['eps_rows']]
    assert study(**args)['conditions']['D04']['inputDays']==0
    args=inputs();args['eps_rows'].append({**args['eps_rows'][0],'eps':100})
    with pytest.raises(ValueError,match='ambiguous_eps'):study(**args)
