"""Bounded in-memory live sensor and safe EVENT-frame parser."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import base64
import re
import threading
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .config import TachibanaConfig
from .models import TachibanaObservation


ALLOWED_EVENT_COMMANDS = frozenset({"ST", "KP", "FD", "SS", "US"})
FORBIDDEN_EVENT_COMMANDS = frozenset({"EC", "NS", "RR", "FC"})
_MAX_EVENT_FRAME_BYTES = 256 * 1024
_MAX_EVENT_FIELDS = 5_000
_FD_FIELD = re.compile(
    r"^(?P<kind>[ptx])_(?P<row>[1-9][0-9]{0,2})_"
    r"(?P<code>[A-Z][A-Z0-9]*)(?P<suffix>:T)?$"
)
_SECURITY_CODE = re.compile(r"^[0-9ACDFGHJKLMNPRSTUWXY]{4}$")
_EVENT_DATE = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}$")
_COMMON_EVENT_FIELDS = frozenset({"p_no", "p_date", "p_cmd"})
_ST_FIELDS = frozenset({"p_errno", "p_err"})
_SS_FIELDS = frozenset({
    "p_PV", "p_ENO", "p_ALT", "p_CT", "p_LK", "p_SS",
})
_US_FIELDS = frozenset({
    "p_PV", "p_ENO", "p_ALT", "p_CT", "p_MC", "p_GSCD", "p_SHSB",
    "p_UC", "p_UU", "p_EDK", "p_US",
})
_SAFE_EXTENSION_FIELD = re.compile(r"^p_[A-Z][A-Z0-9_]{0,63}$")
_EVENT_SOURCE_TIME = re.compile(r"^[0-9]{14}$")
_DOCUMENTED_MARKETS = frozenset({"00", "01", "02", "05", "07", "08", "09"})
_DOCUMENTED_OPERATION_CATEGORIES = frozenset(
    f"{number:02d}" for number in range(1, 13)
)
_DOCUMENTED_OPERATION_UNITS = frozenset({
    "0101", "0102", "0103", "0201", "0202", "0301", "0401", "0402",
    "0500", "0600", "0700", "0800", "0900", "1000", "1100", "1200",
})
_FD_VALUE_FIELDS = frozenset({
    "pAAV", "pABV", "pAV", "pBV", "xDCFS", "pDHF", "pDHP", "tDHP:T",
    "pDJ", "pDLF", "pDLP", "tDLP:T", "pDOP", "tDOP:T", "pDPG", "pDPP",
    "tDPP:T", "pDV", "xDVES", "pDYRP", "pDYWP", "xLISS", "pPRP", "pQAP",
    "pQAS", "pQBP", "pQBS", "pQOV", "pQUV", "pVWAP",
    *(f"pGAP{level}" for level in range(1, 11)),
    *(f"pGAV{level}" for level in range(1, 11)),
    *(f"pGBP{level}" for level in range(1, 11)),
    *(f"pGBV{level}" for level in range(1, 11)),
})
TOKYO = ZoneInfo("Asia/Tokyo")


def decode_event_base64_shift_jis(
    value: str, *, maximum_decoded_bytes: int = 8_192
) -> str:
    """Decode an explicitly documented WebSocket Japanese-text field.

    EVENT WebSocket messages themselves are RFC 6455 text frames.  The v4r7
    contract Base64-encodes only fields whose values contain Shift-JIS text
    (currently p_IN on EC and p_HDL/p_TX on NS).  EC and NS remain rejected by
    this market-data-only parser; this bounded primitive exists so callers can
    never mistake that field encoding for an encoding of the entire frame.
    """
    if (
        not isinstance(value, str)
        or not 1 <= maximum_decoded_bytes <= _MAX_EVENT_FRAME_BYTES
    ):
        raise ValueError("event_base64_shift_jis_invalid")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("event_base64_shift_jis_invalid") from None
    maximum_encoded = 4 * ((maximum_decoded_bytes + 2) // 3)
    if len(encoded) > maximum_encoded:
        raise ValueError("event_base64_shift_jis_too_large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ValueError("event_base64_shift_jis_invalid") from None
    if len(raw) > maximum_decoded_bytes:
        raise ValueError("event_base64_shift_jis_too_large")
    try:
        return raw.decode("shift_jis")
    except UnicodeDecodeError:
        raise ValueError("event_base64_shift_jis_invalid") from None


def _validate_source_time(value: str) -> bool:
    if not _EVENT_SOURCE_TIME.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return False
    return True


def _validate_shift_jis_hex(value: str) -> None:
    """Validate FD's documented xLISS Shift-JIS-as-hex representation."""
    try:
        raw = bytes.fromhex(value)
        if not raw or raw.hex().upper() != value.upper():
            raise ValueError
        raw.decode("shift_jis")
    except (UnicodeDecodeError, ValueError):
        raise ValueError("event_fd_shift_jis_hex_invalid") from None


