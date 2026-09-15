from copy import deepcopy
import pytest
import jp_market_engine as engine
from jp_market_price_paths import VALUATION_BASIS

AT = '2026-09-15T10:00:00Z'


def valuation():
    return {'instrumentId':'NIKKEI_225_INDEX','basis':VALUATION_BASIS,'currency':'JPY',
        'date':'2026-09-03','indexClose':64214.48,'per':21.35,'knownAt':AT,'availableFrom':AT,
        'publishedAt':None,'sourceRef':'arithmetic-fixture:D04_20260903'}


def test_d04_uses_canonical_index_scale_without_fixed_bands_or_signal():
    r=engine.evaluate_d04(cutoff=AT,analysis_instrument='NIKKEI_225_INDEX',index_valuation=valuation())
    assert r['status']=='AVAILABLE' and round(r['eps'],2)==3007.70
    assert r['epsLabelJa']=='終値・指数ベースPERから算出した概算EPS'
    assert r['conditionMet'] is None and r['levels']==[] and r['probability'] is None
    assert r['actionAuthority'] is False and r['validationStatus']=='UNVALIDATED'
    assert r['valuation']['publishedAt'] is None


@pytest.mark.parametrize('changes', [
    {'basis':'WEIGHTED_AVERAGE'},{'instrumentId':'JP:1321:ETF'},
    {'knownAt':'2026-09-16T00:00:00Z'},{'knownAt':None,'availableFrom':None},{'per':0}])
def test_incompatible_or_future_valuation_does_not_fill_d04(changes):
    row={**valuation(),**changes}
    r=engine.evaluate_d04(cutoff=AT,analysis_instrument='NIKKEI_225_INDEX',index_valuation=row)
    assert r['status']=='MISSING' and r['conditionMet'] is None and r['eps'] is None


def test_combined_engine_accepts_same_valuation_without_changing_original_inputs():
    row=valuation();before=deepcopy(row)
    r=engine.evaluate_d01_d07(cutoff=AT,nikkei_valuation=row)
    assert r['families']['D04']['eps']==row['indexClose']/row['per']
    assert row==before
