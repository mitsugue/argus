"""Owner-adopted ARGUS research rules, separate from original warning evidence.

Pure cached-input calculations. Missing coverage cannot become a clear signal;
retrospective downloads cannot certify a historical vintage or trading action.
"""
from collections.abc import Mapping
from datetime import date, datetime, time
from math import isfinite
import re
from zoneinfo import ZoneInfo

from jp_market_engine import _instant, _sha256
from jp_market_level_map import EPS_BASIS, estimate_input_usable

RULE_VERSION = 'jp-warning-conditions-v3'
SCHEMA = 'argus-adopted-warning-inputs-v1'
TOKYO = ZoneInfo('Asia/Tokyo')
RULES = {
    'D03': '日経平均÷S&P500が25営業日の移動平均より下（米国は前営業日まで）',
    'D04': '同じ方式の推計EPSが10営業日前より低い',
    'D07': '直近10営業日の営業利益予想上方修正が5件以上あり、半数以上が発表翌営業日にTOPIXを下回る',
}


def _number(value):
    try:
        return float(value) if type(value) in (int, float) and isfinite(value) and value > 0 else None
    except (ValueError, OverflowError):
        return None


def _row_time(row):
    known = _instant(row.get('knownAt') or row.get('availableFrom') or row.get('recordedAt'))
    received = _instant(row.get('receivedAt'))
    return max(known, received) if known is not None and received is not None else known


def _forecast(value):
    # The existing financial store preserves the provider's decimal strings.
    if isinstance(value, str) and re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        value = float(value)
    try:
        return float(value) if type(value) in (int, float) and isfinite(value) else None
    except (ValueError, OverflowError):
        return None


def _session_close(day):
    return datetime.combine(date.fromisoformat(day), time(15, 30), TOKYO)


def _calendar(days, cutoff):
    limit = _instant(cutoff)
    if limit is None or not isinstance(days, (list, tuple)) or len(days) > 3001 or list(days) != sorted(set(days)):
        raise ValueError('adopted_warning_official_calendar_required')
    return [day for day in days if _session_close(day) <= limit], limit


def _closes(rows, instrument, cutoff):
    if len(rows) > 6000:
        raise ValueError('adopted_warning_price_bound')
    result = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get('instrumentId') != instrument:
            continue
        day = row.get('date') or row.get('periodEnd')
        known, value = _row_time(row), _number(row.get('close'))
        try:
            date.fromisoformat(day)
        except (ValueError, TypeError):
            continue
        if known is None or known > cutoff or value is None:
            continue
        old = result.get(day)
        # Corrections apply only from their actual availability. Conflicting
        # prices at the same receipt are ambiguous, never last-row-wins.
        if old and known == old[1] and value != old[0]:
            raise ValueError('adopted_warning_ambiguous_price')
        if old is None or known > old[1]:
            result[day] = (value, known)
    return result


def _empty(family, reason):
    return {'family': family, 'ruleId': RULE_VERSION + '.' + family,
            'lineage': 'ARGUS_VALIDATION_RULE', 'ruleStatus': 'DEFINED',
            'conditionRuleJa': RULES[family], 'state': 'DATA_GATED', 'status': 'PARTIAL',
            'conditionMet': None, 'reasonJa': reason, 'value': None, 'distance': None,
            'knowledgeTime': None, 'historicalVintageVerified': False,
            'validationStatus': 'UNVALIDATED', 'actionAuthority': False, 'probability': None}


def _measured(row, *, value, threshold, operator, unit, known, day):
    met = value < threshold if operator == '<' else value >= threshold
    return {**row, 'state': 'ACTIVE' if met else 'CLEAR', 'status': 'AVAILABLE',
            'conditionMet': met, 'reasonJa': None, 'value': value,
            'threshold': {'value': threshold, 'operator': operator, 'unit': unit},
            'distance': {'signedFromBoundary': value-threshold, 'unit': unit, 'operator': operator,
                         'atBoundary': value == threshold, 'boundaryCounts': operator == '>='},
            'knowledgeTime': known.isoformat(), 'sourcePeriodEnd': day}