def _valid_security_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and _SECURITY_CODE.fullmatch(value) is not None
        and any(character.isdigit() for character in value)
    )


def parse_event_frame(frame: str | bytes) -> Mapping[str, str]:
    if isinstance(frame, bytes):
        if len(frame) > _MAX_EVENT_FRAME_BYTES:
            raise ValueError("event_frame_too_large")
        try:
            text = frame.decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("event_frame_invalid_encoding") from None
    elif isinstance(frame, str):
        try:
            encoded = frame.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("event_frame_invalid_encoding") from None
        if len(encoded) > _MAX_EVENT_FRAME_BYTES:
            raise ValueError("event_frame_too_large")
        text = frame
    else:
        raise ValueError("event_frame_invalid_type")
    fields: dict[str, str] = {}
    records = text.split("\x01")
    if records and records[-1] == "":
        records.pop()
    if not records or any(not item for item in records):
        raise ValueError("event_frame_malformed")
    if len(records) > _MAX_EVENT_FIELDS:
        raise ValueError("event_frame_too_many_fields")
    for record in records:
        parts = record.split("\x02")
        if (
            len(parts) != 2
            or not parts[0]
            or len(parts[0]) > 64
            or len(parts[1]) > 8192
            # ETX is only a list separator. None of the admitted
            # ST/KP/FD/SS/US fields is a documented list-valued field.
            or "\x03" in parts[1]
            or any(ord(character) < 0x20 or ord(character) == 0x7f
                   for character in parts[0] + parts[1])
        ):
            raise ValueError("event_frame_malformed")
        if parts[0] in fields:
            raise ValueError("event_frame_duplicate_field")
        fields[parts[0]] = parts[1]
    command = fields.get("p_cmd")
    if command is None:
        raise ValueError("event_command_missing")
    if command in FORBIDDEN_EVENT_COMMANDS:
        raise ValueError("event_command_not_read_only_market_data")
    if command not in ALLOWED_EVENT_COMMANDS:
        raise ValueError("event_command_unknown")
    for common in _COMMON_EVENT_FIELDS:
        if common not in fields:
            raise ValueError("event_common_field_missing")
    try:
        sequence = int(fields["p_no"])
    except ValueError:
        raise ValueError("event_connection_sequence_invalid") from None
    if sequence < 1 or not _EVENT_DATE.fullmatch(fields["p_date"]):
        raise ValueError("event_common_field_invalid")
    try:
        datetime.strptime(fields["p_date"], "%Y.%m.%d-%H:%M:%S.%f")
    except ValueError:
        raise ValueError("event_common_field_invalid") from None

    extra_fields = set(fields) - _COMMON_EVENT_FIELDS
    if command == "FD":
        if "p_ENO" in fields or "p_eno" in fields:
            raise ValueError("event_fd_event_number_invalid")
        for key in extra_fields:
            match = _FD_FIELD.fullmatch(key)
            if match is None:
                raise ValueError("event_fd_field_invalid")
            normalized = (
                match.group("kind") + match.group("code")
                + (match.group("suffix") or "")
            )
            if normalized == "xLISS":
                _validate_shift_jis_hex(fields[key])
        if not extra_fields:
            raise ValueError("event_fd_fields_missing")
    elif command == "ST":
        if not _ST_FIELDS <= extra_fields or any(
            key not in _ST_FIELDS and _SAFE_EXTENSION_FIELD.fullmatch(key) is None
            for key in extra_fields
        ):
            raise ValueError("event_status_fields_invalid")
        if fields["p_errno"] not in {
            "0", "1", "2", "9", "-1", "-2", "-3", "-12", "-62",
        }:
            raise ValueError("event_status_error_invalid")
    elif command == "KP":
        if any(
            _SAFE_EXTENSION_FIELD.fullmatch(key) is None
            for key in extra_fields
        ):
            raise ValueError("event_keepalive_fields_invalid")
    else:
        if any(_FD_FIELD.fullmatch(key) for key in extra_fields):
            raise ValueError("event_row_field_on_non_fd")
        expected = _SS_FIELDS if command == "SS" else _US_FIELDS
        if not expected <= extra_fields or any(
            key not in expected and _SAFE_EXTENSION_FIELD.fullmatch(key) is None
            for key in extra_fields
        ):
            raise ValueError("event_system_fields_invalid")
        try:
            if int(fields["p_ENO"]) < 1:
                raise ValueError
        except ValueError:
            raise ValueError("event_number_invalid") from None
        if fields["p_ALT"] not in {"0", "1"} or not _validate_source_time(
            fields["p_CT"]
        ):
            raise ValueError("event_system_field_value_invalid")
        if command == "SS":
            if fields["p_LK"] not in {"0", "1", "2", "9"} or \
                    fields["p_SS"] not in {"0", "1"}:
                raise ValueError("event_system_field_value_invalid")
        elif (
            fields["p_MC"] not in _DOCUMENTED_MARKETS
            or (fields["p_GSCD"] and not re.fullmatch(r"[0-9]{3}", fields["p_GSCD"]))
            or fields["p_SHSB"] not in {"", "01", "02", "03", "04", "05", "06", "07"}
            or fields["p_UC"] not in _DOCUMENTED_OPERATION_CATEGORIES
            or fields["p_UU"] not in _DOCUMENTED_OPERATION_UNITS
            or fields["p_EDK"] not in {"0", "1", "2"}
            or re.fullmatch(r"[0-9]{3}", fields["p_US"]) is None
        ):
            raise ValueError("event_operation_field_value_invalid")
    return MappingProxyType(fields)


