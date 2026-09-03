"""v13.5.44 — ARGUS-derived Japan earnings / valuation evidence (SIG-04).

The SHO-original D04 proposition needs licensed Nikkei 225 EPS/PER that ARGUS
does not hold.  This module derives a *labelled* valuation picture for the
configured Japanese universe from inputs ARGUS is allowed to use:

* J-Quants ``/fins/statements`` rows (annual forecast EPS per issuer), and
* the issuer's latest close (curated watch cache or cached daily history).

Derived metrics (never claimed as the official Nikkei 225 PER): per-issuer
forward PER, universe median, interquartile range, and the share of issuers
above the SHO ladder top (21x).  ``conditionMet`` is true when the universe
median forward PER sits inside the SHO 17x-21x ladder (<= 21x).

A boot-warm thread computes the evidence from the host caches and publishes
it here; the SHO evaluator reads it when no licensed EPS evidence is passed.
Values are deterministic, bounded and free of provider text.
"""
from __future__ import annotations

import math
import statistics
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional

LINEAGE = "ARGUS_CANDIDATE"
DERIVATION = "ARGUS_DERIVED_JAPAN_VALUATION"
LADDER_TOP_PER = 21.0
LADDER_BOTTOM_PER = 17.0
MAX_UNIVERSE = 64

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"evidence": None, "statements": None}

_EPS_FORECAST_KEYS = ("ForecastEarningsPerShare", "FcstEPS", "forecastEps")
_EPS_ACTUAL_KEYS = ("EarningsPerShare", "EPS", "Eps")
_CODE_KEYS = ("LocalCode", "Code", "code")
_DATE_KEYS = ("DisclosedDate", "DiscDate", "disclosedDate")


def _field(row: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def latest_forecast_eps(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Latest disclosed annual forecast EPS per 4-character issuer code."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        code = str(_field(row, _CODE_KEYS) or "")[:4]
        date = str(_field(row, _DATE_KEYS) or "")[:10]
        if len(code) != 4 or len(date) != 10:
            continue
        forecast = _number(_field(row, _EPS_FORECAST_KEYS))
        actual = _number(_field(row, _EPS_ACTUAL_KEYS))
        if forecast is None and actual is None:
            continue
        current = out.get(code)
        if current is None or date > current["disclosedDate"]:
            out[code] = {"code": code, "disclosedDate": date,
                         "forecastEps": forecast, "actualEps": actual}
    return out


def compute(statement_rows: Iterable[Mapping[str, Any]],
            prices: Mapping[str, float], *, computed_at: str,
            universe: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Derive the valuation evidence.  Pure: no I/O, no provider text."""
    eps_by_code = latest_forecast_eps(statement_rows)
    codes = [str(c)[:4] for c in (universe or eps_by_code.keys())][:MAX_UNIVERSE]
    issuers: List[Dict[str, Any]] = []
    for code in sorted(set(codes)):
        eps = eps_by_code.get(code)
        price = _number(prices.get(code)) if isinstance(prices, Mapping) else None
        if not eps or price is None or price <= 0:
            continue
        basis = eps["forecastEps"] if eps["forecastEps"] is not None else eps["actualEps"]
        basis_kind = "FORECAST" if eps["forecastEps"] is not None else "ACTUAL"
        if basis is None or basis <= 0:
            issuers.append({"code": code, "price": price, "eps": basis,
                            "epsBasis": basis_kind, "forwardPer": None,
                            "disclosedDate": eps["disclosedDate"]})
            continue
        issuers.append({"code": code, "price": price, "eps": basis,
                        "epsBasis": basis_kind,
                        "forwardPer": round(price / basis, 4),
                        "disclosedDate": eps["disclosedDate"]})
    pers = [row["forwardPer"] for row in issuers if row["forwardPer"] is not None]
    known_at = max((row["disclosedDate"] for row in issuers), default=None)
    if not pers:
        return {
            "derivation": DERIVATION, "lineage": LINEAGE, "status": "MISSING",
            "computedAt": computed_at, "universeSize": len(set(codes)),
            "coverage": 0, "issuers": issuers, "conditionMet": None,
            "missing": ["derived_forward_per_coverage"],
            "nikkeiOfficialPer": "NOT_CLAIMED",
        }
    ordered = sorted(pers)
    median = statistics.median(ordered)
    q1 = statistics.median(ordered[: max(1, len(ordered) // 2)])
    q3 = statistics.median(ordered[len(ordered) // 2 + (len(ordered) % 2):]) \
        if len(ordered) > 1 else median
    high_share = sum(1 for value in ordered if value > LADDER_TOP_PER) / len(ordered)
    return {
        "derivation": DERIVATION, "lineage": LINEAGE, "status": "AVAILABLE",
        "computedAt": computed_at, "knownAt": known_at,
        "availableFrom": f"{known_at}T23:59:00+09:00" if known_at else None,
        "universeSize": len(set(codes)), "coverage": len(pers),
        "medianForwardPer": round(median, 4),
        "interquartileRange": [round(q1, 4), round(q3, 4)],
        "highValuationShare": round(high_share, 4),
        "ladder": {"bottom": LADDER_BOTTOM_PER, "top": LADDER_TOP_PER, "unit": "PER_X"},
        "conditionMet": median <= LADDER_TOP_PER,
        "conditionRule": f"universe median forward PER <= {LADDER_TOP_PER:g}x (SHO ladder top)",
        "issuers": issuers,
        "missing": [],
        "nikkeiOfficialPer": "NOT_CLAIMED",
    }


def publish(evidence: Optional[Mapping[str, Any]]) -> None:
    with _LOCK:
        _STATE["evidence"] = dict(evidence) if isinstance(evidence, Mapping) else None


def current_evidence() -> Optional[Dict[str, Any]]:
    with _LOCK:
        value = _STATE["evidence"]
        return dict(value) if isinstance(value, dict) else None


def publish_statements_state(state: Optional[Mapping[str, Any]]) -> None:
    """Warm state of the statements feed (warmedAt, rowCount, windowDays)."""
    with _LOCK:
        _STATE["statements"] = dict(state) if isinstance(state, Mapping) else None


def statements_state() -> Optional[Dict[str, Any]]:
    with _LOCK:
        value = _STATE["statements"]
        return dict(value) if isinstance(value, dict) else None


def _reset_for_tests() -> None:
    with _LOCK:
        _STATE["evidence"] = None
        _STATE["statements"] = None
