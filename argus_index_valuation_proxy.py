"""ARGUS proxy for the Nikkei 225 index-based EPS and PER.

Why a proxy exists
------------------
The owner's specification translates a historical analog's path into today's
yen with ``NIKKEI 225 = index EPS × index-based PER``. The official series is
published by Nikkei Inc. Using it as a machine input is, in Nikkei's own
taxonomy, non-display use under licence, and the summary page answers 403 to
anything that is not a browser. J-Quants carries no index valuation at any
plan. So the product reconstructs the quantity from inputs it already holds a
right to: J-Quants per-stock valuation and closes (Standard plan), plus the
constituent weights Nikkei publishes for free at each month end.

What this module promises, and what it does not
-----------------------------------------------
* It is arithmetic on declared inputs. No network, no clock, no file.
* Its output carries ``basis = ARGUS_PROXY_INDEX_BASED_PER`` and must never be
  presented as the official figure. The specification is explicit that an
  official index EPS and a constituent-aggregated proxy are distinguished.
* Every number is accompanied by coverage: which members had a price, which
  had a forecast EPS, how many forecasts were negative, and which factors had
  to be rounded. A proxy with a hole in it says so.
* When an official value for the same session is supplied, the error is
  computed here and travels with the proxy, so the reader is never asked to
  trust a reconstruction whose error nobody measured.

The reconstruction
------------------
The Nikkei 225 is price-weighted with a per-member price adjustment factor::

    Index(t) = Σ_i P_i(t) · f_i / Divisor(t)
    w_i(T0)  = P_i(T0) · f_i / Σ_j P_j(T0) · f_j          (published weights)

so ``f_i ∝ w_i / P_i(T0)`` and the factors follow from one month-end weight
table and that day's closes, up to one common scale. Most members carry the
default factor 1.0, so the scale is fixed by the densest cluster of the raw
ratios. Once the factors are known the divisor cancels out of the PER::

    PER_proxy(t) = Σ_i P_i(t) · f_i  /  Σ_i EPS_i(t) · f_i
    EPS_index(t) = Index(t) / PER_proxy(t)

Nikkei computes its index-based PER on forecast earnings. Whether members with
a negative forecast enter the denominator as negatives or as zero is not
stated on the free pages, so both variants are produced and the measured
error against the official series decides which one the product reports.
"""
from __future__ import annotations

import csv
import io
import math
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SCHEMA = "argus-index-valuation-proxy-v1"
PROXY_BASIS = "ARGUS_PROXY_INDEX_BASED_PER"
OFFICIAL_BASIS = "NIKKEI_225_INDEX_BASED_PER"
INSTRUMENT = "NIKKEI_225_INDEX"
BASIS_LABEL_JA = "ARGUS代理値（構成銘柄の予想EPSから再構成。公式の指数ベースPERではありません）"

WEIGHT_COLUMNS = ("日付", "コード", "社名", "業種", "セクター", "ウエート")
#: Factors are published in steps of 0.1 (1.0 is the default); the snap keeps
#: the recovered value honest about how far it sat from that grid.
FACTOR_STEP = 0.1
FACTOR_SNAP_TOLERANCE = 0.03          # relative distance accepted for a snap
#: Fewer priced members than this and no factor set is derived at all.
MINIMUM_PRICED_MEMBERS = 200

EPS_VARIANTS = ("FORECAST_SIGNED", "FORECAST_NON_NEGATIVE", "ACTUAL_SIGNED")


class ProxyError(ValueError):
    pass


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


# ── month-end weights ────────────────────────────────────────────────────────

