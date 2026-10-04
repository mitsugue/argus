"""既存の価格・推計EPS・事前記録から描画用の小さな配列を作る。"""
from datetime import date, datetime, timedelta, timezone
import math

import argus_market_clock as clock
import jp_market_level_map as levels


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
                   and (r.get('availableFrom') <= now_iso if r.get('availableFrom') else r.get('date') < today_s)],
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
    nearest = []
    if current and _number(current.get('atr14')) and _number(current.get('previousClose')):
        ratio = current['previousClose'] / current['eps']
        for side, multiple in (('UP', math.floor(ratio) + 1), ('DOWN', math.ceil(ratio) - 1)):
            price = current['eps'] * multiple
            # 朝の地図と同じ距離の表を使う。線の種類による予測力とはしない。
            stats = levels.reach(side, abs(price - current['previousClose']) / current['atr14'])
            nearest.append({'side': side, 'multiple': multiple, 'price': round(price, 2), **stats})
    return {'schemaVersion': 'jp-market-chart-layers-v1', 'today': today_s, 'start': start, 'end': end,
            'points': points, 'current': current, 'pivots': turns, 'pending': pending,
            'candidates': open_records[-30:], 'nearest': nearest, 'epsBasis': levels.EPS_BASIS,
            'actionAuthority': False, 'automaticAiCalls': 0}