def ratio_rule(*, sessions, nikkei_rows, sp500_rows, cutoff):
    days, limit = _calendar(sessions, cutoff)
    out = _empty('D03', '現物指数の25営業日と前日の米国終値が不足')
    if len(days) < 25:
        return out
    jp = _closes(nikkei_rows, 'NIKKEI_225_INDEX', limit)
    us = _closes(sp500_rows, 'SP500_INDEX', limit)
    ratios, known, used = [], [], []
    for day in days[-25:]:
        if day not in jp:
            return out
        # Strictly earlier US date: the US close for the JP calendar date is
        # still in the future at the Japanese close. Never substitute SPY.
        candidates = [u for u in us if u < day]
        if not candidates:
            return out
        prior = max(candidates)
        # A missing US run cannot silently carry an arbitrarily old close.
        if (date.fromisoformat(day)-date.fromisoformat(prior)).days > 7:
            return out
        ratios.append(jp[day][0]/us[prior][0]); known += [jp[day][1], us[prior][1]]
        used.append({'japanDate': day, 'usDate': prior})
    average = sum(ratios)/25
    return {**_measured(out, value=ratios[-1], threshold=average, operator='<', unit='INDEX_RATIO',
                       known=max(known), day=days[-1]),
            'sampleCount': 25, 'movingAverage': average, 'pairedDates': used,
            'factNoteJa': f'現物指数の比率 {ratios[-1]:.4f}・25営業日平均 {average:.4f}'}


def eps_rule(*, sessions, eps_rows, cutoff):
    days, limit = _calendar(sessions, cutoff)
    out = _empty('D04', '同方式の当日と10営業日前の推計EPSが不足')
    if len(days) < 11 or len(eps_rows) > 6000:
        return out
    by_day = {}
    for row in eps_rows:
        if (not isinstance(row, Mapping) or row.get('basis') != EPS_BASIS
                or not estimate_input_usable(row)):
            continue
        day = row.get('date') or row.get('sessionDate')
        known, eps = _row_time(row), _number(row.get('eps'))
        if day in days and known is not None and known <= limit and eps is not None:
            old = by_day.get(day)
            if old and known == old[1] and eps != old[0]:
                raise ValueError('adopted_warning_ambiguous_eps')
            if old is None or known > old[1]:
                by_day[day] = (eps, known)
    current, prior = (by_day.get(day) for day in (days[-1], days[-11]))
    if current is None or prior is None:
        return out
    return {**_measured(out, value=current[0], threshold=prior[0], operator='<', unit='JPY_EPS',
                       known=max(current[1],prior[1]), day=days[-1]),
            'valuationBasis': EPS_BASIS, 'comparisonDate': days[-11],
            'comparisonEps': prior[0], 'changePct': 100*(current[0]/prior[0]-1),
            'factNoteJa': f'推計EPS {current[0]:.2f}円・10営業日前 {prior[0]:.2f}円'}


