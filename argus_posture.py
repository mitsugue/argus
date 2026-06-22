"""A.R.G.U.S. — Calibration Ledger v4: multidimensional market-posture scoring.

Pure-stdlib, side-effect-free. The legacy ledger graded the global posture call
using SPY alone ("RISK_ON → SPY next move > 0"). That is too thin: a posture is a
multi-dimensional claim about risk appetite, credit, duration, volatility, Japan,
FX and liquidity. This module turns a basket of realized returns into per-
dimension outcomes (volatility-normalized, explicit signs) and an aggregate, and
marks the result PARTIAL rather than silently falling back to SPY-only when
dimensions are missing.

Used to SCORE a posture prediction:
- RISK_ON  → aggregate risk-appetite outcome should be > 0
- RISK_OFF → aggregate risk-appetite outcome should be < 0
- EVENT_WAIT → realized dispersion (|moves|) should be elevated
- CAUTIOUS / MIXED → no strong claim (recorded, not graded)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

POSTURE_VERSION = "posture-v1"

# Each dimension is a basket of (symbol, sign). sign=+1 means "a positive return
# in this name is risk-ON for the dimension"; sign=-1 means inverse (VIX up = risk
# off). Volatility-normalization makes a 1% SPY move comparable to a 1% GLD move.
DIMENSIONS: Dict[str, List[Tuple[str, int]]] = {
    "equityRisk":   [("SPY", +1), ("QQQ", +1), ("IWM", +1)],
    "growthRisk":   [("QQQ", +1), ("SMH", +1)],
    "smallCapRisk": [("IWM", +1)],
    "creditRisk":   [("HYG", +1), ("LQD", -1)],   # HY outperforming IG = risk-on
    "duration":     [("TLT", +1)],
    "volatility":   [("VIX", -1)],                  # VIX up = risk-off
    "safeHaven":    [("GLD", +1), ("TLT", +1)],
    "japanRisk":    [("1306", +1), ("1321", +1)],
    "fx":           [("USDJPY", +1)],               # weaker yen = risk-on-ish (context)
    "liquidity":    [("BTC", +1)],
}

# Which dimensions sum into the headline RISK-APPETITE aggregate (safeHaven/
# volatility are inverse and counted with their natural risk-on direction).
RISK_APPETITE_DIMS = ("equityRisk", "growthRisk", "smallCapRisk",
                      "creditRisk", "liquidity")

MIN_DIMENSIONS = 3  # below this the aggregate is PARTIAL, never SPY-only


def _norm(ret_pct: float, vol_pct: Optional[float]) -> Optional[float]:
    """Volatility-normalized return (z-like). None if no usable vol."""
    if ret_pct is None:
        return None
    if vol_pct is None or vol_pct <= 0:
        return ret_pct  # fall back to raw % if vol unknown (still usable)
    return ret_pct / vol_pct


def dimension_outcomes(
    returns: Dict[str, float],
    vols: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compute per-dimension realized outcomes from a basket of returns.

    returns: {symbol: realized_return_pct} ; vols: {symbol: trailing_sigma_pct}.
    Each dimension averages the volatility-normalized, sign-applied component
    returns over the components that are actually present. Missing components are
    reported, never fabricated.
    """
    vols = vols or {}
    out: Dict[str, Any] = {}
    for dim, basket in DIMENSIONS.items():
        vals, used, missing = [], [], []
        for sym, sign in basket:
            if sym in returns and returns[sym] is not None:
                n = _norm(returns[sym] * sign, vols.get(sym))
                if n is not None:
                    vals.append(n)
                    used.append(sym)
                    continue
            missing.append(sym)
        if vals:
            out[dim] = {
                "score": round(sum(vals) / len(vals), 4),
                "components": used, "missing": missing,
                "status": "ok" if not missing else "partial",
            }
        else:
            out[dim] = {"score": None, "components": [], "missing": missing,
                        "status": "missing"}
    return out


def posture_outcome(
    returns: Dict[str, float],
    vols: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Aggregate multidimensional posture outcome.

    Returns per-dimension outcomes plus a headline risk-appetite aggregate and a
    dispersion measure (for EVENT_WAIT). Marked PARTIAL when fewer than
    MIN_DIMENSIONS risk-appetite dimensions are available — NEVER silently SPY-only.
    """
    dims = dimension_outcomes(returns, vols)
    appetite = [dims[d]["score"] for d in RISK_APPETITE_DIMS
                if dims.get(d, {}).get("score") is not None]
    all_scores = [v["score"] for v in dims.values() if v.get("score") is not None]
    dispersion = (sum(abs(s) for s in all_scores) / len(all_scores)
                  if all_scores else None)
    if len(appetite) < MIN_DIMENSIONS:
        return {
            "postureVersion": POSTURE_VERSION,
            "aggregateRiskAppetite": (round(sum(appetite) / len(appetite), 4)
                                      if appetite else None),
            "dispersion": round(dispersion, 4) if dispersion is not None else None,
            "dimensions": dims,
            "status": "partial",
            "reason": f"only {len(appetite)}/{MIN_DIMENSIONS} risk-appetite dimensions available",
        }
    return {
        "postureVersion": POSTURE_VERSION,
        "aggregateRiskAppetite": round(sum(appetite) / len(appetite), 4),
        "dispersion": round(dispersion, 4) if dispersion is not None else None,
        "dimensions": dims,
        "appetiteDimsUsed": len(appetite),
        "status": "ok",
    }


def grade_posture(label: str, outcome: Dict[str, Any],
                  event_wait_min_dispersion: float = 0.8) -> Dict[str, Any]:
    """Grade a posture prediction against the multidimensional outcome.

    Returns {graded: bool, hit: Optional[bool], reason}. CAUTIOUS/MIXED make no
    strong claim → graded=False. Partial outcome → graded=False (not scorable).
    """
    if outcome.get("status") == "partial":
        return {"graded": False, "hit": None, "reason": "partial_outcome"}
    agg = outcome.get("aggregateRiskAppetite")
    disp = outcome.get("dispersion")
    if label == "RISK_ON":
        return {"graded": True, "hit": (agg is not None and agg > 0),
                "reason": f"aggregateRiskAppetite={agg}"}
    if label == "RISK_OFF":
        return {"graded": True, "hit": (agg is not None and agg < 0),
                "reason": f"aggregateRiskAppetite={agg}"}
    if label == "EVENT_WAIT":
        return {"graded": True,
                "hit": (disp is not None and disp >= event_wait_min_dispersion),
                "reason": f"dispersion={disp} vs {event_wait_min_dispersion}"}
    return {"graded": False, "hit": None, "reason": "no_strong_claim (CAUTIOUS/MIXED)"}
