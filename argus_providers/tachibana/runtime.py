"""Single-process, non-authoritative Tachibana live-sensor runtime.

The runtime owns one provider session, one EVENT connection, and only bounded
in-memory observations.  Its public snapshots contain liveness counters and
classifications, never market values, virtual URLs, or raw provider frames.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import threading
import time
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

import requests

from .client import ProviderReadDiagnostic, TachibanaReadOnlyClient
from .config import TachibanaConfig
from .cross_validation import DEFAULT_TOLERANCES, MismatchClass, compare_shadow
from .event_stream import (
    EventLifecycleProgress,
    EventProgressSnapshot,
    TachibanaEventLifecycle,
)
from .models import (
    ErrorClass,
    Freshness,
    MarketStatus,
    ProviderHealth,
    TachibanaError,
    TachibanaObservation,
)
from .normalization import normalize_market_price
from .sensor import EventSubscription, TransientLiveSensor
from .session import TachibanaSession
from .session_truth import (
    JapanCashPhase,
    SessionTruth,
    parse_provider_datetime,
    resolve_jp_cash_session,
)


DEFAULT_SYMBOLS = ("8058", "9984", "5803")
REFERENCE_ENDPOINT = (
    "https://argus-backend-3j2m.onrender.com/api/argus/japan-watchlist"
)
PRICE_COLUMNS = (
    "pDPP", "tDPP:T", "pPRP", "pDOP", "tDOP:T", "pDHP", "tDHP:T",
    "pDLP", "tDLP:T", "pDV", "pDJ", "pVWAP", "pQAP", "pQAS",
    "pQBP", "pQBS", "pAAV", "pABV", "pAV", "pBV", "pQOV", "pQUV",
    *(f"pGAP{level}" for level in range(1, 11)),
    *(f"pGAV{level}" for level in range(1, 11)),
    *(f"pGBP{level}" for level in range(1, 11)),
    *(f"pGBV{level}" for level in range(1, 11)),
)
_REFERENCE_FIELD_NAMES = {
    "current_price": ("price", "currentPrice", "current_price", "close"),
    "previous_close": ("previousClose", "previous_close", "prevClose"),
    "open": ("open",),
    "high": ("high",),
    "low": ("low",),
    "volume": ("volume",),
    "best_ask": ("bestAsk", "best_ask", "ask"),
    "best_bid": ("bestBid", "best_bid", "bid"),
}
_EXECUTION_CROSS_FIELDS = frozenset({
    "current_price", "previous_close", "open", "high", "low", "volume",
})
_BOARD_CROSS_FIELDS = frozenset({"best_ask", "best_bid"})
_CHANGE_FIELDS = (
    "current_price", "best_ask", "best_bid", "volume",
    "best_ask_volume", "best_bid_volume",
)
_BOOK_CHANGE_FIELDS = (
    "best_ask", "best_bid", "market_ask_volume", "market_bid_volume",
    "best_ask_volume", "best_bid_volume", "sell_over", "buy_under",
)
_EXECUTION_CHANGE_FIELDS = (
    "current_price", "volume", "turnover", "vwap",
    "open", "high", "low",
)
_TOKYO = ZoneInfo("Asia/Tokyo")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _parse_iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_live_flags(config: TachibanaConfig) -> None:
    if (
        not config.enabled
        or not config.shadow_only
        or config.authoritative
        or not config.websocket_enabled
        or not 1 <= config.max_symbols <= 3
    ):
        raise TachibanaError(ErrorClass.CONFIGURATION)


def validate_symbols(symbols: tuple[str, ...], maximum: int = 3) -> tuple[str, ...]:
    if not isinstance(symbols, tuple) or not 1 <= len(symbols) <= maximum:
        raise TachibanaError(ErrorClass.CONFIGURATION)
    try:
        EventSubscription(symbols, max_symbols=maximum)
    except ValueError:
        raise TachibanaError(ErrorClass.CONFIGURATION) from None
    return symbols


@dataclass(frozen=True)
class CrossValidationResult:
    classification: str
    trusted_symbol_count: int
    compared_symbol_count: int
    comparable_field_count: int
    mismatch_counts: Mapping[str, int]
    scope: str = "EXECUTION"

    @property
    def acceptable(self) -> bool:
        return self.classification in {
            "ACCEPTABLE", "ACCEPTABLE_WITH_DELAY_DIFFERENCES",
        }


def _reference_fields(row: Mapping[str, object]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for normalized, candidates in _REFERENCE_FIELD_NAMES.items():
        result[normalized] = next((
            parsed for key in candidates
            if (parsed := _finite_number(row.get(key))) is not None
        ), None)
    return result


def cross_validate_current(
    observations: Mapping[str, TachibanaObservation],
    *,
    now: datetime | None = None,
    fetch: Callable[..., object] = requests.get,
    scope: str = "EXECUTION",
    session_phase: JapanCashPhase | None = None,
) -> CrossValidationResult:
    """Compare only independently current, explicitly live ARGUS rows."""
    if scope not in {"EXECUTION", "BOARD"}:
        raise ValueError("invalid_cross_validation_scope")
    eligible_phases = (
        {JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN}
        if scope == "EXECUTION" else {
            JapanCashPhase.PREOPEN,
            JapanCashPhase.OPEN,
            JapanCashPhase.AFTERNOON_PREOPEN,
            JapanCashPhase.AFTERNOON_OPEN,
        }
    )
    if session_phase not in eligible_phases:
        return CrossValidationResult(
            "SESSION_NOT_ELIGIBLE", 0, 0, 0, {}, scope,
        )
    current = (now or _utcnow()).astimezone(timezone.utc)
    try:
        response = fetch(
            REFERENCE_ENDPOINT,
            params={"symbols": ",".join(sorted(observations))},
            timeout=8,
        )
        if getattr(response, "ok", False) is not True:
            raise ValueError
        payload = response.json()
    except Exception:
        return CrossValidationResult(
            "REFERENCE_UNAVAILABLE", 0, 0, 0, {}, scope,
        )
    if not isinstance(payload, Mapping) or payload.get("status") != "live":
        return CrossValidationResult(
            "REFERENCE_NOT_CURRENT", 0, 0, 0, {}, scope,
        )
    raw_rows = payload.get("stocks")
    if not isinstance(raw_rows, list):
        return CrossValidationResult(
            "REFERENCE_INVALID", 0, 0, 0, {}, scope,
        )
    trusted: dict[str, tuple[Mapping[str, object], datetime]] = {}
    for candidate in raw_rows:
        if not isinstance(candidate, Mapping):
            continue
        symbol = candidate.get("symbol")
        source = _parse_iso_timestamp(
            candidate.get("sourceTimestamp") or candidate.get("exchangeTs")
        )
        if (
            symbol not in observations
            or candidate.get("status") != "live"
            or candidate.get("realtimeEvidence") is not True
            or source is None
            or not timedelta(0) <= current - source <= timedelta(minutes=20)
        ):
            continue
        trusted[str(symbol)] = (candidate, source)
    mismatches: dict[str, int] = {}
    delay_differences_bounded = True
    compared_symbols = 0
    comparable_fields = 0
    for symbol, observation in observations.items():
        if (
            observation.freshness != Freshness.FRESH
            or not observation.market_data_date_verified
            or scope == "EXECUTION"
            and (
                observation.market_status != MarketStatus.OPEN
                or observation.source_timestamp is None
            )
        ):
            continue
        trusted_item = trusted.get(symbol)
        if trusted_item is None:
            continue
        row, timestamp = trusted_item
        all_fields = _reference_fields(row)
        selected = (
            _EXECUTION_CROSS_FIELDS
            if scope == "EXECUTION" else _BOARD_CROSS_FIELDS
        )
        fields = {
            key: value for key, value in all_fields.items() if key in selected
        }
        if (
            scope == "EXECUTION" and fields.get("current_price") is None
            or scope == "BOARD"
            and not any(fields.get(key) is not None for key in _BOARD_CROSS_FIELDS)
        ):
            continue
        compared_symbols += 1
        comparable_fields += sum(value is not None for value in fields.values())
        for mismatch in compare_shadow(
            observation, fields, trusted_timestamp=timestamp,
            tolerances={
                key: DEFAULT_TOLERANCES[key] for key in selected
            },
            session_aligned=True,
            market_data_timing=scope == "BOARD",
        ):
            key = mismatch.classification.value
            mismatches[key] = mismatches.get(key, 0) + 1
            if mismatch.classification == MismatchClass.DELAY_DIFFERENCE:
                relative_limit = 0.05 if mismatch.field == "volume" else 0.005
                if (
                    mismatch.relative_difference is None
                    or mismatch.relative_difference > relative_limit
                ):
                    delay_differences_bounded = False
    required_symbols = max(1, (len(observations) * 2 + 2) // 3)
    if compared_symbols < required_symbols:
        classification = "INSUFFICIENT_CURRENT_COVERAGE"
    elif not mismatches:
        classification = "ACCEPTABLE"
    elif (
        delay_differences_bounded
        and set(mismatches) <= {MismatchClass.DELAY_DIFFERENCE.value}
    ):
        classification = "ACCEPTABLE_WITH_DELAY_DIFFERENCES"
    else:
        classification = "MISMATCH"
    return CrossValidationResult(
        classification=classification,
        trusted_symbol_count=len(trusted),
        compared_symbol_count=compared_symbols,
        comparable_field_count=comparable_fields,
        mismatch_counts=dict(sorted(mismatches.items())),
        scope=scope,
    )


@dataclass(frozen=True)
class LiveAcceptanceSnapshot:
    classification: str
    authenticated: bool
    price_current_count: int
    board_current_count: int
    execution_current_count: int
    event_connected: bool
    event_connections_started: int
    event_reconnects_scheduled: int
    event_frames: int
    event_observations: int
    event_last_command: str | None
    event_last_status_code: str | None
    event_last_failure_classification: str | None
    event_last_failure_detail: str | None
    event_last_failure_stage: str | None
    event_subscription_state: str
    event_st_frames: int
    event_kp_frames: int
    event_fd_frames: int
    event_ss_frames: int
    event_us_frames: int
    event_fd_rows_assembled: int
    event_unknown_noncritical_fields: int
    event_normalization_degradations: int
    event_last_normalization_field: str | None
    event_last_normalization_reason: str | None
    event_last_normalization_row: int | None
    event_last_normalization_symbol: str | None
    event_close_code: int | None
    event_close_reason_classification: str | None
    event_timeout_category: str | None
    event_sequence_advanced: bool
    event_timestamp_advanced: bool
    source_timestamp_advanced: bool
    market_value_changed: bool
    book_progression: bool
    execution_progression: bool
    preopen_book_live: bool
    execution_market_live: bool
    transition_window: str | None
    session_phase: str
    session_truth_confident: bool
    market_date_verified: bool
    provider_calendar_current: bool
    event_packet_current: bool
    provider_health: str
    provider_market_status: str
    provider_operation_code: str | None
    provider_login_permission_code: str | None
    provider_system_status_code: str | None
    provider_status_date_verified: bool
    provider_state_conflict: bool
    cross_validation: CrossValidationResult | None

    @property
    def accepted(self) -> bool:
        return self.classification == "ACCEPTED"

    def safe_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["accepted"] = self.accepted
        return result


class TachibanaLiveRuntime:
    """Own one authenticated session and one receive-only EVENT lifecycle."""

    def __init__(
        self,
        config: TachibanaConfig,
        *,
        symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
        clock: Callable[[], datetime] = _utcnow,
        reference_fetch: Callable[..., object] = requests.get,
    ) -> None:
        validate_live_flags(config)
        self.config = config
        self.symbols = validate_symbols(symbols)
        self._clock = clock
        self._reference_fetch = reference_fetch
        self.session = TachibanaSession(config, clock=clock)
        self.sensor = TransientLiveSensor(
            max_symbols=len(self.symbols),
            window_size=config.rolling_window_size,
            window_seconds=config.rolling_window_seconds,
        )
        self.progress = EventLifecycleProgress()
        self.stop_event = threading.Event()
        self._event_thread: threading.Thread | None = None
        self._event_error = ErrorClass.NONE
        self._authenticated = False
        self._provider_calendar_date: date | None = None
        self._price_observations: dict[str, TachibanaObservation] = {}
        self._initial_read_diagnostics = {
            "providerDate": ProviderReadDiagnostic(
                operation="CLMStkGetDateZyouhou",
                endpoint_class="MASTER",
                expected_response_clmid="CLMDateZyouhou",
            ),
            "priceBaseline": ProviderReadDiagnostic(
                operation="CLMMfdsGetMarketPrice",
                endpoint_class="PRICE",
                expected_response_clmid="CLMMfdsGetMarketPrice",
            ),
        }
        self._preopen_event_baseline: datetime | None = None
        self._preopen_event_connection_number: int | None = None
        self._execution_event_baseline: datetime | None = None
        self._execution_event_connection_number: int | None = None
        self._preopen_book_live = False
        self._execution_market_live = False
        self._transition_window: str | None = None
        self._last_acceptable_cross: CrossValidationResult | None = None
        self._last_acceptable_cross_at: datetime | None = None

    @property
    def terminal_error(self) -> ErrorClass:
        return self._event_error

    def initial_read_diagnostics_safe_dict(
        self,
    ) -> dict[str, dict[str, object]]:
        return {
            name: diagnostic.safe_dict()
            for name, diagnostic in self._initial_read_diagnostics.items()
        }

    def start(self) -> None:
        self.session.authenticate()
        self._authenticated = True
        try:
            client = TachibanaReadOnlyClient(self.session)
            try:
                self._provider_calendar_date = client.provider_calendar_date()
            finally:
                self._initial_read_diagnostics["providerDate"] = (
                    client.last_read_diagnostic
                )
            try:
                self._read_price_snapshot(client)
            finally:
                self._initial_read_diagnostics["priceBaseline"] = (
                    client.last_read_diagnostic
                )
            lifecycle = TachibanaEventLifecycle(
                self.session,
                EventSubscription(self.symbols, max_symbols=len(self.symbols)),
                self.sensor,
                session_truth_resolver=resolve_jp_cash_session,
                provider_calendar_date=self._provider_calendar_date,
                progress=self.progress,
            )

            def _receive() -> None:
                try:
                    lifecycle.run(self.stop_event)
                except TachibanaError as exc:
                    self._event_error = exc.classification
                except Exception:
                    self._event_error = ErrorClass.NETWORK

            self._event_thread = threading.Thread(
                target=_receive,
                name="tachibana-event-receiver",
                daemon=False,
            )
            self._event_thread.start()
        except Exception:
            self.stop()
            raise

    def _read_price_snapshot(self, client: TachibanaReadOnlyClient) -> None:
        response = client.market_price(
            self.symbols, PRICE_COLUMNS
        )
        rows = response.get("aCLMMfdsMarketPrice")
        if not isinstance(rows, list) or len(rows) != len(self.symbols):
            client.mark_last_read_stage(
                "PRICE_BASELINE_SCHEMA", ErrorClass.PROVIDER.value,
                schema_failure_token="PRICE_ROW_SET_INCOMPLETE",
            )
            raise TachibanaError(ErrorClass.PROVIDER)
        try:
            received = self._clock().astimezone(timezone.utc)
            provider_time = parse_provider_datetime(response.get("p_rv_date"))
            truth = resolve_jp_cash_session(
                now=received,
                provider_time=provider_time,
                provider_calendar_date=self._provider_calendar_date,
                provider_health=ProviderHealth.AVAILABLE,
            )
            normalized: dict[str, TachibanaObservation] = {}
            for row in rows:
                observation = normalize_market_price(
                    row,
                    received_at=received,
                    market_date=truth.market_date,
                    market_status=truth.market_status,
                    # p_rv_date establishes the PRICE response time, not the
                    # trade-date of a time-only tDPP. During pre-open, tDPP may
                    # still be the prior close and must not be relabelled today.
                    market_date_verified=bool(
                        truth.market_date_verified
                        and truth.phase in {
                            JapanCashPhase.OPEN,
                            JapanCashPhase.AFTERNOON_OPEN,
                        }
                    ),
                    market_data_timestamp=provider_time,
                    market_data_date_verified=bool(
                        truth.provider_calendar_current
                        and truth.event_packet_current
                    ),
                    fresh_for_seconds=self.config.fresh_for_seconds,
                )
                normalized[observation.symbol] = observation
            if set(normalized) != set(self.symbols):
                client.mark_last_read_stage(
                    "PRICE_BASELINE_NORMALIZE", ErrorClass.PROVIDER.value,
                    schema_failure_token="NORMALIZED_SYMBOL_SET_MISMATCH",
                )
                raise TachibanaError(ErrorClass.PROVIDER)
        except TachibanaError as exc:
            if client.last_read_diagnostic.classification == "PASS":
                client.mark_last_read_stage(
                    "PRICE_BASELINE_NORMALIZE", exc.classification.value,
                    schema_failure_token="NORMALIZATION_REJECTED",
                )
            raise
        except Exception:
            client.mark_last_read_stage(
                "PRICE_BASELINE_NORMALIZE", ErrorClass.NORMALIZATION.value,
                schema_failure_token="NORMALIZATION_EXCEPTION",
            )
            raise TachibanaError(ErrorClass.NORMALIZATION) from None
        client.mark_last_read_stage("PRICE_BASELINE_NORMALIZE", "PASS")
        self._price_observations = normalized

    def _latest_board_current(
        self, now: datetime
    ) -> dict[str, TachibanaObservation]:
        result: dict[str, TachibanaObservation] = {}
        for symbol in self.symbols:
            candidates = (
                self.sensor.latest(symbol, now=now),
                self._price_observations.get(symbol),
            )
            for observation in candidates:
                if (
                    observation is not None
                    and observation.freshness == Freshness.FRESH
                    and observation.market_data_date_verified
                    and observation.fresh_until is not None
                    and observation.fresh_until >= now
                    and (
                        observation.asks
                        or observation.bids
                        or any(
                            observation.field_availability.get(field, False)
                            for field in _BOOK_CHANGE_FIELDS
                        )
                    )
                ):
                    result[symbol] = observation
                    break
        return result

    def _latest_execution_current(
        self, now: datetime, truth: SessionTruth
    ) -> dict[str, TachibanaObservation]:
        if (
            truth.phase not in {
                JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN,
            }
            or not truth.market_date_verified
        ):
            return {}
        result: dict[str, TachibanaObservation] = {}
        for symbol, observation in self._latest_board_current(now).items():
            source = observation.source_timestamp
            if (
                source is not None
                and source.astimezone(_TOKYO).date() == truth.market_date
                and timedelta(0) <= now - source <= timedelta(minutes=20)
                and observation.market_status == MarketStatus.OPEN
                and _finite_number(observation.fields.get("current_price"))
                is not None
            ):
                result[symbol] = observation
        return result

    def acceptance_snapshot(self, *, cross_validate: bool = False) -> LiveAcceptanceSnapshot:
        now = self._clock().astimezone(timezone.utc)
        progress = self.progress.snapshot()
        truth = resolve_jp_cash_session(
            now=now,
            provider_time=progress.last_provider_timestamp,
            provider_calendar_date=self._provider_calendar_date,
            provider_health=self.session.diagnostics.health,
            provider_market_status=MarketStatus(
                progress.provider_market_status
            ),
            control_state_confident=not progress.provider_state_conflict,
        )
        board_current = self._latest_board_current(now)
        current = self._latest_execution_current(now, truth)
        source_advanced = False
        market_changed = False
        book_progression = False
        book_progression_symbols: set[str] = set()
        execution_progression = False
        morning_preopen_start = datetime.combine(
            truth.market_date, datetime.min.time(), _TOKYO
        ).replace(hour=8).astimezone(timezone.utc)
        morning_execution_start = morning_preopen_start + timedelta(hours=1)
        afternoon_preopen_start = morning_preopen_start + timedelta(
            hours=4, minutes=5
        )
        afternoon_execution_start = morning_preopen_start + timedelta(
            hours=4, minutes=30
        )
        execution_start = (
            morning_execution_start
            if self._transition_window == "MORNING"
            else afternoon_execution_start
            if self._transition_window == "AFTERNOON"
            else None
        )
        for symbol in self.symbols:
            window = tuple(
                item for item in self.sensor.window(symbol, now=now)
                if item.market_data_date_verified
                and item.market_data_timestamp is not None
                and item.market_data_timestamp.astimezone(_TOKYO).date()
                == truth.market_date
            )
            timestamps = {
                item.source_timestamp for item in window
                if item.source_timestamp is not None
                and item.source_timestamp.astimezone(_TOKYO).date()
                == truth.market_date
            }
            source_advanced = source_advanced or len(timestamps) >= 2
            for previous, latest in zip(window, window[1:]):
                if any(
                    previous.fields.get(field) != latest.fields.get(field)
                    for field in _CHANGE_FIELDS
                ):
                    market_changed = True
                if (
                    (
                        morning_preopen_start
                        <= previous.received_timestamp
                        < morning_execution_start
                        and latest.received_timestamp < morning_execution_start
                    )
                    or (
                        afternoon_preopen_start
                        <= previous.received_timestamp
                        < afternoon_execution_start
                        and latest.received_timestamp < afternoon_execution_start
                    )
                ) and (
                    previous.asks != latest.asks
                    or previous.bids != latest.bids
                    or any(
                        previous.fields.get(field)
                        != latest.fields.get(field)
                        for field in _BOOK_CHANGE_FIELDS
                    )
                ):
                    book_progression = True
                    book_progression_symbols.add(symbol)
                if (
                    execution_start is not None
                    and previous.received_timestamp >= execution_start
                    and any(
                        previous.fields.get(field) != latest.fields.get(field)
                        for field in _EXECUTION_CHANGE_FIELDS
                    )
                ):
                    execution_progression = True
        sequence_advanced = progress.sequence_advanced
        timestamp_advanced = progress.provider_timestamp_advanced
        connection_timestamp = progress.current_connection_last_provider_timestamp
        if (
            not self._preopen_book_live
            and truth.phase in {
                JapanCashPhase.PREOPEN,
                JapanCashPhase.AFTERNOON_PREOPEN,
            }
            and truth.market_date_verified
            and connection_timestamp is not None
            and self._preopen_event_connection_number
            != progress.connections_started
        ):
            self._preopen_event_connection_number = progress.connections_started
            self._preopen_event_baseline = connection_timestamp
        if (
            truth.phase in {JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN}
            and truth.market_date_verified
            and connection_timestamp is not None
            and self._execution_event_connection_number
            != progress.connections_started
        ):
            self._execution_event_connection_number = progress.connections_started
            self._execution_event_baseline = connection_timestamp
        preopen_event_progression = bool(
            self._preopen_event_baseline is not None
            and connection_timestamp is not None
            and connection_timestamp > self._preopen_event_baseline
        )
        execution_event_progression = bool(
            self._execution_event_baseline is not None
            and connection_timestamp is not None
            and connection_timestamp > self._execution_event_baseline
        )
        if (
            not self._preopen_book_live
            and truth.phase in {
                JapanCashPhase.PREOPEN,
                JapanCashPhase.AFTERNOON_PREOPEN,
            }
            and truth.market_date_verified
            and bool(set(board_current) & book_progression_symbols)
            and self.session.diagnostics.websocket_connected
            and preopen_event_progression
            and book_progression
        ):
            self._preopen_book_live = True
            self._transition_window = (
                "MORNING"
                if truth.phase == JapanCashPhase.PREOPEN
                else "AFTERNOON"
            )
        cross = (
            cross_validate_current(
                current,
                now=now,
                fetch=self._reference_fetch,
                session_phase=truth.phase,
            ) if cross_validate and current else None
        )
        if cross is not None:
            if cross.acceptable:
                self._last_acceptable_cross = cross
                self._last_acceptable_cross_at = now
            else:
                self._last_acceptable_cross = None
                self._last_acceptable_cross_at = None
        effective_cross = cross
        if (
            effective_cross is None
            and self._last_acceptable_cross is not None
            and self._last_acceptable_cross_at is not None
            and now - self._last_acceptable_cross_at <= timedelta(seconds=60)
        ):
            effective_cross = self._last_acceptable_cross
        event_connected = self.session.diagnostics.websocket_connected
        if (
            truth.phase in {JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN}
            and truth.market_date_verified
            and len(current) == len(self.symbols)
            and event_connected
            and execution_event_progression
            and source_advanced
            and execution_progression
            and effective_cross is not None
            and effective_cross.acceptable
        ):
            self._execution_market_live = True
        if self._event_error != ErrorClass.NONE:
            event_error = self._event_error.value
            classification = (
                event_error
                if event_error.startswith("EVENT_")
                else f"EVENT_{event_error}"
            )
        elif not self._preopen_book_live:
            classification = (
                "PREOPEN_BOOK_PROGRESSING"
                if truth.phase in {
                    JapanCashPhase.PREOPEN,
                    JapanCashPhase.AFTERNOON_PREOPEN,
                }
                and truth.market_date_verified
                else "PREOPEN_BOOK_UNPROVEN"
            )
        elif truth.phase in {
            JapanCashPhase.PREOPEN,
            JapanCashPhase.AFTERNOON_PREOPEN,
        }:
            classification = "PREOPEN_BOOK_LIVE"
        elif truth.phase not in {
            JapanCashPhase.OPEN, JapanCashPhase.AFTERNOON_OPEN,
        }:
            classification = "EXECUTION_WINDOW_NOT_OPEN"
        elif len(current) != len(self.symbols):
            classification = "PRICE_OR_EVENT_NOT_CURRENT"
        elif not event_connected:
            classification = "EVENT_NOT_CONNECTED"
        elif not sequence_advanced or not timestamp_advanced:
            classification = "EVENT_NOT_ADVANCING"
        elif not source_advanced:
            classification = "SOURCE_TIMESTAMP_NOT_ADVANCING"
        elif not execution_event_progression:
            classification = "EXECUTION_EVENT_NOT_ADVANCING"
        elif not execution_progression:
            classification = "EXECUTION_MARKET_MOVE_NOT_OBSERVED"
        elif effective_cross is None or not effective_cross.acceptable:
            classification = "CROSS_VALIDATION_NOT_ACCEPTABLE"
        elif not self._execution_market_live:
            classification = "EXECUTION_MARKET_UNPROVEN"
        else:
            classification = "ACCEPTED"
        return LiveAcceptanceSnapshot(
            classification=classification,
            authenticated=self._authenticated,
            price_current_count=len(current),
            board_current_count=len(board_current),
            execution_current_count=len(current),
            event_connected=event_connected,
            event_connections_started=progress.connections_started,
            event_reconnects_scheduled=progress.reconnects_scheduled,
            event_frames=progress.frames_received,
            event_observations=progress.observations_ingested,
            event_last_command=progress.last_command,
            event_last_status_code=progress.last_status_code,
            event_last_failure_classification=(
                progress.last_failure_classification
            ),
            event_last_failure_detail=progress.last_failure_detail,
            event_last_failure_stage=progress.last_failure_stage,
            event_subscription_state=progress.subscription_state,
            event_st_frames=progress.st_frames,
            event_kp_frames=progress.kp_frames,
            event_fd_frames=progress.fd_frames,
            event_ss_frames=progress.ss_frames,
            event_us_frames=progress.us_frames,
            event_fd_rows_assembled=progress.fd_rows_assembled,
            event_unknown_noncritical_fields=(
                progress.unknown_noncritical_fields
            ),
            event_normalization_degradations=(
                progress.normalization_degradations
            ),
            event_last_normalization_field=(
                progress.last_normalization_field
            ),
            event_last_normalization_reason=(
                progress.last_normalization_reason
            ),
            event_last_normalization_row=progress.last_normalization_row,
            event_last_normalization_symbol=(
                progress.last_normalization_symbol
            ),
            event_close_code=progress.close_code,
            event_close_reason_classification=(
                progress.close_reason_classification
            ),
            event_timeout_category=progress.timeout_category,
            event_sequence_advanced=sequence_advanced,
            event_timestamp_advanced=timestamp_advanced,
            source_timestamp_advanced=source_advanced,
            market_value_changed=market_changed,
            book_progression=(book_progression or self._preopen_book_live),
            execution_progression=(
                execution_progression or self._execution_market_live
            ),
            preopen_book_live=self._preopen_book_live,
            execution_market_live=self._execution_market_live,
            transition_window=self._transition_window,
            session_phase=truth.phase.value,
            session_truth_confident=truth.session_truth_confident,
            market_date_verified=truth.market_date_verified,
            provider_calendar_current=truth.provider_calendar_current,
            event_packet_current=truth.event_packet_current,
            provider_health=self.session.diagnostics.health.value,
            provider_market_status=progress.provider_market_status,
            provider_operation_code=progress.provider_operation_code,
            provider_login_permission_code=(
                progress.provider_login_permission_code
            ),
            provider_system_status_code=progress.provider_system_status_code,
            provider_status_date_verified=(
                progress.provider_status_date_verified
            ),
            provider_state_conflict=progress.provider_state_conflict,
            cross_validation=effective_cross,
        )

    def wait_for_acceptance(
        self, *, timeout_seconds: int, interval_seconds: float = 2.0,
    ) -> LiveAcceptanceSnapshot:
        if not 30 <= timeout_seconds <= 7200 or not 0.2 <= interval_seconds <= 10:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        deadline = time.monotonic() + timeout_seconds
        latest = self.acceptance_snapshot()
        last_cross_validation = 0.0
        while time.monotonic() < deadline and not self.stop_event.wait(
            interval_seconds
        ):
            should_cross_validate = (
                time.monotonic() - last_cross_validation >= 30
                and latest.execution_current_count == len(self.symbols)
            )
            latest = self.acceptance_snapshot(
                cross_validate=bool(should_cross_validate)
            )
            if should_cross_validate:
                last_cross_validation = time.monotonic()
            if latest.accepted or self._event_error != ErrorClass.NONE:
                return latest
        return latest

    def stop(self) -> bool:
        self.stop_event.set()
        if self._event_thread is not None and self._event_thread.is_alive():
            self._event_thread.join(timeout=5)
        teardown = True
        if self._authenticated:
            teardown = self.session.logout()
        self._authenticated = False
        self._provider_calendar_date = None
        self.sensor.clear()
        self._price_observations.clear()
        self._preopen_event_baseline = None
        self._execution_event_baseline = None
        self._preopen_book_live = False
        self._execution_market_live = False
        self._transition_window = None
        self._last_acceptable_cross = None
        self._last_acceptable_cross_at = None
        return teardown


__all__ = [
    "CrossValidationResult",
    "DEFAULT_SYMBOLS",
    "LiveAcceptanceSnapshot",
    "PRICE_COLUMNS",
    "REFERENCE_ENDPOINT",
    "TachibanaLiveRuntime",
    "cross_validate_current",
    "validate_live_flags",
    "validate_symbols",
]
