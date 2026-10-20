"""How many points each member moved the Nikkei 225 over a period (2026-10-17).

The index is Σ(price × factor) / divisor. The factors are recovered from the
owner's month-end weight table (they are published on a 0.1 grid; all 225
official factors of 2026-10-07 were on it). A member missing from that table
(a new member) is counted with the most common factor, 1.0 (owner decision
2026-10-17: fully automatic, a small error is acceptable). The divisor is
implied by the start session: Σ(P_start × f) / official close. The same divisor
and factors must then reproduce the end session's official close: exactly
(within two roundings) or within a small tolerance, shown as an estimate.
Otherwise no member value is shown.

Pure functions: no clock, no store, no network.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "jp-index-contribution-v1"
#: Both ends are official closes rounded to 0.01; a consistent period leaves
#: a residual within two roundings.
RESIDUAL_TOLERANCE_POINTS = Decimal("0.02")
#: Accepted as an estimate (owner: "within the error range is fine"): the
#: larger of one index point and 3% of the period's index move.
ESTIMATE_TOLERANCE_POINTS = Decimal("1")
ESTIMATE_TOLERANCE_SHARE = Decimal("0.03")
DEFAULT_FACTOR = Decimal("1.0")
TOP_MEMBERS = 5


def _dec(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    return number if number.is_finite() and number > 0 else None


def _points(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def period(*, start: str, end: str, members_start: Iterable[str], members_end: Iterable[str],
           closes: Mapping[str, Mapping[str, Any]], index_close: Mapping[str, Any],
           derived_factors: Mapping[str, Any],
           names: Optional[Mapping[str, str]] = None, factors_as_of: Optional[str] = None,
           factor_basis: str = "RECOVERED_FROM_WEIGHTS_OR_OWNER_ENTRY") -> Dict[str, Any]:
    """One period's contributions, or why they cannot be shown."""
    names = names or {}
    base = {"schemaVersion": SCHEMA, "startDate": start, "endDate": end, "factorsAsOf": factors_as_of,
            "factorBasis": factor_basis, "priceBasis": "JQUANTS_UNADJUSTED_CLOSE",
            "quoteSelectionVerified": False, "actionAuthority": False}
    first, last = set(members_start), set(members_end)
    if not first or not last:
        return {**base, "status": "UNAVAILABLE", "reason": "members_unknown"}
    if first != last:
        return {**base, "status": "UNAVAILABLE", "reason": "constituents_changed_in_period"}
    factors = {code: _dec(derived_factors.get(code)) for code in sorted(first)}
    assumed = sorted(code for code, factor in factors.items() if factor is None)
    for code in assumed:
        factors[code] = DEFAULT_FACTOR
    start_closes, end_closes = closes.get(start) or {}, closes.get(end) or {}
    prices = {code: (_dec(start_closes.get(code)), _dec(end_closes.get(code))) for code in first}
    if any(p is None or q is None for p, q in prices.values()):
        return {**base, "status": "UNAVAILABLE", "reason": "member_closes_missing",
                "missingCloses": sum(1 for p, q in prices.values() if p is None or q is None)}
    close_start, close_end = _dec(index_close.get(start)), _dec(index_close.get(end))
    if close_start is None or close_end is None:
        return {**base, "status": "UNAVAILABLE", "reason": "index_close_missing"}
    sum_start = sum(prices[c][0] * factors[c] for c in first)
    sum_end = sum(prices[c][1] * factors[c] for c in first)
    divisor = sum_start / close_start
    predicted_end = sum_end / divisor
    residual = predicted_end - close_end
    common = {**base, "members": len(first), "impliedDivisor": float(divisor.quantize(Decimal("0.00000001"))),
              "indexDeltaPoints": _points(close_end - close_start), "residualPoints": _points(residual),
              "assumedFactorCodes": assumed}
    allowed = max(ESTIMATE_TOLERANCE_POINTS, ESTIMATE_TOLERANCE_SHARE * abs(close_end - close_start))
    if abs(residual) > allowed:
        return {**common, "status": "SUM_MISMATCH", "reason": "factor_or_divisor_changed"}
    estimate = bool(assumed) or abs(residual) > RESIDUAL_TOLERANCE_POINTS
    rows = []
    for code in first:
        before, after = prices[code]
        rows.append({"code": code, "nameJa": names.get(code),
                     "points": _points((after - before) * factors[code] / divisor),
                     "pricePct": float(((after / before - 1) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))})
    rows.sort(key=lambda r: (-r["points"], r["code"]))
    return {**common, "status": "AVAILABLE", "reason": None, "estimate": estimate,
            "sumOfContributionsPoints": _points(sum_end / divisor - sum_start / divisor),
            "top": rows[:TOP_MEMBERS], "bottom": sorted(rows[-TOP_MEMBERS:], key=lambda r: (r["points"], r["code"]))}
