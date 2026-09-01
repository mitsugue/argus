"""Receive-only Tachibana EVENT WebSocket transport and bounded lifecycle.

The official WebSocket is a delivery-only RFC 6455 text stream.  This module
doesn't expose a send method, doesn't log credential-equivalent virtual URLs,
and remains unreachable unless both the provider and WebSocket feature flags
are explicitly enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import random
import re
import threading
import time
from typing import Callable, Iterable, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .models import (
    Diagnostics,
    ErrorClass,
    MarketStatus,
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
_MAX_CASH_EQUITY_OPERATION_KEYS = 16
# The provider allows only one EVENT connection per customer.  ARGUS has no
# safe, non-secret customer identifier to key by, so enforce the conservative
# process-wide singleton rather than risk two sessions evicting each other.
_PROCESS_EVENT_LOCK = threading.Lock()


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
    except Exception:
        raise TachibanaError(ErrorClass.NETWORK) from None


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
        except Exception:
            raise TachibanaError(ErrorClass.NETWORK) from None

        def _messages() -> Iterable[str]:
            last_message_at = self._monotonic()
            try:
                while not stop_event.is_set():
                    remaining = (
                        float(idle_timeout_seconds)
                        - (self._monotonic() - last_message_at)
                    )
                    if remaining <= 0:
                        raise TachibanaError(ErrorClass.EVENT_IDLE_TIMEOUT)
                    try:
                        message = connection.recv(timeout=min(1.0, remaining))
                    except TimeoutError:
                        if self._monotonic() - last_message_at >= idle_timeout_seconds:
                            raise TachibanaError(ErrorClass.EVENT_IDLE_TIMEOUT) from None
                        continue
                    except TachibanaError:
                        raise
                    except Exception:
                        raise TachibanaError(ErrorClass.NETWORK) from None
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


class EventStatusTracker:
    """Reconstruct current SS/US state conservatively from replayed records."""

    def __init__(self) -> None:
        self._provider_health = ProviderHealth.UNAVAILABLE
        self._market_status = MarketStatus.UNKNOWN
        self._explicit_system_status = False
        self._last_system_update = ""
        self._operation_updates: dict[tuple[str, str, str, str, str], str] = {}

    @property
    def snapshot(self) -> EventStatusSnapshot:
        return EventStatusSnapshot(self._provider_health, self._market_status)

    def apply(self, fields: Mapping[str, str]) -> EventStatusSnapshot:
        command = fields["p_cmd"]
        if command == "ST":
            self._provider_health = ProviderHealth.UNAVAILABLE
            self._market_status = MarketStatus.UNKNOWN
        elif command in {"KP", "FD"}:
            # Valid traffic proves transport liveness, but cannot override an
            # explicit SS state and never proves that the exchange is open.
            if not self._explicit_system_status:
                self._provider_health = ProviderHealth.AVAILABLE
        elif command == "SS":
            update = fields["p_CT"]
            if update >= self._last_system_update:
                self._last_system_update = update
                self._explicit_system_status = True
                if fields["p_LK"] == "0":
                    self._provider_health = ProviderHealth.MAINTENANCE
                elif fields["p_LK"] == "1" and fields["p_SS"] == "0":
                    self._provider_health = ProviderHealth.AVAILABLE
                else:
                    self._provider_health = ProviderHealth.UNAVAILABLE
                if self._provider_health != ProviderHealth.AVAILABLE:
                    self._market_status = MarketStatus.UNKNOWN
        elif command == "US":
            if not self._explicit_system_status:
                self._provider_health = ProviderHealth.AVAILABLE
            if not (
                fields["p_UC"] == "01"
                and fields["p_UU"] == "0101"
                and fields["p_MC"] in {"00", "01"}
            ):
                # Other operation categories are not evidence for the cash-
                # equity market state and must not grow retained state.
                return self.snapshot
            key = (
                fields["p_UC"], fields["p_UU"], fields["p_MC"],
                fields["p_GSCD"], fields["p_SHSB"],
            )
            if (
                key not in self._operation_updates
                and len(self._operation_updates) >= _MAX_CASH_EQUITY_OPERATION_KEYS
            ):
                # Fail closed instead of evicting chronology and later
                # accepting an old replay for an evicted status key.
                self._market_status = MarketStatus.UNKNOWN
                if self._provider_health == ProviderHealth.AVAILABLE:
                    self._provider_health = ProviderHealth.DEGRADED
                return self.snapshot
            update = fields["p_CT"]
            if update >= self._operation_updates.get(key, ""):
                self._operation_updates[key] = update
                if fields["p_EDK"] == "1":
                    self._market_status = MarketStatus.CLOSED
                elif fields["p_EDK"] == "2":
                    self._market_status = MarketStatus.HALTED
                elif fields["p_US"] in _FAULT_STOCK_OPERATIONS:
                    self._market_status = MarketStatus.UNKNOWN
                    if self._provider_health == ProviderHealth.AVAILABLE:
                        self._provider_health = ProviderHealth.DEGRADED
                elif fields["p_US"] in _DEFINITELY_CLOSED_STOCK_OPERATIONS:
                    self._market_status = MarketStatus.CLOSED
                else:
                    # 000/100/200/240 are order/operations phases.  The
                    # official contract doesn't define a market-open edge.
                    self._market_status = MarketStatus.UNKNOWN
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
    frames_received: int
    observations_ingested: int
    first_sequence: int | None
    last_sequence: int | None
    first_provider_timestamp: datetime | None
    last_provider_timestamp: datetime | None
    last_frame_received_at: datetime | None
    provider_market_status: str
    provider_operation_code: str | None


class EventLifecycleProgress:
    """Thread-safe EVENT progression proof without retaining raw frames."""

    def __init__(self) -> None:
        self._connections = 0
        self._frames = 0
        self._observations = 0
        self._first_sequence: int | None = None
        self._last_sequence: int | None = None
        self._first_provider_timestamp: datetime | None = None
        self._last_provider_timestamp: datetime | None = None
        self._last_frame_received_at: datetime | None = None
        self._provider_market_status = MarketStatus.UNKNOWN.value
        self._provider_operation_code: str | None = None
        self._lock = threading.Lock()

    def connection_started(self) -> None:
        with self._lock:
            self._connections += 1

    def frame_received(
        self, *, sequence: int, provider_timestamp: datetime,
        received_at: datetime,
    ) -> None:
        if (
            type(sequence) is not int
            or sequence < 1
            or provider_timestamp.tzinfo is None
            or received_at.tzinfo is None
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
            self._last_frame_received_at = received

    def observations_ingested(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        with self._lock:
            self._observations += count

    def provider_state_observed(
        self, *, market_status: MarketStatus, operation_code: str | None,
    ) -> None:
        if (
            not isinstance(market_status, MarketStatus)
            or operation_code is not None
            and re.fullmatch(r"[0-9]{3}", operation_code) is None
        ):
            raise TachibanaError(ErrorClass.PROVIDER)
        with self._lock:
            self._provider_market_status = market_status.value
            if operation_code is not None:
                # Keep the official code verbatim.  Do not invent a stronger
                # trading semantic than the provider contract supplies.
                self._provider_operation_code = operation_code

    def snapshot(self) -> EventProgressSnapshot:
        with self._lock:
            return EventProgressSnapshot(
                connections_started=self._connections,
                frames_received=self._frames,
                observations_ingested=self._observations,
                first_sequence=self._first_sequence,
                last_sequence=self._last_sequence,
                first_provider_timestamp=self._first_provider_timestamp,
                last_provider_timestamp=self._last_provider_timestamp,
                last_frame_received_at=self._last_frame_received_at,
                provider_market_status=self._provider_market_status,
                provider_operation_code=self._provider_operation_code,
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
        progress: EventLifecycleProgress | None = None,
    ) -> None:
        if (
            not isinstance(session, TachibanaSession)
            or not isinstance(subscription, EventSubscription)
            or not isinstance(sensor, TransientLiveSensor)
            or sensor.bounds.max_symbols < len(subscription.symbols)
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
        self._progress = progress or EventLifecycleProgress()
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
                tracker = EventStatusTracker()
                stream: Iterable[str | bytes] | None = None
                failure: Exception | None = None
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
                    for raw_frame in stream:
                        if stop_event.is_set():
                            break
                        fields = parse_event_frame(raw_frame)
                        rows = assembler.apply(fields)
                        status = tracker.apply(fields)
                        self._progress.provider_state_observed(
                            market_status=status.market_status,
                            operation_code=(
                                fields["p_US"]
                                if fields["p_cmd"] == "US"
                                else None
                            ),
                        )
                        frames += 1
                        last_error = ErrorClass.NONE
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
                        )
                        self._diagnostics(
                            connected=True,
                            health=status.provider_health,
                            error=ErrorClass.NONE,
                            success_at=received_at,
                        )
                        if fields["p_cmd"] == "ST":
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
                            session_truth = self._session_truth_resolver(
                                now=received_at,
                                provider_time=provider_time,
                                provider_health=status.provider_health,
                                provider_market_status=status.market_status,
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
                            observation = normalize_market_price(
                                row,
                                received_at=received_at,
                                market_date=market_date,
                                market_status=market_status,
                                market_date_verified=market_date_verified,
                                fresh_for_seconds=self._session.config.fresh_for_seconds,
                                endpoint_category="EVENT",
                            )
                            self._sensor.ingest(observation)
                            observations += 1
                        self._progress.observations_ingested(len(rows))
                    if stop_event.is_set():
                        break
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
                if not self._budget.consume():
                    last_error = ErrorClass.EVENT_RECONNECT_EXHAUSTED
                    self._diagnostics(error=last_error)
                    raise TachibanaError(last_error)
                reconnects += 1
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
    "EventStatusSnapshot",
    "EventStatusTracker",
    "TachibanaEventLifecycle",
    "WebSocketEventConnector",
]
