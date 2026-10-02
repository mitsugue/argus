"""Delayed intraday Nikkei 225 quote for the Today page (owner request 2026-10-02).

A daemon thread reads the public Yahoo v8 chart endpoint at most once a minute
while the Tokyo cash session can be open, and once more after the close; the
web route only reads the last result. The quote carries its own trade time and
the measured delay, so the page can say "10:25時点・約20分遅れ" instead of
implying real time. Display only: it never enters engine evidence, history or
any decision.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional

SCHEMA = "argus-index-live-v1"
SYMBOL = "^N225"
POLL_SECONDS = 60
_JST = timezone(timedelta(hours=9))

_lock = threading.Lock()
_state: Dict[str, Any] = {"quote": None, "error": None, "thread": None}


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and value not in (float("inf"), float("-inf")) and value > 0 else None


def parse_quote(payload: Any, *, received_epoch: float) -> Optional[Dict[str, Any]]:
    """Shape one Yahoo chart response; None when price or trade time is missing."""
    try:
        meta = (((payload or {}).get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
    except (AttributeError, IndexError, TypeError):
        return None
    price = _finite(meta.get("regularMarketPrice"))
    previous = _finite(meta.get("chartPreviousClose")) or _finite(meta.get("previousClose"))
    traded = meta.get("regularMarketTime")
    if price is None or isinstance(traded, bool) or not isinstance(traded, (int, float)) or traded <= 0:
        return None
    regular = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    start, end = regular.get("start"), regular.get("end")
    session_open = (isinstance(start, (int, float)) and isinstance(end, (int, float))
                    and start <= received_epoch < end)
    iso = lambda epoch: datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schemaVersion": SCHEMA, "instrumentId": "NIKKEI_225_INDEX", "symbol": SYMBOL,
        "price": price, "previousClose": previous,
        "changePct": ((price / previous - 1) * 100) if previous else None,
        "tradedAt": iso(float(traded)), "receivedAt": iso(received_epoch),
        "delaySeconds": max(0, int(received_epoch - float(traded))),
        "sessionOpen": bool(session_open),
        "source": "Yahoo Finance (delayed)", "realtime": False, "actionAuthority": False,
    }


def session_window(now: datetime) -> bool:
    """Tokyo weekday 08:55-15:45 JST, when a fresh intraday value can exist."""
    local = now.astimezone(_JST)
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return 8 * 60 + 55 <= minutes <= 15 * 60 + 45


def refresh_once(get: Callable[..., Any], now_epoch: Optional[float] = None) -> Optional[Dict[str, Any]]:
    received = time.time() if now_epoch is None else now_epoch
    try:
        response = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}",
                       params={"interval": "1m", "range": "1d"},
                       headers={"User-Agent": "Mozilla/5.0 (argus)"}, timeout=10)
        if getattr(response, "status_code", 200) != 200:
            raise ValueError("index_live_http_failure")
        quote = parse_quote(response.json(), received_epoch=received)
        if quote is None:
            raise ValueError("index_live_shape_invalid")
    except Exception as exc:  # provider failures stay visible, never fatal
        with _lock:
            _state["error"] = type(exc).__name__
        return None
    with _lock:
        _state["quote"], _state["error"] = quote, None
    return quote


def _loop(get: Callable[..., Any], sleep: Callable[[float], None]) -> None:
    after_close_done = None
    while True:
        now = datetime.now(timezone.utc)
        local_day = now.astimezone(_JST).date()
        if session_window(now):
            refresh_once(get)
            after_close_done = None
        elif after_close_done != local_day:
            refresh_once(get)          # one read outside the window (boot, after the close)
            after_close_done = local_day
        sleep(POLL_SECONDS)


def ensure_started(get: Optional[Callable[..., Any]] = None, sleep: Callable[[float], None] = time.sleep) -> str:
    with _lock:
        thread = _state["thread"]
        if thread is not None and thread.is_alive():
            return "RUNNING"
        if get is None:
            import requests
            get = requests.get
        thread = threading.Thread(target=_loop, args=(get, sleep), name="argus-index-live", daemon=True)
        _state["thread"] = thread
        thread.start()
        return "STARTED"


def current_quote_safe() -> Dict[str, Any]:
    with _lock:
        quote, error = _state["quote"], _state["error"]
    if quote is None:
        return {"status": "UNAVAILABLE", "reason": error or "not_yet_fetched", "quote": None, "actionAuthority": False}
    return {"status": "AVAILABLE", "quote": dict(quote), "lastError": error, "actionAuthority": False}
