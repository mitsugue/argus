"""Offline replay of adopted D07 using retained, dated original inputs.

No collection or store writes. This evaluator deliberately does not turn a
recent download into a vintage that was observable ten years ago.
"""
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, time

from argus_warning_candidates import RULE_VERSION, TOKYO, _calendar, _closes, earnings_rule
from jp_market_engine import _instant, _sha256
from jp_market_sign_event_study import _condition

METHOD = 'jp-warning-earnings-original-replay-v1'


def study(*, sessions, nikkei_rows, financial_rows, membership_by_day,
          stock_bars, topix_rows, coverage_by_day, cutoff):
    """Replay known originals after each close; forward outcomes are separate.

    Called offline, never from a public GET. Each replay uses only receipts
    observable by 18:00 JST that day; earnings_rule additionally requires the
    original prior forecast, the dated 225-member scope and next-session bars.
    Missing windows reset activation continuity, not become clear conditions.
    """
    days, limit = _calendar(sessions, cutoff)
    if (len(financial_rows) > 30000 or not isinstance(stock_bars, Mapping)
            or len(stock_bars) > 400 or sum(len(rows) for rows in stock_bars.values()) > 1200000
            or len(membership_by_day) > 3001 or len(coverage_by_day) > 3001):
        raise ValueError('earnings_replay_input_bound')
    prices = _closes(nikkei_rows, 'NIKKEI_225_INDEX', limit)
    closes = {day: value[0] for day, value in prices.items() if day in days}
    events, measured, reasons = {}, [], Counter()
    previous = None
    for index, day in enumerate(days):
        if index < 10:
            continue
        instant = datetime.combine(date.fromisoformat(day), time(18), TOKYO)
        if instant > limit:
            continue
        row = earnings_rule(sessions=days[:index+1], financial_rows=financial_rows,
            membership_by_day=membership_by_day, stock_bars=stock_bars, topix_rows=topix_rows,
            coverage_by_day=coverage_by_day, cutoff=instant.isoformat())
        if row.get('status') != 'AVAILABLE' or type(row.get('conditionMet')) is not bool:
            previous = None
            reasons['INPUT_OR_FOLLOWING_REACTION_NOT_OBSERVABLE'] += 1
            continue
        known = _instant(row.get('knowledgeTime'))
        if known is None or known > instant:
            raise ValueError('earnings_replay_future_knowledge')
        met = row['conditionMet']
        measured.append(day)
        if previous is not None and previous[0] == index-1 and previous[1] != met:
            events[(RULE_VERSION + '.D07', day)] = (instant, 1 if met else -1)
        previous = (index, met)
    result = _condition('D07', {'seriesId': RULE_VERSION + '.D07', 'value': 1, 'expects': 'FALL'},
                        events, closes, days)
    condition = {**result, 'ruleId': RULE_VERSION + '.D07', 'expects': 'FALL',
        'evaluated': result.get('horizons', {}).get('5', {}).get('evaluated', 0),
        'inputDays': len(measured), 'inputStart': measured[0] if measured else None,
        'inputEnd': measured[-1] if measured else None, 'gatedDays': sum(reasons.values()),
        'historicalVintageVerified': False, 'validationStatus': 'UNVALIDATED',
        'actionAuthority': False, 'predictiveProbabilities': None}
    body = {'schemaVersion': METHOD, 'informationCutoff': cutoff, 'ruleVersion': RULE_VERSION,
        'availabilityBasis': 'ACTUAL_RETAINED_RECEIPTS_AT_DAILY_18JST', 'condition': condition,
        'missingCounts': dict(reasons), 'requestedSessions': len(days),
        'tenYearOriginalCoverageComplete': False,
        'historicalVintageVerified': False, 'validationStatus': 'UNVALIDATED',
        'sourceDigest': _sha256({'sessions': days, 'nikkei': nikkei_rows, 'financial': financial_rows,
            'membership': membership_by_day, 'stocks': stock_bars, 'topix': topix_rows,
            'coverage': coverage_by_day}),
        'legacySupportResultsReused': False, 'actionAuthority': False,
        'automaticAiCalls': 0, 'providerCalls': 0, 'predictiveProbabilities': None}
    return {**body, 'artifactId': 'jp-warning-earnings-study-' + _sha256(body)}