def parse_weight_table(text: str) -> Dict[str, Any]:
    """Parse Nikkei's published month-end weight table (already decoded).

    The file ends with a copyright notice line; it is recognised and dropped,
    and its presence is recorded, because the product must never redistribute
    this table. Nothing but codes, weights and the as-of date leave here.
    """
    if not isinstance(text, str) or not text.strip():
        raise ProxyError("weight_table_empty")
    lines = [line for line in text.splitlines() if line.strip()]
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = next(reader, None)
    if header is None or tuple(cell.strip() for cell in header) != WEIGHT_COLUMNS:
        raise ProxyError("weight_table_columns")
    rows: List[Dict[str, Any]] = []
    notice_seen = False
    as_of: Optional[str] = None
    for cells in reader:
        if len(cells) == 1:
            notice_seen = notice_seen or ("著作物" in cells[0])
            continue
        if len(cells) != len(WEIGHT_COLUMNS):
            raise ProxyError("weight_table_row_shape")
        date_text, code, _name, _industry, _sector, weight_text = (c.strip() for c in cells)
        day = date_text.replace("/", "-")
        if len(day) != 10:
            raise ProxyError("weight_table_date")
        as_of = as_of or day
        if day != as_of:
            raise ProxyError("weight_table_mixed_dates")
        if not weight_text.endswith("%"):
            raise ProxyError("weight_table_weight_unit")
        weight = _finite(weight_text[:-1])
        if weight is None or weight <= 0:
            raise ProxyError("weight_table_weight_value")
        if not code or any(code == row["code"] for row in rows):
            raise ProxyError("weight_table_duplicate_code")
        rows.append({"code": code, "weightPct": weight})
    if not rows or as_of is None:
        raise ProxyError("weight_table_no_rows")
    total = sum(row["weightPct"] for row in rows)
    if not 99.0 <= total <= 101.0:
        raise ProxyError("weight_table_total")
    return {"asOf": as_of, "members": rows, "memberCount": len(rows),
            "weightTotalPct": round(total, 4), "noticeSeen": notice_seen}


# ── factor recovery ──────────────────────────────────────────────────────────

def _snap(value: float) -> Dict[str, Any]:
    grid = max(FACTOR_STEP, round(value / FACTOR_STEP) * FACTOR_STEP)
    distance = abs(value - grid) / grid
    return {"factor": round(grid, 6) if distance <= FACTOR_SNAP_TOLERANCE else round(value, 6),
            "snapped": distance <= FACTOR_SNAP_TOLERANCE,
            "rawFactor": round(value, 6), "snapDistance": round(distance, 6)}


def derive_factors(weights: Mapping[str, Any], closes_at_as_of: Mapping[str, Any]) -> Dict[str, Any]:
    """Recover each member's price adjustment factor from weights and closes.

    ``closes_at_as_of`` maps code → close on the weight table's as-of session.
    The common scale is the densest cluster of raw ratios (the 1.0 default);
    a median would be pulled by a review that changed many factors at once,
    so the mode of the rounded ratios is used and the median only breaks ties.
    """
    members = weights.get("members") or []
    ratios: Dict[str, float] = {}
    unpriced: List[str] = []
    for row in members:
        close = _finite(closes_at_as_of.get(row["code"]))
        if close is None or close <= 0:
            unpriced.append(row["code"])
            continue
        ratios[row["code"]] = row["weightPct"] / close
    if len(ratios) < MINIMUM_PRICED_MEMBERS:
        raise ProxyError("factor_derivation_insufficient_prices")
    median = statistics.median(ratios.values())
    # Cluster at 2% resolution around the median; the largest cluster is 1.0.
    buckets: Dict[int, List[float]] = {}
    for value in ratios.values():
        buckets.setdefault(int(round(math.log(value / median) / math.log(1.02))), []).append(value)
    densest = max(buckets.values(), key=len)
    scale = statistics.median(densest)
    factors: Dict[str, Dict[str, Any]] = {}
    unsnapped: List[str] = []
    for code, ratio in ratios.items():
        entry = _snap(ratio / scale)
        factors[code] = entry
        if not entry["snapped"]:
            unsnapped.append(code)
    reduced = sorted(code for code, entry in factors.items() if entry["factor"] < 0.999)
    return {"schemaVersion": SCHEMA, "asOf": weights.get("asOf"),
            "factors": {code: entry["factor"] for code, entry in factors.items()},
            "detail": factors, "scale": scale,
            "coverage": {"members": len(members), "priced": len(ratios),
                         "unpriced": sorted(unpriced), "reducedFactorMembers": reduced,
                         "unsnapped": sorted(unsnapped),
                         "defaultFactorShare": round(
                             sum(1 for e in factors.values() if e["factor"] == 1.0) / len(factors), 4)}}