def earnings_rule(*, sessions, financial_rows, membership_by_day, stock_bars, topix_rows,
                  coverage_by_day, cutoff):
    days, limit = _calendar(sessions, cutoff)
    out = _empty('D07', '日経225全体の予想原本・対象構成・翌営業日の比較が不足')
    if len(days) < 11 or len(financial_rows) > 30000:
        return out
    window = set(days[-10:]); prior_by_code_fy = {}; events = {}; missed = 0; missing_comparisons = 0
    accepted = []
    for row in financial_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get('summary'), Mapping):
            continue
        known, published = _row_time(row), _instant(row.get('publishedAt'))
        summary = row['summary']; day = summary.get('DiscDate'); code = str(summary.get('Code') or '')[:4]
        if known is None or known > limit or published is None or published > known or published > limit:
            continue
        if published.astimezone(TOKYO).date().isoformat() != day or not summary.get('DiscNo'):
            continue
        accepted.append((published, known, row))
    # Receipt time retains corrections; forecasts with the same disclosure ID
    # are a single event, not duplicate good-earnings cases.
    vintages = {}
    for published, known, row in accepted:
        s = row['summary']; key = (str(s.get('Code'))[:4], s.get('DiscDate'), s.get('DiscNo'))
        if key not in vintages or known > vintages[key][1]:
            vintages[key] = (published,known,row)
    for published, known, row in sorted(vintages.values(), key=lambda x:(x[0],x[1],str(x[2]['summary'].get('DiscNo')))):
        s=row['summary']; code=str(s['Code'])[:4]; day=s['DiscDate']; fy=s.get('CurFYEn')
        forecasts=[(fy,s.get('FOP'),'consolidated'),(fy,s.get('FNCOP'),'nonconsolidated'),
                   (s.get('NxtFYEn'),s.get('NxFOP'),'consolidated'),(s.get('NxtFYEn'),s.get('NxFNCOP'),'nonconsolidated')]
        revised=False; used_known=known; compared=False; has_forecast=False
        for fiscal, raw, lane in forecasts:
            value=_forecast(raw)
            # Consolidated/non-consolidated forecasts remain distinct.
            if not fiscal or value is None: continue
            has_forecast=True
            key=(code,fiscal,lane); prior=prior_by_code_fy.get(key)
            if prior and prior[2]==published and value!=prior[0]:
                return {**out,'reasonJa':'同じ公表時刻の営業利益予想が矛盾しています'}
            if prior and prior[2]<published and value>prior[0]:
                revised=True; used_known=max(used_known,prior[1])
            if prior and prior[2]<published: compared=True
            prior_by_code_fy[key]=(value,known,published)
        if day in window and has_forecast and not compared and code in (membership_by_day.get(day) or ()):
            missing_comparisons+=1
        if day not in window or not revised: continue
        members=membership_by_day.get(day)
        coverage=coverage_by_day.get(day)
        # Complete coverage must come from the existing date response receipt;
        # an empty response or five registered stocks is not a market cohort.
        if not isinstance(members,(list,tuple,set)) or len(set(members))!=225 or not isinstance(coverage,Mapping) \
                or coverage.get('complete') is not True or set(coverage.get('memberCodes') or ())!=set(members) \
                or (_row_time(coverage) is None or _row_time(coverage)>limit):
            missed+=1; continue
        if code in members:
            events[(code,day,s.get('DiscNo'))]=(used_known,_row_time(coverage))
    if missed:
        return {**out,'missingCoverageCases':missed}
    if missing_comparisons:
        return {**out,'goodEarningsCount':len(events),'missingComparisonCases':missing_comparisons,
                'reasonJa':'同じ年度の修正前の営業利益予想原本が不足'}
    # Every window date needs scope+receipt proof, even when it had no revisions.
    for day in window:
        cov=coverage_by_day.get(day); members=membership_by_day.get(day)
        if not isinstance(cov,Mapping) or cov.get('complete') is not True or not isinstance(members,(list,tuple,set)) \
                or len(set(members))!=225 or set(cov.get('memberCodes') or ())!=set(members) \
                or _row_time(cov) is None or _row_time(cov)>limit:
            return out
    if len(events)<5:
        return {**out,'goodEarningsCount':len(events),'reasonJa':'好決算の対象件数が5件未満'}
    topix=_closes(topix_rows,'TOPIX_INDEX',limit); measured=[]
    known=[_row_time(coverage_by_day[d]) for d in window]
    for (code,day,disc), stamps in events.items():
        following=next((d for d in days if d>day),None)
        previous=max((d for d in days if d<=day),default=None)
        if not following or not previous:
            return {**out,'goodEarningsCount':len(events),'reasonJa':'発表翌営業日の終値が未到着'}
        bars=_closes([r for r in stock_bars.get(code,()) if r.get('priceBasis')=='JQUANTS_ADJUSTED_CLOSE'],code,limit)
        if any(d not in bars or d not in topix for d in (previous,following)):
            return {**out,'goodEarningsCount':len(events),'reasonJa':'発表翌営業日の調整済み株価とTOPIXが不足'}
        relative=bars[following][0]/bars[previous][0]-topix[following][0]/topix[previous][0]
        measured.append(relative<0);known.extend([*stamps,bars[following][1],bars[previous][1],topix[following][1],topix[previous][1]])
    fraction=sum(measured)/len(measured)
    return {**_measured(out,value=fraction,threshold=.5,operator='>=',unit='FRACTION',known=max(known),day=days[-1]),
            'goodEarningsCount':len(measured),'underperformedCount':sum(measured),
            'factNoteJa':f'上方修正 {len(measured)}件・翌営業日にTOPIXを下回った {sum(measured)}件'}


