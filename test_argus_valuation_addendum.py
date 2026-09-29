from copy import deepcopy
import pytest
import jp_market_engine as engine
from jp_market_price_paths import VALUATION_BASIS

AT = '2026-09-15T10:00:00Z'


def valuation():
    return {'instrumentId':'NIKKEI_225_INDEX','basis':VALUATION_BASIS,'currency':'JPY',
        'date':'2026-09-03','indexClose':64214.48,'per':21.35,'knownAt':AT,'availableFrom':AT,
        'publishedAt':None,'sourceRef':'arithmetic-fixture:D04_20260903'}


def test_d04_uses_canonical_index_scale_with_reference_ladder_and_argus_threshold():
    """The original defines the 17x..21x ladder, not an activation multiple:
    the ladder is projected as reference levels (never support/resistance)
    and the family still lights nothing."""
    r=engine.evaluate_d04(cutoff=AT,analysis_instrument='NIKKEI_225_INDEX',index_valuation=valuation())
    assert r['status']=='AVAILABLE' and round(r['eps'],2)==3007.70
    assert r['epsLabelJa']=='終値・指数ベースPERから算出した概算EPS'
    assert r['conditionMet'] is True and r['probability'] is None          # 21.35x >= 19x
    assert r['activationRule']['multiple'] == 19 and r['activationRule']['lineage'] == 'ARGUS_CANDIDATE'
    assert r['conditionLineage'] == 'ARGUS_CANDIDATE' and '19倍' in r['conditionRuleJa']
    assert [lv['multiple'] for lv in r['levels']] == [17, 18, 19, 20, 21]
    assert all(lv['supportOrResistance'] is False and lv['classification'] == 'reference_level'
               for lv in r['levels'])
    assert r['levels'][0]['value'] == round(r['eps'] * 17, 2)
    assert r['band']['position'] == 'above_ladder' and r['band']['lowerMultiple'] == 21
    within = engine.evaluate_d04(cutoff=AT, analysis_instrument='NIKKEI_225_INDEX',
                                 index_valuation={**valuation(), 'per': 18.4})
    assert within['band'] == {'per': 18.4, 'position': 'within_ladder', 'lowerMultiple': 18,
                              'upperMultiple': 19, 'labelJa': '18倍〜19倍の帯'}
    assert within['conditionMet'] is False                                   # 18.4x < 19x
    edge = engine.evaluate_d04(cutoff=AT, analysis_instrument='NIKKEI_225_INDEX',
                               index_valuation={**valuation(), 'per': 19.0})
    assert edge['conditionMet'] is True
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
