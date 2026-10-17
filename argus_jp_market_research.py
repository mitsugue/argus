"""Bounded reuse of already calculated Japanese market research snapshots.

No providers, model clients, backtests, or storage mutations are available here.
Packages travel with the existing immutable explanation and recovery stores.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import argus_today_intelligence as engine

SCHEMA = 'argus-jp-market-research-package-v1'
LOOKUP_SCHEMA = 'argus-jp-market-research-lookup-v1'
MAX_SNAPSHOTS = 1024
MAX_PACKAGE_BYTES = 65536
SYMBOLS = {'N225': ('日経平均', 'INDEX'), '1321': ('日経平均連動ETF（1321）', 'ETF')}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _instant(value):
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('research_time_requires_timezone')
    return instant


def package_from_snapshot(snapshot):
    """Wrap the original output without changing any computed value or gate."""
    if snapshot.get('symbol') not in SYMBOLS or snapshot.get('market') != 'JP':
        raise ValueError('research_instrument_outside_scope')
    if snapshot.get('methodVersion') != engine.METHOD_VERSION:
        raise ValueError('research_method_not_admitted')
    body = {k: v for k, v in snapshot.items() if k != 'id'}
    if snapshot.get('id') != 'today-' + _digest(body)[:24]:
        raise ValueError('research_source_integrity_failed')
    calibration = snapshot.get('calibration')
    if not isinstance(calibration, dict) or calibration.get('methodVersion') != engine.METHOD_VERSION:
        raise ValueError('research_calibration_missing')
    if calibration.get('calibrationVersion') != engine.CALIBRATION_VERSION:
        raise ValueError('research_calibration_version_not_admitted')
    _instant(snapshot['asOf'])
    symbol = snapshot['symbol']
    package = {'schemaVersion': SCHEMA,
        'packageId': 'jp-market-engine-calibration-JP-' + symbol,
        'instrumentId': 'JP:' + symbol + ':' + SYMBOLS[symbol][1],
        'labelJa': SYMBOLS[symbol][0], 'methodVersion': engine.METHOD_VERSION,
        'sourceStore': 'todayIntelligence.snapshots',
        'calculation': deepcopy(calibration),
        'actionAuthority': False, 'predictiveProbabilityValidated': False,
        'validationScope': 'stored_calibration_results_not_independent_holdout_acceptance'}
    package['packageVersion'] = _digest(package)
    if len(_json(package).encode()) > MAX_PACKAGE_BYTES:
        raise ValueError('research_package_bound_exceeded')
    return package


def lookup(state, *, cutoff):
    """Select latest eligible stored calculations; never compute a missing one."""
    at = _instant(cutoff)
    candidates = {}
    scanned = 0
    omitted = 0
    source = state.get('snapshots', []) if isinstance(state, dict) else []
    if not isinstance(source, list):
        source = []
    for row in source[-MAX_SNAPSHOTS:]:
        scanned += 1
        if not isinstance(row, dict) or row.get('symbol') not in SYMBOLS or row.get('market') != 'JP':
            continue
        try:
            if _instant(row['asOf']) > at:
                continue
        except (KeyError, TypeError, ValueError, AttributeError):
            omitted += 1
            continue
        symbol = row['symbol']
        if symbol not in candidates or row['asOf'] > candidates[symbol]['asOf']:
            candidates[symbol] = row
    packages, receipts, errors = [], [], []
    for symbol in SYMBOLS:
        row = candidates.get(symbol)
        if row is None:
            errors.append({'symbol': symbol, 'reason': 'no_stored_calculation'})
            continue
        try:
            package = package_from_snapshot(row)
            packages.append(package)
            receipts.append({'packageId': package['packageId'],
                'packageVersion': package['packageVersion'],
                'sourceSnapshotId': row['id'], 'calculatedAt': row['asOf']})
        except (TypeError, ValueError, KeyError) as exc:
            errors.append({'symbol': symbol, 'reason': str(exc)[:100]})
    return {'schemaVersion': LOOKUP_SCHEMA, 'packages': packages,
        'readReceipt': {'cutoff': cutoff, 'scannedSnapshots': scanned,
            'omittedSnapshots': max(0, len(source) - MAX_SNAPSHOTS) + omitted,
            'sources': receipts, 'errors': errors, 'mode': 'stored_calculation_only',
            'historicalFetches': 0, 'fullRecalculations': 0, 'automaticAiCalls': 0},
        'actionAuthority': False}


def explanation_facts(result):
    """Short references, with index and ETF coverage explicitly separated."""
    facts = []
    for package in result.get('packages', []):
        calculation = package['calculation']
        row = (calculation.get('horizons') or {}).get('5') or {}
        status = row.get('calibrationStatus')
        validation = ('基準モデル未達' if status == 'poor_calibration' else
                      '標本不足' if status in {'insufficient_sample', 'insufficient_history'} else
                      '独立期間の予測力受入は未完了')
        subject = {'labelJa': f"保存済み条件別予測研究（{package['labelJa']}）",
            'methodVersion': package['methodVersion'], 'instrumentId': package['instrumentId'],
            'horizonSessions': 5, 'calibrationStatus': status}
        text = (f"{subject['labelJa']}: "
            f"{calculation.get('historyStart')}〜{calculation.get('historyEnd')}、"
            f"{calculation.get('historyCount')}営業日。5営業日先の有効標本"
            f"{row.get('effectiveSampleCount', 0)}件。{validation}。売買根拠への自動昇格なし。"
            "この検証は別方式の過去局面重ね描きや、その参考経路の検証結果ではありません。")
        facts.append({'text': text, 'source': 'jp_market_research', 'priority': 'P2',
            'verification': 'UNCONFIRMED', 'validationSubject': subject, 'provenance': {
                'scope': 'published_metadata_snapshot', 'eventId': package['packageId'] + '-horizon-5',
                'revision': None, 'publishedAt': None, 'receivedAt': None,
                'observedAt': calculation.get('historyEnd'), 'url': None,
                'sourceLabel': '日本株分析エンジン・保存済み計算結果',
                'sourceRowSha256': package['packageVersion']}})
    return facts


def context_references(result):
    """Give the LLM only the selected numerical summaries, never ten-year rows."""
    refs = []
    for package in result.get('packages', []):
        c = package['calculation']
        refs.append({k: deepcopy(package[k]) for k in (
            'packageId', 'packageVersion', 'instrumentId', 'labelJa', 'methodVersion',
            'actionAuthority', 'predictiveProbabilityValidated', 'validationScope')})
        refs[-1].update({'appliesTo': 'stored_conditional_forecast',
            'doesNotValidate': ['current_analog_selection', 'historical_reference_paths'],
            'coverage': {k: c.get(k) for k in ('historyStart', 'historyEnd', 'historyCount')},
            'conditioning': deepcopy(c.get('marketConditioning')),
            'horizons': {h: {k: deepcopy(v.get(k)) for k in (
                'horizon', 'effectiveSampleCount', 'calibrationStatus', 'modelBrier',
                'baselineBrier', 'brierSkill', 'returnDistribution', 'calibrationDatasetHash')}
                for h, v in (c.get('horizons') or {}).items() if h in {'1', '5', '20'}}})
    if len(_json(refs).encode()) > 8192:
        return []
    return refs
