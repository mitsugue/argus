"""Past-only descriptive inputs for the Japan market analysis engine.

No action authority, provider calls, storage, or predictive probabilities.
Existing decision rules are consumers of their original evidence, not these
additional descriptive calculations.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable, Mapping

from jp_market_engine import point_in_time_rows

SCHEMA_VERSION = "jp-market-dynamics-v1"
RATIO_METHOD = "symmetric-two-factor-ratio-v1"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _period(row: Mapping[str, Any]) -> str:
    return str(row.get("periodEnd") or row.get("date") or "")[:10]


def decompose_margin_ratio(previous: Mapping[str, Any],
                           current: Mapping[str, Any]) -> dict[str, Any]:
    """Split B/S change symmetrically, without assigning a causal order.

    Balances must describe the same instrument, balance kind and unit. A zero
    long balance is legitimate; a zero short balance has no finite ratio.
    Changes over a missing week are not labelled one-week changes.
    """
    result: dict[str, Any] = {
        "method": RATIO_METHOD, "status": "UNAVAILABLE", "reason": None,
        "previousRatio": None, "currentRatio": None, "ratioChange": None,
        "longContribution": None, "shortContribution": None,
        "longBalanceChange": None, "shortBalanceChange": None,
        "longBalanceChangePct": None, "shortBalanceChangePct": None,
        "periodDays": None, "isOneWeekChange": False,
        "observedCoveringOrders": False, "actionAuthority": False,
        "validationStatus": "DESCRIPTIVE_NOT_PREDICTIVE",
    }
    for key in ("instrumentId", "balanceKind", "unit"):
        if not previous.get(key) or previous.get(key) != current.get(key):
            return {**result, "reason": "incompatible_" + key}
    try:
        gap = (date.fromisoformat(_period(current)) -
               date.fromisoformat(_period(previous))).days
    except ValueError:
        return {**result, "reason": "invalid_period"}
    if gap <= 0:
        return {**result, "reason": "non_increasing_period"}
    b0, s0, b1, s1 = (_number(row.get(key)) for row, key in (
        (previous, "longBalance"), (previous, "shortBalance"),
        (current, "longBalance"), (current, "shortBalance")))
    if any(value is None for value in (b0, s0, b1, s1)):
        return {**result, "reason": "missing_or_nonfinite_balance"}
    if min(b0, b1) < 0 or min(s0, s1) <= 0:
        return {**result, "reason": "invalid_balance_or_zero_denominator"}
    try:
        long_part = (b1 - b0) * (1 / s0 + 1 / s1) / 2
        short_part = (b0 / 2 + b1 / 2) * (1 / s1 - 1 / s0)
        values = {
            "previousRatio": b0 / s0, "currentRatio": b1 / s1,
            "ratioChange": b1 / s1 - b0 / s0,
            "longContribution": long_part, "shortContribution": short_part,
            "longBalanceChange": b1 - b0, "shortBalanceChange": s1 - s0,
            "longBalanceChangePct": (b1 / b0 - 1) * 100 if b0 > 0 else None,
            "shortBalanceChangePct": (s1 / s0 - 1) * 100,
        }
    except (OverflowError, ZeroDivisionError):
        return {**result, "reason": "numeric_range_exceeded"}
    if any(not math.isfinite(v) for v in values.values() if v is not None):
        return {**result, "reason": "numeric_range_exceeded"}
    return {**result, **values, "status": "AVAILABLE", "periodDays": gap,
            "isOneWeekChange": gap == 7}


def credit_dynamics(rows: Iterable[Mapping[str, Any]], *, cutoff: str,
                    instrument_id: str, balance_kind: str,
                    long_series: str, short_series: str) -> dict[str, Any]:
    """Join matching observations before calculating changes.

    Call separately for two-market margin, instrument margin and securities
    finance balances. Never backfill one side from an earlier period. Preserve
    raw provenance and the temporal proof; availability filtering alone is not
    proof that archived data represent unrevised historical vintages.
    """
    if not instrument_id or not balance_kind or not long_series or not short_series \
            or long_series == short_series:
        raise ValueError("explicit_distinct_credit_series_required")
    scoped = [dict(row) for row in rows if isinstance(row, Mapping) and
              str(row.get("instrumentId") or "MARKET") == instrument_id and
              (row.get("seriesId") or row.get("field")) in (long_series, short_series)]
    visible, proof = point_in_time_rows(scoped, cutoff)
    by_period: dict[str, dict[str, Any]] = {}
    for row in visible:
        side = "long" if (row.get("seriesId") or row.get("field")) == long_series else "short"
        by_period.setdefault(_period(row), {})[side] = row
    snapshots = []
    for period, sides in sorted(by_period.items()):
        long_row, short_row = sides.get("long", {}), sides.get("short", {})
        unit = long_row.get("unit")
        compatible = bool(unit) and unit == short_row.get("unit")
        long_value, short_value = _number(long_row.get("value")), _number(short_row.get("value"))
        valid = (compatible and long_value is not None and long_value >= 0 and
                 short_value is not None and short_value > 0)
        ratio = long_value / short_value if valid else None
        valid = valid and ratio is not None and math.isfinite(ratio)
        snapshots.append({
            "instrumentId": instrument_id, "balanceKind": balance_kind,
            "periodEnd": period, "unit": unit if compatible else None,
            "longBalance": long_value, "shortBalance": short_value,
            "ratio": ratio if valid else None,
            "status": "AVAILABLE" if valid else "INCOMPLETE_OR_INVALID",
            "sourceRows": {"long": long_row or None, "short": short_row or None},
        })
    current = snapshots[-1] if snapshots else None
    previous = snapshots[-2] if len(snapshots) > 1 else None
    change = (decompose_margin_ratio(previous, current) if previous and current
              else {"status": "UNAVAILABLE", "reason": "two_periods_required"})
    return {
        "schemaVersion": SCHEMA_VERSION, "informationCutoff": cutoff,
        "instrumentId": instrument_id, "balanceKind": balance_kind,
        "status": current["status"] if current else "MISSING",
        "current": current, "previous": previous, "change": change,
        "observationCount": len(snapshots), "pointInTimeProof": proof,
        "historicalVintageVerified": False,
        "actionAuthority": False, "observedCoveringOrders": False,
        "predictiveProbability": None,
    }


def normalize_valuation_loss(value: Any, *, sign_convention: str,
                             unit: str) -> dict[str, Any]:
    """Return positive-as-loss percentage points with explicit source semantics."""
    number = _number(value)
    reason = ("missing_or_nonfinite_value" if number is None else
              "unknown_sign_convention" if sign_convention not in
              {"positive_is_loss", "negative_is_loss"} else
              "unknown_unit" if unit not in {"PERCENT", "FRACTION"} else None)
    normalized = (number * (100 if unit == "FRACTION" else 1) *
                  (-1 if sign_convention == "negative_is_loss" else 1)
                  if reason is None else None)
    if normalized is not None and not math.isfinite(normalized):
        reason, normalized = "numeric_range_exceeded", None
    return {"status": "AVAILABLE" if reason is None else "UNAVAILABLE",
            "reason": reason, "sourceValue": number,
            "sourceSignConvention": sign_convention, "sourceUnit": unit,
            "lossPct": normalized, "outputSignConvention": "positive_is_loss",
            "actionAuthority": False}