def event_unknown_noncritical_field_count(fields: Mapping[str, str]) -> int:
    """Count admitted forward-compatible fields without retaining their values."""
    command = fields.get("p_cmd")
    if command == "FD":
        count = 0
        for key in fields:
            match = _FD_FIELD.fullmatch(key)
            if match is None:
                continue
            normalized = (
                match.group("kind") + match.group("code")
                + (match.group("suffix") or "")
            )
            count += normalized not in _FD_VALUE_FIELDS
        return count
    expected = {
        "ST": _ST_FIELDS,
        "KP": frozenset(),
        "SS": _SS_FIELDS,
        "US": _US_FIELDS,
    }.get(command, frozenset())
    return len(set(fields) - _COMMON_EVENT_FIELDS - expected)


@dataclass(frozen=True)
class EventSubscription:
    """Immutable, market-data-only EVENT query and row association."""

    symbols: tuple[str, ...]
    max_symbols: int = 64
    row_to_symbol: Mapping[int, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.max_symbols <= 64:
            raise ValueError("invalid_event_symbol_bound")
        if (
            not isinstance(self.symbols, tuple)
            or not 1 <= len(self.symbols) <= self.max_symbols
            or any(not _valid_security_code(item) for item in self.symbols)
            or len(set(self.symbols)) != len(self.symbols)
        ):
            raise ValueError("invalid_event_subscription")
        object.__setattr__(
            self, "row_to_symbol",
            MappingProxyType({index: symbol for index, symbol in enumerate(
                self.symbols, start=1
            )}),
        )

    @property
    def parameters(self) -> Mapping[str, str]:
        rows = tuple(str(index) for index in self.row_to_symbol)
        return MappingProxyType({
            "p_rid": "22",
            "p_board_no": "1000",
            "p_eno": "0",
            # EC (orders/executions) and NS (news) are intentionally absent.
            "p_evt_cmd": "ST,KP,FD,SS,US",
            "p_issue_code": ",".join(self.symbols),
            "p_gyou_no": ",".join(rows),
            "p_mkt_code": ",".join("00" for _ in rows),
        })

    def query_string(self) -> str:
        # Commas are the documented list separator in the official sample.
        return urlencode(tuple(self.parameters.items()), safe=",")


class EventConnector(Protocol):
    """Narrow seam for a future audited WebSocket implementation.

    A connector may only receive provider frames; it has no send/order API.
    The implementation must honor the supplied limits and stop event.
    """

    def receive(
        self,
        endpoint: str,
        subscription: EventSubscription,
        *,
        connect_timeout_seconds: int,
        idle_timeout_seconds: int,
        maximum_frame_bytes: int,
        stop_event: threading.Event,
    ) -> Iterable[str | bytes]: ...


@dataclass(frozen=True)
class EventConnectionPolicy:
    """Disabled-by-default bounds for the future connector integration."""

    enabled: bool
    connect_timeout_seconds: int
    idle_timeout_seconds: int = 30
    maximum_frame_bytes: int = _MAX_EVENT_FRAME_BYTES
    maximum_reconnects_per_day: int = 10
    reconnect_initial_seconds: float = 1.0
    reconnect_maximum_seconds: float = 30.0
    reconnect_jitter_fraction: float = 0.20

    @classmethod
    def from_config(cls, config: TachibanaConfig) -> "EventConnectionPolicy":
        return cls(
            enabled=config.websocket_enabled,
            connect_timeout_seconds=config.request_timeout_seconds,
            maximum_reconnects_per_day=config.max_event_reconnects_per_day,
        )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.enabled, bool)
            or not 2 <= self.connect_timeout_seconds <= 30
            or not 5 <= self.idle_timeout_seconds <= 120
            or not 1 <= self.maximum_frame_bytes <= _MAX_EVENT_FRAME_BYTES
            or not 1 <= self.maximum_reconnects_per_day <= 10
            or type(self.reconnect_initial_seconds) not in {int, float}
            or not 0.1 <= self.reconnect_initial_seconds <= 10.0
            or type(self.reconnect_maximum_seconds) not in {int, float}
            or not self.reconnect_initial_seconds <= self.reconnect_maximum_seconds <= 60.0
            or type(self.reconnect_jitter_fraction) not in {int, float}
            or not 0.0 <= self.reconnect_jitter_fraction <= 0.5
        ):
            raise ValueError("invalid_event_connection_policy")


