"""引け後の価格と推計入力の確認時刻。取得・保存・AI生成は呼出側で行う。"""
from datetime import datetime, timezone, timedelta
import argus_market_clock as clock

JST = timezone(timedelta(hours=9))
SLOTS = ((15, 31), (15, 35), (15, 45), (16, 5), (18, 5), (19, 5), (20, 5), (21, 5))


def due(now_iso, *, last_slot=None, close_date=None, eps_date=None):
    now = datetime.fromisoformat(now_iso.replace('Z', '+00:00')).astimezone(JST)
    day = now.date()
    if not clock.canonical_trading_day(clock.JP_EQUITY, day):
        return None
    eligible = [(h, m) for h, m in SLOTS if (h, m) <= (now.hour, now.minute)]
    if not eligible or now.hour >= 22:
        return None
    hour, minute = eligible[-1]
    slot = f'{day.isoformat()}T{hour:02d}:{minute:02d}'
    if last_slot is not None and last_slot >= slot:
        return None
    price = close_date != day.isoformat()
    valuation = (hour, minute) >= (16, 5) and eps_date != day.isoformat()
    if not price and not valuation:
        return None
    return {'slot': slot, 'session': day.isoformat(), 'price': price, 'valuation': valuation}
