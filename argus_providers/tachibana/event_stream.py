"""Receive-only Tachibana EVENT WebSocket transport and bounded lifecycle.

The official WebSocket is a delivery-only RFC 6455 text stream.  This module
doesn't expose a send method, doesn't log credential-equivalent virtual URLs,
and remains unreachable unless both the provider and WebSocket feature flags
are explicitly enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
import random
import re
import socket
import threading
import time
from typing import Callable, Iterable, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .models import (
    Diagnostics,
    ErrorClass,
    MarketStatus,
    NormalizationIssue,
    ProviderHealth,
    TachibanaError,
)
from .normalization import normalize_market_price
from .sensor import (
    EventConnectionPolicy,
    EventConnector,
    EventReconnectBudget,
    EventSnapshotAssembler,
    EventSubscription,
    TransientLiveSensor,
    event_unknown_noncritical_field_count,
    parse_event_frame,
)
from .session import TachibanaSession
from .session_truth import JapanCashPhase, SessionTruth, parse_provider_datetime


TOKYO = ZoneInfo("Asia/Tokyo")
_MAX_EVENT_FRAME_BYTES = 256 * 1024
_ALLOWED_EVENT_HOSTS = frozenset({
    "kabuka.e-shiten.jp",
    "price-kabuka.e-shiten.jp",
    "demo-kabuka.e-shiten.jp",
})
_EVENT_WS_PATH = re.compile(
    r"^/e_api_v4r10/event_ws/[A-Za-z0-9+_=-]{1,1024}/$"
)
_ST_ERROR_CLASSES = {
    "-62": ErrorClass.OUTSIDE_HOURS,
    "-12": ErrorClass.MAINTENANCE,
    "-3": ErrorClass.PROVIDER,
    "-2": ErrorClass.PROVIDER,
    "-1": ErrorClass.CONFIGURATION,
    "0": ErrorClass.PROVIDER,
    "1": ErrorClass.PROVIDER,
    "2": ErrorClass.SESSION_EXPIRED,
    "9": ErrorClass.MAINTENANCE,
}
_DEFINITELY_CLOSED_STOCK_OPERATIONS = frozenset({
    "140",  # morning session ended
    "160",  # morning execution notifications ended
    "260",  # afternoon session ended
    "280",  # afternoon execution notifications ended
    "290",  # delivery/receipt stopped
    "300",  # equities closed
    "400",  # repricing
    "500",  # next-day acceptance
    "700",  # repricing completed
    "900",  # online closed
})
_FAULT_STOCK_OPERATIONS = frozenset({"898", "899"})
_MAX_SYSTEM_STATUS_KEYS = 8
_MAX_OPERATION_STATUS_KEYS = 64
# The provider allows only one EVENT connection per customer.  ARGUS has no
# safe, non-secret customer identifier to key by, so enforce the conservative
# process-wide singleton rather than risk two sessions evicting each other.
_PROCESS_EVENT_LOCK = threading.Lock()


class EventTransportError(TachibanaError):
    """A bounded transport error carrying only non-secret diagnostics."""

    def __init__(
        self,
        classification: ErrorClass,
        *,
        close_code: int | None = None,
        close_reason_classification: str | None = None,
        timeout_category: str | None = None,
    ) -> None:
        if (
            (
                close_code is not None
                and (
                    type(close_code) is not int
                    or not 1000 <= close_code <= 4999
                )
            )
            or close_reason_classification
            not in {None, "EMPTY", "PRESENT_REDACTED"}
            or timeout_category not in {None, "CONNECT", "IDLE"}
        ):
            raise ValueError("invalid_event_transport_diagnostic")
        self.close_code = close_code
        self.close_reason_classification = close_reason_classification
        self.timeout_category = timeout_category
        super().__init__(classification)


def _safe_close_diagnostics(error: Exception) -> tuple[int | None, str | None]:
    received = getattr(error, "rcvd", None)
    code = getattr(received, "code", None)
    reason = getattr(received, "reason", None)
    if code is None:
        code = getattr(error, "code", None)
    if reason is None:
        reason = getattr(error, "reason", None)
    safe_code = code if type(code) is int and 1000 <= code <= 4999 else None
    if reason is None:
        safe_reason = None
    elif isinstance(reason, str) and reason == "":
        safe_reason = "EMPTY"
    else:
        safe_reason = "PRESENT_REDACTED"
    return safe_code, safe_reason


class _WebSocketConnection(Protocol):
    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


class _WebSocketConnectFactory(Protocol):
    def __call__(self, uri: str, **kwargs: object) -> _WebSocketConnection: ...


_PRIVATE_LOGGER = logging.Logger(
    "argus.tachibana.event.private", level=logging.CRITICAL + 1
)
_PRIVATE_LOGGER.disabled = True
_PRIVATE_LOGGER.propagate = False
_PRIVATE_LOGGER.addHandler(logging.NullHandler())


def _validated_event_url(endpoint: str, subscription: EventSubscription) -> str:
    """Build the official query without retaining or rendering the secret URL."""
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID)
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID) from None
    if (
        parsed.scheme != "wss"
        or parsed.hostname not in _ALLOWED_EVENT_HOSTS
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or _EVENT_WS_PATH.fullmatch(parsed.path) is None
    ):
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID)
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        subscription.query_string(),
        "",
    ))


def _default_websocket_connect(
    uri: str, **kwargs: object
) -> _WebSocketConnection:
    # Import lazily: disabled-by-default deployments don't need to import or
    # initialize a WebSocket stack.  Import/provider details never reach the
    # bounded public error.
    try:
        from websockets.sync.client import connect
    except (ImportError, RuntimeError):
        raise TachibanaError(ErrorClass.CONFIGURATION) from None
    try:
        return connect(uri, **kwargs)
    except TachibanaError:
        raise
    except TimeoutError:
        raise EventTransportError(
            ErrorClass.NETWORK, timeout_category="CONNECT"
        ) from None
    except Exception as error:
        close_code, close_reason = _safe_close_diagnostics(error)
        raise EventTransportError(
            ErrorClass.NETWORK,
            close_code=close_code,
            close_reason_classification=close_reason,
        ) from None


class WebSocketEventConnector:
    """Bounded EVENT receiver with no application-data send surface."""

    def __init__(
        self,
        connect_factory: _WebSocketConnectFactory | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connect_factory = connect_factory or _default_websocket_connect
        self._monotonic = monotonic

    def receive(
        self,
        endpoint: str,
        subscription: EventSubscription,
        *,
        connect_timeout_seconds: int,
        idle_timeout_seconds: int,
        maximum_frame_bytes: int,
        stop_event: threading.Event,
    ) -> Iterable[str]:
        if (
            not isinstance(subscription, EventSubscription)
            or not isinstance(stop_event, threading.Event)
            or type(connect_timeout_seconds) is not int
            or type(idle_timeout_seconds) is not int
            or type(maximum_frame_bytes) is not int
            or not 2 <= connect_timeout_seconds <= 30
            or not 5 <= idle_timeout_seconds <= 120
            or not 1 <= maximum_frame_bytes <= _MAX_EVENT_FRAME_BYTES
        ):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        if stop_event.is_set():
            return ()
        uri = _validated_event_url(endpoint, subscription)
        try:
            connection = self._connect_factory(
                uri,
                open_timeout=float(connect_timeout_seconds),
                close_timeout=min(2.0, float(connect_timeout_seconds)),
                max_size=maximum_frame_bytes,
                max_queue=1,
                compression=None,
                # Tachibana already provides an application keepalive (KP)
                # after five seconds without another notification.
                ping_interval=None,
                proxy=None,
                logger=_PRIVATE_LOGGER,
            )
        except TachibanaError:
            raise
        except TimeoutError:
            raise EventTransportError(
                ErrorClass.NETWORK, timeout_category="CONNECT"
            ) from None
        except Exception as error:
            close_code, close_reason = _safe_close_diagnostics(error)
            raise EventTransportError(
                ErrorClass.NETWORK,
                close_code=close_code,
                close_reason_classification=close_reason,
            ) from None

        def _messages() -> Iterable[str]:
            last_message_at = self._monotonic()
            try:
                while not stop_event.is_set():
                    remaining = (
                        float(idle_timeout_seconds)
                        - (self._monotonic() - last_message_at)
                    )
                    if remaining <= 0:
                        raise EventTransportError(
                            ErrorClass.EVENT_IDLE_TIMEOUT,
                            timeout_category="IDLE",
                        )
                    try:
                        message = connection.recv(timeout=min(1.0, remaining))
                    except TimeoutError:
                        if self._monotonic() - last_message_at >= idle_timeout_seconds:
                            raise EventTransportError(
                                ErrorClass.EVENT_IDLE_TIMEOUT,
                                timeout_category="IDLE",
                            ) from None
                        continue
                    except TachibanaError:
                        raise
                    except Exception as error:
                        close_code, close_reason = _safe_close_diagnostics(error)
                        raise EventTransportError(
                            ErrorClass.NETWORK,
                            close_code=close_code,
                            close_reason_classification=close_reason,
                        ) from None
                    # The official contract specifies RFC 6455 text frames.
                    # Binary messages are not silently decoded as Shift-JIS.
                    if not isinstance(message, str):
                        raise TachibanaError(ErrorClass.PROVIDER)
                    try:
                        wire_size = len(message.encode("utf-8"))
                    except UnicodeEncodeError:
                        raise TachibanaError(ErrorClass.PROVIDER) from None
                    if wire_size > maximum_frame_bytes:
                        raise TachibanaError(ErrorClass.PROVIDER)
                    last_message_at = self._monotonic()
                    yield message
            finally:
                try:
                    connection.close()
                except Exception:
                    pass

        return _messages()


@dataclass(frozen=True)
class EventStatusSnapshot:
    provider_health: ProviderHealth
    market_status: MarketStatus
    login_permission_code: str | None = None
    system_status_code: str | None = None
    system_effective_time: datetime | None = None
    operation_code: str | None = None
    operation_effective_time: datetime | None = None
    status_date_verified: bool = False
    state_conflict: bool = False


@dataclass(frozen=True)
class _SystemStatusState:
    effective_time: datetime
    login_permission: str
    system_status: str


@dataclass(frozen=True)
class _OperationStatusState:
    effective_time: datetime
    business_day: str
    operation_status: str


class EventStatusTracker:
    """Reconstruct current SS/US state conservatively from replayed records."""

    def __init__(self, *, provider_calendar_date: date | None = None) -> None:
        if provider_calendar_date is not None and not isinstance(
            provider_calendar_date, date
        ):
            raise ValueError("invalid_provider_calendar_date")
        self._provider_calendar_date = provider_calendar_date
        self._system_states: dict[tuple[str], _SystemStatusState] = {}
        self._operation_states: dict[
            tuple[str, str, str, str, str, str], _OperationStatusState
        ] = {}
        self._system_conflicts: set[tuple[str]] = set()
        self._operation_conflicts: set[
            tuple[str, str, str, str, str, str]
        ] = set()
        self._overflow = False
        self._traffic_observed = False
        self._terminal_status = False

    @property
    def snapshot(self) -> EventStatusSnapshot:
        return self._reconcile()

    @staticmethod
    def _control_time(value: str) -> datetime:
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(
            tzinfo=TOKYO
        ).astimezone(timezone.utc)

    def _is_current_date(self, effective_time: datetime) -> bool:
        return bool(
            self._provider_calendar_date is None
            or effective_time.astimezone(TOKYO).date()
            == self._provider_calendar_date
        )

    @staticmethod
    def _cash_equity_key(
        key: tuple[str, str, str, str, str, str]
    ) -> bool:
        _provider, market, group, product, category, unit = key
        return bool(
            category == "01"
            and unit == "0101"
            and market in {"00", "01"}
            and group == ""
            and product in {"", "01"}
        )

    def _reconcile(self) -> EventStatusSnapshot:
        if self._terminal_status:
            return EventStatusSnapshot(
                ProviderHealth.UNAVAILABLE,
                MarketStatus.UNKNOWN,
                state_conflict=bool(
                    self._system_conflicts or self._operation_conflicts
                ),
            )
        systems = [
            state for state in self._system_states.values()
            if self._is_current_date(state.effective_time)
        ]
        relevant_operations = [
            state for key, state in self._operation_states.items()
            if self._cash_equity_key(key)
            and self._is_current_date(state.effective_time)
        ]
        current_system_conflict = any(
            key in self._system_conflicts
            and self._is_current_date(self._system_states[key].effective_time)
            for key in self._system_states
        )
        current_operation_conflict = any(
            key in self._operation_conflicts
            and self._cash_equity_key(key)
            and self._is_current_date(self._operation_states[key].effective_time)
            for key in self._operation_states
        )
        state_conflict = bool(
            self._overflow
            or current_system_conflict
            or current_operation_conflict
        )

        health = (
            ProviderHealth.AVAILABLE
            if self._traffic_observed or systems or relevant_operations
            else ProviderHealth.UNAVAILABLE
        )
        permissions = {state.login_permission for state in systems}
        if "0" in permissions:
            health = ProviderHealth.MAINTENANCE
        elif permissions & {"2", "9"}:
            health = ProviderHealth.UNAVAILABLE
        elif permissions == {"1"}:
            # p_LK=1 means login is permitted. p_SS=1 is a system closure
            # state, not a provider-health failure and not an exchange phase.
            health = ProviderHealth.AVAILABLE
        if (
            health == ProviderHealth.AVAILABLE
            and any(
                state.operation_status in _FAULT_STOCK_OPERATIONS
                for state in relevant_operations
            )
        ) or state_conflict and health == ProviderHealth.AVAILABLE:
            health = ProviderHealth.DEGRADED

        if health == ProviderHealth.MAINTENANCE:
            market_status = MarketStatus.MAINTENANCE
        elif current_operation_conflict or self._overflow:
            market_status = MarketStatus.UNKNOWN
        elif any(state.business_day == "2" for state in relevant_operations):
            market_status = MarketStatus.HALTED
        elif any(
            state.operation_status in _FAULT_STOCK_OPERATIONS
            for state in relevant_operations
        ):
            market_status = MarketStatus.UNKNOWN
        elif relevant_operations and all(
            state.business_day == "1"
            or state.operation_status in _DEFINITELY_CLOSED_STOCK_OPERATIONS
            for state in relevant_operations
        ):
            market_status = MarketStatus.CLOSED
        else:
            # Order-acceptance states (000/100/200/240) do not prove an
            # exchange-open edge. The JPX calendar resolves that separately.
            market_status = MarketStatus.UNKNOWN

        login_permission = (
            next(iter(permissions)) if len(permissions) == 1 else None
        )
        system_codes = {state.system_status for state in systems}
        system_status = (
            next(iter(system_codes)) if len(system_codes) == 1 else None
        )
        operation_codes = {
            state.operation_status for state in relevant_operations
        }
        operation_code = (
            next(iter(operation_codes)) if len(operation_codes) == 1 else None
        )
        system_effective = max(
            (state.effective_time for state in systems), default=None
        )
        operation_effective = max(
            (state.effective_time for state in relevant_operations), default=None
        )
        return EventStatusSnapshot(
            provider_health=health,
            market_status=market_status,
            login_permission_code=login_permission,
            system_status_code=system_status,
            system_effective_time=system_effective,
            operation_code=operation_code,
            operation_effective_time=operation_effective,
            status_date_verified=bool(
                self._provider_calendar_date is not None
                and (systems or relevant_operations)
            ),
            state_conflict=state_conflict,
        )

    def apply(self, fields: Mapping[str, str]) -> EventStatusSnapshot:
        command = fields["p_cmd"]
        self._traffic_observed = True
        if command == "ST":
            self._terminal_status = True
        elif command == "SS":
            key = (fields["p_PV"],)
            candidate = _SystemStatusState(
                self._control_time(fields["p_CT"]),
                fields["p_LK"],
                fields["p_SS"],
            )
            current = self._system_states.get(key)
            if current is None and len(self._system_states) >= _MAX_SYSTEM_STATUS_KEYS:
                self._overflow = True
            elif current is None or candidate.effective_time > current.effective_time:
                self._system_states[key] = candidate
                self._system_conflicts.discard(key)
            elif candidate.effective_time == current.effective_time and (
                candidate.login_permission != current.login_permission
                or candidate.system_status != current.system_status
            ):
                self._system_conflicts.add(key)
        elif command == "US":
            key = (
                fields["p_PV"], fields["p_MC"], fields["p_GSCD"],
                fields["p_SHSB"], fields["p_UC"], fields["p_UU"],
            )
            candidate = _OperationStatusState(
                self._control_time(fields["p_CT"]),
                fields["p_EDK"],
                fields["p_US"],
            )
            current = self._operation_states.get(key)
            if current is None and len(self._operation_states) >= _MAX_OPERATION_STATUS_KEYS:
                self._overflow = True
            elif current is None or candidate.effective_time > current.effective_time:
                self._operation_states[key] = candidate
                self._operation_conflicts.discard(key)
            elif candidate.effective_time == current.effective_time and (
                candidate.business_day != current.business_day
                or candidate.operation_status != current.operation_status
            ):
                self._operation_conflicts.add(key)
        return self.snapshot


@dataclass(frozen=True)
class EventRunSummary:
    connections_started: int
    reconnects: int
    frames_received: int
    observations_ingested: int
    provider_health: ProviderHealth
    market_status: MarketStatus
    stopped: bool
    last_error: ErrorClass


@dataclass(frozen=True)
class EventProgressSnapshot:
    """Secret-free, value-free liveness counters for an active EVENT loop."""

    connections_started: int
    reconnects_scheduled: int
    frames_received: int
    observations_ingested: int
    first_sequence: int | None
    last_sequence: int | None
    first_provider_timestamp: datetime | None
    last_provider_timestamp: datetime | None
    current_connection_first_sequence: int | None
    current_connection_last_sequence: int | None
    current_connection_first_provider_timestamp: datetime | None
    current_connection_last_provider_timestamp: datetime | None
    sequence_advanced: bool
    provider_timestamp_advanced: bool
    last_frame_received_at: datetime | None
    st_frames: int
    kp_frames: int
    fd_frames: int
    ss_frames: int
    us_frames: int
    fd_rows_assembled: int
    unknown_noncritical_fields: int
    subscription_state: str
    last_command: str | None
    last_status_code: str | None
    last_failure_classification: str | None
    last_failure_detail: str | None
    last_failure_stage: str | None
    close_code: int | None
    close_reason_classification: str | None
    timeout_category: str | None
    provider_market_status: str
    provider_operation_code: str | None
    provider_login_permission_code: str | None
    provider_system_status_code: str | None
    provider_status_date_verified: bool
    provider_state_conflict: bool
    normalization_degradations: int
    last_normalization_field: str | None
    last_normalization_reason: str | None
    last_normalization_row: int | None
    last_normalization_symbol: str | None
    # v13.5.39: CONNECT failures while the provider host was unreachable are
    # waited out (bounded) instead of consuming the reconnect budget.
    transport_unreachable_waits: int = 0


def _default_reachability(endpoint: str, timeout_seconds: float = 3.0) -> bool:
    """True when a plain TCP connection to the EVENT host succeeds.

    Only the public hostname and port are used; the credential-equivalent
    virtual path never leaves the session object.  Any failure is
    'unreachable' — this is a transport probe, not a provider request.
    """
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme in {"wss", "https"} else 80)
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


class EventLifecycleProgress:
    """Thread-safe EVENT progression proof without retaining raw frames."""

    def __init__(self) -> None:
        self._connections = 0
        self._reconnects = 0
        self._transport_unreachable = 0
        self._frames = 0
        self._observations = 0
        self._first_sequence: int | None = None
        self._last_sequence: int | None = None
        self._first_provider_timestamp: datetime | None = None
        self._last_provider_timestamp: datetime | None = None
        self._connection_first_sequence: int | None = None
        self._connection_last_sequence: int | None = None
        self._connection_first_provider_timestamp: datetime | None = None
        self._connection_last_provider_timestamp: datetime | None = None
        self._command_counts = {
            command: 0 for command in ("ST", "KP", "FD", "SS", "US")
        }
        self._fd_rows_assembled = 0
        self._unknown_noncritical_fields = 0
        self._subscription_state = "NOT_CONNECTED"
        self._last_frame_received_at: datetime | None = None
        self._last_command: str | None = None
        self._last_status_code: str | None = None
        self._last_failure_classification: str | None = None
        self._last_failure_detail: str | None = None
        self._last_failure_stage: str | None = None
        self._close_code: int | None = None
        self._close_reason_classification: str | None = None
        self._timeout_category: str | None = None
        self._provider_market_status = MarketStatus.UNKNOWN.value
        self._provider_operation_code: str | None = None
        self._provider_login_permission_code: str | None = None
        self._provider_system_status_code: str | None = None
        self._provider_status_date_verified = False
        self._provider_state_conflict = False
        self._normalization_degradations = 0
        self._last_normalization_field: str | None = None
        self._last_normalization_reason: str | None = None
        self._last_normalization_row: int | None = None
        self._last_normalization_symbol: str | None = None
        self._lock = threading.Lock()

    def connection_started(self) -> None:
        with self._lock:
            self._connections += 1
            self._connection_first_sequence = None
            self._connection_last_sequence = None
            self._connection_first_provider_timestamp = None
            self._connection_last_provider_timestamp = None
            # The official contract has no registration ACK. A successful
            # connection means only that the query-carried registration was
            # presented, never that FD is active.
            self._subscription_state = "QUERY_REGISTERED"

    def reconnect_scheduled(self) -> None:
        with self._lock:
            self._reconnects += 1

    def transport_unreachable(self) -> None:
        with self._lock:
            self._transport_unreachable += 1

    def frame_received(
        self, *, sequence: int, provider_timestamp: datetime,
        received_at: datetime, command: str | None = None,
        status_code: str | None = None, fd_rows: int = 0,
        unknown_noncritical_fields: int = 0,
    ) -> None:
        if (
            type(sequence) is not int
            or sequence < 1
            or provider_timestamp.tzinfo is None
            or received_at.tzinfo is None
            or command is not None and command not in {
                "ST", "KP", "FD", "SS", "US",
            }
            or status_code is not None and status_code not in {
                "0", "1", "2", "9", "-1", "-2", "-3", "-12", "-62",
            }
            or status_code is not None and command != "ST"
            or type(fd_rows) is not int
            or fd_rows < 0
            or type(unknown_noncritical_fields) is not int
            or unknown_noncritical_fields < 0
            or command != "FD" and fd_rows != 0
        ):
            raise TachibanaError(ErrorClass.CLOCK_SKEW)
        provider = provider_timestamp.astimezone(timezone.utc)
        received = received_at.astimezone(timezone.utc)
        with self._lock:
            self._frames += 1
            if self._first_sequence is None:
                self._first_sequence = sequence
                self._first_provider_timestamp = provider
            self._last_sequence = sequence
            self._last_provider_timestamp = provider
            if self._connection_first_sequence is None:
                self._connection_first_sequence = sequence
                self._connection_first_provider_timestamp = provider
            self._connection_last_sequence = sequence
            self._connection_last_provider_timestamp = provider
            self._last_frame_received_at = received
            if command is not None:
                self._last_command = command
                self._command_counts[command] += 1
                if command == "FD":
                    self._subscription_state = "FD_ACTIVE"
                elif self._subscription_state != "FD_ACTIVE":
                    self._subscription_state = "CONTROL_ACTIVE"
            self._fd_rows_assembled += fd_rows
            self._unknown_noncritical_fields += unknown_noncritical_fields
            if status_code is not None:
                self._last_status_code = status_code

    def failure_observed(
        self, *, classification: ErrorClass, detail: str, stage: str,
        close_code: int | None = None,
        close_reason_classification: str | None = None,
        timeout_category: str | None = None,
    ) -> None:
        if (
            not isinstance(classification, ErrorClass)
            or not isinstance(detail, str)
            or re.fullmatch(r"[A-Z0-9_]{1,96}", detail) is None
            or re.fullmatch(r"[A-Z0-9_]{1,32}", stage) is None
            or (
                close_code is not None
                and (
                    type(close_code) is not int
                    or not 1000 <= close_code <= 4999
                )
            )
            or close_reason_classification
            not in {None, "EMPTY", "PRESENT_REDACTED"}
            or timeout_category not in {None, "CONNECT", "IDLE"}
        ):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        with self._lock:
            self._last_failure_classification = classification.value
            self._last_failure_detail = detail
            self._last_failure_stage = stage
            self._close_code = close_code
            self._close_reason_classification = close_reason_classification
            self._timeout_category = timeout_category

    def observations_ingested(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        with self._lock:
            self._observations += count

    def provider_state_observed(self, status: EventStatusSnapshot) -> None:
        if (
            not isinstance(status, EventStatusSnapshot)
            or status.operation_code is not None
            and re.fullmatch(r"[0-9]{3}", status.operation_code) is None
            or status.login_permission_code not in {None, "0", "1", "2", "9"}
            or status.system_status_code not in {None, "0", "1"}
        ):
            raise TachibanaError(ErrorClass.PROVIDER)
        with self._lock:
            self._provider_market_status = status.market_status.value
            self._provider_login_permission_code = status.login_permission_code
            self._provider_system_status_code = status.system_status_code
            self._provider_status_date_verified = status.status_date_verified
            self._provider_state_conflict = status.state_conflict
            # Keep only a uniquely reconciled current official code. A mixed
            # per-key state clears this field rather than preserving the last
            # arrival as false global authority.
            self._provider_operation_code = status.operation_code

    def normalization_degraded(
        self, *, row_number: int, symbol: str, issue: NormalizationIssue,
    ) -> None:
        if (
            type(row_number) is not int
            or not 1 <= row_number <= 120
            or re.fullmatch(r"[0-9ACDFGHJKLMNPRSTUWXY]{4}", symbol) is None
            or not any(character.isdigit() for character in symbol)
            or not isinstance(issue, NormalizationIssue)
        ):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        with self._lock:
            self._normalization_degradations += 1
            self._last_normalization_field = issue.field
            self._last_normalization_reason = issue.reason
            self._last_normalization_row = row_number
            self._last_normalization_symbol = symbol

    def snapshot(self) -> EventProgressSnapshot:
        with self._lock:
            return EventProgressSnapshot(
                connections_started=self._connections,
                reconnects_scheduled=self._reconnects,
                transport_unreachable_waits=self._transport_unreachable,
                frames_received=self._frames,
                observations_ingested=self._observations,
                first_sequence=self._first_sequence,
                last_sequence=self._last_sequence,
                first_provider_timestamp=self._first_provider_timestamp,
                last_provider_timestamp=self._last_provider_timestamp,
                current_connection_first_sequence=(
                    self._connection_first_sequence
                ),
                current_connection_last_sequence=(
                    self._connection_last_sequence
                ),
                current_connection_first_provider_timestamp=(
                    self._connection_first_provider_timestamp
                ),
                current_connection_last_provider_timestamp=(
                    self._connection_last_provider_timestamp
                ),
                sequence_advanced=bool(
                    self._connection_first_sequence is not None
                    and self._connection_last_sequence is not None
                    and self._connection_last_sequence
                    > self._connection_first_sequence
                ),
                provider_timestamp_advanced=bool(
                    self._connection_first_provider_timestamp is not None
                    and self._connection_last_provider_timestamp is not None
                    and self._connection_last_provider_timestamp
                    > self._connection_first_provider_timestamp
                ),
                last_frame_received_at=self._last_frame_received_at,
                st_frames=self._command_counts["ST"],
                kp_frames=self._command_counts["KP"],
                fd_frames=self._command_counts["FD"],
                ss_frames=self._command_counts["SS"],
                us_frames=self._command_counts["US"],
                fd_rows_assembled=self._fd_rows_assembled,
                unknown_noncritical_fields=self._unknown_noncritical_fields,
                subscription_state=self._subscription_state,
                last_command=self._last_command,
                last_status_code=self._last_status_code,
                last_failure_classification=self._last_failure_classification,
                last_failure_detail=self._last_failure_detail,
                last_failure_stage=self._last_failure_stage,
                close_code=self._close_code,
                close_reason_classification=self._close_reason_classification,
                timeout_category=self._timeout_category,
                provider_market_status=self._provider_market_status,
                provider_operation_code=self._provider_operation_code,
                provider_login_permission_code=(
                    self._provider_login_permission_code
                ),
                provider_system_status_code=self._provider_system_status_code,
                provider_status_date_verified=(
                    self._provider_status_date_verified
                ),
                provider_state_conflict=self._provider_state_conflict,
                normalization_degradations=self._normalization_degradations,
                last_normalization_field=self._last_normalization_field,
                last_normalization_reason=self._last_normalization_reason,
                last_normalization_row=self._last_normalization_row,
                last_normalization_symbol=self._last_normalization_symbol,
            )


class TachibanaEventLifecycle:
    """One synchronous, stop-aware EVENT receive loop with bounded recovery."""

    def __init__(
        self,
        session: TachibanaSession,
        subscription: EventSubscription,
        sensor: TransientLiveSensor,
        *,
        policy: EventConnectionPolicy | None = None,
        connector: EventConnector | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
        waiter: Callable[[threading.Event, float], bool] | None = None,
        session_truth_resolver: Callable[..., SessionTruth] | None = None,
        provider_calendar_date: date | None = None,
        progress: EventLifecycleProgress | None = None,
        reachability_probe: Callable[[str], bool] | None = None,
    ) -> None:
        if (
            not isinstance(session, TachibanaSession)
            or not isinstance(subscription, EventSubscription)
            or not isinstance(sensor, TransientLiveSensor)
            or sensor.bounds.max_symbols < len(subscription.symbols)
            or provider_calendar_date is not None
            and not isinstance(provider_calendar_date, date)
        ):
            raise ValueError("invalid_event_lifecycle")
        self._session = session
        self._subscription = subscription
        self._sensor = sensor
        self._policy = policy or EventConnectionPolicy.from_config(session.config)
        self._connector = connector or WebSocketEventConnector(monotonic=monotonic)
        self._clock = clock
        self._random_value = random_value
        self._waiter = waiter or (lambda stop, seconds: stop.wait(seconds))
        self._session_truth_resolver = session_truth_resolver
        self._provider_calendar_date = provider_calendar_date
        self._symbol_to_row = {
            symbol: row for row, symbol in subscription.row_to_symbol.items()
        }
        self._progress = progress or EventLifecycleProgress()
        self._reachability = reachability_probe or _default_reachability
        self._budget = EventReconnectBudget(
            self._policy.maximum_reconnects_per_day, clock=clock
        )
        self._run_lock = _PROCESS_EVENT_LOCK

    def _diagnostics(
        self,
        *,
        connected: bool | None = None,
        health: ProviderHealth | None = None,
        error: ErrorClass | None = None,
        success_at: datetime | None = None,
    ) -> None:
        with self._session._lock:
            diagnostics: Diagnostics = self._session.diagnostics
            if connected is not None:
                diagnostics.websocket_connected = connected
            if health is not None:
                diagnostics.health = health
            if error is not None:
                diagnostics.last_error_class = error
            if success_at is not None:
                diagnostics.last_success_at = success_at

    @staticmethod
    def _classification(error: Exception) -> ErrorClass:
        if isinstance(error, TachibanaError):
            return error.classification
        if (
            isinstance(error, ValueError)
            and str(error) in {
                "event_connection_sequence_gap",
                "event_number_not_ascending",
            }
        ):
            return ErrorClass.SEQUENCE_DESYNC
        if isinstance(error, ValueError):
            return ErrorClass.PROVIDER
        return ErrorClass.NETWORK

    @staticmethod
    def _safe_failure_detail(error: Exception) -> str:
        if isinstance(error, TachibanaError):
            return error.classification.value
        if isinstance(error, ValueError):
            detail = str(error)
            if re.fullmatch(r"event_[a-z0-9_]{1,89}", detail):
                return detail.upper()
        return "UNCLASSIFIED_EVENT_FAILURE"

    def _backoff(self, reconnect_number: int) -> float:
        try:
            sample = float(self._random_value())
        except (TypeError, ValueError):
            raise TachibanaError(ErrorClass.CONFIGURATION) from None
        if not 0.0 <= sample <= 1.0:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        base = min(
            self._policy.reconnect_maximum_seconds,
            self._policy.reconnect_initial_seconds
            * (2 ** min(reconnect_number - 1, 10)),
        )
        return min(
            self._policy.reconnect_maximum_seconds,
            base * (1.0 + self._policy.reconnect_jitter_fraction * sample),
        )

    def run(self, stop_event: threading.Event) -> EventRunSummary:
        if not isinstance(stop_event, threading.Event):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        if (
            not self._session.config.enabled
            or not self._session.config.websocket_enabled
            or not self._policy.enabled
        ):
            self._diagnostics(connected=False, error=ErrorClass.DISABLED)
            raise TachibanaError(ErrorClass.DISABLED)
        if not self._run_lock.acquire(blocking=False):
            raise TachibanaError(ErrorClass.CONFIGURATION)

        connections = 0
        reconnects = 0
        frames = 0
        observations = 0
        outage_waited = 0.0
        last_error = ErrorClass.NONE
        status = EventStatusSnapshot(
            ProviderHealth.UNAVAILABLE, MarketStatus.UNKNOWN
        )
        try:
            while not stop_event.is_set():
                assembler = EventSnapshotAssembler(
                    row_to_symbol=self._subscription.row_to_symbol,
                    max_symbols=self._subscription.max_symbols,
                )
                tracker = EventStatusTracker(
                    provider_calendar_date=self._provider_calendar_date
                )
                stream: Iterable[str | bytes] | None = None
                failure: Exception | None = None
                failure_stage = "CONNECT"
                endpoint = ""
                try:
                    endpoint = self._session._market_data_endpoint("event_websocket")
                    stream = self._connector.receive(
                        endpoint,
                        self._subscription,
                        connect_timeout_seconds=self._policy.connect_timeout_seconds,
                        idle_timeout_seconds=self._policy.idle_timeout_seconds,
                        maximum_frame_bytes=self._policy.maximum_frame_bytes,
                        stop_event=stop_event,
                    )
                    connections += 1
                    self._progress.connection_started()
                    self._diagnostics(connected=True)
                    failure_stage = "RECEIVE"
                    for raw_frame in stream:
                        if stop_event.is_set():
                            break
                        failure_stage = "PARSE"
                        fields = parse_event_frame(raw_frame)
                        failure_stage = "ASSEMBLE"
                        rows = assembler.apply(fields)
                        failure_stage = "STATUS"
                        status = tracker.apply(fields)
                        self._progress.provider_state_observed(status)
                        frames += 1
                        last_error = ErrorClass.NONE
                        failure_stage = "CLOCK"
                        received_at = self._clock()
                        if received_at.tzinfo is None:
                            raise TachibanaError(ErrorClass.CLOCK_SKEW)
                        received_at = received_at.astimezone(timezone.utc)
                        provider_time = parse_provider_datetime(fields["p_date"])
                        if provider_time is None:
                            raise TachibanaError(ErrorClass.CLOCK_SKEW)
                        self._progress.frame_received(
                            sequence=int(fields["p_no"]),
                            provider_timestamp=provider_time,
                            received_at=received_at,
                            command=fields["p_cmd"],
                            status_code=(
                                fields["p_errno"]
                                if fields["p_cmd"] == "ST"
                                else None
                            ),
                            fd_rows=len(rows),
                            unknown_noncritical_fields=(
                                event_unknown_noncritical_field_count(fields)
                            ),
                        )
                        self._diagnostics(
                            connected=True,
                            health=status.provider_health,
                            error=ErrorClass.NONE,
                            success_at=received_at,
                        )
                        if fields["p_cmd"] == "ST":
                            failure_stage = "STATUS"
                            raise TachibanaError(
                                _ST_ERROR_CLASSES[fields["p_errno"]]
                            )
                        frame_time = datetime.strptime(
                            fields["p_date"], "%Y.%m.%d-%H:%M:%S.%f"
                        ).replace(tzinfo=TOKYO)
                        market_date = frame_time.date()
                        market_status = status.market_status
                        market_date_verified = False
                        if self._session_truth_resolver is not None:
                            failure_stage = "SESSION_TRUTH"
                            session_truth = self._session_truth_resolver(
                                now=received_at,
                                provider_time=provider_time,
                                provider_calendar_date=(
                                    self._provider_calendar_date
                                ),
                                provider_health=status.provider_health,
                                provider_market_status=status.market_status,
                                control_state_confident=(
                                    not status.state_conflict
                                ),
                            )
                            market_date = session_truth.market_date
                            market_status = session_truth.market_status
                            # A same-day EVENT frame proves the frame date, not
                            # the date of tDPP.  Before an execution phase,
                            # tDPP may legitimately describe the prior close.
                            market_date_verified = bool(
                                session_truth.market_date_verified
                                and session_truth.phase in {
                                    JapanCashPhase.OPEN,
                                    JapanCashPhase.AFTERNOON_OPEN,
                                }
                            )
                        for row in rows:
                            failure_stage = "NORMALIZE"
                            observation = normalize_market_price(
                                row,
                                received_at=received_at,
                                market_date=market_date,
                                market_status=market_status,
                                market_date_verified=market_date_verified,
                                market_data_timestamp=provider_time,
                                market_data_date_verified=bool(
                                    self._session_truth_resolver is not None
                                    and session_truth.provider_calendar_current
                                    and session_truth.event_packet_current
                                ),
                                degrade_noncritical=True,
                                fresh_for_seconds=self._session.config.fresh_for_seconds,
                                endpoint_category="EVENT",
                            )
                            for issue in observation.normalization_issues:
                                self._progress.normalization_degraded(
                                    row_number=self._symbol_to_row[
                                        observation.symbol
                                    ],
                                    symbol=observation.symbol,
                                    issue=issue,
                                )
                            failure_stage = "INGEST"
                            self._sensor.ingest(observation)
                            observations += 1
                        self._progress.observations_ingested(len(rows))
                        failure_stage = "RECEIVE"
                    if stop_event.is_set():
                        break
                    failure_stage = "STREAM_END"
                    failure = TachibanaError(ErrorClass.NETWORK)
                except (TachibanaError, ValueError) as error:
                    failure = error
                except Exception:
                    failure = TachibanaError(ErrorClass.NETWORK)
                finally:
                    if stream is not None:
                        close = getattr(stream, "close", None)
                        if callable(close):
                            try:
                                close()
                            except Exception:
                                pass
                    assembler.clear()
                    self._diagnostics(connected=False)

                if stop_event.is_set():
                    break
                if failure is None:
                    failure = TachibanaError(ErrorClass.NETWORK)
                last_error = self._classification(failure)
                self._progress.failure_observed(
                    classification=last_error,
                    detail=self._safe_failure_detail(failure),
                    stage=failure_stage,
                    close_code=getattr(failure, "close_code", None),
                    close_reason_classification=getattr(
                        failure, "close_reason_classification", None
                    ),
                    timeout_category=getattr(failure, "timeout_category", None),
                )
                self._diagnostics(error=last_error)
                if last_error in {
                    ErrorClass.DISABLED,
                    ErrorClass.CONFIGURATION,
                    ErrorClass.SESSION_EXPIRED,
                    ErrorClass.MAINTENANCE,
                    ErrorClass.OUTSIDE_HOURS,
                    ErrorClass.CLOCK_SKEW,
                }:
                    if last_error == ErrorClass.SESSION_EXPIRED:
                        self._session.expire()
                    raise TachibanaError(last_error)
                # v13.5.39 official-contract recovery order:
                #   1. a CONNECT failure while the provider host is unreachable
                #      is a network outage — wait it out (bounded), never
                #      spending the reconnect budget nor re-authenticating;
                #   2. after an established connection closes, wait for the
                #      provider's disconnect processing (drain) before the
                #      SAME-SESSION reconnect (virtual URLs stay valid);
                #   3. only then consume one reconnect and back off 5 s→60 s.
                if failure_stage == "CONNECT" and last_error == ErrorClass.NETWORK \
                        and endpoint and not self._reachability(endpoint):
                    outage_waited += self._policy.outage_backoff_seconds
                    if outage_waited > self._policy.outage_budget_seconds:
                        last_error = ErrorClass.EVENT_RECONNECT_EXHAUSTED
                        self._diagnostics(error=last_error)
                        raise TachibanaError(last_error)
                    self._progress.transport_unreachable()
                    if self._waiter(stop_event, self._policy.outage_backoff_seconds):
                        break
                    continue
                if failure_stage != "CONNECT" and self._policy.drain_wait_seconds > 0:
                    if self._waiter(stop_event, self._policy.drain_wait_seconds):
                        break
                if not self._budget.consume():
                    last_error = ErrorClass.EVENT_RECONNECT_EXHAUSTED
                    self._diagnostics(error=last_error)
                    raise TachibanaError(last_error)
                reconnects += 1
                self._progress.reconnect_scheduled()
                if self._waiter(stop_event, self._backoff(reconnects)):
                    break
            return EventRunSummary(
                connections_started=connections,
                reconnects=reconnects,
                frames_received=frames,
                observations_ingested=observations,
                provider_health=status.provider_health,
                market_status=status.market_status,
                stopped=stop_event.is_set(),
                last_error=last_error,
            )
        finally:
            self._diagnostics(connected=False)
            self._run_lock.release()


__all__ = [
    "EventRunSummary",
    "EventLifecycleProgress",
    "EventProgressSnapshot",
    "EventTransportError",
    "EventStatusSnapshot",
    "EventStatusTracker",
    "TachibanaEventLifecycle",
    "WebSocketEventConnector",
]
