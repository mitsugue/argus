"""Definition-bound fiscal arithmetic. No providers, storage, LLM or trade authority."""
from copy import deepcopy
from datetime import datetime, date
import hashlib
import json
import math
import re

RULE_VERSION = 'jp-fiscal-pressure-v1'
METRICS = ('nominal_growth', 'effective_rate', 'primary_balance', 'debt_ratio')
COMMON = ('country', 'periodBasis', 'frequency', 'accountingBasis', 'debtDefinition')
FISCAL = ('governmentScope', 'balanceCoverage')
RULE = {
    'version': RULE_VERSION,
    'validationStatus': 'UNVALIDATED',
    'thresholdBasis': 'Zero crossings and changes exceeding source rounding uncertainty; not a crisis model',
    'watch': 'Adverse comparable fiscal change or positive mechanical pressure',
    'warning': 'Not enabled until the independent market assessment is connected',
    'criticalEnabled': False,
    'release': 'Complete comparable inputs, no adverse reasons, no unresolved market deterioration',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite_number_required')
    return float(value)


def mechanical_values(growth, rate, surplus, base_debt):
    """The same definition-bound arithmetic for official rows and private what-ifs."""
    growth, rate, surplus, base_debt = map(finite, (growth, rate, surplus, base_debt))
    if growth <= -100 or rate <= -100 or base_debt < 0:
        raise ValueError('invalid_fiscal_scenario_domain')
    effect = (rate-growth)/(100+growth)*base_debt
    result = {'growthPct': growth, 'effectiveRatePct': rate,
        'spreadPoints': growth-rate, 'primarySurplusPct': surplus,
        'priorDebtRatioPct': base_debt, 'interestGrowthEffectPoints': effect,
        'pressurePoints': effect-surplus,
        'mechanicalDebtRatioPct': base_debt+effect-surplus}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError('nonfinite_result')
    return result


def exceeds(value, threshold):
    return value > threshold and not math.isclose(value, threshold, rel_tol=1e-10, abs_tol=1e-12)


def _validate(row, metric, cutoff):
    if not isinstance(row, dict) or row.get('metric') != metric:
        raise ValueError('missing_or_wrong_metric:' + metric)
    finite(row.get('value'))
    if row.get('country') != 'JP' or row.get('priceBasis') != 'NOMINAL':
        raise ValueError('japan_nominal_required:' + metric)
    if row.get('periodBasis') not in ('FISCAL_YEAR', 'CALENDAR_YEAR') or row.get('frequency') != 'ANNUAL':
        raise ValueError('annual_period_required:' + metric)
    if type(row.get('year')) is not int or not 1900 <= row['year'] <= 2200:
        raise ValueError('year_required:' + metric)
    if row.get('unit') != 'PERCENT' or row.get('estimateType') not in ('ACTUAL', 'ESTIMATE', 'FORECAST'):
        raise ValueError('unit_or_estimate_type:' + metric)
    if row.get('estimateType') == 'FORECAST' and not row.get('scenario'):
        raise ValueError('forecast_case_required:' + metric)
    for key in ('accountingBasis', 'debtDefinition', 'governmentScope', 'balanceCoverage',
                'sourceUrl', 'sourceRevision', 'sourceHash', 'id'):
        if not isinstance(row.get(key), str) or not row[key]:
            raise ValueError('definition_or_provenance_missing:' + metric + ':' + key)
    if row.get('acquisitionStatus') != 'AVAILABLE':
        raise ValueError('acquisition_unavailable:' + metric)
    if not re.fullmatch('[a-f0-9]{64}', row['sourceHash']):
        raise ValueError('source_hash_required:' + metric)
    if not row['sourceUrl'].startswith('https://'):
        raise ValueError('source_url_required:' + metric)
    if instant(row['acquiredAt']) > cutoff or instant(row['knownAt']) > cutoff:
        raise ValueError('future_knowledge:' + metric)
    if instant(row['knownAt']) > instant(row['acquiredAt']):
        raise ValueError('knowledge_after_acquisition:' + metric)
    if row.get('publishedAt') is not None and instant(row['publishedAt']) > instant(row['knownAt']):
        raise ValueError('knowledge_before_publication:' + metric)
    if row.get('publishedDate') and date.fromisoformat(row['publishedDate']) > instant(row['knownAt']).date():
        raise ValueError('knowledge_before_publication_date:' + metric)
    if finite(row.get('roundingHalfWidth')) < 0:
        raise ValueError('rounding_uncertainty:' + metric)
    expected = {'nominal_growth': ('rateBasis', 'YEAR_OVER_YEAR'),
        'effective_rate': ('rateBasis', 'INTEREST_OVER_START_DEBT'),
        'primary_balance': ('ratioBasis', 'SURPLUS_OVER_CURRENT_GDP'),
        'debt_ratio': ('ratioBasis', 'END_DEBT_OVER_SAME_YEAR_GDP')}[metric]
    if row.get(expected[0]) != expected[1]:
        raise ValueError('measure_definition_mismatch:' + metric)
    if metric == 'debt_ratio' and row['value'] < 0:
        raise ValueError('negative_debt')


def _comparison(current, previous):
    if not previous or previous.get('status') != 'AVAILABLE':
        return {'status': 'UNAVAILABLE', 'reason': 'no_comparable_prior'}
    a, b = current['definition'], previous['definition']
    if any(a[k] != b.get(k) for k in (*COMMON, *FISCAL, 'estimateType', 'scenario')):
        return {'status': 'UNAVAILABLE', 'reason': 'prior_definition_mismatch'}
    if a['year'] not in (b['year'], b['year'] + 1):
        return {'status': 'UNAVAILABLE', 'reason': 'nonadjacent_period'}
    kind = 'REVISION' if a['year'] == b['year'] else 'ANNUAL_CHANGE'
    return {'status': 'AVAILABLE', 'kind': kind, 'fromYear': b['year'], 'toYear': a['year'],
        'priorId': previous['id'],
        'changes': {k: current['values'][k] - previous['values'][k]
            for k in ('growthPct', 'effectiveRatePct', 'spreadPoints', 'primarySurplusPct', 'pressurePoints')},
        'spreadChangeUncertainty': current['uncertainty']['spreadPoints'] + previous['uncertainty']['spreadPoints']}


def calculate(rows, *, as_of, previous=None):
    """Rows contain current g/r/PB and previous-year debt/GDP. PB surplus positive."""
    result = {'rule': deepcopy(RULE), 'asOf': as_of, 'status': 'UNAVAILABLE',
        'dataCompleteness': 'INCOMPLETE', 'values': None, 'warningLevel': 'UNKNOWN',
        'reasons': [], 'missing': [], 'actionAuthority': False, 'probability': None,
        'automaticAiCalls': 0, 'recordKind': 'FISCAL_REFERENCE',
        'limitations': ['Mechanical pressure excludes unobserved stock-flow adjustments.',
            'Market yields are not the effective rate on existing debt.',
            'No causal attribution, crisis forecast or stock-return probability.']}
    try:
        cutoff = instant(as_of)
        for metric in METRICS:
            _validate(rows.get(metric), metric, cutoff)
        g, r, pb, debt = (rows[k] for k in METRICS)
        for key in COMMON:
            if len({row[key] for row in (g, r, pb, debt)}) != 1:
                raise ValueError('incompatible_definition:' + key)
        for key in FISCAL:
            if len({row[key] for row in (r, pb, debt)}) != 1:
                raise ValueError('incompatible_definition:' + key)
        if r['year'] != g['year'] or pb['year'] != g['year'] or debt['year'] != g['year'] - 1:
            raise ValueError('incompatible_period')
        if any(row['estimateType'] != g['estimateType'] or row.get('scenario') != g.get('scenario') for row in (r, pb)):
            raise ValueError('incompatible_estimate_or_scenario')
        if debt['estimateType'] == 'FORECAST' and debt.get('scenario') != g.get('scenario'):
            raise ValueError('incompatible_prior_debt_scenario')
        if g['value'] <= -100 or r['value'] <= -100:
            raise ValueError('invalid_rate_domain')
        growth, rate, surplus, base_debt = (float(row['value']) for row in (g, r, pb, debt))
        values = mechanical_values(growth, rate, surplus, base_debt)
        definition = {k: r[k] for k in (*COMMON, *FISCAL, 'year', 'estimateType')}
        definition['scenario'] = g.get('scenario')
        # Interval propagation over the published rounding cells. A near-zero
        # rounded result is not a confirmed crossing of the debt-pressure sign.
        pressure_bounds = []
        for gv in (growth-g['roundingHalfWidth'], growth+g['roundingHalfWidth']):
            if gv <= -100:
                raise ValueError('growth_uncertainty_domain')
            for rv in (rate-r['roundingHalfWidth'], rate+r['roundingHalfWidth']):
                for bv in (max(0, base_debt-debt['roundingHalfWidth']), base_debt+debt['roundingHalfWidth']):
                    for pv in (surplus-pb['roundingHalfWidth'], surplus+pb['roundingHalfWidth']):
                        pressure_bounds.append((rv-gv)/(100+gv)*bv-pv)
        result.update(status='AVAILABLE', dataCompleteness='COMPLETE_FOR_MECHANICAL_CALCULATION',
            values=values, definition=definition, inputs=deepcopy(rows),
            uncertainty={'spreadPoints': g['roundingHalfWidth']+r['roundingHalfWidth'],
                'pressurePointsRange': [min(pressure_bounds), max(pressure_bounds)]},
            otherStockFlowAdjustments=None)
        # A scheduled reread is not a new revision or an excuse to drop the
        # original comparison reasons. Ignore only receipt-clock fields.
        def evidence_key(source):
            return digest({k: {field: value for field, value in row.items()
                if field not in ('acquiredAt', 'knownAt')} for k, row in source.items()})
        if (previous and previous.get('status') == 'AVAILABLE'
                and previous.get('recordKind') == 'FISCAL_REFERENCE'
                and previous.get('rule', {}).get('version') == RULE_VERSION
                and evidence_key(rows) == evidence_key(previous.get('inputs', {}))):
            retained = deepcopy(previous)
            retained['asOf'] = as_of
            return retained
        result['comparison'] = _comparison(result, previous)
        reasons = []
        if min(pressure_bounds) > 0:
            reasons.append('POSITIVE_MECHANICAL_PRESSURE')
        comp = result['comparison']
        if comp['status'] == 'AVAILABLE':
            changes = comp['changes']
            if exceeds(-changes['spreadPoints'], comp['spreadChangeUncertainty']):
                reasons.append('GROWTH_RATE_GAP_NARROWED')
            if (previous['values']['spreadPoints'] > previous['uncertainty']['spreadPoints']
                    and values['spreadPoints'] < -result['uncertainty']['spreadPoints']):
                reasons.append('GROWTH_RATE_GAP_REVERSED')
            if changes['primarySurplusPct'] < -(pb['roundingHalfWidth'] + previous['inputs']['primary_balance']['roundingHalfWidth']):
                reasons.append('PRIMARY_BALANCE_DETERIORATED')
            if comp['kind'] == 'REVISION' and g['estimateType'] == 'FORECAST':
                if changes['growthPct'] < -(g['roundingHalfWidth'] + previous['inputs']['nominal_growth']['roundingHalfWidth']):
                    reasons.append('GROWTH_FORECAST_REVISED_DOWN')
                if changes['effectiveRatePct'] > r['roundingHalfWidth'] + previous['inputs']['effective_rate']['roundingHalfWidth']:
                    reasons.append('EFFECTIVE_RATE_FORECAST_REVISED_UP')
        result.update(reasons=reasons, warningLevel='WATCH' if reasons else 'NO_TRIGGER')
        # Receipt time never makes identical evidence a new condition.
        identity = {'rule': RULE_VERSION, 'definition': definition, 'values': values,
            'inputIds': {k: row['id'] for k, row in rows.items()}, 'reasons': reasons}
        result['id'] = 'fiscal-' + digest(identity)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        result['missing'] = [str(exc)]
        result['status'] = 'DATA_GATED'
        result.update(values=None, warningLevel='UNKNOWN', dataCompleteness='INCOMPLETE')
    return result


def scenario(rows, *, as_of, growth_pct=None, effective_rate_pct=None):
    """Explicit effective-rate assumption only; never accept a market-yield alias."""
    changed = deepcopy(rows)
    assumptions = {}
    for metric, value in (('nominal_growth', growth_pct), ('effective_rate', effective_rate_pct)):
        if value is not None:
            changed[metric]['value'] = finite(value)
            assumptions[metric] = value
    result = calculate(changed, as_of=as_of)
    result.update(recordKind='HYPOTHETICAL_SCENARIO', assumptions=assumptions,
        officialHistoryWriteAllowed=False, notificationAllowed=False)
    if result.get('id'):
        result['id'] = 'fiscal-scenario-' + digest({'base':result['id'], 'assumptions':assumptions})
    return result


def reference_scenario(reference, *, as_of, growth_pct=None, effective_rate_pct=None):
    """Private dialogue what-if from an already calculated, source-bound case.

    The compact dialogue reference deliberately omits raw fiscal rows. This
    recomputes only the published mechanical expression, never its warning
    rule, official history, notifications, or an equity price forecast.
    """
    cutoff = instant(as_of)
    assumptions = {}
    for key, value in (('growthPct', growth_pct), ('effectiveRatePct', effective_rate_pct)):
        if value is not None:
            assumptions[key] = finite(value)
    if not assumptions:
        raise ValueError('fiscal_assumption_required')
    unavailable = {'status':'UNAVAILABLE','reason':'verified_fiscal_reference_required',
        'recordKind':'HYPOTHETICAL_SCENARIO','isHypothesis':True,
        'actionAuthority':False,'officialHistoryWriteAllowed':False,
        'notificationAllowed':False,'probability':None}
    try:
        if not isinstance(reference, dict) or reference.get('status') != 'AVAILABLE':
            return unavailable
        case = (reference.get('cases') or {}).get('baseline') or {}
        fiscal = case.get('fiscal') or {}
        if fiscal.get('status') != 'AVAILABLE' or not isinstance(fiscal.get('id'), str):
            return unavailable
        definition = fiscal.get('definition') or {}
        if (definition.get('country') != 'JP' or definition.get('frequency') != 'ANNUAL'
                or definition.get('periodBasis') not in ('FISCAL_YEAR','CALENDAR_YEAR')
                or definition.get('estimateType') not in ('ACTUAL','ESTIMATE','FORECAST')):
            return unavailable
        sources = reference.get('sources') or []
        if not sources or any(not isinstance(source, dict)
                or not re.fullmatch('[a-f0-9]{64}', str(source.get('sourceHash') or ''))
                or instant(source['knownAt']) > cutoff for source in sources):
            return unavailable
        current = fiscal.get('values') or {}
        base = mechanical_values(current['growthPct'], current['effectiveRatePct'],
            current['primarySurplusPct'], current['priorDebtRatioPct'])
        if any(not math.isclose(base[key], finite(current[key]), rel_tol=1e-10, abs_tol=1e-10)
                for key in base):
            return unavailable
        changed = mechanical_values(assumptions.get('growthPct', base['growthPct']),
            assumptions.get('effectiveRatePct', base['effectiveRatePct']),
            base['primarySurplusPct'], base['priorDebtRatioPct'])
        identity = {'sourceCaseId': fiscal['id'], 'assumptions': assumptions,
            'method': 'jp-fiscal-mechanical-what-if-v1'}
        return {'status':'AVAILABLE','id':'fiscal-scenario-'+digest(identity),
            'kind':'FISCAL_ASSUMPTION','recordKind':'HYPOTHETICAL_SCENARIO',
            'isHypothesis':True,'sourceReferenceId':reference.get('id'),
            'sourceCaseId':fiscal['id'],'definition':deepcopy(definition),
            'sourceKnownAt':max(sources,key=lambda source:instant(source['knownAt']))['knownAt'],
            'assumptions':assumptions,'baselinePressurePoints':base['pressurePoints'],
            'value':changed['pressurePoints'],'unit':'ポイント',
            'pressureChangePoints':changed['pressurePoints']-base['pressurePoints'],
            'calculatedValues':changed,'actionAuthority':False,
            'officialHistoryWriteAllowed':False,'notificationAllowed':False,
            'probability':None,'stockPriceForecast':None,
            'noteJa':'成長率・政府実効金利の明示した仮定による、債務GDP比の機械的な圧力です。'
                '基礎的財政収支と前年度の債務比率は保存時点の値に固定しています。'
                '市場の10年国債利回りではなく、政府の実効金利を仮定しています。'
                '実績・正式予測・財政危機や株価方向の予測ではありません。'}
    except (KeyError, TypeError, ValueError, OverflowError):
        return unavailable


def transition(previous, current):
    """Candidate transition only; caller persists through existing stores and delivery controls."""
    if current.get('recordKind') != 'FISCAL_REFERENCE' or current.get('status') != 'AVAILABLE':
        return {'event': None, 'effectiveState': deepcopy(previous),
            'assessmentStatus': current.get('status'), 'releaseAllowed': False}
    before = (previous or {}).get('warningLevel')
    after = current['warningLevel']
    if previous and (current.get('comparison', {}).get('status') != 'AVAILABLE'
            or current['comparison'].get('priorId') != previous.get('id')):
        # An unrelated government scope, period or forecast case cannot clear
        # or replace the last accepted warning. Identical rereads are harmless.
        return {'event': None, 'effectiveState': deepcopy(previous),
            'assessmentStatus': 'UNCHANGED' if previous.get('id') == current.get('id') else 'NOT_COMPARABLE',
            'releaseAllowed': False}
    if after == 'NO_TRIGGER' and current['uncertainty']['pressurePointsRange'][1] > 0:
        return {'event': None, 'effectiveState': deepcopy(previous),
            'assessmentStatus': 'ROUNDING_INDETERMINATE', 'releaseAllowed': False}
    kind = ('NEW_WATCH' if before in (None, 'NO_TRIGGER') and after == 'WATCH'
        else 'RELEASED' if before in ('WATCH', 'WARNING') and after == 'NO_TRIGGER'
        else 'EVIDENCE_UPDATED' if before in ('WATCH', 'WARNING') and after in ('WATCH', 'WARNING')
            and (previous or {}).get('id') != current['id'] else None)
    event = None if kind is None else {'kind':kind, 'from':before, 'to':after,
        'evidenceId':current['id'], 'ruleVersion':RULE_VERSION,
        'deduplicationKey':digest({'kind':kind, 'prior':(previous or {}).get('id'), 'current':current['id']}),
        'actionAuthority':False, 'deliveryConfirmed':False}
    return {'event':event, 'effectiveState':deepcopy(current), 'assessmentStatus':'AVAILABLE',
        'releaseAllowed':kind=='RELEASED'}


MARKET_RULE = {
    'version': 'jp-fiscal-market-watch-v1', 'validationStatus':'UNVALIDATED',
    'comparisonSessions':5, 'confirmationSessions':3,
    'changeThreshold':'Positive change beyond the sum of published rounding bounds',
    'jgbCondition':'At least two of the 10/20/30/40-year series increase over five observed sessions and the last three sessions',
    'fxCondition':'USD/JPY increases over five observed sessions and the last three sessions',
    'release':'All previously adverse categories are fresh and no longer satisfy the same condition',
    'causalityConfirmed':False, 'criticalEnabled':False,
}


def market_assessment(observations, *, expected_session, as_of):
    """Daily market change is separate from fiscal g/r and any attribution."""
    cutoff = instant(as_of)
    date.fromisoformat(expected_session)
    expected = {'jp.market.jgb.'+str(t)+'y':'MARKET_YIELD' for t in (10,20,30,40)}
    expected['fx.usdjpy'] = 'FX_SPOT'
    views = {}
    for series_id, basis in expected.items():
        relevant = [row for row in observations if row.get('seriesId') == series_id]
        view = {'status':'MISSING', 'adverse':None, 'seriesId':series_id}
        try:
            by_session = {}
            for row in relevant:
                if instant(row['knownAt']) > cutoff:
                    continue
                session = row['sessionDate']; date.fromisoformat(session)
                if session > expected_session:
                    continue
                if row['rateBasis'] != basis or row.get('unit') != ('JPY_PER_USD' if basis == 'FX_SPOT' else 'PERCENT'):
                    raise ValueError('market_definition_mismatch')
                prior = by_session.get(session)
                if prior and prior['id'] != row['id']:
                    raise ValueError('unresolved_market_revision')
                by_session[session] = row
            ordered = [by_session[k] for k in sorted(by_session)]
            if not ordered:
                views[series_id] = view; continue
            latest = ordered[-1]
            view.update(observedAt=latest['sessionDate'], sourceUrl=latest.get('sourceUrl'),
                latestValue=latest.get('value'), inputIds=[row['id'] for row in ordered[-6:]])
            if latest['sessionDate'] != expected_session:
                view['status'] = 'UPDATE_DUE'; views[series_id] = view; continue
            if len(ordered) < 6:
                view['status'] = 'INSUFFICIENT_COMPARISON'; views[series_id] = view; continue
            window = ordered[-6:]
            if any(row.get('acquisitionStatus') != 'AVAILABLE' or row.get('value') is None for row in window):
                view['status'] = 'MISSING_COMPARISON'; views[series_id] = view; continue
            for row in window:
                finite(row['value'])
                if finite(row['roundingHalfWidth']) < 0:raise ValueError('market_rounding')
            # Refuse a hidden change of instrument/compounding/source within a window.
            for field in ('instrument','compounding','sourceUrl','tenorYears'):
                if len({row.get(field) for row in window}) != 1:
                    raise ValueError('market_series_definition_changed')
            delta = latest['value']-window[0]['value']
            threshold = latest['roundingHalfWidth']+window[0]['roundingHalfWidth']
            confirmed = all(exceeds(b['value']-a['value'], a['roundingHalfWidth']+b['roundingHalfWidth'])
                for a,b in zip(window[-3:],window[-2:]))
            view.update(status='AVAILABLE', adverse=exceeds(delta, threshold) and confirmed,
                change=delta, comparisonFrom=window[0]['sessionDate'], comparisonTo=latest['sessionDate'],
                comparisonSessions=5, confirmationSessions=3, threshold=threshold)
        except (ValueError,TypeError,KeyError) as exc:
            view.update(status='DEFINITION_OR_DATA_ERROR', error=str(exc), adverse=None)
        views[series_id] = view
    jgb = [row for sid,row in views.items() if sid.startswith('jp.market.jgb.')]
    jgb_known = sum(row['status']=='AVAILABLE' for row in jgb)
    jgb_adverse = sum(row.get('adverse') is True for row in jgb)
    groups = {'JGB': {'status':'AVAILABLE' if jgb_known==4 else 'PARTIAL' if jgb_known else 'MISSING',
        'adverse':True if jgb_adverse>=2 else False if jgb_known==4 else None},
        'FX':{'status':views['fx.usdjpy']['status'], 'adverse':views['fx.usdjpy']['adverse']}}
    adverse = sorted(key for key,row in groups.items() if row['adverse'] is True)
    body = {'rule':deepcopy(MARKET_RULE), 'series':views, 'groups':groups,
        'adverseGroups':adverse, 'auctionStatus':'NOT_CONNECTED',
        'status':'AVAILABLE' if all(row['status']=='AVAILABLE' for row in groups.values()) else 'PARTIAL',
        'warningLevel':'WATCH' if adverse else 'NO_TRIGGER' if all(row['adverse'] is False for row in groups.values()) else 'UNKNOWN',
        'actionAuthority':False, 'probability':None, 'causalityConfirmed':False}
    body['id']='fiscal-market-'+digest(body)
    return body


def environment_assessment(fiscal, market, *, previous=None):
    """Combine independent lanes, retaining the last warning across missing data."""
    known_fiscal = fiscal.get('status') == 'AVAILABLE'
    groups = market.get('adverseGroups') or []
    fiscal_watch = known_fiscal and fiscal.get('warningLevel') == 'WATCH'
    complete = known_fiscal and market.get('status') == 'AVAILABLE'
    level = ('WARNING' if fiscal_watch and len(groups)>=2 else
        'WATCH' if fiscal_watch or groups else 'NO_TRIGGER' if complete else 'UNKNOWN')
    reasons = (['FISCAL:'+reason for reason in fiscal.get('reasons', [])] if known_fiscal else [])
    reasons += ['MARKET:'+group for group in groups]
    prior_level = (previous or {}).get('warningLevel')
    rank = {'UNKNOWN':-1, 'NO_TRIGGER':0, 'WATCH':1, 'WARNING':2}
    comparable = True
    if previous:
        prior_fiscal = previous.get('lastComparableFiscal') or previous.get('fiscal') or {}
        comparable = (fiscal.get('id') == prior_fiscal.get('id') or
            fiscal.get('comparison', {}).get('priorId') == prior_fiscal.get('id'))
        if fiscal.get('rule', {}).get('version') != prior_fiscal.get('rule', {}).get('version'):
            comparable = False
    rounding_clear = known_fiscal and fiscal['uncertainty']['pressurePointsRange'][1] <= 0
    can_lower = complete and comparable and (level != 'NO_TRIGGER' or rounding_clear)
    retained = prior_level in ('WATCH','WARNING') and (not can_lower) and rank[level] < rank[prior_level]
    if retained:
        level = prior_level
    body = {'recordKind':'FISCAL_ENVIRONMENT', 'ruleVersion':'jp-fiscal-environment-v1',
        'ruleValidation':'UNVALIDATED', 'fiscal':deepcopy(fiscal), 'market':deepcopy(market),
        'lastComparableFiscal':deepcopy(fiscal if known_fiscal and comparable else
            (previous or {}).get('lastComparableFiscal') or (previous or {}).get('fiscal')),
        'warningLevel':level, 'currentReasons':reasons,
        'dataCompleteness':'COMPLETE_FOR_CONNECTED_RULES' if complete else 'INCOMPLETE',
        'previousWarningRetained':retained,
        'retainedWarningEvidenceId':previous.get('retainedWarningEvidenceId') or previous['id'] if retained else None,
        'notConnected':['JGB_AUCTION_RESULTS','REFINANCING_MATURITY_SCHEDULE'],
        'actionAuthority':False, 'probability':None, 'causalityConfirmed':False,
        'releaseConditions':['Comparable fiscal inputs and fresh previously adverse market categories',
            'No active adverse reasons and rounding interval entirely nonpositive',
            'Missing acquisition is never evidence of release']}
    body['id']='fiscal-environment-'+digest({'rule':body['ruleVersion'],
        'fiscal':fiscal.get('id'), 'fiscalStatus':fiscal.get('status'), 'market':market.get('id'),
        'level':level, 'reasons':reasons, 'retained':body['retainedWarningEvidenceId']})
    event = None
    # Data-gated or different-scope updates are visible status, not releases.
    if comparable and not retained and known_fiscal and fiscal.get('recordKind')=='FISCAL_REFERENCE':
        material_update = previous and reasons != previous.get('currentReasons')
        if previous and not material_update:
            for metric, field in (('nominal_growth','growthPct'), ('effective_rate','effectiveRatePct'),
                    ('primary_balance','primarySurplusPct')):
                old_row = prior_fiscal.get('inputs', {}).get(metric)
                if old_row and exceeds(abs(fiscal['values'][field]-prior_fiscal['values'][field]),
                        fiscal['inputs'][metric]['roundingHalfWidth']+old_row['roundingHalfWidth']):
                    material_update = True
        kind = ('NEW_WATCH' if rank.get(prior_level,0)<=0 and rank[level]>0 else
            'ESCALATED' if rank.get(prior_level,0)>0 and rank[level]>rank[prior_level] else
            'RELEASED' if rank.get(prior_level,0)>0 and level=='NO_TRIGGER' and can_lower else
            'EVIDENCE_UPDATED' if material_update and rank[level]>0 and body['id']!=previous.get('id') else None)
        if kind:
            event={'kind':kind,'from':prior_level,'to':level,'evidenceId':body['id'],
                'deduplicationKey':digest({'kind':kind,'evidenceId':body['id']}),
                'ruleVersion':body['ruleVersion'],'actionAuthority':False,'deliveryConfirmed':False}
    body['notificationCandidate']=event
    if fiscal.get('recordKind')=='HYPOTHETICAL_SCENARIO':
        body.update(recordKind='HYPOTHETICAL_SCENARIO',notificationCandidate=None,
            officialHistoryWriteAllowed=False)
    return body
