"""Explicit scales and descriptive scenario paths for the Japan index.

The ensemble is a research forecast, not a calibrated probability. A reference
frequency is not an accuracy claim. The price scale requires definition-aligned
index valuation; ETF or capitalization-weighted PER is not a substitute.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Sequence

from jp_market_engine import _instant

VALUATION_BASIS = "NIKKEI_225_INDEX_BASED_PER"
METHOD = "jp-index-analog-median-research-v1"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def index_valuation_scale(valuation: Mapping[str, Any] | None, *, cutoff: str,
                          anchor_date: str, anchor_price: float) -> dict[str, Any]:
    result = {"status": "UNAVAILABLE", "reason": "missing_index_valuation",
              "instrumentId": "NIKKEI_225_INDEX", "currency": "JPY",
              "eps": None, "per": None, "anchorPrice": None}
    if not valuation:
        return result
    if valuation.get("instrumentId") != "NIKKEI_225_INDEX" or valuation.get("basis") != VALUATION_BASIS:
        return {**result, "reason": "incompatible_index_valuation_definition"}
    if valuation.get("currency") != "JPY" or valuation.get("date") != anchor_date:
        return {**result, "reason": "incompatible_valuation_currency_or_session"}
    limit = _instant(cutoff)
    known = [_instant(valuation.get(key)) for key in ("availableFrom", "knownAt") if valuation.get(key)]
    if not limit or not known or any(value is None or value > limit for value in known):
        return {**result, "reason": "valuation_not_known_at_cutoff"}
    if not valuation.get("sourceRef"):
        return {**result, "reason": "valuation_source_required"}
    index = _finite(valuation.get("indexClose"))
    per = _finite(valuation.get("per"))
    anchor = _finite(anchor_price)
    if any(value is None or value <= 0 for value in (index, per, anchor)):
        return {**result, "reason": "invalid_valuation_value"}
    if not math.isclose(index, anchor, rel_tol=1e-6, abs_tol=.01):
        return {**result, "reason": "valuation_anchor_price_mismatch"}
    eps = index / per
    if not math.isfinite(eps) or eps <= 0:
        return {**result, "reason": "invalid_derived_index_eps"}
    return {**result, "status": "AVAILABLE", "reason": None,
            "eps": eps, "per": per, "anchorPrice": anchor, "date": anchor_date,
            "basis": VALUATION_BASIS, "sourceRef": valuation["sourceRef"],
            "availableFrom": valuation.get("availableFrom"), "knownAt": valuation.get("knownAt"),
            "epsDerivation": "same-session index close / index-based PER",
            "shapeToYenFormula": "current index EPS * current index PER * shape / 100",
            "assumptions": ["constant_current_index_eps_for_reference_mapping",
                            "shape_returns_are_not_observed_historical_per_changes"],
            "revocationConditions": ["new_index_eps_or_definition", "anchor_session_changes"],
            "perClippingApplied": False}


def convert_shape_to_yen(points: Sequence[Mapping[str, Any]], *, scale: Mapping[str, Any]) -> list[dict[str, Any]]:
    if scale.get("status") != "AVAILABLE" or scale.get("basis") != VALUATION_BASIS:
        return []
    eps, per = _finite(scale.get("eps")), _finite(scale.get("per"))
    if eps is None or per is None or min(eps, per) <= 0:
        return []
    converted = []
    for row in points:
        value = _finite(row.get("value"))
        if value is None or value <= 0:
            raise ValueError("invalid_shape_value")
        price = eps * per * value / 100
        if not math.isfinite(price):
            raise ValueError("price_conversion_overflow")
        converted.append({**dict(row), "shapeValue": value, "value": price,
                          "unit": "JPY_INDEX_POINTS"})
    return converted


def reference_ensemble(selection: Mapping[str, Any], paths: Sequence[Mapping[str, Any]], *,
                       horizon_sessions: int = 5, flat_threshold_pct: float = .5) -> dict[str, Any]:
    """Summarize complete, uniquely selected historical paths after selection.

    This may be drawn as a provisional calculation-engine forecast. Its band
    is the 25th–75th percentile of these past outcomes, NOT a future coverage
    interval. Small samples and failed independent validation remain visible.
    """
    if isinstance(horizon_sessions, bool) or horizon_sessions not in (1, 5, 10, 20):
        raise ValueError("unsupported_scenario_horizon")
    threshold = _finite(flat_threshold_pct)
    if threshold is None or threshold < 0:
        raise ValueError("invalid_flat_classification_threshold")
    selection_cutoff = _instant(selection.get("informationCutoff"))
    if selection_cutoff is None:
        raise ValueError("selection_information_cutoff_required")
    eligible = {row["snapshotId"] for row in selection.get("selected", [])}
    admitted: dict[str, list[float]] = {}
    for path in paths:
        identifier = path.get("snapshotId")
        points = path.get("subsequentReference", [])
        path_cutoff = _instant(path.get("displayCutoff"))
        if path_cutoff is None or path_cutoff > selection_cutoff:
            continue
        if identifier not in eligible or identifier in admitted:
            continue
        if path.get("scale") != "ANCHOR_100" or path.get("status") != "AVAILABLE" \
                or path.get("horizonSessions") != horizon_sessions or len(points) != horizon_sessions + 1:
            continue
        values = [_finite(point.get("value")) for point in points]
        if any(v is None or v <= 0 for v in values) or values[0] != 100 \
                or [point.get("offsetSessions") for point in points] != list(range(horizon_sessions + 1)):
            continue
        admitted[identifier] = values
    counts = {"up": 0, "flat": 0, "down": 0}
    for path in admitted.values():
        change = path[-1] - 100
        counts["up" if change > threshold else "down" if change < -threshold else "flat"] += 1
    sample = len(admitted)
    line = []
    band = []
    if sample >= 2:
        for session in range(horizon_sessions + 1):
            values = [path[session] for path in admitted.values()]
            line.append({"offsetSessions": session, "value": statistics.median(values)})
            band.append({"offsetSessions": session, "lower": _quantile(values, .25),
                         "upper": _quantile(values, .75)})
    return {
        "method": METHOD, "selectionId": selection.get("selectionId"),
        "instrumentId": "NIKKEI_225_INDEX", "horizonSessions": horizon_sessions,
        "classification": {"unit": "PERCENT", "upAbove": threshold,
                           "flatInclusive": [-threshold, threshold], "downBelow": -threshold},
        "status": "PROVISIONAL_RESEARCH_FORECAST" if line else "INSUFFICIENT_COMPLETE_ANALOGS",
        "forecastLine": line, "forecastBand": band, "scale": "ANCHOR_100",
        "frequency": {"meaning": "SELECTED_HISTORICAL_OUTCOME_FREQUENCY", "sampleCount": sample,
                      "counts": counts, "fractions": {key: count / sample if sample else None
                                                      for key, count in counts.items()}},
        "bandMeaning": "selected historical path quartiles; not a predictive coverage interval",
        "predictiveProbabilities": None, "predictionConfidence": None,
        "validationStatus": "UNVALIDATED", "baselineAdditionalBenefitVerified": False,
        "selectionCoverage": selection.get("status"), "actionAuthority": False,
    }
