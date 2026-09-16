"""Bounded source adapters; no requests, LLM calls or writes during parsing."""
from copy import deepcopy
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import re

from argus_jp_fiscal_monitor import METRICS, calculate, digest, instant, market_assessment, environment_assessment

JGB_URL = 'https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv'
JGB_DEFINITION_URL = 'https://www.mof.go.jp/faq/jgbs/04ha.htm'
TABLE_PATH = Path(__file__).parent / 'ops/fiscal/cao_20260730.json'
# Explicit copy avoids implicitly admitting changed table editions.
TABLE_SOURCE_SHA = '7ed2aac791cb650c7ba975955bc562a84936fa0adf0927bb862baeb575e67cbe'


def reviewed_table():
    table = json.loads(TABLE_PATH.read_text())
    if (table.get('schemaVersion') != 'jp-fiscal-reviewed-table-v1'
            or table.get('sourceSha256') != TABLE_SOURCE_SHA
            or table.get('editionId') != 'cao-medium-term-20260730'):
        raise ValueError('unreviewed_table_edition')
    return table


def annual_rows(table, *, year, case, acquired_at):
    """Normalize one year's calculation inputs with prior-year debt, not forecasts as facts."""
    instant(acquired_at)
    if case not in table['cases'] or year not in table['years'] or year-1 not in table['years']:
        raise ValueError('period_or_case_unavailable')
    result = {}
    for metric in METRICS:
        period = year-1 if metric == 'debt_ratio' else year
        pos = table['years'].index(period)
        cell = table['cases'][case][metric][pos]
        kind = ('ACTUAL' if period <= table['actualThroughFiscalYear']
            else 'ESTIMATE' if period == 2025 else 'FORECAST')
        row = {**deepcopy(table['definition']), 'metric': metric, 'value': float(cell),
            'sourceCell': cell, 'roundingHalfWidth': 0.05, 'year': period,
            'estimateType': kind, 'scenario': case,
            'sourceUrl': table['sourceUrl'], 'sourceRevision': table['editionId'],
            'sourceHash': table['sourceSha256'], 'sourcePage': table['sourcePage'],
            'publishedDate': table['publishedDate'], 'publishedAt': table['publishedAt'],
            'knownAt': acquired_at, 'acquiredAt': acquired_at, 'acquisitionStatus': 'AVAILABLE'}
        row['id'] = 'fiscal-input-' + digest({'edition':table['editionId'], 'hash':table['sourceSha256'],
            'case':case, 'metric':metric, 'year':period, 'cell':cell, 'definition':table['definition']})
        if metric in ('nominal_growth', 'effective_rate'):
            row['rateBasis'] = 'YEAR_OVER_YEAR' if metric == 'nominal_growth' else 'INTEREST_OVER_START_DEBT'
        else:
            row['ratioBasis'] = 'SURPLUS_OVER_CURRENT_GDP' if metric == 'primary_balance' else 'END_DEBT_OVER_SAME_YEAR_GDP'
        result[metric] = row
    return result


def fiscal_report(table, *, fiscal_year, acquired_at, as_of):
    cases = {}
    for case in table['cases']:
        rows = annual_rows(table, year=fiscal_year, case=case, acquired_at=acquired_at)
        cases[case] = calculate(rows, as_of=as_of)
        cases[case]['sourceLimitations'] = deepcopy(table['limitations'])
    return {'cases':cases, 'periodBasis':'FISCAL_YEAR', 'fiscalYear':fiscal_year,
        'selectedCase':None, 'sourceEdition':table['editionId'],
        'sourcePublishedDate':table['publishedDate'], 'publishedAt':table['publishedAt'],
        'sourceUpdateStatus':'NOT_CHECKED', 'predictivePerformance':'UNVALIDATED',
        'fetchesDuringRead':0, 'aiCallsDuringRead':0}


