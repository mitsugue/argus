import copy
import math
from datetime import date, timedelta

import jp_market_level_map as m


def _inputs():
    days=[(date(2026,1,1)+timedelta(days=i)).isoformat()for i in range(100)]
    prices=[{'date':d,'close':1700+30*math.sin(i/4),
             'high':1706+30*math.sin(i/4),'low':1694+30*math.sin(i/4)}
            for i,d in enumerate(days)]
    eps={d:100+i%3 for i,d in enumerate(days)}
    mornings=[{'morningOf':d,'recordId':'synthetic-'+d,
               'rows':[{'side':s,'kinds':['PER_LINE'],'multiple':17,
                        'moving':True,'price':1700,'tier':'MAP'}for s in ['UP','DOWN']],
               'atrGuides':{'UP':[1730,1760,1790],'DOWN':[1670,1640,1610]}}
              for d in days[30:60]]
    return mornings,prices,eps


def test_strict_prior_eps_missing_zero_nonfinite_and_future_are_unchanged():
    eps={'2026-01-01':100,'2026-01-02':0,'2026-01-03':float('nan'),
         '2026-01-04':True,'2026-01-05':-2,'2026-01-06':float('inf'),
         '2026-01-09':'3'}
    view=m._ScoringEpsSeries(eps)
    expected=[None,None,('2026-01-01',100.0),('2026-01-05',-2.0),
              ('2026-01-05',-2.0),('2026-01-09',3.0)]
    for day,value in zip(['2025-12-31','2026-01-01','2026-01-02',
                          '2026-01-06','2026-01-09','2026-01-10'],expected):
        assert m.eps_before(view,day)==m.eps_before(eps,day)==value


def test_full_scoring_matches_uncached_lookup_and_reduces_source_scans(monkeypatch):
    inputs=_inputs();before=copy.deepcopy(inputs)
    class Counted(dict):
        scans=0
        def __iter__(self):
            self.scans+=1
            return super().__iter__()
    cached_source=Counted(inputs[2])
    actual=m.score_records(inputs[0],inputs[1],cached_source)
    # A direct reference implementation of the previous date lookup, with
    # no class or persistent cache, keeps all score rules under comparison.
    def uncached(source,day):
        earlier=[d for d in source if d<day and m._finite(source[d])]
        if not earlier:return None
        latest=max(earlier)
        return latest,float(source[latest])
    monkeypatch.setattr(m,'eps_before',uncached)
    monkeypatch.setattr(m,'_ScoringEpsSeries',lambda source:source)
    uncached_source=Counted(inputs[2])
    expected=m.score_records(inputs[0],inputs[1],uncached_source)
    assert actual==expected and list(actual)==list(expected)
    assert cached_source.scans<=len(inputs[1])
    assert uncached_source.scans>cached_source.scans*5
    assert inputs==before


def test_second_scoring_call_observes_revised_eps_without_reusing_first_call():
    mornings,prices,eps=_inputs()
    first=m.score_records(mornings,prices,eps)
    revised={k:1000 for k in eps}
    second=m.score_records(mornings,prices,revised)
    assert first!=second
    assert m.score_records(mornings,prices,eps)==first


def test_same_day_missing_result_is_cached_only_inside_one_scoring_view():
    class Counted(dict):
        scans=0
        def __iter__(self):
            self.scans+=1
            return super().__iter__()
    source=Counted({'2026-01-02':100})
    view=m._ScoringEpsSeries(source)
    assert m.eps_before(view,'2026-01-01')is None
    assert m.eps_before(view,'2026-01-01')is None
    assert source.scans==1
    source['2025-12-31']=90
    assert m.eps_before(m._ScoringEpsSeries(source),'2026-01-01')==('2025-12-31',90.0)
