"""Serialized, rate-bounded, structurally read-only v4r10 request client.

Only the explicitly modelled market-data/date inquiry functions below can be
sent. There is deliberately no public generic ``read``/``request`` method and
this client cannot address the REQUEST virtual URL.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
import random
import re
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .models import ErrorClass, ProviderHealth, TachibanaError
from .session import TachibanaSession


@dataclass(frozen=True)
class _FunctionContract:
    function_id: str
    endpoint_category: str
    allowed_parameters: frozenset[str]
    response_list: str
    maximum_rows: int
    response_id: str | None = None


_FUNCTION_CONTRACTS: Mapping[str, _FunctionContract] = MappingProxyType({
    "CLMMfdsGetMarketPrice": _FunctionContract(
        "CLMMfdsGetMarketPrice", "price",
        frozenset({"sTargetIssueCode", "sTargetColumn"}),
        "aCLMMfdsMarketPrice", 64,
    ),
    "CLMMfdsGetMarketPriceHistory": _FunctionContract(
        "CLMMfdsGetMarketPriceHistory", "price",
        frozenset({"sIssueCode", "sSizyouC"}),
        "aCLMMfdsMarketPriceHistory", 8_000,
    ),
    # These four use MASTER in the official interface overview. Their CLMMfds
    # prefix does not make them PRICE functions.
    "CLMMfdsGetIssueDetail": _FunctionContract(
        "CLMMfdsGetIssueDetail", "master", frozenset({"sTargetIssueCode"}),
        "aCLMMfdsIssueDetail", 64,
    ),
    "CLMMfdsGetSyoukinZan": _FunctionContract(
        "CLMMfdsGetSyoukinZan", "master", frozenset({"sTargetIssueCode"}),
        "aCLMMfdsSyoukinZan", 64,
    ),
    "CLMMfdsGetShinyouZan": _FunctionContract(
        "CLMMfdsGetShinyouZan", "master", frozenset({"sTargetIssueCode"}),
        "aCLMMfdsShinyouZan", 64,
    ),
    "CLMMfdsGetHibuInfo": _FunctionContract(
        "CLMMfdsGetHibuInfo", "master", frozenset({"sTargetIssueCode"}),
        "aCLMMfdsHibuInfo", 64,
    ),
    "CLMStkGetIssueMstKabu": _FunctionContract(
        "CLMStkGetIssueMstKabu", "master", frozenset(),
        "aCLMStkIssueMstKabu", 20_000,
    ),
    # Current v4r10 official master inquiry. Day key 001 supplies the
    # provider's current calendar date; it is deliberately distinct from an
    # EVENT packet's send date and SS/US effective time.
    "CLMStkGetDateZyouhou": _FunctionContract(
        "CLMStkGetDateZyouhou", "master", frozenset(),
        "aCLMDateZyouhou", 2, "CLMDateZyouhou",
    ),
})

# Public for auditability, immutable for safety. Values use the provider's
# documented virtual-URL category names.
READ_ONLY_FUNCTIONS: Mapping[str, str] = MappingProxyType({
    function_id: contract.endpoint_category.upper()
    for function_id, contract in _FUNCTION_CONTRACTS.items()
})

# TSE cash-equity security codes are exactly four characters. Since January
# 2024 the second character may be one of the published alpha-code letters.
_SECURITY_CODE = re.compile(r"^[0-9ACDFGHJKLMNPRSTUWXY]{4}$")
_MARKET_PRICE_COLUMNS = frozenset({
    "pAAV", "pABV", "pAV", "pBV", "xDCFS", "pDHF", "pDHP", "tDHP:T",
    "pDJ", "pDLF", "pDLP", "tDLP:T", "pDOP", "tDOP:T", "pDPG", "pDPP",
    "tDPP:T", "pDV", "xDVES", "pDYRP", "pDYWP", "xLISS", "pPRP", "pQAP",
    "pQAS", "pQBP", "pQBS", "pQOV", "pQUV", "pVWAP",
    *(f"pGAP{level}" for level in range(1, 11)),
    *(f"pGAV{level}" for level in range(1, 11)),
    *(f"pGBP{level}" for level in range(1, 11)),
    *(f"pGBV{level}" for level in range(1, 11)),
})
_PROTOCOL_PARAMETERS = frozenset({"p_no", "p_sd_date", "sJsonOfmt", "sCLMID"})
_AUTH_PARAMETERS = frozenset({"sAuthId", "sSecondPassword", "sPassword"})
_ORDER_PARAMETER_PREFIXES = ("sOrder", "sBaibai", "sBensai", "sCondition")
_MAINTENANCE_ERRNOS = frozenset({"9", "-12"})
_RATE_ERRNOS = frozenset({"-2", "-3"})
_MAINTENANCE_RESULTS = frozenset({"990002", "990003", "990004"})
_OUTSIDE_HOURS_RESULTS = frozenset({"990005"})
_SESSION_RESULTS = frozenset({"990006", "991034"})
_RESPONSE_COMMON_FIELDS = frozenset({
    "p_no", "p_sd_date", "p_rv_date", "p_errno", "p_err", "sCLMID",
    "sResultCode", "sResultText", "sWarningCode", "sWarningText",
})
_MAX_PARAMETER_VALUE = 4096


def _security_code(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _SECURITY_CODE.fullmatch(value)
        or not any(character.isdigit() for character in value)
    ):
        raise TachibanaError(ErrorClass.CONFIGURATION)
    return value


def _security_codes(values: tuple[str, ...], maximum: int) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not 1 <= len(values) <= maximum:
        raise TachibanaError(ErrorClass.CONFIGURATION)
    normalized = tuple(_security_code(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise TachibanaError(ErrorClass.CONFIGURATION)
    return normalized


def _validate_parameters(
    parameters: Mapping[str, str], contract: _FunctionContract
) -> dict[str, str]:
    """Enforce the exact parameter schema and reserve protocol credentials."""
    if not isinstance(parameters, Mapping) or set(parameters) != set(
        contract.allowed_parameters
    ):
        raise TachibanaError(ErrorClass.CONFIGURATION)
    result: dict[str, str] = {}
    for key, value in parameters.items():
        if (
            key in _PROTOCOL_PARAMETERS
            or key in _AUTH_PARAMETERS
            or key.startswith(_ORDER_PARAMETER_PREFIXES)
            or not isinstance(value, str)
            or len(value) > _MAX_PARAMETER_VALUE
        ):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        result[key] = value
    return result


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, period_seconds: float = 60.0, *, clock=time.monotonic
    ) -> None:
        self._limit = limit
        self._period = period_seconds
        self._clock = clock
        self._events: deque[float] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            self._prune()
            if len(self._events) >= self._limit:
                return False
            self._events.append(self._clock())
            return True

    def count(self) -> int:
        with self._lock:
            self._prune()
            return len(self._events)

    def _prune(self) -> None:
        now = self._clock()
        while self._events and now - self._events[0] >= self._period:
            self._events.popleft()


class CircuitBreaker:
    def __init__(
        self, threshold: int, cooldown_seconds: int, *, clock=time.monotonic
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False
        self._lock = threading.Lock()

    def permit(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return not self._half_open_probe
            if self._clock() - self._opened_at < self._cooldown:
                return False
            if self._half_open_probe:
                return False
            self._half_open_probe = True
            return True

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False

    def failure(self) -> None:
        with self._lock:
            self._half_open_probe = False
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = self._clock()

    def neutral(self) -> None:
        """Release a half-open probe without treating provider state as I/O."""
        with self._lock:
            if self._half_open_probe:
                self._half_open_probe = False
                self._opened_at = self._clock()


class TachibanaReadOnlyClient:
    def __init__(
        self,
        session: TachibanaSession,
        *,
        monotonic=time.monotonic,
        sleeper=time.sleep,
        random_source: Callable[[], float] = random.random,
        utcnow=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.session = session
        config = session.config
        self._limiter = SlidingWindowLimiter(
            config.max_requests_per_minute, clock=monotonic
        )
        self._breaker = CircuitBreaker(
            config.circuit_failure_threshold,
            config.circuit_cooldown_seconds,
            clock=monotonic,
        )
        self._sleeper = sleeper
        self._random = random_source
        self._utcnow = utcnow

    def market_price(
        self, symbols: tuple[str, ...], columns: tuple[str, ...]
    ) -> Mapping[str, Any]:
        symbols = _security_codes(symbols, self.session.config.max_symbols)
        if (
            not isinstance(columns, tuple)
            or not 1 <= len(columns) <= len(_MARKET_PRICE_COLUMNS)
            or len(set(columns)) != len(columns)
            or any(column not in _MARKET_PRICE_COLUMNS for column in columns)
        ):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        return self._read_contract("CLMMfdsGetMarketPrice", {
            "sTargetIssueCode": ",".join(symbols),
            "sTargetColumn": ",".join(columns),
        })

    def market_price_history(
        self, symbol: str, *, market: str = "00"
    ) -> Mapping[str, Any]:
        if market != "00":
            raise TachibanaError(ErrorClass.CONFIGURATION)
        return self._read_contract("CLMMfdsGetMarketPriceHistory", {
            "sIssueCode": _security_code(symbol), "sSizyouC": market,
        })

    def issue_detail(self, symbols: tuple[str, ...]) -> Mapping[str, Any]:
        return self._symbol_inquiry("CLMMfdsGetIssueDetail", symbols)

    def securities_finance_balance(
        self, symbols: tuple[str, ...]
    ) -> Mapping[str, Any]:
        return self._symbol_inquiry("CLMMfdsGetSyoukinZan", symbols)

    def margin_balance(self, symbols: tuple[str, ...]) -> Mapping[str, Any]:
        return self._symbol_inquiry("CLMMfdsGetShinyouZan", symbols)

    def reverse_day_interest(self, symbols: tuple[str, ...]) -> Mapping[str, Any]:
        return self._symbol_inquiry("CLMMfdsGetHibuInfo", symbols)

    def stock_issue_master(self) -> Mapping[str, Any]:
        return self._read_contract("CLMStkGetIssueMstKabu", {})

    def provider_calendar_date(self) -> date:
        """Return the official day-key 001 provider calendar date."""
        response = self._read_contract("CLMStkGetDateZyouhou", {})
        rows = response.get("aCLMDateZyouhou")
        if not isinstance(rows, list):
            raise TachibanaError(ErrorClass.PROVIDER)
        current_rows = [
            row for row in rows
            if isinstance(row, Mapping) and row.get("sDayKey") == "001"
        ]
        if len(current_rows) != 1:
            raise TachibanaError(ErrorClass.PROVIDER)
        value = current_rows[0].get("sTheDay")
        if not isinstance(value, str):
            raise TachibanaError(ErrorClass.PROVIDER)
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            raise TachibanaError(ErrorClass.PROVIDER) from None

    def _symbol_inquiry(
        self, function_id: str, symbols: tuple[str, ...]
    ) -> Mapping[str, Any]:
        symbols = _security_codes(symbols, self.session.config.max_symbols)
        return self._read_contract(function_id, {
            "sTargetIssueCode": ",".join(symbols),
        })

    def _read_contract(
        self, function_id: str, parameters: Mapping[str, str]
    ) -> Mapping[str, Any]:
        contract = _FUNCTION_CONTRACTS[function_id]
        clean_parameters = _validate_parameters(parameters, contract)
        attempts = self.session.config.max_read_attempts
        last_error = ErrorClass.PROVIDER

        # Authentication, logout, sequence allocation, circuit probing, and
        # reads share this lock. Re-authentication cannot invalidate a read in
        # flight and only one half-open circuit probe can escape.
        with self.session.request_lock:
            if not self._breaker.permit():
                self._record_failure(ErrorClass.CIRCUIT_OPEN)
                raise TachibanaError(ErrorClass.CIRCUIT_OPEN)
            for attempt in range(attempts):
                if not self._limiter.acquire():
                    self._breaker.neutral()
                    self.session.diagnostics.rate_limited_requests += 1
                    self._record_failure(ErrorClass.RATE_LIMITED)
                    raise TachibanaError(ErrorClass.RATE_LIMITED)
                self.session.diagnostics.requests_last_minute = self._limiter.count()
                try:
                    url = self.session._market_data_endpoint(contract.endpoint_category)
                    payload = clean_parameters.copy()
                    # Protocol-owned fields are written last.
                    payload.update(self.session._next_header())
                    payload["sCLMID"] = contract.function_id
                    response = self.session._transport.post_json(
                        url, payload, self.session.config.request_timeout_seconds
                    )
                    self._check_response(
                        response,
                        contract,
                        clean_parameters,
                        expected_p_no=payload["p_no"],
                    )
                    self._breaker.success()
                    diagnostics = self.session.diagnostics
                    diagnostics.successful_requests += 1
                    diagnostics.last_success_at = self._utcnow()
                    diagnostics.last_error_class = ErrorClass.NONE
                    diagnostics.health = ProviderHealth.AVAILABLE
                    return MappingProxyType(dict(response))
                except TachibanaError as exc:
                    last_error = exc.classification
                    retryable = last_error in {ErrorClass.NETWORK, ErrorClass.HTTP}
                    if not retryable or attempt + 1 >= attempts:
                        break
                    self._sleeper(
                        min(2.0, 0.25 * (2 ** attempt) + self._random() * 0.25)
                    )

            if last_error in {ErrorClass.NETWORK, ErrorClass.HTTP, ErrorClass.PROVIDER}:
                self._breaker.failure()
            else:
                self._breaker.neutral()
            self._record_failure(last_error)
            raise TachibanaError(last_error)

    def _check_response(
        self,
        response: Mapping[str, Any],
        contract: _FunctionContract,
        request_parameters: Mapping[str, str],
        *,
        expected_p_no: str,
    ) -> None:
        if (
            not isinstance(response, Mapping)
            or not isinstance(response.get("p_errno"), str)
        ):
            raise TachibanaError(ErrorClass.PROVIDER)
        # The REQUEST common envelope requires p_no on every response and
        # requires it to echo the request value.  An absent or different echo
        # can be a delayed/replayed response, so retire the session rather than
        # accepting same-function, same-symbol data as current.
        if response.get("p_no") != expected_p_no:
            self.session.expire()
            raise TachibanaError(ErrorClass.SEQUENCE_DESYNC)
        errno = response["p_errno"]
        if errno != "0":
            if errno in _MAINTENANCE_ERRNOS:
                raise TachibanaError(ErrorClass.MAINTENANCE)
            if errno in _RATE_ERRNOS:
                raise TachibanaError(ErrorClass.RATE_LIMITED)
            if errno == "2":
                self.session.expire()
                raise TachibanaError(ErrorClass.SESSION_EXPIRED)
            if errno == "6":
                self.session.expire()
                raise TachibanaError(ErrorClass.SEQUENCE_DESYNC)
            if errno == "8":
                raise TachibanaError(ErrorClass.CLOCK_SKEW)
            if errno == "-62":
                raise TachibanaError(ErrorClass.OUTSIDE_HOURS)
            raise TachibanaError(ErrorClass.PROVIDER)

        # Inquiry examples legitimately omit sResultCode. When present, keep
        # this business-code namespace separate from protocol p_errno.
        if "sResultCode" in response:
            if not isinstance(response["sResultCode"], str):
                raise TachibanaError(ErrorClass.PROVIDER)
            result = response["sResultCode"]
            if result != "0":
                if result in _MAINTENANCE_RESULTS:
                    raise TachibanaError(ErrorClass.MAINTENANCE)
                if result in _OUTSIDE_HOURS_RESULTS:
                    raise TachibanaError(ErrorClass.OUTSIDE_HOURS)
                if result in _SESSION_RESULTS:
                    self.session.expire()
                    raise TachibanaError(ErrorClass.SESSION_EXPIRED)
                raise TachibanaError(ErrorClass.PROVIDER)

        if response.get("sCLMID") != (
            contract.response_id or contract.function_id
        ):
            raise TachibanaError(ErrorClass.PROVIDER)
        allowed_top_level = (
            _RESPONSE_COMMON_FIELDS
            | contract.allowed_parameters
            | frozenset({contract.response_list})
        )
        if not set(response) <= allowed_top_level:
            raise TachibanaError(ErrorClass.PROVIDER)
        if contract.response_list in response:
            rows = response[contract.response_list]
            requested_symbols = tuple(filter(None, request_parameters.get(
                "sTargetIssueCode", ""
            ).split(",")))
            maximum_rows = (
                min(contract.maximum_rows, len(requested_symbols))
                if requested_symbols else contract.maximum_rows
            )
            if not isinstance(rows, list) or len(rows) > maximum_rows:
                raise TachibanaError(ErrorClass.PROVIDER)
            if any(not isinstance(row, Mapping) for row in rows):
                raise TachibanaError(ErrorClass.PROVIDER)
            if contract.function_id == "CLMMfdsGetMarketPrice":
                requested_columns = frozenset(request_parameters[
                    "sTargetColumn"
                ].split(","))
                if any(not set(row) <= requested_columns | {"sIssueCode"}
                       for row in rows):
                    raise TachibanaError(ErrorClass.PROVIDER)
            elif contract.function_id == "CLMStkGetDateZyouhou":
                date_fields = frozenset({
                    "sDayKey", "sMaeEigyouDay_1", "sMaeEigyouDay_2",
                    "sMaeEigyouDay_3", "sTheDay", "sYokuEigyouDay_1",
                    "sYokuEigyouDay_2", "sYokuEigyouDay_3",
                    "sYokuEigyouDay_4", "sYokuEigyouDay_5",
                    "sYokuEigyouDay_6", "sYokuEigyouDay_7",
                    "sYokuEigyouDay_8", "sYokuEigyouDay_9",
                    "sYokuEigyouDay_10", "sKabuUkewatasiDay",
                    "sKabuKariUkewatasiDay", "sBondUkewatasiDay",
                })
                if any(
                    not set(row) <= date_fields
                    or row.get("sDayKey") not in {"001", "002"}
                    or any(
                        not isinstance(value, str)
                        or re.fullmatch(r"[0-9]{8}", value) is None
                        for key, value in row.items()
                        if key != "sDayKey"
                    )
                    for row in rows
                ):
                    raise TachibanaError(ErrorClass.PROVIDER)
            if requested_symbols:
                returned_symbols = tuple(row.get("sIssueCode") for row in rows)
                if (
                    any(symbol not in requested_symbols for symbol in returned_symbols)
                    or len(set(returned_symbols)) != len(returned_symbols)
                ):
                    raise TachibanaError(ErrorClass.PROVIDER)
        if contract.function_id == "CLMMfdsGetMarketPriceHistory":
            if response.get("sIssueCode") not in {
                None, request_parameters["sIssueCode"]
            } or response.get("sSizyouC") not in {
                None, request_parameters["sSizyouC"]
            }:
                raise TachibanaError(ErrorClass.PROVIDER)

    def _record_failure(self, classification: ErrorClass) -> None:
        diagnostics = self.session.diagnostics
        diagnostics.failed_requests += 1
        diagnostics.last_error_class = classification
        if classification == ErrorClass.RATE_LIMITED:
            diagnostics.health = ProviderHealth.RATE_LIMITED
        elif classification == ErrorClass.MAINTENANCE:
            diagnostics.health = ProviderHealth.MAINTENANCE
        elif classification == ErrorClass.OUTSIDE_HOURS:
            diagnostics.health = ProviderHealth.UNAVAILABLE
        elif classification in {
            ErrorClass.SESSION_EXPIRED, ErrorClass.SEQUENCE_DESYNC,
        }:
            diagnostics.health = ProviderHealth.UNAVAILABLE
        else:
            diagnostics.health = ProviderHealth.DEGRADED
