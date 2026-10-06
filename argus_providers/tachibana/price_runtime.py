"""Price-only single-session runner. No EVENT, reconnect, order or account reads."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from .client import TachibanaReadOnlyClient, _security_code
from .models import ErrorClass, ProviderHealth, TachibanaError
from .normalization import normalize_market_price
from .session import RequestsJsonTransport, TachibanaSession
from .session_truth import parse_provider_datetime, resolve_jp_cash_session, JapanCashPhase
from .usage_policy import UsagePolicy

COLUMNS = ("pDPP", "tDPP:T", "pPRP", "pDYRP", "pDYWP", "pDOP", "pDHP", "pDLP")

class GuardedTransport:
    def __init__(self, transport, policy):
        self.transport, self.policy = transport, policy
        self.session_day = None
    @property
    def last_http_status(self):
        return getattr(self.transport, "last_http_status", None)
    def post_json(self, url, payload, timeout):
        login = payload.get("sCLMID") == "CLMAuthLoginRequest"
        day = self.policy.clock().astimezone(ZoneInfo("Asia/Tokyo")).date()
        if not login and self.session_day != day:
            raise TachibanaError(ErrorClass.SESSION_EXPIRED)
        self.policy.before_send(login=login)
        if login: self.session_day = day
        try:
            return self.transport.post_json(url, payload, timeout)
        except Exception:
            self.policy.block()
            raise

class TachibanaPriceRuntime:
    def __init__(self, config, *, symbols, policy_path, clock=lambda: datetime.now(timezone.utc), transport=None, symbols_supplier=None):
        if not symbols or len(symbols) > config.max_symbols or len(set(symbols)) != len(symbols):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        for symbol in symbols:
            if symbol != "101": _security_code(symbol)
        self.config = replace(config, max_read_attempts=1, websocket_enabled=False)
        self.symbols, self.clock = tuple(symbols), clock
        self.symbols_supplier = symbols_supplier
        self.policy = UsagePolicy(Path(policy_path), clock)
        self.session = TachibanaSession(self.config, GuardedTransport(transport or RequestsJsonTransport(), self.policy), clock=clock)
        self.client = TachibanaReadOnlyClient(self.session)
        self.sensor = SimpleNamespace(latest=lambda symbol, now: self._price_observations.get(symbol))
        self._price_observations = {}
        self.terminal_error = ErrorClass.NONE
        self._day = None
        self._phase = "UNKNOWN"
        self._leased = False

    def start(self):
        self.policy.acquire()
        self._leased = True
        try:
            self.session.authenticate()
            self._day = self.client.provider_calendar_date()
            self.refresh()
        except Exception:
            self.policy.block()
            raise

    def refresh(self):
        try:
            self.policy.before_send()
            if self.clock().astimezone(ZoneInfo("Asia/Tokyo")).date() != self._day:
                raise TachibanaError(ErrorClass.CLOCK_SKEW)
            if self.symbols_supplier is not None:
                next_symbols = tuple(self.symbols_supplier())
                if len(next_symbols) > self.config.max_symbols or len(set(next_symbols)) != len(next_symbols):
                    raise TachibanaError(ErrorClass.CONFIGURATION)
                for symbol in next_symbols:
                    if symbol != "101": _security_code(symbol)
                self.symbols = next_symbols
            if not self.symbols:
                self._price_observations = {}
                return  # No registered subjects: no price request, keep one session.
            response = self.client.market_price(self.symbols, COLUMNS, allow_nikkei=True)
            received = self.clock()
            truth = resolve_jp_cash_session(now=received, provider_time=parse_provider_datetime(response.get("p_rv_date")),
                provider_calendar_date=self._day, provider_health=ProviderHealth.AVAILABLE)
            rows = response.get("aCLMMfdsMarketPrice", [])
            if len(rows) != len(self.symbols): raise TachibanaError(ErrorClass.PROVIDER)
            normalized = {row["sIssueCode"]: normalize_market_price(row, received_at=received,
                market_date=truth.market_date, market_status=truth.market_status,
                market_date_verified=truth.market_date_verified and truth.phase in {JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN},
                market_data_timestamp=None,  # Receipt time must not refresh an old trade.
                market_data_date_verified=truth.provider_calendar_current and truth.event_packet_current,
                fresh_for_seconds=15, allow_nikkei=True) for row in rows}
            if set(normalized) != set(self.symbols): raise TachibanaError(ErrorClass.PROVIDER)
            self._price_observations = normalized
            self._phase = truth.phase.value
        except Exception as exc:
            self.terminal_error = getattr(exc, "classification", ErrorClass.NORMALIZATION)
            self.policy.block()
            self._price_observations = {}
            raise

    def acceptance_snapshot(self):
        return SimpleNamespace(provider_health="AVAILABLE", session_phase=self._phase)

    def stop(self):
        if not self._leased: return True
        try:
            ok = self.session.logout()  # Guard also covers quiet hours and terminal errors.
            if not ok: self.policy.block()
            return ok
        finally:
            self.session.expire()
            self.policy.release()
            self._leased = False