def seal_candidates(*, cutoff, results, performance=None):
    if set(results) != set(RULES) or any(r.get('ruleId')!=RULE_VERSION+'.'+f for f,r in results.items()):
        raise ValueError('adopted_warning_rules_required')
    body={'schemaVersion':SCHEMA,'ruleVersion':RULE_VERSION,'informationCutoff':cutoff,
          'results':results,'performanceStudy':performance,'validationStatus':'UNVALIDATED','historicalVintageVerified':False,
          'actionAuthority':False,'automaticAiCalls':0,'probability':None}
    return {**body,'artifactId':'argus-adopted-warning-'+_sha256(body)}


def admitted_results(artifact, cutoff):
    from jp_market_engine import _content_id_valid
    if (not isinstance(artifact, Mapping) or artifact.get('schemaVersion') != SCHEMA
            or artifact.get('informationCutoff') != cutoff or artifact.get('ruleVersion') != RULE_VERSION
            or artifact.get('validationStatus') != 'UNVALIDATED'
            or artifact.get('historicalVintageVerified') is not False
            or artifact.get('actionAuthority') is not False or artifact.get('probability') is not None
            or not _content_id_valid(artifact, 'argus-adopted-warning-')):
        return None
    rows=artifact.get('results'); limit=_instant(cutoff)
    if not isinstance(rows, Mapping) or set(rows)!=set(RULES) or limit is None:
        return None
    for family,row in rows.items():
        if (not isinstance(row, Mapping) or row.get('ruleId') != RULE_VERSION+'.'+family
                or row.get('lineage') != 'ARGUS_VALIDATION_RULE' or row.get('actionAuthority') is not False
                or row.get('probability') is not None or row.get('validationStatus') != 'UNVALIDATED'):
            return None
        if row.get('state') not in ('ACTIVE','CLEAR'):
            if row.get('state')!='DATA_GATED' or row.get('conditionMet') is not None:
                return None
            continue
        known=_instant(row.get('knowledgeTime')); value=_forecast(row.get('value'))
        threshold=row.get('threshold') or {}; boundary=_forecast(threshold.get('value'))
        operator='>=' if family=='D07' else '<'
        if (known is None or known>limit or row.get('status')!='AVAILABLE' or value is None
                or boundary is None or threshold.get('operator')!=operator):
            return None
        met=value>=boundary if operator=='>=' else value<boundary
        if row.get('conditionMet') is not met or row.get('state')!=('ACTIVE' if met else 'CLEAR'):
            return None
        if family=='D03' and (row.get('sampleCount')!=25 or value<=0 or boundary<=0
                or row.get('movingAverage')!=boundary or threshold.get('unit')!='INDEX_RATIO'):return None
        if family=='D04' and (row.get('valuationBasis')!=EPS_BASIS or value<=0 or boundary<=0
                or row.get('comparisonEps')!=boundary or threshold.get('unit')!='JPY_EPS'):return None
        if family=='D07' and (type(row.get('goodEarningsCount')) is not int
                or row['goodEarningsCount']<5 or not 0<=value<=1 or boundary!=.5
                or type(row.get('underperformedCount')) is not int
                or row['underperformedCount']/row['goodEarningsCount']!=value
                or threshold.get('unit')!='FRACTION'):return None
    return rows


def reaction_instruments(*, sessions, financial_rows, membership_by_day, cutoff):
    """Price acquisition scope only: a forecast disclosure is not a lit warning."""
    days, limit = _calendar(sessions, cutoff)
    if len(financial_rows) > 30000 or len(days) < 10: return []
    recent = set(days[-10:]); codes = set()
    for row in financial_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get('summary'), Mapping): continue
        known, published = _row_time(row), _instant(row.get('publishedAt')); summary = row['summary']
        day = summary.get('DiscDate'); code = str(summary.get('Code') or '')[:4]
        members = membership_by_day.get(day)
        if (day not in recent or not isinstance(members, (list, tuple, set)) or len(set(members)) != 225
                or code not in members or known is None or known > limit or published is None
                or published > known or published > limit or published.astimezone(TOKYO).date().isoformat() != day): continue
        if any(fiscal and _forecast(value) is not None for fiscal, value in (
                (summary.get('CurFYEn'), summary.get('FOP')), (summary.get('CurFYEn'), summary.get('FNCOP')),
                (summary.get('NxtFYEn'), summary.get('NxFOP')), (summary.get('NxtFYEn'), summary.get('NxFNCOP')))):
            codes.add(code)
    return sorted(codes)