def factor_identity_check(factors: Mapping[str, Any], closes: Mapping[str, Any], *,
                          divisor: float, official_close: float) -> Dict[str, Any]:
    """Σ P·f / divisor must reproduce the official close on the same session."""
    total = 0.0
    used = 0
    for code, factor in (factors.get("factors") or {}).items():
        close = _finite(closes.get(code))
        if close is None:
            continue
        total += close * float(factor)
        used += 1
    if used == 0 or not divisor or divisor <= 0:
        return {"status": "UNAVAILABLE", "reason": "no_prices_or_divisor"}
    implied = total / divisor
    error_pct = (implied - official_close) / official_close * 100.0
    return {"status": "AVAILABLE", "impliedClose": round(implied, 2),
            "officialClose": official_close, "errorPct": round(error_pct, 4),
            "membersUsed": used}


# ── the proxy itself ─────────────────────────────────────────────────────────

def proxy_valuation(*, factors: Mapping[str, Any], closes: Mapping[str, Any],
                    forecast_eps: Mapping[str, Any], actual_eps: Mapping[str, Any],
                    index_close: float, date: str, available_from: str,
                    known_at: str, source_ref: str,
                    official_per: Optional[float] = None) -> Dict[str, Any]:
    """Reconstruct the index-based PER and EPS for one session."""
    table = factors.get("factors") or {}
    if not table:
        raise ProxyError("factors_required")
    index = _finite(index_close)
    if index is None or index <= 0:
        raise ProxyError("index_close_required")
    price_sum = 0.0
    sums = {"FORECAST_SIGNED": 0.0, "FORECAST_NON_NEGATIVE": 0.0, "ACTUAL_SIGNED": 0.0}
    priced = with_forecast = with_actual = negative_forecast = 0
    missing_price: List[str] = []
    missing_forecast: List[str] = []
    for code, factor in table.items():
        f = float(factor)
        close = _finite(closes.get(code))
        if close is None or close <= 0:
            missing_price.append(code)
            continue
        priced += 1
        price_sum += close * f
        fwd = _finite(forecast_eps.get(code))
        if fwd is None:
            missing_forecast.append(code)
        else:
            with_forecast += 1
            sums["FORECAST_SIGNED"] += fwd * f
            sums["FORECAST_NON_NEGATIVE"] += max(fwd, 0.0) * f
            if fwd < 0:
                negative_forecast += 1
        act = _finite(actual_eps.get(code))
        if act is not None:
            with_actual += 1
            sums["ACTUAL_SIGNED"] += act * f
    variants: Dict[str, Any] = {}
    for name in EPS_VARIANTS:
        denominator = sums[name]
        if priced == 0 or denominator <= 0:
            variants[name] = {"per": None, "indexEps": None, "reason": "non_positive_eps_sum"}
            continue
        per = price_sum / denominator
        # Full precision travels; rounding is a display decision, and the
        # index EPS is derived from this PER downstream.
        variants[name] = {"per": per, "indexEps": index / per}
        if official_per is not None and official_per > 0:
            variants[name]["officialPer"] = official_per
            variants[name]["errorPct"] = round((per - official_per) / official_per * 100.0, 4)
    coverage = {"members": len(table), "priced": priced, "withForecastEps": with_forecast,
                "withActualEps": with_actual, "negativeForecastEps": negative_forecast,
                "missingPrice": sorted(missing_price), "missingForecastEps": sorted(missing_forecast),
                "pricedShare": round(priced / len(table), 4) if table else 0.0}
    return {"schemaVersion": SCHEMA, "instrumentId": INSTRUMENT, "basis": PROXY_BASIS,
            "basisLabelJa": BASIS_LABEL_JA, "currency": "JPY", "date": date,
            "indexClose": index, "impliedDivisor": round(price_sum / index, 8) if index else None,
            "variants": variants, "coverage": coverage,
            "factorsAsOf": factors.get("asOf"), "sourceRef": source_ref,
            "availableFrom": available_from, "knownAt": known_at,
            "epsKind": "PROXY_FROM_CONSTITUENT_FORECAST_EPS",
            "actionAuthority": False, "validationStatus": "UNVALIDATED",
            "historicalVintageVerified": False}