class EventReconnectBudget:
    def __init__(self, maximum_per_day: int, *, clock=lambda: datetime.now(timezone.utc)) -> None:
        if not 1 <= maximum_per_day <= 10:
            raise ValueError("invalid_event_reconnect_bound")
        self._maximum = maximum_per_day
        self._clock = clock
        self._day: date | None = None
        self._count = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        with self._lock:
            now = self._clock()
            if now.tzinfo is None:
                raise ValueError("event_reconnect_clock_naive")
            current_day = now.astimezone(TOKYO).date()
            if current_day != self._day:
                self._day = current_day
                self._count = 0
            if self._count >= self._maximum:
                return False
            self._count += 1
            return True


@dataclass(frozen=True)
class SensorBounds:
    max_symbols: int
    window_size: int
    window_seconds: int


class TransientLiveSensor:
    """No persistence methods: current state and windows exist only in RAM."""

    def __init__(self, *, max_symbols: int, window_size: int, window_seconds: int) -> None:
        if not 1 <= max_symbols <= 64 or not 2 <= window_size <= 600 or \
                not 30 <= window_seconds <= 3600:
            raise ValueError("invalid_sensor_bounds")
        self.bounds = SensorBounds(max_symbols, window_size, window_seconds)
        self._windows: OrderedDict[str, deque[TachibanaObservation]] = OrderedDict()
        self._lock = threading.RLock()

    def ingest(self, observation: TachibanaObservation) -> None:
        if not isinstance(observation, TachibanaObservation):
            raise ValueError("invalid_sensor_observation")
        with self._lock:
            window = self._windows.get(observation.symbol)
            if window is None:
                if len(self._windows) >= self.bounds.max_symbols:
                    self._windows.popitem(last=False)
                window = deque(maxlen=self.bounds.window_size)
                self._windows[observation.symbol] = window
            else:
                if window and observation.received_timestamp < window[-1].received_timestamp:
                    raise ValueError("sensor_observation_out_of_order")
                self._windows.move_to_end(observation.symbol)
            cutoff = observation.received_timestamp - timedelta(
                seconds=self.bounds.window_seconds
            )
            while window and window[0].received_timestamp < cutoff:
                window.popleft()
            window.append(observation)

    def latest(self, symbol: str, *, now: datetime | None = None) -> TachibanaObservation | None:
        with self._lock:
            window = self._windows.get(symbol)
            if not window:
                return None
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            if current - window[-1].received_timestamp > timedelta(
                seconds=self.bounds.window_seconds
            ):
                self._windows.pop(symbol, None)
                return None
            return window[-1]

    def window(
        self, symbol: str, *, now: datetime | None = None
    ) -> tuple[TachibanaObservation, ...]:
        with self._lock:
            window = self._windows.get(symbol)
            if not window:
                return ()
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            cutoff = current - timedelta(seconds=self.bounds.window_seconds)
            while window and window[0].received_timestamp < cutoff:
                window.popleft()
            if not window:
                self._windows.pop(symbol, None)
                return ()
            return tuple(window)

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()

    def diagnostics(self, *, now: datetime | None = None) -> dict[str, int]:
        with self._lock:
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            cutoff = current - timedelta(seconds=self.bounds.window_seconds)
            empty = []
            for symbol, window in self._windows.items():
                while window and window[0].received_timestamp < cutoff:
                    window.popleft()
                if not window:
                    empty.append(symbol)
            for symbol in empty:
                self._windows.pop(symbol, None)
            return {
                "symbolCount": len(self._windows),
                "observationCount": sum(len(item) for item in self._windows.values()),
                "maxSymbols": self.bounds.max_symbols,
                "maxWindowSize": self.bounds.window_size,
                "windowSeconds": self.bounds.window_seconds,
            }


