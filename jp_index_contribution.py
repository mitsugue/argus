"""How many points each member moved the Nikkei 225 over a period (2026-10-17).

The index is Σ(price × factor) / divisor. The factors are recovered from the
owner's month-end weight table (they are published on a 0.1 grid; all 225
official factors of 2026-10-07 were on it) or entered by the owner for a
member whose factor is not in that table. The divisor is implied by the start
session: Σ(P_start × f) / official close. The same divisor and factors must
then reproduce the end session's official close; otherwise a factor or the
divisor changed inside the period and no member value is shown.

Pure functions: no clock, no store, no network.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "jp-index-contribution-v1"
#: Both ends are official closes rounded to 0.01; a consistent period leaves
#: a residual within two roundings.
RESIDUAL_TOLERANCE_POINTS = Decimal("0.02")
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


def factor_on(code: str, day: str, derived: Mapping[str, Any],
              overrides: Iterable[Mapping[str, Any]]) -> Optional[Decimal]:
    """The owner's entry effective on `day` wins over the derived factor."""
    chosen = None
    for row in overrides or ():
        if row.get("code") == code and str(row.get("effectiveFrom") or "") <= day:
            if chosen is None or str(row["effectiveFrom"]) > str(chosen["effectiveFrom"]):
                chosen = row
    if chosen is not None:
        return _dec(chosen.get("factor"))
    return _dec(derived.get(code))


def period(*, start: str, end: str, members_start: Iterable[str], members_end: Iterable[str],
           closes: Mapping[str, Mapping[str, Any]], index_close: Mapping[str, Any],
           derived_factors: Mapping[str, Any], overrides: Iterable[Mapping[str, Any]] = (),
           names: Optional[Mapping[str, str]] = None, factors_as_of: Optional[str] = None) -> Dict[str, Any]:
    """One period's contributions, or why they cannot be shown."""
    names = names or {}
    base = {"schemaVersion": SCHEMA, "startDate": start, "endDate": end, "factorsAsOf": factors_as_of,
            "factorBasis": "RECOVERED_FROM_WEIGHTS_OR_OWNER_ENTRY", "priceBasis": "JQUANTS_UNADJUSTED_CLOSE",
            "quoteSelectionVerified": False, "actionAuthority": False}
    first, last = set(members_start), set(members_end)
    if not first or not last:
        return {**base, "status": "UNAVAILABLE", "reason": "members_unknown"}
    if first != last:
        return {**base, "status": "UNAVAILABLE", "reason": "constituents_changed_in_period"}
    factors = {code: factor_on(code, start, derived_factors, overrides) for code in sorted(first)}
    changed = sorted(code for code in first
                     if factor_on(code, end, derived_factors, overrides) != factors[code])
    if changed:
        return {**base, "status": "UNAVAILABLE", "reason": "factor_changed_in_period"}
    missing = sorted(code for code, factor in factors.items() if factor is None)
    if missing:
        return {**base, "status": "NEEDS_FACTOR", "reason": "factor_missing",
                "missingFactorCodes": missing}
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
              "indexDeltaPoints": _points(close_end - close_start), "residualPoints": _points(residual)}
    if abs(residual) > RESIDUAL_TOLERANCE_POINTS:
        return {**common, "status": "SUM_MISMATCH", "reason": "factor_or_divisor_changed"}
    rows = []
    for code in first:
        before, after = prices[code]
        rows.append({"code": code, "nameJa": names.get(code),
                     "points": _points((after - before) * factors[code] / divisor),
                     "pricePct": float(((after / before - 1) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))})
    rows.sort(key=lambda r: (-r["points"], r["code"]))
    return {**common, "status": "AVAILABLE", "reason": None,
            "sumOfContributionsPoints": _points(sum_end / divisor - sum_start / divisor),
            "top": rows[:TOP_MEMBERS], "bottom": sorted(rows[-TOP_MEMBERS:], key=lambda r: (r["points"], r["code"]))}


def needs(results: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """What the owner must enter now: missing factors, or the latest day does not add up."""
    one = results.get("1") or {}
    missing = sorted({code for row in results.values() for code in row.get("missingFactorCodes") or []})
    mismatch = ({"endDate": one.get("endDate"), "residualPoints": one.get("residualPoints")}
                if one.get("status") == "SUM_MISMATCH" else None)
    return {"missingFactorCodes": missing, "mismatch": mismatch, "inputDue": bool(missing or mismatch)}