def select_variant(proxy: Mapping[str, Any], variant: str) -> Optional[Dict[str, Any]]:
    """The scale-shaped row for one variant, or None when it has no value.

    The row deliberately mirrors the official valuation row so the same price
    scale consumes it, and deliberately differs in ``basis`` so nothing can
    mistake it for the official figure.
    """
    if variant not in EPS_VARIANTS:
        raise ProxyError("unknown_eps_variant")
    body = (proxy.get("variants") or {}).get(variant) or {}
    if body.get("per") is None:
        return None
    return {"instrumentId": INSTRUMENT, "basis": PROXY_BASIS, "basisLabelJa": BASIS_LABEL_JA,
            "currency": "JPY", "date": proxy.get("date"), "indexClose": proxy.get("indexClose"),
            "per": body["per"], "epsVariant": variant, "officialErrorPct": body.get("errorPct"),
            "sourceRef": proxy.get("sourceRef"), "availableFrom": proxy.get("availableFrom"),
            "knownAt": proxy.get("knownAt"), "epsKind": proxy.get("epsKind"),
            "coverage": proxy.get("coverage"), "factorsAsOf": proxy.get("factorsAsOf")}


# ── measured error against the official series ──────────────────────────────

def compare_with_official(proxies: Iterable[Mapping[str, Any]],
                          official: Mapping[str, Any]) -> Dict[str, Any]:
    """Per-variant error statistics over the sessions both sides cover.

    ``official`` maps session date → official index-based PER. Sessions the
    proxy lacks are listed, not skipped silently, and the recommended variant
    is the one with the smallest mean absolute error, on the same sessions.
    """
    per_variant: Dict[str, List[Dict[str, Any]]] = {name: [] for name in EPS_VARIANTS}
    covered: List[str] = []
    for proxy in proxies:
        day = proxy.get("date")
        target = _finite(official.get(day))
        if target is None or target <= 0:
            continue
        covered.append(day)
        for name in EPS_VARIANTS:
            per = _finite(((proxy.get("variants") or {}).get(name) or {}).get("per"))
            if per is None:
                continue
            per_variant[name].append({"date": day, "proxyPer": per, "officialPer": target,
                                      "errorPct": round((per - target) / target * 100.0, 4)})
    summary: Dict[str, Any] = {}
    for name, rows in per_variant.items():
        if not rows:
            summary[name] = {"sessions": 0}
            continue
        errors = [row["errorPct"] for row in rows]
        summary[name] = {"sessions": len(rows),
                         "meanErrorPct": round(statistics.fmean(errors), 4),
                         "meanAbsErrorPct": round(statistics.fmean(abs(e) for e in errors), 4),
                         "maxAbsErrorPct": round(max(abs(e) for e in errors), 4),
                         "rows": rows}
    ranked = [name for name in EPS_VARIANTS if summary[name].get("sessions")]
    ranked.sort(key=lambda name: summary[name]["meanAbsErrorPct"])
    missing = sorted(day for day in official if day not in covered)
    return {"schemaVersion": SCHEMA, "variants": summary,
            "recommendedVariant": ranked[0] if ranked else None,
            "sessionsCompared": len(set(covered)), "officialSessionsWithoutProxy": missing}
