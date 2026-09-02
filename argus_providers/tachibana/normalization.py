"""Provider-truth normalization for v4r10 PRICE/EVENT market fields."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
import re
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .models import (
    ErrorClass,
    Freshness,
    MarketStatus,
    NormalizationIssue,
    QuoteLevel,
    TachibanaError,
    TachibanaObservation,
)


NORMALIZATION_VERSION = "tachibana-v4r10-normalization-v1"
TOKYO = ZoneInfo("Asia/Tokyo")
_FIELD_MAP: Mapping[str, str] = MappingProxyType({
    "current_price": "pDPP",
    "previous_close": "pPRP",
    "change_absolute": "pDYWP",
    "change_percent": "pDYRP",
    "open": "pDOP",
    "high": "pDHP",
    "low": "pDLP",
    "volume": "pDV",
    "turnover": "pDJ",
    "vwap": "pVWAP",
    "best_ask": "pQAP",
    "best_bid": "pQBP",
    "market_ask_volume": "pAAV",
    "market_bid_volume": "pABV",
    # pAV/pBV are the quantities at the best ask/bid quote, not aggregates
    # across all displayed levels.
    "best_ask_volume": "pAV",
    "best_bid_volume": "pBV",
    "sell_over": "pQOV",
    "buy_under": "pQUV",
})
_NULL_MARKERS = frozenset({"", "-", "--", "null", "none"})
_SYMBOL = re.compile(r"^[0-9ACDFGHJKLMNPRSTUWXY]{4}$")


def _record_issue(
    issues: list[NormalizationIssue] | None, field: str, reason: str
) -> None:
    if issues is None:
        raise TachibanaError(ErrorClass.NORMALIZATION)
    if len(issues) < 16:
        token = re.sub(r"[^A-Za-z0-9]+", "_", field).strip("_").upper()
        issues.append(NormalizationIssue(token[:64], reason))


def _number(
    value: Any, *, field: str, issues: list[NormalizationIssue] | None
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        _record_issue(issues, field, "INVALID_NUMBER")
        return None
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.lower() in _NULL_MARKERS:
            return None
        value = stripped
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        _record_issue(issues, field, "INVALID_NUMBER")
        return None
    if not math.isfinite(parsed):
        _record_issue(issues, field, "NONFINITE_NUMBER")
        return None
    return parsed


def _source_timestamp(
    raw: Any, market_date: date | None, *, market_date_verified: bool,
    issues: list[NormalizationIssue] | None,
) -> tuple[datetime | None, str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "UNAVAILABLE"
    text = str(raw).strip()
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d %H:%M:%S"):
        try:
            value = datetime.strptime(text, pattern).replace(
                tzinfo=TOKYO
            ).astimezone(timezone.utc)
            return value, "SECOND"
        except ValueError:
            pass
    parsed_time: time | None = None
    precision = "UNAVAILABLE"
    for pattern, candidate_precision in (
        ("%H:%M:%S", "SECOND"), ("%H%M%S", "SECOND"),
        ("%H:%M", "MINUTE"), ("%H%M", "MINUTE"),
    ):
        try:
            parsed_time = datetime.strptime(text, pattern).time()
            precision = candidate_precision
            break
        except ValueError:
            pass
    if parsed_time is None:
        _record_issue(issues, "TDPP_T", "INVALID_TIME")
        return None, "UNAVAILABLE"
    # A time-of-day has no date semantics. Validate the provider syntax above,
    # but never attach the caller's wall date unless it was established by a
    # separately verified exchange session/calendar. This both surfaces corrupt
    # wire data and prevents prior-session values from being relabelled current.
    if market_date is None or not market_date_verified:
        return None, "UNAVAILABLE"
    return (
        datetime.combine(market_date, parsed_time, TOKYO).astimezone(timezone.utc),
        precision,
    )


def _book(
    row: Mapping[str, Any], side: str,
    issues: list[NormalizationIssue] | None,
) -> tuple[QuoteLevel, ...]:
    levels: list[QuoteLevel] = []
    if side == "ask":
        pairs = ((f"pGAP{level}", f"pGAV{level}") for level in range(1, 11))
        reverse = False
    else:
        pairs = ((f"pGBP{level}", f"pGBV{level}") for level in range(1, 11))
        reverse = True
    for price_field, volume_field in pairs:
        price = _number(row.get(price_field), field=price_field, issues=issues)
        volume = _number(
            row.get(volume_field), field=volume_field, issues=issues
        )
        if price is None:
            if volume is not None:
                _record_issue(issues, volume_field, "ORPHAN_VOLUME")
            continue
        if price <= 0 or (volume is not None and volume < 0):
            _record_issue(issues, price_field, "OUT_OF_RANGE")
            continue
        levels.append(QuoteLevel(price=price, volume=volume))
    # Do not trust wire/order numbering.  Normalize best-to-far explicitly and
    # reject duplicate prices, which otherwise make diff application ambiguous.
    if len({item.price for item in levels}) != len(levels):
        _record_issue(issues, f"{side}_depth", "DUPLICATE_PRICE")
        return ()
    return tuple(sorted(levels, key=lambda item: item.price, reverse=reverse))


def normalize_market_price(
    row: Mapping[str, Any],
    *,
    received_at: datetime,
    market_date: date | None,
    market_status: MarketStatus = MarketStatus.UNKNOWN,
    market_date_verified: bool = False,
    market_data_timestamp: datetime | None = None,
    market_data_date_verified: bool | None = None,
    degrade_noncritical: bool = False,
    fresh_for_seconds: int = 15,
    endpoint_category: str = "PRICE",
) -> TachibanaObservation:
    if not isinstance(row, Mapping):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    # PRICE returns sIssueCode; EVENT rows receive the same field only after
    # trusted subscription-row association in EventSnapshotAssembler.
    symbol = row.get("sIssueCode")
    if (
        not isinstance(symbol, str)
        or not _SYMBOL.fullmatch(symbol)
        or not any(character.isdigit() for character in symbol)
    ):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    if received_at.tzinfo is None:
        raise TachibanaError(ErrorClass.NORMALIZATION)
    if (
        not isinstance(market_status, MarketStatus)
        or type(market_date_verified) is not bool
        or market_data_timestamp is not None
        and (
            not isinstance(market_data_timestamp, datetime)
            or market_data_timestamp.tzinfo is None
            or market_data_timestamp.utcoffset() is None
        )
        or market_data_date_verified is not None
        and type(market_data_date_verified) is not bool
        or type(degrade_noncritical) is not bool
        or not 1 <= fresh_for_seconds <= 60
        or endpoint_category not in {"PRICE", "EVENT"}
    ):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    issues: list[NormalizationIssue] | None = [] if degrade_noncritical else None
    received = received_at.astimezone(timezone.utc)
    source, source_precision = _source_timestamp(
        row.get("tDPP:T"), market_date,
        market_date_verified=market_date_verified,
        issues=issues,
    )
    if source is not None and source > received + timedelta(seconds=5):
        _record_issue(issues, "TDPP_T", "FUTURE_TIME")
        source = None
        source_precision = "UNAVAILABLE"
    data_time = (
        market_data_timestamp.astimezone(timezone.utc)
        if market_data_timestamp is not None else source
    )
    data_date_verified = (
        market_date_verified
        if market_data_date_verified is None
        else market_data_date_verified
    )
    if data_time is not None and data_time > received + timedelta(seconds=5):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    age = (received - data_time).total_seconds() if data_time is not None else None
    freshness = (
        Freshness.FRESH
        if (
            data_date_verified
            and age is not None
            and age <= fresh_for_seconds
        )
        else Freshness.DELAYED
        if (
            data_date_verified
            and age is not None
            and age <= 20 * 60
        )
        else Freshness.STALE
        if source is not None
        else Freshness.UNAVAILABLE
    )
    fresh_until = (
        data_time + timedelta(seconds=fresh_for_seconds)
        if data_time is not None and freshness == Freshness.FRESH
        else data_time + timedelta(minutes=20)
        if data_time is not None and freshness == Freshness.DELAYED
        else None
    )
    fields: dict[str, float | str | None] = {}
    availability: dict[str, bool] = {}
    for normalized_name, provider_field in _FIELD_MAP.items():
        value = _number(
            row.get(provider_field), field=provider_field, issues=issues
        )
        fields[normalized_name] = value
        availability[normalized_name] = value is not None
    for positive in (
        "current_price", "previous_close", "open", "high", "low",
        "vwap", "best_ask", "best_bid",
    ):
        value = fields[positive]
        if isinstance(value, float) and value <= 0:
            _record_issue(issues, _FIELD_MAP[positive], "OUT_OF_RANGE")
            fields[positive] = None
            availability[positive] = False
    for nonnegative in (
        "volume", "turnover", "market_ask_volume", "market_bid_volume",
        "best_ask_volume", "best_bid_volume", "sell_over", "buy_under",
    ):
        value = fields[nonnegative]
        if isinstance(value, float) and value < 0:
            _record_issue(issues, _FIELD_MAP[nonnegative], "OUT_OF_RANGE")
            fields[nonnegative] = None
            availability[nonnegative] = False
    o, h, low, close = (
        fields[name] for name in ("open", "high", "low", "current_price")
    )
    if all(isinstance(item, float) for item in (o, h, low, close)) and (
        h < max(o, close) or low > min(o, close) or h < low
    ):
        _record_issue(issues, "OHLC", "INCONSISTENT_RANGE")
        for name in ("open", "high", "low", "current_price"):
            fields[name] = None
            availability[name] = False
    asks = _book(row, "ask", issues)
    bids = _book(row, "bid", issues)
    return TachibanaObservation(
        provider="TACHIBANA",
        endpoint_category=endpoint_category,
        symbol=symbol,
        source_timestamp=source,
        source_timestamp_precision=source_precision,
        received_timestamp=received,
        fresh_until=fresh_until,
        freshness=freshness,
        market_status=market_status,
        realtime_classification=(
            "CURRENT_MARKET_SNAPSHOT" if endpoint_category == "PRICE"
            else "BEST_EFFORT_THINNED_REALTIME"
        ),
        fields=fields,
        field_availability=availability,
        market_data_timestamp=data_time,
        market_data_date_verified=data_date_verified,
        normalization_issues=tuple(issues or ()),
        asks=asks,
        bids=bids,
        normalization_version=NORMALIZATION_VERSION,
    )
