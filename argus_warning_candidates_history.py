"""Separate retrospective study for the owner-adopted rules.

Downloaded histories can reconstruct a rule, but cannot certify the vintage
available to investors then. Original receipts and old grades are unchanged.
"""
from bisect import bisect_left
from datetime import date
from collections.abc import Mapping

from argus_warning_candidates import RULE_VERSION, _calendar, _closes, _forecast, _row_time
from jp_market_level_map import EPS_BASIS
from jp_market_engine import _sha256
from jp_market_sign_event_study import _condition, _empty_condition

METHOD='jp-warning-adopted-retrospective-v1'


def study(*, sessions, nikkei_rows, sp500_rows, eps_rows, cutoff):
    if len(eps_rows)>6000:raise ValueError('adopted_warning_eps_bound')
    days,limit=_calendar(sessions,cutoff)
    jp=_closes(nikkei_rows,'NIKKEI_225_INDEX',limit)
    us=_closes(sp500_rows,'SP500_INDEX',limit); us_days=sorted(us)
    eps={}
    for r in eps_rows:
        if not isinstance(r,Mapping) or r.get('basis')!=EPS_BASIS:continue
        known=_row_time(r); value=_forecast(r.get('eps')); day=r.get('date')
        if known is None or known>limit or value is None or value<=0:continue
        old=eps.get(day)
        if old and known==old[1] and value!=old[0]:raise ValueError('adopted_warning_ambiguous_eps')
        if old is None or known>old[1]:eps[day]=(value,known)
    ratios={}
    for day in days:
        i=bisect_left(us_days,day)-1
        if day in jp and i>=0 and (date.fromisoformat(day)-date.fromisoformat(us_days[i])).days<=7:
            ratios[day]=jp[day][0]/us[us_days[i]][0]
    points={'D03':[],'D04':[]}
    for i,day in enumerate(days):
        if i>=24 and all(d in ratios for d in days[i-24:i+1]):
            points['D03'].append((day,ratios[day]<sum(ratios[d] for d in days[i-24:i+1])/25))
        if i>=10 and day in eps and days[i-10] in eps:
            points['D04'].append((day,eps[day][0]<eps[days[i-10]][0]))
    conditions={}; position={d:i for i,d in enumerate(days)}
    closes={d:v[0] for d,v in jp.items() if d in position}
    for family,values in points.items():
        events={};previous=None
        for day,met in values:
            # A gap resets the transition; do not join unknown days.
            if previous and position[day]==position[previous[0]]+1 and met!=previous[1]:
                # Conservative publication assumption, explicitly retrospective.
                # The shared scorer enters at the following JP session's close.
                from jp_market_engine import _instant
                events[(RULE_VERSION+'.'+family,day)]=(_instant(day+'T09:00:00Z'),1 if met else -1)
            previous=(day,met)
        result=_condition(family,{'seriesId':RULE_VERSION+'.'+family,'value':1,'expects':'FALL'},events,closes,days)
        conditions[family]={**result,'ruleId':RULE_VERSION+'.'+family,'expects':'FALL',
            'evaluated':result.get('horizons',{}).get('5',{}).get('evaluated',0),
            'inputDays':len(values),'inputStart':values[0][0] if values else None,
            'inputEnd':values[-1][0] if values else None,'valuationBasis':EPS_BASIS if family=='D04' else None,
            'availabilityBasis':'RECONSTRUCTED_PUBLICATION_18JST_NOT_ARCHIVED_VINTAGE',
            'historicalVintageVerified':False,'validationStatus':'UNVALIDATED',
            'actionAuthority':False,'predictiveProbabilities':None}
    conditions['D07']={**_empty_condition('D07','NOT_EVALUABLE','full_financial_cohort_and_reaction_history_required'),
        'ruleId':RULE_VERSION+'.D07','evaluated':0,'expects':'FALL','actionAuthority':False,
        'predictiveProbabilities':None,'historicalVintageVerified':False,'validationStatus':'UNVALIDATED'}
    body={'schemaVersion':METHOD,'informationCutoff':cutoff,'ruleVersion':RULE_VERSION,
        'availabilityBasis':'RECONSTRUCTED_PUBLICATION_18JST_NOT_ARCHIVED_VINTAGE',
        'conditions':conditions,'historicalVintageVerified':False,'validationStatus':'UNVALIDATED',
        'sourceDigest':_sha256({'nikkei':nikkei_rows,'sp500':sp500_rows,'eps':eps_rows,'sessions':days}),
        'legacySupportResultsReused':False,'actionAuthority':False,'predictiveProbabilities':None}
    return {**body,'artifactId':'jp-warning-adopted-study-'+_sha256(body)}


def performance_for(report,family,cutoff):
    from jp_market_engine import _content_id_valid
    if (not isinstance(report,Mapping) or report.get('schemaVersion')!=METHOD
            or report.get('informationCutoff')!=cutoff or report.get('ruleVersion')!=RULE_VERSION
            or report.get('legacySupportResultsReused') is not False
            or report.get('historicalVintageVerified') is not False or report.get('validationStatus')!='UNVALIDATED'
            or report.get('actionAuthority') is not False or report.get('predictiveProbabilities') is not None
            or not _content_id_valid(report,'jp-warning-adopted-study-')):return None
    row=(report.get('conditions') or {}).get(family)
    return row if isinstance(row,Mapping) and row.get('ruleId')==RULE_VERSION+'.'+family else None
