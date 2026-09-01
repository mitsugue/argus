"""Shadow-only bridge from provider truth to canonical ARGUS evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import argus_market_data_truth as market_truth

from .models import Freshness, TachibanaObservation


ADAPTER_ID = "tachibana-live-sensor-v1"
ADAPTER_SCHEMA_VERSION = "tachibana-v4r10-adapter-v1"
_FRESHNESS = MappingProxyType({
    Freshness.FRESH: market_truth.FRESH,
    Freshness.DELAYED: market_truth.DELAYED,
    Freshness.STALE: market_truth.STALE,
    Freshness.UNAVAILABLE: market_truth.UNAVAILABLE,
})


def to_canonical_observations(
    observation: TachibanaObservation,
) -> list[dict[str, Any]]:
    """Adapt without granting authority or retaining raw provider payloads."""
    received = observation.received_timestamp.astimezone(timezone.utc).isoformat()
    observed = (
        observation.source_timestamp.astimezone(timezone.utc).isoformat()
        if observation.source_timestamp is not None else None
    )
    effective_freshness = (
        observation.freshness
        if observation.market_status.value == "OPEN"
        else Freshness.STALE
        if observation.source_timestamp is not None
        else Freshness.UNAVAILABLE
    )
    fresh_until = (
        observation.fresh_until.astimezone(timezone.utc).isoformat()
        if (
            observation.fresh_until is not None
            and effective_freshness in {Freshness.FRESH, Freshness.DELAYED}
        )
        else None
    )
    shared = {
        "instrument_id": f"JP:TSE:{observation.symbol}",
        "symbol": observation.symbol,
        "market": "JP",
        "asset_type": "EQUITY",
        "provider": "tachibana",
        "adapter": ADAPTER_ID,
        "source_ref": "tachibana:v4r10:live-sensor",
        "received_at": received,
        "known_at": received,
        "freshness": _FRESHNESS[effective_freshness],
        "currency": "JPY",
        "provenance": {
            "endpointCategory": observation.endpoint_category,
            "realtimeClassification": observation.realtime_classification,
            "marketStatus": observation.market_status.value,
            "sourceTimestampPrecision": observation.source_timestamp_precision,
            "normalizationVersion": observation.normalization_version,
            "authorityState": observation.authority_state.value,
            "availableFields": sorted(
                key for key, available in observation.field_availability.items()
                if available
            )[:16],
            "rawRetained": 0,
        },
    }
    current = observation.fields.get("current_price")
    quote_values = {
        canonical: observation.fields.get(provider_name)
        for canonical, provider_name in (
            ("price", "current_price"),
            ("previousClose", "previous_close"),
            ("changeAbs", "change_absolute"),
            ("changePct", "change_percent"),
            ("volume", "volume"),
        )
        if observation.fields.get(provider_name) is not None
    }
    if current is None or observed is None:
        canonical = market_truth.build_observation(
            **shared,
            fact_type="QUOTE",
            values={},
            observed_at=None,
            completeness=market_truth.MISSING,
            missing_fields=("price",),
            fresh_until=None,
        )
    else:
        canonical = market_truth.build_observation(
            **shared,
            fact_type="QUOTE",
            values=quote_values,
            observed_at=observed,
            completeness=market_truth.COMPLETE,
            fresh_until=fresh_until,
        )
    # pDOP/pDHP/pDLP/pDPP/pDV in a live snapshot are cumulative session
    # values, not a provider-defined interval bar. Emitting OHLCV_BAR would
    # invent interval semantics.
    return [canonical]


def adapter_normalizer(payload: Any, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, TachibanaObservation):
        return {
            "observations": [],
            "errors": [{
                "code": "tachibana_normalization_input_invalid",
                "instrumentId": None,
                "retryable": False,
            }],
        }
    try:
        return {"observations": to_canonical_observations(payload), "errors": []}
    except (TypeError, ValueError, OverflowError):
        return {
            "observations": [],
            "errors": [{
                "code": "tachibana_canonical_adaptation_failed",
                "instrumentId": f"JP:TSE:{payload.symbol}",
                "retryable": False,
            }],
        }


def register_shadow_adapter(
    registry: market_truth.ProviderAdapterRegistry,
) -> None:
    registry.register(
        market_truth.AdapterSpec(
            adapter_id=ADAPTER_ID,
            provider="tachibana",
            markets=("JP",),
            fact_types=("QUOTE",),
            schema_version=ADAPTER_SCHEMA_VERSION,
        ),
        adapter_normalizer,
    )


def build_live_pressure_evidence(
    observations: Sequence[TachibanaObservation],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Retain only bounded derived judgment metadata, never raw quote streams."""
    bounded = tuple(observations[-120:])
    def unavailable(latest: TachibanaObservation | None = None) -> dict[str, Any]:
        return {
            "kind": "LIVE_PRESSURE",
            "classification": "UNAVAILABLE",
            "confidence": 0.0,
            "calculationVersion": "tachibana-live-pressure-v2",
            "provider": "TACHIBANA",
            "instrumentId": (
                f"JP:TSE:{latest.symbol}" if latest is not None else None
            ),
            "symbol": latest.symbol if latest is not None else None,
            "sourceTimestamp": (
                latest.source_timestamp.astimezone(timezone.utc).isoformat()
                if latest is not None and latest.source_timestamp else None
            ),
            "receivedTimestamp": (
                latest.received_timestamp.astimezone(timezone.utc).isoformat()
                if latest is not None else None
            ),
            "authorityState": (
                latest.authority_state.value if latest is not None
                else "SHADOW_NON_AUTHORITATIVE"
            ),
            "rawRetained": False,
        }
    if not bounded:
        return unavailable()
    latest = bounded[-1]
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        any(item.symbol != latest.symbol for item in bounded)
        or latest.freshness != Freshness.FRESH
        or latest.market_status.value != "OPEN"
        or latest.fresh_until is None
        or latest.fresh_until < current
    ):
        return unavailable(latest)
    bid = latest.fields.get("best_bid_volume")
    ask = latest.fields.get("best_ask_volume")
    classification = "UNAVAILABLE"
    confidence = 0.0
    if (
        isinstance(bid, (int, float)) and not isinstance(bid, bool)
        and isinstance(ask, (int, float)) and not isinstance(ask, bool)
        and bid + ask > 0
    ):
        imbalance = (bid - ask) / (bid + ask)
        classification = (
            "BUY_PRESSURE" if imbalance >= 0.15
            else "SELL_PRESSURE" if imbalance <= -0.15
            else "BALANCED"
        )
        confidence = round(min(1.0, abs(imbalance)), 6)
    return {
        "kind": "LIVE_PRESSURE",
        "classification": classification,
        "confidence": confidence,
        "calculationVersion": "tachibana-live-pressure-v2",
        "provider": "TACHIBANA",
        "instrumentId": f"JP:TSE:{latest.symbol}",
        "symbol": latest.symbol,
        "sourceTimestamp": (
            latest.source_timestamp.astimezone(timezone.utc).isoformat()
            if latest.source_timestamp else None
        ),
        "receivedTimestamp": latest.received_timestamp.astimezone(timezone.utc).isoformat(),
        "authorityState": latest.authority_state.value,
        "rawRetained": False,
    }
