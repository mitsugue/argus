"""Explicit shadow mismatch classification for overlapping provider facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .models import TachibanaObservation


class MismatchClass(str, Enum):
    TIMESTAMP_SKEW = "TIMESTAMP_SKEW"
    DELAY_DIFFERENCE = "DELAY_DIFFERENCE"
    SESSION_DIFFERENCE = "SESSION_DIFFERENCE"
    FIELD_SEMANTICS = "FIELD_SEMANTICS"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    MARKET_STATE = "MARKET_STATE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    NORMALIZATION_ERROR = "NORMALIZATION_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Tolerance:
    absolute: float
    relative: float


DEFAULT_TOLERANCES: Mapping[str, Tolerance] = MappingProxyType({
    # Independently sampled live feeds need a small temporal/tick allowance.
    # One yen or 10 bp is still narrow enough to expose a material divergence.
    "current_price": Tolerance(absolute=1.0, relative=0.001),
    "previous_close": Tolerance(absolute=0.01, relative=0.0001),
    "open": Tolerance(absolute=0.01, relative=0.0001),
    "high": Tolerance(absolute=0.01, relative=0.0001),
    "low": Tolerance(absolute=0.01, relative=0.0001),
    # Both feeds can be captured between lots; tolerate one board lot or 2%.
    "volume": Tolerance(absolute=100.0, relative=0.02),
})


@dataclass(frozen=True)
class Mismatch:
    field: str
    classification: MismatchClass
    absolute_difference: float | None
    relative_difference: float | None


def compare_shadow(
    tachibana: TachibanaObservation,
    trusted_fields: Mapping[str, float | int | None],
    *,
    trusted_timestamp: datetime | None,
    tolerances: Mapping[str, Tolerance] = DEFAULT_TOLERANCES,
    corporate_action_known: bool = False,
    session_aligned: bool = True,
) -> tuple[Mismatch, ...]:
    mismatches: list[Mismatch] = []
    if tachibana.source_timestamp and trusted_timestamp:
        skew = abs((
            tachibana.source_timestamp
            - trusted_timestamp.astimezone(timezone.utc)
        ).total_seconds())
        if skew > 20 * 60:
            mismatches.append(Mismatch(
                "source_timestamp", MismatchClass.TIMESTAMP_SKEW, skew, None
            ))
    for field, tolerance in tolerances.items():
        live = tachibana.fields.get(field)
        trusted = trusted_fields.get(field)
        if live is None or trusted is None:
            continue
        if isinstance(live, bool) or isinstance(trusted, bool) or not isinstance(
            live, (int, float)
        ) or not isinstance(trusted, (int, float)):
            mismatches.append(Mismatch(field, MismatchClass.FIELD_SEMANTICS, None, None))
            continue
        difference = abs(float(live) - float(trusted))
        denominator = max(abs(float(live)), abs(float(trusted)), 1e-12)
        relative = difference / denominator
        if difference <= tolerance.absolute or relative <= tolerance.relative:
            continue
        mismatch_class = (
            MismatchClass.CORPORATE_ACTION if corporate_action_known
            else MismatchClass.SESSION_DIFFERENCE if not session_aligned
            else MismatchClass.DELAY_DIFFERENCE
            if tachibana.source_timestamp and trusted_timestamp
            and abs((
                tachibana.source_timestamp
                - trusted_timestamp.astimezone(timezone.utc)
            ).total_seconds()) > 60
            else MismatchClass.UNKNOWN
        )
        mismatches.append(Mismatch(field, mismatch_class, difference, relative))
    return tuple(mismatches)
