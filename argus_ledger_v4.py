"""A.R.G.U.S. — Calibration Ledger v4 scorer (the v4 runner core).

Pure, dependency-light scoring the prediction-ledger workflow will call to grade
recorded forecasts the v4 way:
  - per-record MARKET-SPECIFIC target dates (from marketClock), not a flat +1/3/5
    calendar-day assumption,
  - APPEND-ONLY: only fills an outcome into scored[horizon]; never rewrites a
    recorded scenario / price (no force-overwrite),
  - COHORT-aware aggregation (regime_sensor_fixed / tactical_benchmark_fixed /
    experimental_cohort), using the v4 scoring math (Brier + RPS + argmax),
  - market-clock honesty: US/crypto horizons can be HELD (experimental_invalid_
    clock) when the runner can't price them at the right time yet.

Designed to run ALONGSIDE the v3 scorer during a dry-run epoch — it takes records
+ an injected price_lookup, so it is fully unit-testable and never touches the v3
data itself.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

import argus_calibration as C

SCORER_VERSION = "ledger-v4-scorer-1"
# Per-market/kind ±band (≈ one daily sigma) — matches the v3 per-kind bands; the
# dynamic no-lookahead band (argus_calibration.volatility_band) can replace this
# once the workflow carries trailing closes.
DEFAULT_BANDS = {"JP": 2.0, "US": 2.0, "CRYPTO": 3.0, "FX": 0.5, "VIX": 8.0}
HORIZONS = ("1d", "3d", "5d")
# Markets the daily (post-JP-close) run can price correctly. US/crypto are held
# until market-specific jobs exist (mirrors the Layer 2B guard).
_VALID_DAILY_MARKETS = {"JP"}


def _scenarios_dict(scenarios: Any) -> Dict[str, float]:
    """Accept [{label,p}] (snapshot shape) or {label:p}; return {label:p}."""
    if isinstance(scenarios, dict):
        return {str(k): float(v) for k, v in scenarios.items()}
    out: Dict[str, float] = {}
    for s in scenarios or []:
        if isinstance(s, dict) and "label" in s:
            try:
                out[str(s["label"])] = float(s.get("p", 0))
            except (TypeError, ValueError):
                continue
    return out


def _record_band(rec: Dict[str, Any]) -> float:
    b = rec.get("bandPct")
    if isinstance(b, (int, float)) and b > 0:
        return float(b)
    return DEFAULT_BANDS.get(str(rec.get("market", "")).upper(), 2.0)


def _record_price(rec: Dict[str, Any]) -> Optional[float]:
    for k in ("priceAtPrediction", "price"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _targets(rec: Dict[str, Any]) -> Dict[str, str]:
    """horizon -> target date/timestamp from the record's marketClock."""
    mc = rec.get("marketClock") or {}
    out: Dict[str, str] = {}
    for t in mc.get("targets", []) or []:
        h = t.get("horizon")
        d = t.get("targetTradingDate") or t.get("targetTimestamp")
        if h and d:
            out[h] = str(d)
    return out


def horizon_due(target: Optional[str], today: str) -> bool:
    """A horizon is due once its target trading date has arrived (date-level)."""
    if not target:
        return False
    return str(target)[:10] <= today


def score_records(
    records: Sequence[Dict[str, Any]],
    price_lookup: Callable[[str], Optional[float]],
    today: str,
    *,
    valid_markets: Optional[set] = None,
) -> Dict[str, Any]:
    """Score due, unscored horizons in place (append-only). Returns counts.

    Each record needs: symbol, market, cohortId, scenarios, price(AtPrediction),
    marketClock.targets, and a `scored` dict. price_lookup(symbol) returns the
    realized price (the run-day close on/after the target date), or None.
    """
    valid = valid_markets if valid_markets is not None else _VALID_DAILY_MARKETS
    scored = held = 0
    for rec in records:
        sc = rec.get("scored")
        if not isinstance(sc, dict):
            sc = {h: None for h in HORIZONS}
            rec["scored"] = sc
        mkt = str(rec.get("market", "")).upper()
        tgts = _targets(rec)
        for h in HORIZONS:
            if sc.get(h) is not None:
                continue  # already scored — append-only, never re-touch
            if not horizon_due(tgts.get(h), today):
                continue
            if mkt not in valid:
                sc[h] = {"status": "experimental_invalid_clock",
                         "noteJa": "市場別クロック未実装のため採点保留"}
                held += 1
                continue
            realized = price_lookup(rec.get("symbol"))
            if realized is None:
                continue  # stays pending (retried next run)
            res = C.score_prediction(_scenarios_dict(rec.get("scenarios")),
                                     _record_price(rec), realized, _record_band(rec))
            if res:
                res["priceAsOf"] = today
                res["scorerVersion"] = SCORER_VERSION
                sc[h] = res
                scored += 1
    return {"scored": scored, "held": held, "scorerVersion": SCORER_VERSION}


def aggregate_by_cohort(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-cohort × horizon: n, hitRate, brierMean, rpsMean — numeric scores only
    (held/invalid-clock markers excluded). Never labels anything 'proven'."""
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for rec in records:
        cohort = rec.get("cohortId") or "unknown"
        sc = rec.get("scored") or {}
        for h in HORIZONS:
            x = sc.get(h)
            if isinstance(x, dict) and x.get("argmaxHit") is not None:
                buckets.setdefault(cohort, {}).setdefault(h, []).append(x)
    out: Dict[str, Any] = {"scorerVersion": SCORER_VERSION, "cohorts": {}}
    for cohort, by_h in buckets.items():
        ch: Dict[str, Any] = {}
        for h, lst in by_h.items():
            n = len(lst)
            hits = sum(1 for x in lst if x.get("argmaxHit"))
            brier = sum(x.get("brierNormalizedMean", 0) for x in lst) / n
            rps = sum(x.get("rpsNormalized", 0) for x in lst) / n
            ch[h] = {"n": n, "hitRate": round(hits / n, 4),
                     "brierMean": round(brier, 4), "rpsMean": round(rps, 4)}
        out["cohorts"][cohort] = ch
    return out
