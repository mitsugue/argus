"""Closed, provider-specific models for transient Tachibana observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from types import MappingProxyType
from typing import Mapping


class SessionState(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    AUTHENTICATING = "AUTHENTICATING"
    AVAILABLE = "AVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"
    EXPIRED = "EXPIRED"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class ProviderHealth(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    MAINTENANCE = "MAINTENANCE"


class Freshness(str, Enum):
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    HALTED = "HALTED"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


class AuthorityState(str, Enum):
    SHADOW_NON_AUTHORITATIVE = "SHADOW_NON_AUTHORITATIVE"


class ErrorClass(str, Enum):
    NONE = "NONE"
    DISABLED = "DISABLED"
    CONFIGURATION = "CONFIGURATION"
    SECRET_MISSING = "SECRET_MISSING"
    SECRET_PERMISSIONS = "SECRET_PERMISSIONS"
    PRIVATE_KEY_INVALID = "PRIVATE_KEY_INVALID"
    AUTH_REJECTED = "AUTH_REJECTED"
    AUTH_LOCAL_STATE_REJECTED = "AUTH_LOCAL_STATE_REJECTED"
    AUTH_RESPONSE_INVALID = "AUTH_RESPONSE_INVALID"
    AUTH_SERVER_REJECTED = "AUTH_SERVER_REJECTED"
    AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD = "AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD"
    AUTH_SUCCESS_DECRYPT_FAILED = "AUTH_SUCCESS_DECRYPT_FAILED"
    AUTH_HTTP_FAILED = "AUTH_HTTP_FAILED"
    AUTH_PROTOCOL_FAILED = "AUTH_PROTOCOL_FAILED"
    AUTH_TIMEOUT = "AUTH_TIMEOUT"
    AUTH_MAINTENANCE = "AUTH_MAINTENANCE"
    AUTH_IP_REJECTED = "AUTH_IP_REJECTED"
    AUTH_LOCKED = "AUTH_LOCKED"
    VIRTUAL_URL_INVALID = "VIRTUAL_URL_INVALID"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    NETWORK = "NETWORK"
    HTTP = "HTTP"
    PROVIDER = "PROVIDER"
    RATE_LIMITED = "RATE_LIMITED"
    MAINTENANCE = "MAINTENANCE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    NORMALIZATION = "NORMALIZATION"
    OUTSIDE_HOURS = "OUTSIDE_HOURS"
    SEQUENCE_DESYNC = "SEQUENCE_DESYNC"
    CLOCK_SKEW = "CLOCK_SKEW"
    EVENT_IDLE_TIMEOUT = "EVENT_IDLE_TIMEOUT"
    EVENT_RECONNECT_EXHAUSTED = "EVENT_RECONNECT_EXHAUSTED"


@dataclass(frozen=True)
class AuthDiagnostic:
    """Non-secret facts retained from the latest authentication boundary."""

    classification: str = "AUTH_NOT_ATTEMPTED"
    boundary: str = "NOT_REACHED"
    http_status: int | None = None
    response_clmid: str | None = None
    result_code: str | None = None
    official_reason: str | None = None
    response_matched_ack: bool = False
    encrypted_virtual_urls_present: bool | None = None

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Z0-9_]{1,96}", self.classification)
            or not re.fullmatch(r"[A-Z0-9_]{1,64}", self.boundary)
            or (
                self.http_status is not None
                and (
                    type(self.http_status) is not int
                    or not 100 <= self.http_status <= 599
                )
            )
            or (
                self.response_clmid is not None
                and not re.fullmatch(
                    r"[A-Za-z0-9_]{1,128}", self.response_clmid
                )
            )
            or (
                self.result_code is not None
                and not re.fullmatch(r"[0-9]{1,16}", self.result_code)
            )
            or (
                self.official_reason is not None
                and not re.fullmatch(
                    r"[A-Z0-9_]{1,128}", self.official_reason
                )
            )
            or type(self.response_matched_ack) is not bool
            or (
                self.encrypted_virtual_urls_present is not None
                and type(self.encrypted_virtual_urls_present) is not bool
            )
        ):
            raise ValueError("invalid_auth_diagnostic")

    def safe_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "boundary": self.boundary,
            "httpStatus": self.http_status,
            "sCLMID": self.response_clmid,
            "sResultCode": self.result_code,
            "officialReason": self.official_reason,
            "responseMatchedCLMAuthLoginAck": self.response_matched_ack,
            "encryptedVirtualUrlsPresent": (
                self.encrypted_virtual_urls_present
            ),
        }


@dataclass(frozen=True)
class QuoteLevel:
    price: float
    volume: float | None


@dataclass(frozen=True)
class NormalizationIssue:
    """One bounded, value-free field degradation diagnostic."""

    field: str
    reason: str

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[A-Z0-9_]{1,64}", self.field) is None
            or re.fullmatch(r"[A-Z0-9_]{1,64}", self.reason) is None
        ):
            raise ValueError("invalid_normalization_issue")


@dataclass(frozen=True)
class TachibanaObservation:
    provider: str
    endpoint_category: str
    symbol: str
    source_timestamp: datetime | None
    source_timestamp_precision: str
    received_timestamp: datetime
    fresh_until: datetime | None
    freshness: Freshness
    market_status: MarketStatus
    realtime_classification: str
    fields: Mapping[str, float | str | None]
    field_availability: Mapping[str, bool]
    market_data_timestamp: datetime | None = None
    market_data_date_verified: bool = False
    normalization_issues: tuple[NormalizationIssue, ...] = ()
    asks: tuple[QuoteLevel, ...] = ()
    bids: tuple[QuoteLevel, ...] = ()
    request_result: str = "SUCCESS"
    error_classification: ErrorClass = ErrorClass.NONE
    normalization_version: str = "tachibana-v4r10-normalization-v1"
    authority_state: AuthorityState = AuthorityState.SHADOW_NON_AUTHORITATIVE

    def __post_init__(self) -> None:
        if (
            self.provider != "TACHIBANA"
            or self.endpoint_category not in {"PRICE", "EVENT"}
            or not isinstance(self.symbol, str)
            or not re.fullmatch(r"[0-9ACDFGHJKLMNPRSTUWXY]{4}", self.symbol)
            or not any(character.isdigit() for character in self.symbol)
            or not isinstance(self.freshness, Freshness)
            or not isinstance(self.market_status, MarketStatus)
            or self.received_timestamp.tzinfo is None
            or self.received_timestamp.utcoffset() is None
            or not isinstance(self.fields, Mapping)
            or not isinstance(self.field_availability, Mapping)
            or set(self.fields) != set(self.field_availability)
            or any(type(value) is not bool
                   for value in self.field_availability.values())
            or type(self.market_data_date_verified) is not bool
            or not isinstance(self.normalization_issues, tuple)
            or len(self.normalization_issues) > 16
            or any(
                not isinstance(issue, NormalizationIssue)
                for issue in self.normalization_issues
            )
            or not isinstance(self.asks, tuple)
            or not isinstance(self.bids, tuple)
            or any(not isinstance(level, QuoteLevel)
                   for level in self.asks + self.bids)
        ):
            raise ValueError("invalid_tachibana_observation")
        if self.source_timestamp is None:
            if self.source_timestamp_precision != "UNAVAILABLE":
                raise ValueError("invalid_tachibana_timestamp_precision")
        elif (
            self.source_timestamp.tzinfo is None
            or self.source_timestamp.utcoffset() is None
            or self.source_timestamp_precision not in {"MINUTE", "SECOND"}
        ):
            raise ValueError("invalid_tachibana_timestamp_precision")
        if self.market_data_timestamp is not None and (
            self.market_data_timestamp.tzinfo is None
            or self.market_data_timestamp.utcoffset() is None
        ):
            raise ValueError("invalid_tachibana_market_data_timestamp")
        if self.fresh_until is not None and (
            self.fresh_until.tzinfo is None or self.fresh_until.utcoffset() is None
        ):
            raise ValueError("invalid_tachibana_fresh_until")
        if self.freshness in {Freshness.FRESH, Freshness.DELAYED}:
            if (
                self.market_data_timestamp is None
                or not self.market_data_date_verified
                or self.fresh_until is None
                or self.fresh_until < self.received_timestamp
            ):
                raise ValueError("invalid_tachibana_freshness_window")
        elif self.fresh_until is not None:
            raise ValueError("invalid_tachibana_freshness_window")
        # ``frozen=True`` does not freeze nested dictionaries.  Provider truth
        # must not be mutable after validation because downstream evidence is
        # derived from these exact values.
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))
        object.__setattr__(
            self,
            "field_availability",
            MappingProxyType(dict(self.field_availability)),
        )


@dataclass
class Diagnostics:
    requests_last_minute: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limited_requests: int = 0
    last_success_at: datetime | None = None
    last_error_class: ErrorClass = ErrorClass.NONE
    session_started_at: datetime | None = None
    websocket_connected: bool = False
    health: ProviderHealth = ProviderHealth.UNAVAILABLE

    def public_snapshot(self, now: datetime) -> dict[str, object]:
        session_age = None
        if self.session_started_at is not None:
            session_age = max(0, int((now - self.session_started_at).total_seconds()))
        return {
            "requestsPerMinute": self.requests_last_minute,
            "successfulRequests": self.successful_requests,
            "failedRequests": self.failed_requests,
            "rateLimitedRequests": self.rate_limited_requests,
            "lastSuccessAt": (self.last_success_at.isoformat()
                              if self.last_success_at else None),
            "lastErrorClass": self.last_error_class.value,
            "sessionAgeSeconds": session_age,
            "webSocketConnected": self.websocket_connected,
            "health": self.health.value,
        }


@dataclass
class VirtualEndpoints:
    """Credential-equivalent session URLs; intentionally opaque and RAM-only."""

    request: str = field(repr=False)
    master: str = field(repr=False)
    price: str = field(repr=False)
    event: str = field(repr=False)
    event_websocket: str = field(repr=False)

    def clear(self) -> None:
        self.request = ""
        self.master = ""
        self.price = ""
        self.event = ""
        self.event_websocket = ""

    def __repr__(self) -> str:
        return "VirtualEndpoints(<redacted>)"


class TachibanaError(RuntimeError):
    """A bounded error whose message is always a classification, never provider text."""

    def __init__(self, classification: ErrorClass):
        self.classification = classification
        super().__init__(classification.value)
