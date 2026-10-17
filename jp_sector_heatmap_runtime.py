"""Bounded, shared display collection. Public reads never fetch or start work."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from threading import Lock
from copy import deepcopy
import jp_sector_heatmap as heatmap
import argus_market_clock as clock

SECTORS = [dict(symbol=s, nameJa=n) for s,n in (
    ('1622','自動車・輸送機'),('1625','電機・精密'),('1631','銀行'),
    ('1629','商社・卸売'),('1626','情報通信・サービス'),('1621','医薬品'),
    ('1627','電力・ガス'),('1633','不動産'))]

class Runtime:
    def __init__(self, get, *, load=lambda: {}, save=lambda value: None):
        self.get, self.save, self.lock = get, save, Lock()
        raw = load() or {}
        self.quotes = raw.get('quotes', {})
        self.histories = raw.get('histories', {})
        self.history_dates = raw.get('historyDates', {})
        self.errors = {}
        self.last_attempt = 0
        self.boot_collected = False
        self.published = deepcopy(raw)

    def read(self, now=None):
        snapshot = self.published
        result = heatmap.project(snapshot.get('quotes', {}), snapshot.get('histories', {}), SECTORS, now=now)
        result['collectionErrors'] = snapshot.get('errors', {})
        result['lastAttemptAt'] = snapshot.get('lastAttemptAt')
        return result

    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        session = clock.market_session(clock.JP_EQUITY, now)
        regular = session['session'] in ('MORNING_SESSION','AFTERNOON_SESSION')
        # One bounded cold-start fill; subsequent fetching only while the market is open.
        close = heatmap.timestamp(session.get('regularCloseJst'))
        closing_fill = (session['session'] == 'POST_MARKET' and close is not None
                        and self.last_attempt < close.timestamp())
        if self.boot_collected and not regular and not closing_fill:
            return False
        if now.timestamp()-self.last_attempt < 1200 or not self.lock.acquire(False):
            return False
        try:
            self.last_attempt = now.timestamp()
            self.boot_collected = True
            day = now.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat()
            for symbol in [s['symbol'] for s in SECTORS] + ['1306']:
                response = None
                try:
                    response = self.get('https://query1.finance.yahoo.com/v8/finance/chart/'+symbol+'.T',
                        params={'interval':'1d','range':'5d' if self.history_dates.get(symbol)==day else '3mo',
                                'events':'splits'}, headers={'User-Agent':'Mozilla/5.0 (argus)'}, timeout=10)
                    response.raise_for_status()
                    chart = response.json()['chart']['result'][0]
                    meta = chart['meta']
                    if meta.get('symbol') != symbol+'.T' or meta.get('currency') != 'JPY':
                        raise ValueError('instrument_definition_mismatch')
                    stamp = meta.get('regularMarketTime')
                    price = meta.get('regularMarketPrice')
                    if not heatmap.number(stamp) or not heatmap.number(price):
                        raise ValueError('quote_timestamp_missing')
                    self.quotes[symbol] = {'price':price,
                        'sourceTimestamp':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
                        'source':'Yahoo Finance delayed sector ETF', 'receivedAt':now.isoformat()}
                    closes = chart['indicators']['quote'][0].get('close', [])
                    history = dict(self.histories.get(symbol, {}))
                    for timestamp, close in zip(chart.get('timestamp',[]), closes):
                        date = datetime.fromtimestamp(timestamp,ZoneInfo('Asia/Tokyo')).date().isoformat()
                        if heatmap.number(close) and close > 0:
                            history[date] = close
                    # Never compare across a split without an independently verified adjustment basis.
                    splits = (chart.get('events') or {}).get('splits') or {}
                    split_dates = [datetime.fromtimestamp(int(x['date']),ZoneInfo('Asia/Tokyo')).date().isoformat()
                                   for x in splits.values() if x.get('date')]
                    if split_dates:
                        history = {d:v for d,v in history.items() if d >= max(split_dates)}
                    self.histories[symbol] = dict(sorted(history.items())[-80:])
                    self.history_dates[symbol] = day
                    self.errors.pop(symbol, None)
                except Exception as exc:
                    self.errors[symbol] = {'kind':type(exc).__name__, 'at':now.isoformat()}
                finally:
                    if response is not None:
                        response.close()
            self.published = deepcopy({'quotes':self.quotes,'histories':self.histories,
                'historyDates':self.history_dates,'errors':self.errors,'lastAttemptAt':self.last_attempt})
            self.save(self.published)
            return True
        finally:
            self.lock.release()
