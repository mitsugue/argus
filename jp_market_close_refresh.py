"""引け後の価格と推計入力の確認時刻。取得・保存・AI生成は呼出側で行う。"""
from datetime import datetime, timezone, timedelta
import argus_market_clock as clock

JST = timezone(timedelta(hours=9))
SLOTS = ((15, 31), (15, 35), (15, 45), (16, 5), (16, 35), (17, 5),
         (18, 5), (19, 5), (20, 5), (21, 5))


def due(now_iso, *, last_slot=None, close_date=None, eps_date=None):
    now = datetime.fromisoformat(now_iso.replace('Z', '+00:00')).astimezone(JST)
    day = now.date()
    eligible = [(h, m) for h, m in SLOTS if (h, m) <= (now.hour, now.minute)]
    regular = clock.canonical_trading_day(clock.JP_EQUITY, day) and eligible and now.hour < 22
    session = day
    if regular:
        hour, minute = eligible[-1]
    else:
        # A restart after the last slot, a new calendar day or a holiday must
        # still repair the latest closed session. At most one recovery per
        # hour; a complete close/EPS pair does not call either provider.
        hour, minute = now.hour, 0
        if (now.hour, now.minute) < (15, 31):
            session -= timedelta(days=1)
        for _ in range(15):
            if clock.canonical_trading_day(clock.JP_EQUITY, session):
                break
            session -= timedelta(days=1)
        else:
            return None
    slot = f'{day.isoformat()}T{hour:02d}:{minute:02d}'
    if last_slot is not None and last_slot >= slot:
        return None
    price = close_date != session.isoformat()
    valuation = (not regular or (hour, minute) >= (16, 35)) and eps_date != session.isoformat()
    if not price and not valuation:
        return None
    return {'slot': slot, 'session': session.isoformat(), 'price': price, 'valuation': valuation}
