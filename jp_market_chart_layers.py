"""既存の価格・推計EPS・事前記録から描画用の小さな配列を作る。"""
from datetime import date, datetime, timedelta, timezone
import math
from statistics import median

import argus_market_clock as clock
import jp_market_level_map as levels


def _available_by(value, now):
    try:
        received = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return received.tzinfo is not None and received <= now
    except (TypeError, ValueError):
        return False


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _pending(bars):
    if not bars:
        return None
    direction, high, low = 0, bars[0], bars[0]
    for bar in bars[1:]:
        value = bar['close']
        if direction == 0:
            if value > high['close']: high = bar
            if value < low['close']: low = bar
            if value <= high['close'] * .96 and high['date'] < bar['date']:
                direction, low = -1, bar
            elif value >= low['close'] * 1.04 and low['date'] < bar['date']:
                direction, high = 1, bar
        elif direction == 1:
            if value > high['close']: high = bar
            elif value <= high['close'] * .96: direction, low = -1, bar
        else:
            if value < low['close']: low = bar
            elif value >= low['close'] * 1.04: direction, high = 1, bar
    if not direction:
        return None
    point = high if direction == 1 else low
    return {'date': point['date'], 'price': point['close'], 'kind': 'TOP' if direction == 1 else 'BOTTOM',
            'confirmPrice': round(point['close'] * (.96 if direction == 1 else 1.04), 2)}


def _deadline(entry):
    day = date.fromisoformat(entry)
    count = 0
    for _ in range(50):
        if clock.is_trading_day(clock.JP_EQUITY, day):
            count += 1
            if count == 20: return day.isoformat()
        day += timedelta(days=1)
    return None


def valuation_history(eps_records, morning, price_rows):
    """同じ方式で再計算した過去との位置比較。到達・反転の予測ではない。"""
    if not morning or not _number(morning.get('eps')) or not _number(morning.get('previousClose')):
        return None
    cutoff = morning.get('epsDate')
    if not isinstance(cutoff, str):
        return None
    records = []
    for day, record in eps_records.items():
        if (not isinstance(record, dict) or record.get('basis') != levels.EPS_BASIS
                or record.get('date') != day or day > cutoff or not _number(record.get('per'))):
            continue
        try:
            parsed = date.fromisoformat(day)
        except (ValueError, TypeError):
            continue
        if parsed.weekday() < 5:
            records.append((day, record['per']))
    records.sort()
    if not records:
        return None
    start, end = date.fromisoformat(records[0][0]), date.fromisoformat(records[-1][0])
    # The runtime holiday table covers recent years only. Use actual stored
    # price sessions so old Japanese holidays are not invented as data gaps.
    price_dates = {r.get('date') for r in price_rows if isinstance(r, dict) and _number(r.get('close'))
                   and records[0][0] <= str(r.get('date', '')) <= records[-1][0]}
    missing = len(price_dates - {day for day, _ in records})
    expected = len(records) + missing
    values = [value for _, value in records]
    multiple = math.floor(morning['previousClose'] / morning['eps']) + 1
    return {'basis': levels.EPS_BASIS, 'firstDate': start.isoformat(), 'lastDate': end.isoformat(),
            'count': len(values), 'missingSessions': missing,
            'sufficient': len(values) >= 60 and len(values) >= expected * .8,
            'median': round(median(values), 2), 'minimum': round(min(values), 2),
            'maximum': round(max(values), 2), 'upperMultiple': multiple,
            'atOrAboveUpper': sum(value >= multiple for value in values),
            'retrospective': True, 'actionAuthority': False}


def closing_map(bars, eps_records, morning, *, now_iso):
    """現在表示の投影。朝の事前記録を変更せず、新しい終値を先に出す。"""
    now = datetime.fromisoformat(now_iso.replace('Z', '+00:00'))
    if now.tzinfo is None or not bars or not morning:
        return None
    last = bars[-1]
    previous = str(morning.get('previousSession') or '')
    # Once tomorrow's fixed map exists, today's closing display still uses
    # today's date. The immutable next-morning record is kept separately.
    if last['date'] < previous or (last['date'] == previous
            and last['date'] != now.astimezone(timezone(timedelta(hours=9))).date().isoformat()):
        return None
    known = {}
    for day, record in eps_records.items():
        try:
            received = datetime.fromisoformat(str(record.get('recordedAt')).replace('Z', '+00:00')) if isinstance(record, dict) else None
        except (ValueError, TypeError):
            received = None
        if (isinstance(record, dict) and record.get('date') == day and day <= last['date']
                and record.get('basis') == levels.EPS_BASIS and _number(record.get('eps'))
                and received is not None and received.tzinfo is not None and received <= now):
            known[day] = record['eps']
    # The morning's already admitted input remains visibly dated while the
    # new valuation is not available. It is never labelled today's EPS.
    if (_number(morning.get('eps')) and isinstance(morning.get('epsDate'), str)
            and morning['epsDate'] <= last['date']):
        known.setdefault(morning['epsDate'], morning['eps'])
    try:
        following = date.fromisoformat(last['date']) + timedelta(days=1)
        projection = levels.morning_map(following.isoformat(), bars, known,
                                       eps_records=eps_records, created_at=now_iso)
    except (levels.LevelMapError, ValueError, TypeError):
        return None
    projection.update(displayOnly=True, asOf=last['date'],
                      valuationPending=projection['epsDate'] != last['date'])
    return projection


