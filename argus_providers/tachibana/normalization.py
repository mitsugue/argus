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


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.lower() in _NULL_MARKERS:
            return None
        value = stripped
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise TachibanaError(ErrorClass.NORMALIZATION) from None
    if not math.isfinite(parsed):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    return parsed


def _source_timestamp(
    raw: Any, market_date: date | None, *, market_date_verified: bool
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
        raise TachibanaError(ErrorClass.NORMALIZATION)
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


def _book(row: Mapping[str, Any], side: str) -> tuple[QuoteLevel, ...]:
    levels: list[QuoteLevel] = []
    if side == "ask":
        pairs = ((f"pGAP{level}", f"pGAV{level}") for level in range(1, 11))
        reverse = False
    else:
        pairs = ((f"pGBP{level}", f"pGBV{level}") for level in range(1, 11))
        reverse = True
    for price_field, volume_field in pairs:
        price = _number(row.get(price_field))
        volume = _number(row.get(volume_field))
        if price is None:
            if volume is not None:
                raise TachibanaError(ErrorClass.NORMALIZATION)
            continue
        if price <= 0 or (volume is not None and volume < 0):
            raise TachibanaError(ErrorClass.NORMALIZATION)
        levels.append(QuoteLevel(price=price, volume=volume))
    # Do not trust wire/order numbering.  Normalize best-to-far explicitly and
    # reject duplicate prices, which otherwise make diff application ambiguous.
    if len({item.price for item in levels}) != len(levels):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    return tuple(sorted(levels, key=lambda item: item.price, reverse=reverse))


def normalize_market_price(
    row: Mapping[str, Any],
    *,
    received_at: datetime,
    market_date: date | None,
    market_status: MarketStatus = MarketStatus.UNKNOWN,
    market_date_verified: bool = False,
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
        or not 1 <= fresh_for_seconds <= 60
        or endpoint_category not in {"PRICE", "EVENT"}
    ):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    received = received_at.astimezone(timezone.utc)
    source, source_precision = _source_timestamp(
        row.get("tDPP:T"), market_date,
        market_date_verified=market_date_verified,
    )
    if source is not None and source > received + timedelta(seconds=5):
        raise TachibanaError(ErrorClass.NORMALIZATION)
    age = (received - source).total_seconds() if source is not None else None
    freshness = (
        Freshness.FRESH
        if (
            market_date_verified
            and market_status == MarketStatus.OPEN
            and age is not None
            and age <= fresh_for_seconds
        )
        else Freshness.DELAYED
        if (
            market_date_verified
            and market_status == MarketStatus.OPEN
            and age is not None
            and age <= 20 * 60
        )
        else Freshness.STALE
        if source is not None
        else Freshness.UNAVAILABLE
    )
    fresh_until = (
        source + timedelta(seconds=fresh_for_seconds)
        if source is not None and freshness == Freshness.FRESH
        else source + timedelta(minutes=20)
        if source is not None and freshness == Freshness.DELAYED
        else None
    )
    fields: dict[str, float | str | None] = {}
    availability: dict[str, bool] = {}
    for normalized_name, provider_field in _FIELD_MAP.items():
        value = _number(row.get(provider_field))
        fields[normalized_name] = value
        availability[normalized_name] = value is not None
    for positive in (
        "current_price", "previous_close", "open", "high", "low",
        "vwap", "best_ask", "best_bid",
    ):
        value = fields[positive]
        if isinstance(value, float) and value <= 0:
            raise TachibanaError(ErrorClass.NORMALIZATION)
    for nonnegative in (
        "volume", "turnover", "market_ask_volume", "market_bid_volume",
        "best_ask_volume", "best_bid_volume", "sell_over", "buy_under",
    ):
        value = fields[nonnegative]
        if isinstance(value, float) and value < 0:
            raise TachibanaError(ErrorClass.NORMALIZATION)
    o, h, low, close = (
        fields[name] for name in ("open", "high", "low", "current_price")
    )
    if all(isinstance(item, float) for item in (o, h, low, close)) and (
        h < max(o, close) or low > min(o, close) or h < low
    ):
        raise TachibanaError(ErrorClass.NORMALIZATION)
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
        asks=_book(row, "ask"),
        bids=_book(row, "bid"),
        normalization_version=NORMALIZATION_VERSION,
    )
