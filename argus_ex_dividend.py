"""Ex-dividend drop of the Nikkei 225 in yen, from members' dividend forecasts.

The index is price-weighted, ``Index = Σ P_i f_i / Divisor``. On the ex-dividend
day every member's price falls by about its per-share dividend D_i, so the index
falls by ``Σ D_i f_i / Divisor``. The divisor cancels against the index level::

    drop_yen = Index × Σ D_i f_i / Σ P_i f_i

Inputs are the adjustment factors already derived from Nikkei's published
weights (``argus_index_valuation_proxy``), the latest closes, and each member's
latest J-Quants financial summary (``/fins/summary``). It is arithmetic on
declared inputs: no network, clock or file. The result is an estimate: members
without an explicit forecast are excluded and the covered share is reported;
nothing is extrapolated or filled.

Which field applies. A record date at the end of month M belongs to the dividend
whose fiscal year ends ``offset`` months later: the year-end dividend (FDivFY,
offset 0), the third-quarter-end (FDiv3Q, 3), the interim (FDiv2Q, 6) or the
first-quarter-end (FDiv1Q, 9). A full-year (FY) disclosure's forecast is for the
NEXT fiscal year (CurFYEn is the year just reported); a quarterly disclosure's
forecast is for the current one, and its NxFDiv* fields are the year after.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "argus-ex-dividend-estimate-v1"
FIELDS = (("FDiv1Q", 9), ("FDiv2Q", 6), ("FDiv3Q", 3), ("FDivFY", 0))
MINIMUM_COVERED_SHARE = 0.60          # below this the estimate is not shown


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value in (None, "", "-"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    return (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)


def _shift_months(day: date, months: int) -> date:
    """Month end `months` after the month end of `day` (negative goes back)."""
    index = day.year * 12 + (day.month - 1) + months
    return _month_end(index // 12, index % 12 + 1)


def latest_disclosures(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Newest disclosure per 4-digit code (by DiscDate, then DiscTime)."""
    best: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("Code") or row.get("LocalCode") or "")[:4]
        if len(code) != 4 or _day(row.get("DiscDate")) is None:
            continue
        key = (str(row.get("DiscDate"))[:10], str(row.get("DiscTime") or ""))
        if code not in best or key >= best[code]["_key"]:
            best[code] = {**dict(row), "_key": key}
    return {code: {k: v for k, v in row.items() if k != "_key"} for code, row in best.items()}


def applicable_dividend(row: Mapping[str, Any], record_day: date) -> Optional[float]:
    """The forecast per-share dividend whose record date is `record_day`, or None."""
    fiscal_end = _day(row.get("CurFYEn"))
    if fiscal_end is None:
        return None
    full_year = str(row.get("CurPerType") or "") == "FY"
    forecast_year_end = _shift_months(fiscal_end, 12) if full_year else fiscal_end
    for field, offset in FIELDS:
        if _shift_months(record_day, offset) == forecast_year_end:
            return _number(row.get(field))
        if _shift_months(record_day, offset) == _shift_months(forecast_year_end, 12):
            return _number(row.get("Nx" + field))
    return None


def estimate(*, record_day: date, factors: Mapping[str, float], closes: Mapping[str, float],
             disclosures: Mapping[str, Mapping[str, Any]], index_close: float) -> Dict[str, Any]:
    """Yen drop at the ex-dividend open for the record date `record_day` (a month end)."""
    covered_p = total_p = covered_d = 0.0
    covered = missing = zero = 0
    for code, factor in factors.items():
        close = _number(closes.get(code))
        if close is None or close <= 0 or not isinstance(factor, (int, float)) or factor <= 0:
            continue
        weight = close * float(factor)
        total_p += weight
        row = disclosures.get(code)
        dividend = applicable_dividend(row, record_day) if row else None
        if dividend is None:
            missing += 1
            continue
        covered += 1
        zero += dividend == 0
        covered_p += weight
        covered_d += dividend * float(factor)
    share = covered_p / total_p if total_p > 0 else 0.0
    result: Dict[str, Any] = {
        "schemaVersion": SCHEMA, "recordDay": record_day.isoformat(), "basis": "ARGUS_ESTIMATE_FROM_FORECAST_DIVIDENDS",
        "membersCovered": covered, "membersMissing": missing, "membersZero": zero,
        "coveredPriceWeightShare": round(share, 4), "dropYen": None, "dropPct": None,
        "actionAuthority": False,
    }
    if share < MINIMUM_COVERED_SHARE or covered_p <= 0 or not index_close or index_close <= 0:
        result["reason"] = "covered_share_too_low"
        return result
    ratio = covered_d / covered_p            # the covered members' dividend yield on the index's own weights
    result.update(dropYen=round(index_close * ratio, 1), dropPct=round(ratio * 100, 3))
    return result


def next_record_days(today: date, months: Iterable[int] = (3, 6, 9, 12), horizon_months: int = 15) -> List[date]:
    """Quarter-end record dates (month ends) from `today` through the horizon."""
    out = []
    for step in range(horizon_months + 1):
        end = _shift_months(date(today.year, today.month, 1), step)
        if end.month in set(months) and end >= today:
            out.append(end)
    return out