def snapshot(rows, eps_records, morning, candidates, *, now_iso):
    """公開用。日付を厳密に守り、個別銘柄・研究原本は返さない。"""
    now = datetime.fromisoformat(now_iso.replace('Z', '+00:00'))
    today = now.astimezone(timezone(timedelta(hours=9))).date()
    start = (today - timedelta(days=184)).isoformat()
    end = (today + timedelta(days=92)).isoformat()
    today_s = today.isoformat()
    # 当日の未確定足は使わない。寄付前から見える値は前営業日終値。
    bars = sorted([r for r in rows if isinstance(r, dict) and str(r.get('date', '')) <= today_s
                   and all(_number(r.get(k)) for k in ('close', 'high', 'low'))
                   and (_available_by(r.get('availableFrom'), now) if r.get('availableFrom') else r.get('date') < today_s)],
                  key=lambda r: r['date'])[-3000:]
    eps = {d: v['eps'] for d, v in eps_records.items() if isinstance(v, dict) and _number(v.get('eps'))}
    points = []
    for bar in bars:
        if bar['date'] < start: continue
        previous_day = date.fromisoformat(bar['date']) - timedelta(days=1)
        while not clock.is_trading_day(clock.JP_EQUITY, previous_day):
            previous_day -= timedelta(days=1)
        previous = previous_day.isoformat()
        points.append({'date': bar['date'], 'close': round(bar['close'], 2),
                       'eps': eps.get(previous), 'epsDate': previous if previous in eps else None})
    # 朝の地図と同じ固定値。過去のEPSの代わりには使わない。
    current = None
    if morning and morning.get('morningOf') <= today_s and _number(morning.get('eps')):
        current = {k: morning.get(k) for k in ('morningOf', 'eps', 'epsDate', 'previousClose', 'previousSession', 'atr14')}
    turns = [{'date': p['closeDate'], 'price': next(b['close'] for b in bars if b['date'] == p['closeDate']),
              'kind': p['kind'], 'confirmedOn': p['confirmedOn']}
             for p in levels.zigzag(bars) if p['closeDate'] >= start]
    pending = _pending(bars)
    if pending and pending['date'] < start: pending = None
    open_records = []
    for record in candidates:
        if (record.get('result') or {}).get('outcome') != 'open' or record.get('skippedAtEntry'): continue
        target, stop = (record.get('target') or {}).get('nikkei'), (record.get('stop') or {}).get('nikkei')
        moving = (record.get('target') or {}).get('kind') == 'PER_LINE'
        multiple = (record.get('target') or {}).get('multiple')
        if moving:
            if not current or not _number(multiple): continue
            target = round(current['eps'] * multiple, 2)
        if not _number(target) or not _number(stop): continue
        entry = record.get('entryDate')
        try: deadline = (record.get('deadline') or {}).get('bd20') or _deadline(entry)
        except (ValueError, TypeError): continue
        if not deadline or deadline < today_s: continue
        open_records.append({'id': record.get('recordId'), 'label': record.get('candidate'),
                             'start': entry, 'end': deadline, 'target': target, 'stop': stop,
                             'movingTarget': moving})
    display = closing_map(bars, eps_records, morning, now_iso=now_iso)
    shown = display or current
    nearest = []
    if shown and _number(shown.get('atr14')) and _number(shown.get('previousClose')):
        ratio = shown['previousClose'] / shown['eps']
        for side, multiple in (('UP', math.floor(ratio) + 1), ('DOWN', math.ceil(ratio) - 1)):
            price = shown['eps'] * multiple
            # 表示中の終値・EPS・ATRから、同じ距離の表を選ぶ。線の種類による予測力とはしない。
            stats = levels.reach(side, abs(price - shown['previousClose']) / shown['atr14'])
            nearest.append({'side': side, 'multiple': multiple, 'price': round(price, 2),
                            'distancePct': round((price / shown['previousClose'] - 1) * 100, 3),
                            'distanceAtr': round((price - shown['previousClose']) / shown['atr14'], 3), **stats})
    local = now.astimezone(timezone(timedelta(hours=9)))
    close_pending = (clock.is_trading_day(clock.JP_EQUITY, today) and (local.hour, local.minute) >= (15, 30)
                     and (not bars or bars[-1]['date'] < today_s))
    return {'schemaVersion': 'jp-market-chart-layers-v1', 'today': today_s, 'start': start, 'end': end,
            'points': points, 'current': current, 'displayMap': display, 'closePending': close_pending,
            'pivots': turns, 'pending': pending,
            'valuationHistory': valuation_history(eps_records, shown, bars) if shown else None,
            'candidates': open_records[-30:], 'nearest': nearest, 'epsBasis': levels.EPS_BASIS,
            'actionAuthority': False, 'automaticAiCalls': 0}