class EventSnapshotAssembler:
    """Apply initial FD snapshots and diffs with distinct sequence semantics."""

    def __init__(self, *, row_to_symbol: Mapping[int, str], max_symbols: int) -> None:
        if not 1 <= max_symbols <= 64:
            raise ValueError("invalid_event_symbol_bound")
        if (not isinstance(row_to_symbol, Mapping)
                or not 1 <= len(row_to_symbol) <= max_symbols):
            raise ValueError("invalid_event_subscription_map")
        normalized_map: dict[int, str] = {}
        for raw_row, raw_symbol in row_to_symbol.items():
            if (not isinstance(raw_row, int) or not 1 <= raw_row <= 120
                    or not _valid_security_code(raw_symbol)):
                raise ValueError("invalid_event_subscription_map")
            normalized_map[raw_row] = raw_symbol
        if len(set(normalized_map.values())) != len(normalized_map):
            raise ValueError("duplicate_event_subscription_symbol")
        if set(normalized_map) != set(range(1, len(normalized_map) + 1)):
            raise ValueError("invalid_event_subscription_rows")
        self._max_symbols = max_symbols
        self._row_to_symbol = MappingProxyType(normalized_map)
        self._rows: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._last_connection_sequence: int | None = None
        self._last_event_number: int | None = None
        self._initial_fd_received = False
        self._lock = threading.RLock()

    def apply(self, fields: Mapping[str, str]) -> tuple[Mapping[str, str], ...]:
        """Apply one official notification and return zero or more FD rows.

        EVENT identifies subscribed instruments by the row number embedded in
        keys such as ``p_1_DPP``.  The symbol never comes from an invented frame
        field; it is resolved against the exact connection subscription map.
        """
        command = fields.get("p_cmd")
        if command not in ALLOWED_EVENT_COMMANDS:
            raise ValueError("event_command_not_admitted")
        with self._lock:
            if (
                any(not isinstance(key, str) or not isinstance(value, str)
                    for key, value in fields.items())
                or not isinstance(fields.get("p_date"), str)
                or not _EVENT_DATE.fullmatch(fields["p_date"])
            ):
                raise ValueError("event_common_field_invalid")
            sequence_raw = fields.get("p_no")
            if not sequence_raw:
                raise ValueError("event_connection_sequence_missing")
            try:
                connection_sequence = int(sequence_raw)
            except ValueError:
                raise ValueError("event_connection_sequence_invalid") from None
            if connection_sequence < 1:
                raise ValueError("event_connection_sequence_invalid")
            if (
                self._last_connection_sequence is None
                and connection_sequence != 1
            ) or (
                self._last_connection_sequence is not None
                and connection_sequence != self._last_connection_sequence + 1
            ):
                raise ValueError("event_connection_sequence_gap")
            self._last_connection_sequence = connection_sequence

            event_raw = fields.get("p_ENO")
            if command in {"SS", "US"}:
                if event_raw is None:
                    raise ValueError("event_number_missing")
                try:
                    event_number = int(event_raw)
                except ValueError:
                    raise ValueError("event_number_invalid") from None
                if event_number < 1:
                    raise ValueError("event_number_invalid")
                # p_ENO is globally ascending (but may have gaps) within one
                # connection.  It orders notifications, not their embedded
                # data time; p_CT per SS/US key owns state chronology.
                if (
                    self._last_event_number is not None
                    and event_number <= self._last_event_number
                ):
                    raise ValueError("event_number_not_ascending")
                self._last_event_number = event_number
            elif event_raw is not None:
                raise ValueError("event_number_not_permitted")
            if command != "FD":
                return ()
            grouped: dict[int, dict[str, str]] = {}
            for key, value in fields.items():
                if key in _COMMON_EVENT_FIELDS:
                    continue
                match = _FD_FIELD.fullmatch(key)
                if match is None:
                    raise ValueError("event_fd_field_invalid")
                row_number = int(match.group("row"))
                if row_number not in self._row_to_symbol:
                    raise ValueError("event_row_not_subscribed")
                normalized_key = (
                    match.group("kind") + match.group("code")
                    + (match.group("suffix") or "")
                )
                # Official EVENT revisions may add non-critical FD values.
                # The parser has already validated the row-key grammar and
                # subscription bound; ignore unknown values until an explicit
                # normalization contract exists for them.
                if normalized_key not in _FD_VALUE_FIELDS:
                    continue
                grouped.setdefault(row_number, {})[normalized_key] = value
            if not grouped:
                raise ValueError("event_fd_fields_missing")
            initial = not self._initial_fd_received
            if initial and set(grouped) != set(self._row_to_symbol):
                raise ValueError("event_initial_snapshot_incomplete")
            snapshots = []
            for row_number, changes in sorted(grouped.items()):
                symbol = self._row_to_symbol[row_number]
                if initial:
                    if symbol not in self._rows and len(self._rows) >= self._max_symbols:
                        self._rows.popitem(last=False)
                    row: dict[str, str] = {"sIssueCode": symbol}
                else:
                    if symbol not in self._rows:
                        raise ValueError("event_diff_before_initial_row")
                    row = dict(self._rows[symbol])
                row.update(changes)
                self._rows[symbol] = row
                self._rows.move_to_end(symbol)
                snapshots.append(MappingProxyType(dict(row)))
            self._initial_fd_received = True
            return tuple(snapshots)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._last_connection_sequence = None
            self._last_event_number = None
            self._initial_fd_received = False
