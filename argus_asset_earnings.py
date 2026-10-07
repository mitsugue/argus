"""銘柄決算の表示用投影。既存の日次取得・保存を共用し、予測や売買判断を作らない。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from collections.abc import Mapping
from zoneinfo import ZoneInfo
import math


def number(value):
    value = value.get('raw') if isinstance(value, Mapping) else value
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def currency(value):
    return value.upper() if isinstance(value, str) and len(value) == 3 and value.isalpha() else None


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
    result['currency'] = currency(block('financialData').get('financialCurrency'))
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
                               'currency': currency(row.get('currency')),
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
        eps_currency = currency(eps.get('earningsCurrency'))
        trend_currency = currency(trend.get('epsTrendCurrency'))
        result['estimate'] = {'periodEnd': end, 'epsCurrency': eps_currency,
            'revenueCurrency': currency(revenue.get('revenueCurrency')),
            'eps': number(eps.get('avg')) if count and count >= 1 and count.is_integer() else None,
            'epsLow': number(eps.get('low')), 'epsHigh': number(eps.get('high')),
            'analysts': int(count) if count and count >= 1 and count.is_integer() else None,
            'epsGrowthPct': number(eps.get('growth')) * 100 if number(eps.get('growth')) is not None else None,
            'revenue': number(revenue.get('avg')) if revenue_count and revenue_count >= 1 and revenue_count.is_integer() else None,
            'revenueAnalysts': int(revenue_count) if revenue_count and revenue_count >= 1 and revenue_count.is_integer() else None,
            'revenueGrowthPct': number(revenue.get('growth')) * 100 if number(revenue.get('growth')) is not None else None,
            'eps30DaysAgo': number(trend.get('30daysAgo')) if eps_currency and trend_currency == eps_currency else None}
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
        document = str(row.get('DocType', ''))
        if 'NonConsolidated' in document:
            consolidated = False
            profit_key = 'OP' if amount('OP') is not None else 'NCOP'
        elif 'Consolidated' in document:
            consolidated = True
            profit_key = 'OP'
        else:
            continue  # Do not infer the reporting scope from an amount's presence.
        actual = amount(profit_key)
        if actual is None:
            continue
        candidates.append(({'disclosedDate': disclosed, 'periodEnd': day(row.get('CurPerEn'), 'JP'),
            'periodType': str(row.get('CurPerType') or '対象期')[:8], 'fiscalYearEnd': day(row.get('CurFYEn'), 'JP'),
            'operatingProfit': actual, 'forecastOperatingProfit': amount('FOP' if profit_key == 'OP' else 'FNCOP'),
            'consolidated': consolidated, 'source': 'J-Quants 決算短信', 'currency': 'JPY',
            'receivedAt': observation.get('receivedAt')}, row, 'FOP' if profit_key == 'OP' else 'FNCOP'))
    if not candidates:
        return None
    result, original, forecast_key = max(candidates,
        key=lambda value: (value[0]['disclosedDate'], value[0].get('receivedAt') or ''))
    # A later plan revision is not a new actual result. Match the issuer,
    # fiscal year and declared reporting field; preserve both receipt clocks.
    forecasts = []
    for observation in observations:
        row = observation.get('summary', {})
        if not isinstance(row, Mapping) or 'ForecastRevision' not in str(row.get('DocType', '')):
            continue
        disclosed = day(row.get('DiscDate'), 'JP')
        if (not result['fiscalYearEnd'] or row.get('CurFYEn') != result['fiscalYearEnd'] or
                not disclosed or not result['disclosedDate'] <= disclosed <= today or
                str(row.get('Code') or '')[:4] != str(original.get('Code') or '')[:4]):
            continue
        try:
            value = float(row[forecast_key])
        except (ValueError, KeyError, TypeError):
            continue
        if math.isfinite(value):
            forecasts.append((disclosed, str(row.get('DiscTime') or ''), observation.get('receivedAt') or '', value))
    result['forecastDisclosedDate'] = result['disclosedDate'] if result['forecastOperatingProfit'] is not None else None
    result['forecastReceivedAt'] = result['receivedAt'] if result['forecastOperatingProfit'] is not None else None
    if forecasts:
        disclosed, stamp, received = max(value[:3] for value in forecasts)
        values = {value[3] for value in forecasts if value[:3] == (disclosed, stamp, received)}
        value = values.pop() if len(values) == 1 else None
        result.update(forecastOperatingProfit=value, forecastDisclosedDate=disclosed, forecastReceivedAt=received)
    return result


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


def scheduled_date(symbol, rows, *, today, fetched_at):
    """Company-reported schedules; latest publication may withdraw a date.

    Each fiscal period has its own correction history. Same-day contradictory
    publications are not resolved by source order. Unknown dates are not zero.
    """
    groups = {}
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get('Code') or '') not in (symbol, symbol + '0'):
            continue
        published = day(row.get('PubDate'), 'JP')
        # Official FYE is MMDD (e.g. 0331), not a fiscal-year date.
        year_end = row.get('FYE')
        valid_year_end = isinstance(year_end, str) and len(year_end) == 4 and year_end.isdigit()
        try:
            if valid_year_end:
                date(2000, int(year_end[:2]), int(year_end[2:]))
        except ValueError:
            valid_year_end = False
        quarter = row.get('FQName')
        if not published or published > today or not valid_year_end or not isinstance(quarter, str) or not quarter:
            continue
        scheduled = day(row.get('SchDate'), 'JP')
        if row.get('SchDate') not in (None, '', '-') and scheduled is None:
            raise ValueError('schedule_date_invalid')
        key = (year_end, quarter)
        groups.setdefault(key, []).append((published, scheduled))
    candidates = []
    for values in groups.values():
        latest = max(value[0] for value in values)
        dates = {value[1] for value in values if value[0] == latest}
        if len(dates) != 1:
            if any(value is None or value >= today for value in dates):
                return None, 'CONFLICT'
            continue  # An expired past-period disagreement is not today's schedule.
        scheduled = dates.pop()
        if scheduled and today <= scheduled <= (date.fromisoformat(today) + timedelta(days=370)).isoformat():
            candidates.append((scheduled, latest))
    if not candidates:
        latest = max((value[0] for values in groups.values() for value in values), default=None)
        withdrawn = latest and any(value == (latest, None) for values in groups.values() for value in values)
        return None, 'NO_SCHEDULE' if withdrawn else 'NOT_REPORTED'
    scheduled, published = min(candidates)
    return {'from': scheduled, 'to': scheduled, 'certainty': 'COMPANY_SCHEDULE',
            'timezone': 'Asia/Tokyo', 'source': 'J-Quants 決算発表予定日',
            'publishedDate': published, 'fetchedAt': fetched_at}, 'AVAILABLE'


def attach_schedule(result, *, symbol, at, next_date, status):
    result = dict(result)
    result['scheduleStatus'] = status
    old = result.get('earnings')
    value = dict(old) if isinstance(old, Mapping) else {
        'symbol': symbol, 'market': 'JP', 'source': 'J-Quants 決算発表予定日',
        'fetchedAt': at, 'currency': 'JPY', 'next': None, 'previous': None,
        'estimate': None, 'actionAuthority': False}
    if status == 'AVAILABLE':
        value['next'] = next_date
    elif status in ('NO_SCHEDULE', 'CONFLICT'):
        # A withdrawal or conflicting company record overrides an old estimate.
        value['next'] = None
    # FETCH_FAILED preserves the saved date and its original receipt clock.
    if any(value.get(key) for key in ('next', 'previous', 'estimate', 'company')):
        result['earnings'] = value
    return result