def parse_jgb_csv(raw, *, acquired_at):
    """Current monthly constant-maturity market yields; never a fiscal effective rate."""
    cutoff = instant(acquired_at).date()
    if not isinstance(raw, bytes) or len(raw) > 512_000:
        raise ValueError('jgb_source_size')
    text = raw.decode('cp932')
    lines = list(csv.reader(io.StringIO(text)))
    if len(lines) < 3 or not lines[0][0].startswith('国債金利情報'):
        raise ValueError('jgb_source_layout')
    head = lines[1]
    required = ['10年', '20年', '30年', '40年']
    if head[0] != '基準日' or any(head.count(k) != 1 for k in required):
        raise ValueError('jgb_tenor_columns')
    source_hash = hashlib.sha256(raw).hexdigest()
    output = []; seen = set()
    for cells in lines[2:]:
        if not cells or not cells[0].strip() or cells[0].startswith('※'):
            continue
        match = re.fullmatch(r'([RH])(\d+)\.(\d+)\.(\d+)', cells[0])
        if not match or len(cells) != len(head):
            raise ValueError('jgb_date_or_columns')
        era, year, month, day = match.groups()
        session = date((2018 if era == 'R' else 1988)+int(year), int(month), int(day))
        if session > cutoff or session in seen:
            raise ValueError('jgb_future_or_duplicate_session')
        seen.add(session)
        for tenor in required:
            cell = cells[head.index(tenor)].strip()
            if cell in ('', '-', '－'):
                value = None
            elif re.fullmatch(r'-?\d+\.\d{1,3}', cell):
                value = float(cell)
            else:
                raise ValueError('jgb_value')
            row = {'seriesId':'jp.market.jgb.'+tenor[:-1]+'y', 'sessionDate':session.isoformat(),
                'value':value, 'unit':'PERCENT', 'instrument':'JGB_FIXED_COUPON_CONSTANT_MATURITY',
                'compounding':'SEMIANNUAL', 'tenorYears':int(tenor[:-1]),
                'rateBasis':'MARKET_YIELD', 'estimateType':'OBSERVED_MARKET',
                'sourceUrl':JGB_URL, 'definitionUrl':JGB_DEFINITION_URL,
                'sourceHash':source_hash, 'publishedAt':None,
                'knownAt':acquired_at, 'acquiredAt':acquired_at,
                'publicationSchedule':'NEXT_JP_BUSINESS_DAY_AROUND_09_30_JST',
                'acquisitionStatus':'AVAILABLE' if value is not None else 'MISSING',
                'roundingHalfWidth':0.0005}
            # Same historical cell in a revised monthly download keeps its identity.
            row['id'] = 'jgb-' + digest({k:row[k] for k in
                ('seriesId','sessionDate','value','instrument','compounding','rateBasis')})
            output.append(row)
    if not output:
        raise ValueError('jgb_empty_source')
    return sorted(output, key=lambda row:(row['sessionDate'],row['tenorYears']))


def ledger_series():
    """Dedicated forecast-case series avoid mixing cases into ordinary macro rows."""
    series = {}
    labels = dict(nominal_growth='名目成長率', effective_rate='実効金利',
        primary_balance='基礎的財政収支', debt_ratio='公債等残高GDP比')
    for case in ('baseline', 'growth_1', 'growth_2'):
        for metric, label in labels.items():
            series['jp.fiscal.'+case+'.'+metric] = ('PERCENT', label, 'cao', 'official')
    for tenor in (10,20,30,40):
        series['jp.market.jgb.'+str(tenor)+'y'] = ('PERCENT', str(tenor)+'年国債市場利回り', 'mof', 'official')
    return series


def annual_ledger_candidates(table, *, acquired_at):
    result = {}; instant(acquired_at)
    for case in table['cases']:
        for year in table['years'][1:]:
            for metric, row in annual_rows(table, year=year, case=case, acquired_at=acquired_at).items():
                sid = 'jp.fiscal.'+case+'.'+metric
                result[sid, row['year']] = {'seriesId':sid, 'periodEnd':str(row['year']+1)+'-03-31',
                    'availableFrom':acquired_at, 'publishedAt':row['publishedAt'],
                    'observedAt':acquired_at, 'source':row['sourceUrl'], 'sourceKind':'official',
                    'value':row['value'], 'unit':'PERCENT', 'status':'live',
                    'metadata':{'fiscalInput':row, 'excludeFromEffective':True,
                        'reason':'Dedicated fiscal view preserves forecast cases and definitions'}}
    return list(result.values())


def missing_ledger_candidates(state, candidates):
    """Compare source identities, not receipt clocks; never delete old revisions."""
    rolled = set(state.get('rolledBackImports') or [])
    known = {row.get('metadata', {}).get('fiscalInput', {}).get('id')
        for row in state.get('observations', []) if row.get('importId') not in rolled}
    return [row for row in candidates if row['metadata']['fiscalInput']['id'] not in known]


def ledger_fiscal_inputs(state, *, year, case, as_of):
    cutoff = instant(as_of); rolled = set(state.get('rolledBackImports') or [])
    groups = {}
    for observation in state.get('observations', []):
        if observation.get('importId') in rolled:
            continue
        row = observation.get('metadata', {}).get('fiscalInput')
        if not isinstance(row, dict) or row.get('scenario') != case:
            continue
        metric = row.get('metric')
        if metric not in METRICS or row.get('year') != (year-1 if metric == 'debt_ratio' else year):
            continue
        if instant(observation['availableFrom']) > cutoff or instant(row['knownAt']) > cutoff:
            continue
        # No mixed editions even when a partial revision arrived last.
        key = (row['sourceRevision'], row['sourceHash'])
        groups.setdefault(key, {})[metric] = deepcopy(row)
    complete = [rows for rows in groups.values() if set(rows) == set(METRICS)]
    if not complete:
        return {}
    return max(complete, key=lambda rows:max(instant(row['knownAt']) for row in rows.values()))


