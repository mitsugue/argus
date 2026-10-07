"""銘柄決算の表示用投影。既存の日次取得・保存を共用し、予測や売買判断を作らない。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from collections.abc import Mapping
from zoneinfo import ZoneInfo
import math


def number(value):
    value = value.get('raw') if isinstance(value, Mapping) else value
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def day(value, market):
    value = value.get('raw') if isinstance(value, Mapping) else value
    try:
        if isinstance(value, str):
            return date.fromisoformat(value).isoformat()
        if number(value) is not None:
            return datetime.fromtimestamp(value, ZoneInfo('Asia/Tokyo' if market == 'JP' else 'America/New_York' if market == 'US' else 'UTC')).date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def market_today(*, at, market):
    return datetime.fromisoformat(at.replace('Z', '+00:00')).astimezone(
        ZoneInfo('Asia/Tokyo' if market == 'JP' else 'America/New_York')).date().isoformat()


def parse(symbol, market, payload, *, fetched_at, today):
    """Yahoo予定は推定。earningsHistory.quarterは発表日ではなく決算期末。"""
    try:
        modules = payload['quoteSummary']['result'][0]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(modules, Mapping) or market not in ('JP', 'US'):
        return None
    block = lambda name: modules.get(name) if isinstance(modules.get(name), Mapping) else {}
    result = {'symbol': symbol, 'market': market, 'source': 'Yahoo Finance', 'fetchedAt': fetched_at,
              'currency': None, 'next': None, 'previous': None, 'estimate': None, 'actionAuthority': False}
    currency = block('financialData').get('financialCurrency')
    if isinstance(currency, str) and len(currency) == 3 and currency.isalpha():
        result['currency'] = currency.upper()  # Reporting unit, including ADRs; never use listing unit here.
    calendar = block('calendarEvents').get('earnings')
    calendar = calendar if isinstance(calendar, Mapping) else {}
    dates = calendar.get('earningsDate')
    dates = dates[:8] if isinstance(dates, list) else []
    horizon = (date.fromisoformat(today) + timedelta(days=370)).isoformat()
    future = sorted({d for value in dates if (d := day(value, market)) and today <= d <= horizon})
    if future:
        result['next'] = {'from': future[0], 'to': future[-1], 'certainty': 'PROVIDER_ESTIMATE',
                          'timezone': 'Asia/Tokyo' if market == 'JP' else 'America/New_York'}
    history = block('earningsHistory').get('history')
    candidates = []
    for row in history[:16] if isinstance(history, list) else []:
        if not isinstance(row, Mapping):
            continue
        period = day(row.get('quarter'), 'UTC')
        actual, expected = number(row.get('epsActual')), number(row.get('epsEstimate'))
        if period and period <= today and actual is not None:
            candidates.append({'periodEnd': period, 'epsActual': actual, 'epsEstimate': expected,
                               'surprisePct': (actual - expected) / abs(expected) * 100 if expected else None})
    if candidates:
        result['previous'] = max(candidates, key=lambda row: row['periodEnd'])
    trends = block('earningsTrend').get('trend')
    for row in trends[:8] if isinstance(trends, list) else []:
        if not isinstance(row, Mapping) or row.get('period') != '0q':
            continue
        end = day(row.get('endDate'), market)
        if not end:
            continue
        eps = row.get('earningsEstimate') if isinstance(row.get('earningsEstimate'), Mapping) else {}
        revenue = row.get('revenueEstimate') if isinstance(row.get('revenueEstimate'), Mapping) else {}
        trend = row.get('epsTrend') if isinstance(row.get('epsTrend'), Mapping) else {}
        count = number(eps.get('numberOfAnalysts'))
        revenue_count = number(revenue.get('numberOfAnalysts'))
        result['estimate'] = {'periodEnd': end,
            'eps': number(eps.get('avg')) if count and count >= 1 and count.is_integer() else None,
            'epsLow': number(eps.get('low')), 'epsHigh': number(eps.get('high')),
            'analysts': int(count) if count and count >= 1 and count.is_integer() else None,
            'epsGrowthPct': number(eps.get('growth')) * 100 if number(eps.get('growth')) is not None else None,
            'revenue': number(revenue.get('avg')) if revenue_count and revenue_count >= 1 and revenue_count.is_integer() else None,
            'revenueAnalysts': int(revenue_count) if revenue_count and revenue_count >= 1 and revenue_count.is_integer() else None,
            'revenueGrowthPct': number(revenue.get('growth')) * 100 if number(revenue.get('growth')) is not None else None,
            'eps30DaysAgo': number(trend.get('30daysAgo'))}
        break
    if not any(result[key] for key in ('next', 'previous', 'estimate')):
        return None
    return result


def company_summary(observations, *, today):
    """既存J-Quants原入力から最新決算を投影。予想訂正を実績決算と混同しない。"""
    candidates = []
    for observation in observations:
        row = observation.get('summary', {})
        if not isinstance(row, Mapping) or 'FinancialStatements' not in str(row.get('DocType', '')):
            continue
        disclosed = day(row.get('DiscDate'), 'JP')
        if not disclosed or disclosed > today:
            continue
        def amount(key):
            try:
                value = float(row[key])
                return value if math.isfinite(value) else None
            except (ValueError, KeyError, TypeError):
                return None
        consolidated = amount('OP') is not None
        actual = amount('OP' if consolidated else 'NCOP')
        if actual is None:
            continue
        candidates.append({'disclosedDate': disclosed, 'periodEnd': day(row.get('CurPerEn'), 'JP'),
            'periodType': str(row.get('CurPerType') or '対象期')[:8], 'fiscalYearEnd': day(row.get('CurFYEn'), 'JP'),
            'operatingProfit': actual, 'forecastOperatingProfit': amount('FOP' if consolidated else 'FNCOP'),
            'consolidated': consolidated, 'source': 'J-Quants 決算短信', 'currency': 'JPY',
            'receivedAt': observation.get('receivedAt')})
    return max(candidates, key=lambda row: (row['disclosedDate'], row.get('receivedAt') or '')) if candidates else None


def attach(previous, result, *, earnings, success):
    """目標株価なしでも決算を保存。取得失敗は旧版・取得時刻を残す。"""
    old = previous.get('earnings') if isinstance(previous, Mapping) else None
    result = dict(result)
    if success:
        result['earnings'] = earnings
        result['earningsStatus'] = 'AVAILABLE' if earnings else 'NO_DATA'
    else:
        result['earnings'] = old
        result['earningsStatus'] = 'FETCH_FAILED'
    return result
