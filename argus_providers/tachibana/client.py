"""Serialized, rate-bounded, structurally read-only v4r10 request client.

Only the explicitly modelled market-data/date inquiry functions below can be
sent. There is deliberately no public generic ``read``/``request`` method and
this client cannot address the REQUEST virtual URL.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import random
import re
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .models import ErrorClass, ProviderHealth, TachibanaError
from .session import TachibanaSession


@dataclass(frozen=True)
class _FunctionContract:
    function_id: str
    response_id: str
    endpoint_category: str
    allowed_parameters: frozenset[str]
    response_list: str
    maximum_rows: int
    compatible_response_ids: frozenset[str] = frozenset()
    # Row-list keys the live provider is proven to use instead of the
    # documented one.  Accepted only together with a compatible response id.
    compatible_response_lists: frozenset[str] = frozenset()

    @property
    def accepted_response_ids(self) -> frozenset[str]:
        return frozenset({self.response_id, *self.compatible_response_ids})

    @property
    def accepted_response_lists(self) -> frozenset[str]:
        return frozenset({self.response_list, *self.compatible_response_lists})


_FUNCTION_CONTRACTS: Mapping[str, _FunctionContract] = MappingProxyType({
    "CLMMfdsGetMarketPrice": _FunctionContract(
        "CLMMfdsGetMarketPrice", "CLMMfdsGetMarketPrice", "price",
        frozenset({"sTargetIssueCode", "sTargetColumn"}),
        "aCLMMfdsMarketPrice", 64,
    ),
    "CLMMfdsGetMarketPriceHistory": _FunctionContract(
        "CLMMfdsGetMarketPriceHistory", "CLMMfdsGetMarketPriceHistory", "price",
        frozenset({"sIssueCode", "sSizyouC"}),
        "aCLMMfdsMarketPriceHistory", 8_000,
    ),
    # These four use MASTER in the official interface overview. Their CLMMfds
    # prefix does not make them PRICE functions.
    "CLMMfdsGetIssueDetail": _FunctionContract(
        "CLMMfdsGetIssueDetail", "CLMMfdsGetIssueDetail", "master",
        frozenset({"sTargetIssueCode"}),
        "aCLMMfdsIssueDetail", 64,
    ),
    "CLMMfdsGetSyoukinZan": _FunctionContract(
        "CLMMfdsGetSyoukinZan", "CLMMfdsGetSyoukinZan", "master",
        frozenset({"sTargetIssueCode"}),
        "aCLMMfdsSyoukinZan", 64,
    ),
    "CLMMfdsGetShinyouZan": _FunctionContract(
        "CLMMfdsGetShinyouZan", "CLMMfdsGetShinyouZan", "master",
        frozenset({"sTargetIssueCode"}),
        "aCLMMfdsShinyouZan", 64,
    ),
    "CLMMfdsGetHibuInfo": _FunctionContract(
        "CLMMfdsGetHibuInfo", "CLMMfdsGetHibuInfo", "master",
        frozenset({"sTargetIssueCode"}),
        "aCLMMfdsHibuInfo", 64,
    ),
    "CLMStkGetIssueMstKabu": _FunctionContract(
        "CLMStkGetIssueMstKabu", "CLMStkGetIssueMstKabu", "master", frozenset(),
        "aCLMStkIssueMstKabu", 20_000,
    ),
    # Current v4r10 official master inquiry. Day key 001 supplies the
    # provider's current calendar date; it is deliberately distinct from an
    # EVENT packet's send date and SS/US effective time.
    "CLMStkGetDateZyouhou": _FunctionContract(
        "CLMStkGetDateZyouhou", "CLMDateZyouhou", "master", frozenset(),
        "aCLMDateZyouhou", 2,
        # Live v4r10 production evidence on 2026-09-02 returned the request
        # identifier here instead of the documented response identifier.
        # This compatibility exception is deliberately Date-only.
        frozenset({"CLMStkGetDateZyouhou"}),
        # Live v4r10 production evidence on 2026-09-03 (bounded names-only
        # diagnostic session, 10:46 JST): the same echo response names its
        # row list "aCLMStkDateZyouhou" instead of the documented
        # "aCLMDateZyouhou".  Accepted only with the echoed sCLMID above and
        # normalized to the documented key before any consumer sees it.
        compatible_response_lists=frozenset({"aCLMStkDateZyouhou"}),
    ),
})

# Public for auditability, immutable for safety. Values use the provider's
# documented virtual-URL category names.
READ_ONLY_FUNCTIONS: Mapping[str, str] = MappingProxyType({
    function_id: contract.endpoint_category.upper()
    for function_id, contract in _FUNCTION_CONTRACTS.items()
})
READ_ONLY_RESPONSE_IDS: Mapping[str, str] = MappingProxyType({
    function_id: contract.response_id
    for function_id, contract in _FUNCTION_CONTRACTS.items()
})
READ_ONLY_COMPATIBLE_RESPONSE_IDS: Mapping[str, frozenset[str]] = (
    MappingProxyType({
        function_id: contract.compatible_response_ids
        for function_id, contract in _FUNCTION_CONTRACTS.items()
        if contract.compatible_response_ids
    })
)
READ_ONLY_COMPATIBLE_RESPONSE_LISTS: Mapping[str, frozenset[str]] = (
    MappingProxyType({
        function_id: contract.compatible_response_lists
        for function_id, contract in _FUNCTION_CONTRACTS.items()
        if contract.compatible_response_lists
    })
)

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
_READ_DIAGNOSTIC_STAGES = frozenset({
    "NOT_STARTED",
    "PROVIDER_DATE_REQUEST", "PROVIDER_DATE_HTTP",
    "PROVIDER_DATE_RESPONSE_CLMID", "PROVIDER_DATE_SCHEMA",
    "PROVIDER_DATE_DAYKEY", "PROVIDER_DATE_VALUE",
    "PRICE_BASELINE_REQUEST", "PRICE_BASELINE_HTTP",
    "PRICE_BASELINE_RESPONSE_CLMID", "PRICE_BASELINE_SCHEMA",
    "PRICE_BASELINE_NORMALIZE",
    "PROVIDER_READ_REQUEST", "PROVIDER_READ_HTTP",
    "PROVIDER_READ_RESPONSE_CLMID", "PROVIDER_READ_SCHEMA",
})
_READ_DIAGNOSTIC_TOKENS = frozenset({
    "CIRCUIT_NOT_PERMITTED", "LOCAL_RATE_LIMIT",
    "TRANSPORT_OR_PROVIDER_CLASSIFICATION", "PROTOCOL_ERRNO_MISSING",
    "SEQUENCE_ECHO_MISMATCH", "PROTOCOL_MAINTENANCE",
    "PROTOCOL_RATE_LIMIT", "PROTOCOL_SESSION_EXPIRED",
    "PROTOCOL_SEQUENCE_ERROR", "PROTOCOL_CLOCK_SKEW",
    "PROTOCOL_OUTSIDE_HOURS", "PROTOCOL_ERROR", "RESULT_CODE_INVALID",
    "RESULT_MAINTENANCE", "RESULT_OUTSIDE_HOURS", "RESULT_SESSION_EXPIRED",
    "RESULT_ERROR", "CLMID_MISMATCH", "TOP_LEVEL_FIELD_UNKNOWN",
    "RESPONSE_LIST_SHAPE_INVALID",
    "ROW_LIST_INVALID", "ROW_TYPE_INVALID", "PRICE_ROW_FIELD_UNKNOWN",
    "DATE_ROW_INVALID", "SYMBOL_IDENTITY_INVALID", "HISTORY_IDENTITY_INVALID",
    "DATE_LIST_MISSING", "DAYKEY_001_MISSING", "DAYKEY_001_DUPLICATE",
    "DAYKEY_001_CONFLICT", "CURRENT_DATE_MISSING", "CURRENT_DATE_INVALID",
    "PRICE_ROW_SET_INCOMPLETE", "NORMALIZED_SYMBOL_SET_MISMATCH",
    "NORMALIZATION_REJECTED", "NORMALIZATION_EXCEPTION",
})
_READ_DIAGNOSTIC_CLASSIFICATIONS = frozenset({
    "NOT_ATTEMPTED", "IN_PROGRESS", "PASS",
    *(classification.value for classification in ErrorClass),
})


@dataclass(frozen=True)
class ProviderReadDiagnostic:
    """One bounded, value-free initial/read contract boundary."""

    operation: str = "NONE"
    endpoint_class: str | None = None
    stage: str = "NOT_STARTED"
    classification: str = "NOT_ATTEMPTED"
    http_status: int | None = None
    expected_response_clmid: str | None = None
    observed_response_clmid: str | None = None
    response_clmid_mode: str | None = None
    response_list_mode: str | None = None
    result_code: str | None = None
    schema_failure_token: str | None = None
    # Names only (never values) of top-level response keys outside the
    # contract, so a live schema mismatch is diagnosable without retaining
    # any provider payload.  Bounded: identifier characters, <= 40 chars,
    # <= 8 names.
    unexpected_top_level_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.unexpected_top_level_fields) is not tuple
            or len(self.unexpected_top_level_fields) > 8
            or any(
                type(name) is not str
                or re.fullmatch(r"[A-Za-z0-9_]{1,40}", name) is None
                for name in self.unexpected_top_level_fields
            )
            or self.operation not in {"NONE", *_FUNCTION_CONTRACTS}
            or self.endpoint_class not in {None, "MASTER", "PRICE"}
            or self.stage not in _READ_DIAGNOSTIC_STAGES
            or self.classification not in _READ_DIAGNOSTIC_CLASSIFICATIONS
            or self.http_status is not None
            and (type(self.http_status) is not int or not 100 <= self.http_status <= 599)
            or any(
                value is not None
                and re.fullmatch(r"[A-Za-z0-9_]{1,128}", value) is None
                for value in (
                    self.expected_response_clmid,
                    self.observed_response_clmid,
                )
            )
            or self.response_clmid_mode not in {
                None, "DOCUMENTED", "PRODUCTION_ECHO_COMPAT"
            }
            or self.response_list_mode not in {
                None, "DOCUMENTED", "PRODUCTION_ECHO_COMPAT"
            }
            or self.result_code is not None
            and re.fullmatch(r"[0-9-]{1,16}", self.result_code) is None
            or self.schema_failure_token not in {
                None, *_READ_DIAGNOSTIC_TOKENS
            }
        ):
            raise ValueError("invalid_provider_read_diagnostic")

    def safe_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "endpointClass": self.endpoint_class,
            "stage": self.stage,
            "classification": self.classification,
            "httpStatus": self.http_status,
            "expectedResponseCLMID": self.expected_response_clmid,
            "observedResponseCLMID": self.observed_response_clmid,
            "responseCLMIDMode": self.response_clmid_mode,
            "responseListMode": self.response_list_mode,
            "resultCode": self.result_code,
            "schemaFailureToken": self.schema_failure_token,
            "unexpectedTopLevelFields": list(self.unexpected_top_level_fields),
        }


_UNEXPECTED_FIELD_NAME = re.compile(r"[A-Za-z0-9_]{1,40}")


def _safe_field_names(names: Iterable[object]) -> tuple[str, ...]:
    """Reduce foreign key names to a bounded, value-free identifier list."""
    safe: list[str] = []
    for name in sorted(str(item) for item in names):
        safe.append(
            name if _UNEXPECTED_FIELD_NAME.fullmatch(name) else "INVALID_NAME"
        )
        if len(safe) == 8:
            break
    return tuple(safe)


class _ReadContractError(TachibanaError):
    def __init__(
        self, classification: ErrorClass, *, stage_suffix: str, token: str,
        unexpected_fields: tuple[str, ...] = (),
    ) -> None:
        self.stage_suffix = stage_suffix
        self.token = token
        self.unexpected_fields = unexpected_fields
        super().__init__(classification)


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
        self.last_read_diagnostic = ProviderReadDiagnostic()

    def read_diagnostic_safe_dict(self) -> dict[str, object]:
        return self.last_read_diagnostic.safe_dict()

    def mark_last_read_stage(
        self,
        stage: str,
        classification: str,
        *,
        schema_failure_token: str | None = None,
    ) -> None:
        """Advance the current safe diagnostic after contract validation.

        The runtime uses this only for PRICE baseline interpretation. It may
        attach a bounded token but can never add provider values or payloads.
        """
        self.last_read_diagnostic = replace(
            self.last_read_diagnostic,
            stage=stage,
            classification=classification,
            schema_failure_token=schema_failure_token,
        )

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
            self.mark_last_read_stage(
                "PROVIDER_DATE_SCHEMA", ErrorClass.PROVIDER.value,
                schema_failure_token="DATE_LIST_MISSING",
            )
            raise TachibanaError(ErrorClass.PROVIDER)
        current_rows = [
            row for row in rows
            if isinstance(row, Mapping) and row.get("sDayKey") == "001"
        ]
        if not current_rows:
            self.mark_last_read_stage(
                "PROVIDER_DATE_DAYKEY", ErrorClass.PROVIDER.value,
                schema_failure_token="DAYKEY_001_MISSING",
            )
            raise TachibanaError(ErrorClass.PROVIDER)
        if len(current_rows) > 1:
            dates = {row.get("sTheDay") for row in current_rows}
            self.mark_last_read_stage(
                "PROVIDER_DATE_DAYKEY", ErrorClass.PROVIDER.value,
                schema_failure_token=(
                    "DAYKEY_001_DUPLICATE"
                    if len(dates) == 1
                    else "DAYKEY_001_CONFLICT"
                ),
            )
            raise TachibanaError(ErrorClass.PROVIDER)
        value = current_rows[0].get("sTheDay")
        if not isinstance(value, str):
            self.mark_last_read_stage(
                "PROVIDER_DATE_VALUE", ErrorClass.PROVIDER.value,
                schema_failure_token="CURRENT_DATE_MISSING",
            )
            raise TachibanaError(ErrorClass.PROVIDER)
        try:
            result = datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            self.mark_last_read_stage(
                "PROVIDER_DATE_VALUE", ErrorClass.PROVIDER.value,
                schema_failure_token="CURRENT_DATE_INVALID",
            )
            raise TachibanaError(ErrorClass.PROVIDER) from None
        self.mark_last_read_stage("PROVIDER_DATE_VALUE", "PASS")
        return result

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
        stage_prefix = (
            "PROVIDER_DATE"
            if function_id == "CLMStkGetDateZyouhou"
            else "PRICE_BASELINE"
            if function_id == "CLMMfdsGetMarketPrice"
            else "PROVIDER_READ"
        )
        self.last_read_diagnostic = ProviderReadDiagnostic(
            operation=function_id,
            endpoint_class=contract.endpoint_category.upper(),
            stage=f"{stage_prefix}_REQUEST",
            classification="IN_PROGRESS",
            expected_response_clmid=contract.response_id,
        )
        attempts = self.session.config.max_read_attempts
        last_error = ErrorClass.PROVIDER

        # Authentication, logout, sequence allocation, circuit probing, and
        # reads share this lock. Re-authentication cannot invalidate a read in
        # flight and only one half-open circuit probe can escape.
        with self.session.request_lock:
            if not self._breaker.permit():
                self.mark_last_read_stage(
                    f"{stage_prefix}_REQUEST", ErrorClass.CIRCUIT_OPEN.value,
                    schema_failure_token="CIRCUIT_NOT_PERMITTED",
                )
                self._record_failure(ErrorClass.CIRCUIT_OPEN)
                raise TachibanaError(ErrorClass.CIRCUIT_OPEN)
            for attempt in range(attempts):
                if not self._limiter.acquire():
                    self._breaker.neutral()
                    self.session.diagnostics.rate_limited_requests += 1
                    self.mark_last_read_stage(
                        f"{stage_prefix}_REQUEST",
                        ErrorClass.RATE_LIMITED.value,
                        schema_failure_token="LOCAL_RATE_LIMIT",
                    )
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
                    self.last_read_diagnostic = replace(
                        self.last_read_diagnostic,
                        stage=f"{stage_prefix}_HTTP",
                        classification="PASS",
                        http_status=self._safe_http_status(),
                        observed_response_clmid=self._safe_clmid(response),
                        result_code=self._safe_result_code(response),
                        schema_failure_token=None,
                    )
                    self._check_response(
                        response,
                        contract,
                        clean_parameters,
                        expected_p_no=payload["p_no"],
                    )
                    if function_id == "CLMStkGetDateZyouhou":
                        compat_list = next((
                            key for key in sorted(contract.compatible_response_lists)
                            if key in response
                        ), None)
                        if compat_list is not None:
                            # Normalize the live-proven echo list key to the
                            # documented key so no consumer learns a second
                            # spelling.  _check_response already rejected any
                            # ambiguous or mismatched shape.
                            normalized = dict(response)
                            normalized[contract.response_list] = normalized.pop(
                                compat_list
                            )
                            response = normalized
                        self.last_read_diagnostic = replace(
                            self.last_read_diagnostic,
                            response_clmid_mode=(
                                "DOCUMENTED"
                                if response.get("sCLMID") == contract.response_id
                                else "PRODUCTION_ECHO_COMPAT"
                            ),
                            response_list_mode=(
                                "DOCUMENTED"
                                if compat_list is None
                                else "PRODUCTION_ECHO_COMPAT"
                            ),
                        )
                    self._breaker.success()
                    diagnostics = self.session.diagnostics
                    diagnostics.successful_requests += 1
                    diagnostics.last_success_at = self._utcnow()
                    diagnostics.last_error_class = ErrorClass.NONE
                    diagnostics.health = ProviderHealth.AVAILABLE
                    self.mark_last_read_stage(f"{stage_prefix}_SCHEMA", "PASS")
                    return MappingProxyType(dict(response))
                except TachibanaError as exc:
                    last_error = exc.classification
                    if isinstance(exc, _ReadContractError):
                        stage = f"{stage_prefix}_{exc.stage_suffix}"
                        token = exc.token
                        unexpected_fields = exc.unexpected_fields
                    else:
                        stage = f"{stage_prefix}_HTTP"
                        token = "TRANSPORT_OR_PROVIDER_CLASSIFICATION"
                        unexpected_fields = ()
                    self.last_read_diagnostic = replace(
                        self.last_read_diagnostic,
                        stage=stage,
                        classification=last_error.value,
                        http_status=self._safe_http_status(),
                        schema_failure_token=token,
                        unexpected_top_level_fields=unexpected_fields,
                    )
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

    def _safe_http_status(self) -> int | None:
        value = getattr(self.session._transport, "last_http_status", None)
        return value if type(value) is int and 100 <= value <= 599 else None

    @staticmethod
    def _safe_clmid(response: object) -> str | None:
        if not isinstance(response, Mapping):
            return None
        value = response.get("sCLMID")
        if isinstance(value, str) and re.fullmatch(
            r"[A-Za-z0-9_]{1,128}", value
        ):
            return value
        return None

    @staticmethod
    def _safe_result_code(response: object) -> str | None:
        if not isinstance(response, Mapping):
            return None
        value = response.get("sResultCode")
        if isinstance(value, str) and re.fullmatch(r"[0-9-]{1,16}", value):
            return value
        return None

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
            raise _ReadContractError(
                ErrorClass.PROVIDER,
                stage_suffix="SCHEMA",
                token="PROTOCOL_ERRNO_MISSING",
            )
        # The REQUEST common envelope requires p_no on every response and
        # requires it to echo the request value.  An absent or different echo
        # can be a delayed/replayed response, so retire the session rather than
        # accepting same-function, same-symbol data as current.
        if response.get("p_no") != expected_p_no:
            self.session.expire()
            raise _ReadContractError(
                ErrorClass.SEQUENCE_DESYNC,
                stage_suffix="SCHEMA",
                token="SEQUENCE_ECHO_MISMATCH",
            )
        errno = response["p_errno"]
        if errno != "0":
            if errno in _MAINTENANCE_ERRNOS:
                raise _ReadContractError(
                    ErrorClass.MAINTENANCE,
                    stage_suffix="SCHEMA", token="PROTOCOL_MAINTENANCE",
                )
            if errno in _RATE_ERRNOS:
                raise _ReadContractError(
                    ErrorClass.RATE_LIMITED,
                    stage_suffix="SCHEMA", token="PROTOCOL_RATE_LIMIT",
                )
            if errno == "2":
                self.session.expire()
                raise _ReadContractError(
                    ErrorClass.SESSION_EXPIRED,
                    stage_suffix="SCHEMA", token="PROTOCOL_SESSION_EXPIRED",
                )
            if errno == "6":
                self.session.expire()
                raise _ReadContractError(
                    ErrorClass.SEQUENCE_DESYNC,
                    stage_suffix="SCHEMA", token="PROTOCOL_SEQUENCE_ERROR",
                )
            if errno == "8":
                raise _ReadContractError(
                    ErrorClass.CLOCK_SKEW,
                    stage_suffix="SCHEMA", token="PROTOCOL_CLOCK_SKEW",
                )
            if errno == "-62":
                raise _ReadContractError(
                    ErrorClass.OUTSIDE_HOURS,
                    stage_suffix="SCHEMA", token="PROTOCOL_OUTSIDE_HOURS",
                )
            raise _ReadContractError(
                ErrorClass.PROVIDER,
                stage_suffix="SCHEMA", token="PROTOCOL_ERROR",
            )

        # Inquiry examples legitimately omit sResultCode. When present, keep
        # this business-code namespace separate from protocol p_errno.
        if "sResultCode" in response:
            if not isinstance(response["sResultCode"], str):
                raise _ReadContractError(
                    ErrorClass.PROVIDER,
                    stage_suffix="SCHEMA", token="RESULT_CODE_INVALID",
                )
            result = response["sResultCode"]
            if result != "0":
                if result in _MAINTENANCE_RESULTS:
                    raise _ReadContractError(
                        ErrorClass.MAINTENANCE,
                        stage_suffix="SCHEMA", token="RESULT_MAINTENANCE",
                    )
                if result in _OUTSIDE_HOURS_RESULTS:
                    raise _ReadContractError(
                        ErrorClass.OUTSIDE_HOURS,
                        stage_suffix="SCHEMA", token="RESULT_OUTSIDE_HOURS",
                    )
                if result in _SESSION_RESULTS:
                    self.session.expire()
                    raise _ReadContractError(
                        ErrorClass.SESSION_EXPIRED,
                        stage_suffix="SCHEMA", token="RESULT_SESSION_EXPIRED",
                    )
                raise _ReadContractError(
                    ErrorClass.PROVIDER,
                    stage_suffix="SCHEMA", token="RESULT_ERROR",
                )

        if response.get("sCLMID") not in contract.accepted_response_ids:
            raise _ReadContractError(
                ErrorClass.PROVIDER,
                stage_suffix="RESPONSE_CLMID", token="CLMID_MISMATCH",
            )
        allowed_top_level = (
            _RESPONSE_COMMON_FIELDS
            | contract.allowed_parameters
            | contract.accepted_response_lists
        )
        if not set(response) <= allowed_top_level:
            raise _ReadContractError(
                ErrorClass.PROVIDER,
                stage_suffix="SCHEMA", token="TOP_LEVEL_FIELD_UNKNOWN",
                unexpected_fields=_safe_field_names(
                    set(response) - allowed_top_level
                ),
            )
        present_lists = [
            key for key in sorted(contract.accepted_response_lists)
            if key in response
        ]
        # Exactly one row-list key may appear, and a live-compatible key is
        # accepted only in the same echo shape that was live-proven (the
        # echoed sCLMID).  Any other combination is an unknown shape.
        if len(present_lists) > 1 or (
            present_lists
            and present_lists[0] != contract.response_list
            and response.get("sCLMID") not in contract.compatible_response_ids
        ):
            raise _ReadContractError(
                ErrorClass.PROVIDER,
                stage_suffix="SCHEMA", token="RESPONSE_LIST_SHAPE_INVALID",
            )
        response_list = (
            present_lists[0] if present_lists else contract.response_list
        )
        if response_list in response:
            rows = response[response_list]
            requested_symbols = tuple(filter(None, request_parameters.get(
                "sTargetIssueCode", ""
            ).split(",")))
            maximum_rows = (
                min(contract.maximum_rows, len(requested_symbols))
                if requested_symbols else contract.maximum_rows
            )
            if not isinstance(rows, list) or len(rows) > maximum_rows:
                raise _ReadContractError(
                    ErrorClass.PROVIDER,
                    stage_suffix="SCHEMA", token="ROW_LIST_INVALID",
                )
            if any(not isinstance(row, Mapping) for row in rows):
                raise _ReadContractError(
                    ErrorClass.PROVIDER,
                    stage_suffix="SCHEMA", token="ROW_TYPE_INVALID",
                )
            if contract.function_id == "CLMMfdsGetMarketPrice":
                requested_columns = frozenset(request_parameters[
                    "sTargetColumn"
                ].split(","))
                if any(not set(row) <= requested_columns | {"sIssueCode"}
                       for row in rows):
                    raise _ReadContractError(
                        ErrorClass.PROVIDER,
                        stage_suffix="SCHEMA", token="PRICE_ROW_FIELD_UNKNOWN",
                    )
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
                    raise _ReadContractError(
                        ErrorClass.PROVIDER,
                        stage_suffix="SCHEMA", token="DATE_ROW_INVALID",
                    )
            if requested_symbols:
                returned_symbols = tuple(row.get("sIssueCode") for row in rows)
                if (
                    any(symbol not in requested_symbols for symbol in returned_symbols)
                    or len(set(returned_symbols)) != len(returned_symbols)
                ):
                    raise _ReadContractError(
                        ErrorClass.PROVIDER,
                        stage_suffix="SCHEMA", token="SYMBOL_IDENTITY_INVALID",
                    )
        if contract.function_id == "CLMMfdsGetMarketPriceHistory":
            if response.get("sIssueCode") not in {
                None, request_parameters["sIssueCode"]
            } or response.get("sSizyouC") not in {
                None, request_parameters["sSizyouC"]
            }:
                raise _ReadContractError(
                    ErrorClass.PROVIDER,
                    stage_suffix="SCHEMA", token="HISTORY_IDENTITY_INVALID",
                )

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