def market_ledger_candidates(rows):
    """Keep official market yields separate from annual fiscal effective interest."""
    result=[]
    for row in rows:
        if row.get('rateBasis')!='MARKET_YIELD' or row.get('seriesId') not in ledger_series():
            raise ValueError('unexpected_market_yield_series')
        result.append({'seriesId':row['seriesId'], 'periodEnd':row['sessionDate'],
            'availableFrom':row['knownAt'], 'observedAt':row['acquiredAt'],
            'publishedAt':row['publishedAt'], 'source':row['sourceUrl'], 'sourceKind':'official',
            'value':row['value'], 'unit':'PERCENT',
            'status':'live' if row['value'] is not None else 'missing',
            'metadata':{'fiscalMarketInput':deepcopy(row), 'excludeFromEffective':True,
                'reason':'Market yield is not government effective interest'}})
    return result


def missing_market_candidates(state, candidates):
    rolled=set(state.get('rolledBackImports') or [])
    latest={}
    for observation in state.get('observations',[]):
        if observation.get('importId') in rolled:continue
        row=observation.get('metadata',{}).get('fiscalMarketInput')
        if isinstance(row,dict):
            key=(row['seriesId'],row['sessionDate'])
            if key not in latest or instant(observation['availableFrom'])>=latest[key][0]:
                latest[key]=(instant(observation['availableFrom']),row['id'])
    # Compare with the latest revision, not every historic value: a correction
    # can legitimately restore a previously published value.
    return [c for c in candidates if latest.get((c['seriesId'],c['periodEnd']), (None,None))[1]
            !=c['metadata']['fiscalMarketInput']['id']]


def ledger_market_rows(state, *, as_of):
    cutoff=instant(as_of); rolled=set(state.get('rolledBackImports') or []); latest={}
    for observation in state.get('observations',[]):
        if observation.get('importId') in rolled:continue
        row=observation.get('metadata',{}).get('fiscalMarketInput')
        if not isinstance(row,dict) or instant(observation['availableFrom'])>cutoff or instant(row['knownAt'])>cutoff:
            continue
        key=(row['seriesId'],row['sessionDate']); at=instant(observation['availableFrom'])
        if key not in latest or at>=latest[key][0]:latest[key]=(at,deepcopy(row))
    return [latest[key][1] for key in sorted(latest)]


def ledger_environment_report(state, *, fiscal_year, expected_session, as_of,
                              fx_rows=(), previous=None, market_acquisition='AVAILABLE'):
    """Read the existing vintage ledger; keep alternative fiscal cases separate.

    The caller supplies the official expected session and acquisition outcome.
    A failed request retains recorded observations but cannot clear a warning.
    No fetch, persistence, model invocation or notification delivery occurs here.
    """
    instant(as_of)
    if market_acquisition not in ('AVAILABLE', 'UPDATE_WAIT', 'NOT_RUN', 'FAILED'):
        raise ValueError('unknown_market_acquisition_status')
    market = market_assessment([*ledger_market_rows(state, as_of=as_of), *fx_rows],
        expected_session=expected_session, as_of=as_of)
    market['acquisitionStatus'] = market_acquisition
    if market_acquisition in ('NOT_RUN', 'FAILED'):
        market['status'] = 'ACQUISITION_UNCONFIRMED'
        market['id'] = 'fiscal-market-' + digest({
            'recordedEvidenceId': market['id'], 'acquisitionStatus': market_acquisition})
    cases = {}
    for case in ('baseline', 'growth_1', 'growth_2'):
        prior = ((previous or {}).get('cases') or {}).get(case)
        prior_fiscal = (prior or {}).get('lastComparableFiscal') or (prior or {}).get('fiscal')
        if not prior_fiscal:
            prior_rows = ledger_fiscal_inputs(state, year=fiscal_year-1, case=case, as_of=as_of)
            prior_fiscal = calculate(prior_rows, as_of=as_of)
        rows = ledger_fiscal_inputs(state, year=fiscal_year, case=case, as_of=as_of)
        fiscal = calculate(rows, as_of=as_of, previous=prior_fiscal)
        cases[case] = environment_assessment(fiscal, market, previous=prior)
    body = {'schemaVersion':'jp-fiscal-ledger-report-v1', 'fiscalYear':fiscal_year,
        'periodBasis':'FISCAL_YEAR', 'asOf':as_of, 'cases':cases,
        'selectedCase':None, 'expectedMarketSession':expected_session,
        'actionAuthority':False, 'predictivePerformance':'UNVALIDATED',
        'fetchesDuringRead':0, 'aiCallsDuringRead':0, 'notificationsDelivered':False}
    body['id'] = 'fiscal-report-' + digest({
        'fiscalYear':fiscal_year, 'caseIds':{case:row['id'] for case,row in cases.items()}})
    return body
