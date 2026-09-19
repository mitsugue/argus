"""Display-only sector ETF returns; no trading authority or provider calls."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import math
import argus_market_clock as clock

PERIODS = (1, 5, 20)
SCHEMA = 'jp-sector-heatmap-v1'


def number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def project(quotes, histories, sectors, *, now=None, benchmark='1306', max_delay=1800):
    """quotes: unadjusted price/sourceTimestamp/source, histories: date->same-basis close.

    Callers must supply like-for-like prices (including corporate-action basis).
    Missing exact trading-day anchors stay missing; never compress missing sessions.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    session = clock.market_session(clock.JP_EQUITY, now)
    today = now.astimezone(ZoneInfo('Asia/Tokyo')).date()
    target = today if session['isTradingDay'] else clock.latest_completed_session_date(clock.JP_EQUITY, now)
    open_now = session['session'] in ('MORNING_SESSION', 'AFTERNOON_SESSION')

    anchors = {}
    prior = target
    count = 0
    for _ in range(90):
        prior -= timedelta(days=1)
        if clock.is_trading_day(clock.JP_EQUITY, prior):
            count += 1
            if count in PERIODS:
                anchors[count] = prior.isoformat()
            if count == max(PERIODS):
                break

    def observation(symbol):
        q = quotes.get(symbol) or {}
        stamp = timestamp(q.get('sourceTimestamp'))
        state = 'MISSING'
        if stamp:
            observed = stamp.astimezone(ZoneInfo('Asia/Tokyo')).date()
            state = ('INVALID_TIME' if stamp > now else 'NOT_UPDATED' if observed != target
                     else 'DELAYED' if open_now and (now-stamp).total_seconds() > max_delay
                     else 'AVAILABLE')
        if not number(q.get('price')) or q.get('price', 0) <= 0:
            state = 'MISSING'
        values = {}
        for period in PERIODS:
            anchor = anchors.get(period)
            base = (histories.get(symbol) or {}).get(anchor)
            valid = state == 'AVAILABLE' and number(base) and base > 0
            values[str(period)] = {'startDate': anchor, 'endDate': target.isoformat(),
                'returnPct': round((q['price']/base-1)*100, 4) if valid else None}
        return {'sourceTimestamp': q.get('sourceTimestamp'), 'source': q.get('source'),
                'observedDelaySeconds': max(0, int((now-stamp).total_seconds())) if stamp else None,
                'state': state, 'periods': values}

    reference = observation(benchmark)
    rows = []
    for sector in sectors:
        symbol = sector['symbol']
        row = {**sector, **observation(symbol), 'instrumentType': 'SECTOR_ETF_PROXY'}
        for period in PERIODS:
            value = row['periods'][str(period)]
            other = reference['periods'][str(period)]['returnPct']
            stamp, refstamp = timestamp(row['sourceTimestamp']), timestamp(reference['sourceTimestamp'])
            aligned = stamp and refstamp and abs((stamp-refstamp).total_seconds()) <= max_delay
            value['relativeToBenchmarkPct'] = (round(value['returnPct']-other, 4)
                if value['returnPct'] is not None and other is not None and aligned else None)
        rows.append(row)
    return {'schemaVersion': SCHEMA, 'generatedAt': now.isoformat(), 'session': session,
            'targetDate': target.isoformat(), 'isToday': target == today,
            'benchmarkSymbol': benchmark, 'benchmark': reference, 'rows': rows,
            'actionAuthority': False, 'refreshIntervalSeconds': 1200,
            'interpretation': 'PRICE_RETURN_NOT_CAPITAL_FLOW',
            'universe': 'SELECTED_SECTOR_ETF_PROXIES_NOT_OFFICIAL_33_SECTORS'}
