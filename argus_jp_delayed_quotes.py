"""Registered JP display backup, driven by the existing index loop (2026-11-05).

No persistence or decision inputs. Membership comes from the existing owner
store, never a browser's requested symbols. Failed reads retain their original
times; neither a new GET nor a new receipt makes an old trade current.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone, timedelta
import json
import math
import re
import threading
import time

from argus_market_clock import JP_EQUITY, market_session

MAX_SYMBOLS = 50
INTERVAL = 60
FAILURE_INTERVAL = 120
RATE_LIMIT_PAUSE = 600
ROUND_SECONDS = 20
MAX_BODY = 512 * 1024
JST = timezone(timedelta(hours=9))
SCHEMA = 'argus-jp-delayed-display-v1'


def symbols_from_members(rows):
    if not isinstance(rows, list):
        raise ValueError('membership_unavailable')
    return tuple(dict.fromkeys(str(r.get('symbol', '')).upper().removesuffix('.T')
        for r in rows if isinstance(r, dict) and r.get('market') == 'JP'
        and r.get('enabled', True) is True
        and re.fullmatch(r'[0-9][0-9A-Z]{3}(?:\.T)?', str(r.get('symbol', '')).upper())))[:MAX_SYMBOLS]


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def parse_quote(payload, symbol, received):
    try:
        if not _number(received) or received <= 0:
            return None
        result = payload['chart']['result']
        if payload['chart'].get('error') or len(result) != 1:
            return None
        m = result[0]['meta']
        price, traded = m.get('regularMarketPrice'), m.get('regularMarketTime')
        if m.get('symbol') != symbol + '.T' or m.get('currency') != 'JPY':
            return None
        if not _number(price) or price <= 0 or not _number(traded) or not 0 < traded <= received:
            return None
        source = datetime.fromtimestamp(traded, JST)
        receipt = datetime.fromtimestamp(received, JST)
        # A prior day's stale meta is not an intraday quote or today's change.
        if source.date() != receipt.date() or not 9 * 60 <= source.hour * 60 + source.minute <= 15 * 60 + 30:
            return None
        source_session = market_session(JP_EQUITY, source)
        if not source_session['isTradingDay'] or (source_session['session'] not in ('MORNING_SESSION', 'AFTERNOON_SESSION')
                and source.hour * 60 + source.minute not in (11 * 60 + 30, 15 * 60 + 30)):
            return None
        previous = m.get('chartPreviousClose')
        previous = previous if _number(previous) and previous > 0 else None
        iso = lambda n: datetime.fromtimestamp(n, timezone.utc).isoformat()
        return {'symbol': symbol, 'price': price, 'previousClose': previous,
            'changePct': (price / previous - 1) * 100 if previous else None,
            'sourceTimestamp': iso(traded), 'receivedAt': iso(received),
            'delaySeconds': int(received - traded), 'provider': 'YAHOO_DELAYED',
            'realtime': False, 'actionAuthority': False}
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, OSError):
        return None


def _read(get, symbol, epoch, clock, deadline):
    response = None
    try:
        response = get('https://query1.finance.yahoo.com/v8/finance/chart/' + symbol + '.T',
            params={'interval': '1m', 'range': '1d'},
            headers={'User-Agent': 'Mozilla/5.0 (argus)'}, timeout=(2, 4), stream=True,
            allow_redirects=False)
        code = response.status_code
        if code != 200:
            return None, 'HTTP_429' if code == 429 else 'HTTP_' + str(code)
        body = bytearray()
        for chunk in response.iter_content(chunk_size=16384):
            if clock() >= deadline:
                return None, 'TIME_BUDGET'
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return None, 'BODY_LIMIT'
        quote = parse_quote(json.loads(body), symbol, epoch())
        return (quote, None) if quote else (None, 'INVALID_QUOTE')
    except Exception as exc:
        name = type(exc).__name__
        return None, name if name in ('Timeout', 'ReadTimeout', 'ConnectTimeout', 'ConnectionError') else 'READ_FAILED'
    finally:
        if response is not None:
            response.close()


class Collector:
    def __init__(self):
        self.lock = threading.Lock()
        self.round_lock = threading.Lock()
        self.rows = {}
        self.attempts = {}
        self.errors = {}
        self.registered = ()
        self.pause_until = 0
        self.membership_error = None

    def tick(self, get, members, fresh_symbols=(), *, epoch=time.time, clock=time.monotonic):
        """One bounded round in the existing daemon, with no additional timer."""
        if not self.round_lock.acquire(blocking=False):
            return
        try:
            now = epoch()
            session = market_session(JP_EQUITY, datetime.fromtimestamp(now, timezone.utc))
            if session['session'] not in ('MORNING_SESSION', 'AFTERNOON_SESSION'):
                return
            try:
                registered = symbols_from_members(members())
            except Exception:
                with self.lock:
                    self.registered = ()
                    self.rows.clear()
                    self.membership_error = 'MEMBERSHIP_UNAVAILABLE'
                return
            with self.lock:
                self.registered = registered
                self.membership_error = None
                for cache in (self.rows, self.attempts, self.errors):
                    for key in list(cache):
                        if key not in registered:
                            del cache[key]
                candidates = [s for s in registered if s not in fresh_symbols
                    and now - self.attempts.get(s, float('-inf')) >= (FAILURE_INTERVAL if self.errors.get(s) else INTERVAL)]
                candidates.sort(key=lambda s: self.attempts.get(s, float('-inf')))
                if now < self.pause_until:
                    return
            deadline = clock() + ROUND_SECONDS
            pending = {}
            todo = iter(candidates)
            rate_limited = False
            # At most four in-flight requests. No queued work survives the round.
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix='jp-delayed-display') as pool:
                while True:
                    while len(pending) < 4 and not rate_limited and clock() < deadline:
                        symbol = next(todo, None)
                        if symbol is None:
                            break
                        with self.lock:
                            self.attempts[symbol] = epoch()
                        pending[pool.submit(_read, get, symbol, epoch, clock, min(deadline, clock() + 8))] = symbol
                    if not pending:
                        break
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        symbol = pending.pop(future)
                        quote, error = future.result()
                        with self.lock:
                            self.errors[symbol] = error
                            if quote:
                                self.rows[symbol] = quote
                            if error == 'HTTP_429':
                                self.pause_until = epoch() + RATE_LIMIT_PAUSE
                                rate_limited = True
        finally:
            self.round_lock.release()

    def document(self, requested, *, now=None):
        """Cache-only projection. It cannot register a new symbol or fetch."""
        now = time.time() if now is None else now
        with self.lock:
            selected = [s for s in self.registered if s in requested]
            return {'schemaVersion': SCHEMA, 'provider': 'YAHOO_DELAYED',
                'actionAuthority': False, 'readAt': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                'membershipError': self.membership_error, 'requestedSymbols': list(requested)[:MAX_SYMBOLS],
                'symbols': {s: {**self.rows[s], 'lastError': self.errors.get(s)}
                    for s in selected if s in self.rows},
                'errors': {s: self.errors[s] for s in selected if self.errors.get(s)}}


collector = Collector()
