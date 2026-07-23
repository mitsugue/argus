# -*- coding: utf-8 -*-
"""Deterministic Today forecast replay, calibration, and failed-rally facts.

The module is deliberately provider-agnostic and stdlib-only.  It never calls an
AI API, never sees owner holdings, and never treats daily short-selling turnover
as weekly credit balance or reported institutional short interest.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "argus-today-intelligence-v1"
METHOD_VERSION = "today-replay-calibration-v1"
CALIBRATION_VERSION = "beta-dirichlet-walk-forward-v1"
MIN_EFFECTIVE_SAMPLES = 30
HORIZONS = (1, 5, 20)
UNIFORM_MULTICLASS_BRIER = 2.0 / 3.0
MAX_BRIER_DEGRADATION = 0.02


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _hash(value: Any, length: int = 24) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None else round(value, digits)


def normalize_bars(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return ascending, valid OHLCV rows without inventing missing values."""
    out: Dict[str, Dict[str, Any]] = {}
    for raw in rows or []:
        date = str(raw.get("date") or raw.get("Date") or "")[:10]
        open_ = _number(raw.get("open", raw.get("O")))
        high = _number(raw.get("high", raw.get("H")))
        low = _number(raw.get("low", raw.get("L")))
        close = _number(raw.get("close", raw.get("C")))
        if len(date) != 10 or min(open_ or 0, high or 0, low or 0, close or 0) <= 0:
            continue
        volume = _number(raw.get("volume", raw.get("Vo")))
        out[date] = {
            "date": date, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
            "source": raw.get("source") or "existing_market_data_cache",
            "availableFrom": str(raw.get("availableFrom") or date),
            "observedAt": raw.get("observedAt"),
            "revision": int(raw.get("revision") or 0),
            "adjusted": bool(raw.get("adjusted", True)),
        }
    return [out[key] for key in sorted(out)]


def normalize_short_history(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize the JPX/J-Quants *daily turnover* series (not a balance)."""
    by_date: Dict[str, Dict[str, Any]] = {}
    for raw in rows or []:
        date = str(raw.get("date") or raw.get("Date") or "")[:10]
        sell_ex = _number(raw.get("sellingExcludingShortValue", raw.get("SellExShortVa")))
        regulated = _number(raw.get("regulatedShortValue", raw.get("ShrtWithResVa")))
        non_regulated = _number(raw.get("nonRegulatedShortValue", raw.get("ShrtNoResVa")))
        # normalize_short_history is intentionally idempotent so restored
        # durable rows can pass through the same validator as provider rows.
        if regulated is None:
            regulated = _number(raw.get("regulatedShortValue"))
        if non_regulated is None:
            non_regulated = _number(raw.get("nonRegulatedShortValue"))
        if sell_ex is None:
            total_existing = _number(raw.get("totalTradingValue"))
            short_existing = _number(raw.get("totalShortSellingValue"))
            if total_existing is not None and short_existing is not None:
                sell_ex = total_existing - short_existing
        if len(date) != 10 or sell_ex is None or regulated is None or non_regulated is None:
            continue
        total = sell_ex + regulated + non_regulated
        short_value = regulated + non_regulated
        if total <= 0:
            continue
        by_date[date] = {
            "date": date,
            "totalTradingValue": total,
            "totalShortSellingValue": short_value,
            "totalShortRatio": short_value / total * 100.0,
            "regulatedShortValue": regulated,
            "nonRegulatedShortValue": non_regulated,
            "source": raw.get("source") or "J-Quants /markets/short-ratio S33=0050",
            "publishedAt": raw.get("publishedAt") or date,
            "availableFrom": raw.get("availableFrom") or date,
            "observedAt": raw.get("observedAt"),
            "revision": int(raw.get("revision") or 0),
            "unit": "JPY",
        }
    ordered = [by_date[key] for key in sorted(by_date)]
    ratios: List[float] = []
    for index, row in enumerate(ordered):
        ratio = float(row["totalShortRatio"])
        ratios.append(ratio)
        previous = ratios[index - 1] if index else None
        history = ratios[:index + 1]
        row["previousDayDifference"] = None if previous is None else ratio - previous
        row["average5"] = _mean(history[-5:]) if len(history) >= 5 else None
        row["average20"] = _mean(history[-20:]) if len(history) >= 20 else None
        row["rollingPercentile"] = (100.0 * sum(1 for value in history[-1300:] if value <= ratio)
                                    / len(history[-1300:]))
        for key in ("totalShortRatio", "previousDayDifference", "average5",
                    "average20", "rollingPercentile"):
            row[key] = _round(row.get(key), 3)
    return ordered


def short_selling_summary(rows: Iterable[Dict[str, Any]], as_of: Optional[str] = None) -> Dict[str, Any]:
    history = normalize_short_history(rows)
    if as_of:
        history = [row for row in history if row["date"] <= as_of[:10]]
    if not history:
        return {
            "schemaVersion": "argus-daily-short-selling-v1",
            "status": "missing", "latest": None, "historyStart": None,
            "historyCount": 0, "missingReason": "daily_short_ratio_unavailable",
            "seriesType": "daily_short_selling_turnover",
        }
    latest = dict(history[-1])
    return {
        "schemaVersion": "argus-daily-short-selling-v1",
        "status": "live", "latest": latest,
        "historyStart": history[0]["date"], "historyCount": len(history),
        "latestDate": latest["date"], "publicationTiming": "JPX after daily close",
        "freshness": "close", "coverage": "TSE auction-market aggregate S33=0050",
        "seriesType": "daily_short_selling_turnover",
        "weeklyCreditShortIsSeparate": True,
        "institutionalShortIsSeparate": True,
        "missingReason": None,
    }


def _feature(bars: Sequence[Dict[str, Any]], index: int) -> Optional[Dict[str, float]]:
    if index < 24:
        return None
    close = float(bars[index]["close"])
    closes20 = [float(row["close"]) for row in bars[index - 19:index + 1]]
    ma20 = sum(closes20) / 20
    tr: List[float] = []
    for pos in range(index - 13, index + 1):
        prev_close = float(bars[pos - 1]["close"]) if pos else float(bars[pos]["close"])
        row = bars[pos]
        tr.append(max(float(row["high"]) - float(row["low"]),
                      abs(float(row["high"]) - prev_close),
                      abs(float(row["low"]) - prev_close)))
    atr_pct = (sum(tr) / len(tr)) / close
    high = float(bars[index]["high"])
    low = float(bars[index]["low"])
    location = (close - low) / (high - low) if high > low else .5
    momentum5 = close / float(bars[index - 5]["close"]) - 1
    trend = close / ma20 - 1
    volume_values = [_number(row.get("volume")) for row in bars[index - 19:index + 1]]
    clean_volume = [value for value in volume_values if value is not None and value > 0]
    volume_ratio = 1.0
    current_volume = _number(bars[index].get("volume"))
    if current_volume and clean_volume:
        volume_ratio = current_volume / (sum(clean_volume) / len(clean_volume))
    return {"trend20": trend, "momentum5": momentum5, "atrPct": atr_pct,
            "closeLocation": location, "volumeRatio": volume_ratio}


def _signal_family(feature: Dict[str, float]) -> str:
    if feature["trend20"] >= .01 and feature["momentum5"] >= 0:
        return "trend_up"
    if feature["trend20"] <= -.01 and feature["momentum5"] <= 0:
        return "trend_down"
    return "range"


def _distance(left: Dict[str, float], right: Dict[str, float]) -> float:
    scales = {"trend20": .05, "momentum5": .04, "atrPct": .015,
              "closeLocation": .5, "volumeRatio": 1.0}
    return math.sqrt(sum(((left[key] - right[key]) / scales[key]) ** 2 for key in scales))


def _direction(return_pct: float, atr_pct: float, horizon: int) -> str:
    threshold = max(.003, atr_pct * math.sqrt(horizon) * .35)
    return "UP" if return_pct > threshold else "DOWN" if return_pct < -threshold else "RANGE"


def _episodes(candidates: Sequence[Dict[str, Any]], cooldown: int) -> List[Dict[str, Any]]:
    """Keep one best occurrence per family and non-overlapping trading window."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        family = str(candidate.get("family") or candidate.get("state") or "default")
        grouped.setdefault(family, []).append(candidate)
    selected: List[Dict[str, Any]] = []
    for family_rows in grouped.values():
        family_selected: List[Dict[str, Any]] = []
        for candidate in sorted(family_rows, key=lambda row: (row["index"], row["distance"])):
            if family_selected and candidate["index"] - family_selected[-1]["index"] <= cooldown:
                if candidate["distance"] < family_selected[-1]["distance"]:
                    family_selected[-1] = candidate
                continue
            family_selected.append(candidate)
        selected.extend(family_selected)
    return sorted(selected, key=lambda row: (row["index"], row.get("distance", 0.0)))


def _integer_probabilities(values: Dict[str, float]) -> Dict[str, int]:
    raw = {key: max(0.0, value) * 100 for key, value in values.items()}
    base = {key: int(math.floor(value)) for key, value in raw.items()}
    remaining = 100 - sum(base.values())
    order = sorted(raw, key=lambda key: (raw[key] - base[key], key), reverse=True)
    for key in order[:remaining]:
        base[key] += 1
    return base


def _walk_forward_brier(episodes: Sequence[Dict[str, Any]]) -> Optional[float]:
    labels = ("UP", "RANGE", "DOWN")
    counts = {label: 0 for label in labels}
    scores: List[float] = []
    # A fixed symmetric prior is intentional.  Using the full-sample base rate
    # here would leak labels from later episodes into earlier walk-forward
    # predictions, even though the live forecast itself only uses past bars.
    prior_weight = 12.0
    prior = 1.0 / len(labels)
    for index, episode in enumerate(episodes):
        if index >= 10:
            denominator = index + prior_weight
            prediction = {label: (counts[label] + prior_weight * prior) / denominator
                          for label in labels}
            actual = episode["direction"]
            scores.append(sum((prediction[label] - (1.0 if label == actual else 0.0)) ** 2
                              for label in labels))
        counts[episode["direction"]] += 1
    return _mean(scores)


def _confidence_interval(probability: float, effective_n: int) -> Dict[str, float]:
    # Normal approximation over a shrunk posterior.  Stored as a quality range,
    # not presented as a guaranteed market interval.
    n = effective_n + 12
    delta = 1.96 * math.sqrt(max(0.0, probability * (1 - probability) / n))
    return {"low": round(max(0.0, probability - delta) * 100, 1),
            "high": round(min(1.0, probability + delta) * 100, 1)}


def calibrate_horizon(bars: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    normalized = normalize_bars(bars)
    if len(normalized) < 80 + horizon:
        return {"horizon": horizon, "calibrationStatus": "insufficient_history",
                "rawOccurrenceCount": 0, "episodeCount": 0, "effectiveSampleCount": 0,
                "probabilities": None}
    current_feature = _feature(normalized, len(normalized) - 1)
    if current_feature is None:
        return {"horizon": horizon, "calibrationStatus": "insufficient_history",
                "rawOccurrenceCount": 0, "episodeCount": 0, "effectiveSampleCount": 0,
                "probabilities": None}
    family = _signal_family(current_feature)
    all_rows: List[Dict[str, Any]] = []
    for index in range(24, len(normalized) - horizon):
        feature = _feature(normalized, index)
        if feature is None:
            continue
        start = float(normalized[index]["close"])
        end = float(normalized[index + horizon]["close"])
        future = normalized[index + 1:index + horizon + 1]
        high_return = max(float(row["high"]) for row in future) / start - 1
        low_return = min(float(row["low"]) for row in future) / start - 1
        final_return = end / start - 1
        all_rows.append({
            "index": index, "date": normalized[index]["date"],
            "distance": _distance(feature, current_feature),
            "family": _signal_family(feature), "atrPct": feature["atrPct"],
            "return": final_return, "mfe": high_return, "mae": low_return,
            "direction": _direction(final_return, feature["atrPct"], horizon),
        })
    family_rows = [row for row in all_rows if row["family"] == family]
    pool = family_rows if len(family_rows) >= 60 else all_rows
    nearest = sorted(pool, key=lambda row: (row["distance"], row["date"]))[:240]
    episodes = _episodes(nearest, max(1, horizon))
    labels = ("UP", "RANGE", "DOWN")
    base_candidates = _episodes(all_rows, max(1, horizon))
    base_counts = {label: sum(1 for row in base_candidates if row["direction"] == label)
                   for label in labels}
    base_total = max(1, sum(base_counts.values()))
    base = {label: base_counts[label] / base_total for label in labels}
    counts = {label: sum(1 for row in episodes if row["direction"] == label) for label in labels}
    n = len(episodes)
    prior_weight = 12.0
    posterior = {label: (counts[label] + prior_weight * base[label]) / (n + prior_weight)
                 for label in labels}
    probabilities = _integer_probabilities(posterior)
    brier = _walk_forward_brier(episodes)
    base_brier = 1.0 - sum(value * value for value in base.values())
    # The walk-forward score and the full-history class base rate are useful but
    # are not the same estimand.  The visibility gate therefore compares the
    # prequential score with the fixed three-class random baseline.  The
    # historical base-rate score remains stored as a separate comparison, never
    # as a falsely out-of-sample benchmark.
    status = ("insufficient_sample" if n < MIN_EFFECTIVE_SAMPLES else
              "poor_calibration" if brier is None or
              brier > UNIFORM_MULTICLASS_BRIER + MAX_BRIER_DEGRADATION else
              "calibrated")
    returns = [row["return"] for row in episodes]
    mfes = [row["mfe"] for row in episodes]
    maes = [row["mae"] for row in episodes]
    q10, q25, q50, q75, q90 = (_quantile(returns, q) for q in (.10, .25, .50, .75, .90))
    upper_touch = (sum(1 for row in episodes if q75 is not None and row["mfe"] >= q75) / n
                   if n else None)
    lower_touch = (sum(1 for row in episodes if q25 is not None and row["mae"] <= q25) / n
                   if n else None)
    close_in_band = (sum(1 for row in episodes if q25 is not None and q75 is not None
                         and q25 <= row["return"] <= q75) / n if n else None)
    invalidation_touch = (sum(1 for row in episodes if q10 is not None and row["mae"] <= q10) / n
                          if n else None)
    ci = {label: _confidence_interval(posterior[label], n) for label in labels}
    # Percentages are withheld unless all calibration gates pass.
    visible = probabilities if status == "calibrated" else None
    return {
        "horizon": horizon, "signalFamily": family,
        "rawOccurrenceCount": len(pool), "episodeCount": n,
        "effectiveSampleCount": n, "cooldownTradingDays": max(1, horizon),
        "calibrationStatus": status, "probabilities": visible,
        "unroundedProbabilities": ({key: round(value * 100, 3) for key, value in posterior.items()}
                                   if status == "calibrated" else None),
        "baseRates": {key: round(value * 100, 2) for key, value in base.items()},
        "brierScore": _round(brier, 4), "baseRateBrierScore": _round(base_brier, 4),
        "uniformBaselineBrierScore": _round(UNIFORM_MULTICLASS_BRIER, 4),
        "brierGateMaximum": _round(UNIFORM_MULTICLASS_BRIER + MAX_BRIER_DEGRADATION, 4),
        "confidenceInterval": ci if status == "calibrated" else None,
        "noFutureLeakage": True, "walkForward": True,
        "calibrationDatasetFixedAt": normalized[-1]["date"],
        "calibrationDatasetHash": _hash([
            (row["date"], row["open"], row["high"], row["low"], row["close"], row.get("volume"))
            for row in normalized
        ], 32),
        "calibrationVersion": CALIBRATION_VERSION,
        "methodVersion": METHOD_VERSION,
        "returnDistribution": {
            "q10": _round(q10), "q25": _round(q25), "median": _round(q50),
            "q75": _round(q75), "q90": _round(q90),
            "meanMfe": _round(_mean(mfes)), "meanMae": _round(_mean(maes)),
        },
        "targetProbabilities": ({
            "upperTargetTouch": round(upper_touch * 100, 1) if upper_touch is not None else None,
            "baseRangeClose": round(close_in_band * 100, 1) if close_in_band is not None else None,
            "lowerTargetTouch": round(lower_touch * 100, 1) if lower_touch is not None else None,
            "invalidationTouch": round(invalidation_touch * 100, 1) if invalidation_touch is not None else None,
        } if status == "calibrated" else None),
        "averageReactionDelay": _round(_mean([
            next((day for day in range(1, horizon + 1)
                  if ((normalized[row["index"] + day]["close"] /
                       normalized[row["index"]]["close"] - 1) > 0) ==
                  (row["return"] > 0)), horizon)
            for row in episodes
        ]), 2),
    }


def calibrate_forecast(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    bars = normalize_bars(rows)
    result = {str(horizon): calibrate_horizon(bars, horizon) for horizon in HORIZONS}
    return {
        "schemaVersion": "argus-forecast-calibration-v1",
        "methodVersion": METHOD_VERSION,
        "calibrationVersion": CALIBRATION_VERSION,
        "historyStart": bars[0]["date"] if bars else None,
        "historyEnd": bars[-1]["date"] if bars else None,
        "historyCount": len(bars), "horizons": result,
        "automaticAiCalls": 0,
    }


def failed_rally_state(previous: Dict[str, Any], current: Dict[str, Any], *,
                       short_change: Optional[float] = None,
                       breadth_divergence: bool = False) -> Dict[str, Any]:
    prev_close = _number(previous.get("close"))
    open_ = _number(current.get("open")); high = _number(current.get("high"))
    low = _number(current.get("low")); close = _number(current.get("close"))
    if None in (prev_close, open_, high, low, close) or min(prev_close, open_, high, low, close) <= 0:
        return {"state": "NONE", "facts": [], "metrics": {}}
    daily_range = max(1e-12, high - low)
    gap = (open_ / prev_close - 1) * 100
    high_to_close = (high / close - 1) * 100
    close_vs_previous = (close / prev_close - 1) * 100
    location = (close - low) / daily_range
    upper_wick = (high - max(open_, close)) / daily_range
    volume_ratio = _number(current.get("volumeRatio20"))
    conditions = {
        "gapUp": gap >= .5,
        "highToCloseDecline": high_to_close >= 1.0,
        "closeBelowPrevious": close_vs_previous < 0,
        "weakCloseLocation": location <= .35,
        "upperWick": upper_wick >= .35,
        "volumeConfirmed": volume_ratio is not None and volume_ratio >= 1.1,
        "shortRatioFell": short_change is not None and short_change <= -1.5,
        "breadthDivergence": bool(breadth_divergence),
    }
    core = conditions["gapUp"] and conditions["highToCloseDecline"]
    confirmed = (core and conditions["closeBelowPrevious"] and conditions["weakCloseLocation"]
                 and any(conditions[key] for key in
                         ("volumeConfirmed", "shortRatioFell", "breadthDivergence", "upperWick")))
    watch = core and sum(1 for value in conditions.values() if value) >= 3
    state = "CONFIRMED" if confirmed else "WATCH" if watch else "NONE"
    labels = {
        "gapUp": "寄り付きギャップ高", "highToCloseDecline": "高値から終値へ失速",
        "closeBelowPrevious": "終値が前日比マイナス", "weakCloseLocation": "日中安値圏引け",
        "upperWick": "長い上ヒゲ", "volumeConfirmed": "出来高増",
        "shortRatioFell": "日次SHORT比率が低下", "breadthDivergence": "指数間の方向乖離",
    }
    return {
        "state": state, "facts": [labels[key] for key, value in conditions.items() if value],
        "conditions": conditions,
        "metrics": {"gapUpPct": round(gap, 2), "highToClosePct": round(high_to_close, 2),
                    "closeVsPreviousPct": round(close_vs_previous, 2),
                    "closeLocation": round(location, 3), "upperWickRatio": round(upper_wick, 3),
                    "volumeRatio20": volume_ratio, "shortRatioChangePt": short_change},
    }


def _comparison_divergence(primary: Sequence[Dict[str, Any]], comparison: Sequence[Dict[str, Any]],
                           date: str) -> bool:
    by_primary = {row["date"]: row for row in primary}
    by_comparison = {row["date"]: row for row in comparison}
    dates = sorted(set(by_primary) & set(by_comparison))
    if date not in dates:
        return False
    index = dates.index(date)
    if index < 1:
        return False
    previous = dates[index - 1]
    p = float(by_primary[date]["close"]) / float(by_primary[previous]["close"]) - 1
    c = float(by_comparison[date]["close"]) / float(by_comparison[previous]["close"]) - 1
    return p * c < 0


def failed_rally_backtest(rows: Iterable[Dict[str, Any]], *,
                          short_history: Iterable[Dict[str, Any]] = (),
                          comparison_rows: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    bars = normalize_bars(rows)
    comparison = normalize_bars(comparison_rows)
    short_rows = normalize_short_history(short_history)
    short_by_date = {row["date"]: row for row in short_rows}
    cases: List[Dict[str, Any]] = []
    for index in range(1, len(bars) - 20):
        current = dict(bars[index])
        volume_window = [_number(row.get("volume")) for row in bars[max(0, index - 19):index + 1]]
        clean = [value for value in volume_window if value and value > 0]
        if clean and current.get("volume"):
            current["volumeRatio20"] = float(current["volume"]) / (sum(clean) / len(clean))
        short = short_by_date.get(current["date"])
        state = failed_rally_state(
            bars[index - 1], current,
            short_change=_number((short or {}).get("previousDayDifference")),
            breadth_divergence=_comparison_divergence(bars, comparison, current["date"]),
        )
        if state["state"] == "NONE":
            continue
        start = float(current["close"])
        outcomes = {str(h): round((float(bars[index + h]["close"]) / start - 1) * 100, 3)
                    for h in HORIZONS}
        future = bars[index + 1:index + 21]
        cases.append({"index": index, "date": current["date"], "state": state["state"],
                      "facts": state["facts"], "outcomes": outcomes,
                      "mfe20Pct": round((max(float(row["high"]) for row in future) / start - 1) * 100, 3),
                      "mae20Pct": round((min(float(row["low"]) for row in future) / start - 1) * 100, 3)})
    effective = _episodes([{**row, "distance": 0.0} for row in cases], 5)
    summary: Dict[str, Any] = {}
    for horizon in HORIZONS:
        values = [row["outcomes"][str(horizon)] for row in effective]
        summary[str(horizon)] = {
            "averageReturnPct": _round(_mean(values), 3),
            "declineRatePct": _round(100 * sum(1 for value in values if value < 0) / len(values), 1)
            if values else None,
        }
    return {
        "rawOccurrenceCount": len(cases), "episodeCount": len(effective),
        "effectiveSampleCount": len(effective), "cooldownTradingDays": 5,
        "outcomes": summary,
        "meanMfe20Pct": _round(_mean([row["mfe20Pct"] for row in effective]), 3),
        "meanMae20Pct": _round(_mean([row["mae20Pct"] for row in effective]), 3),
        "probability": (summary["5"]["declineRatePct"]
                        if len(effective) >= MIN_EFFECTIVE_SAMPLES else None),
        "calibrationStatus": ("calibrated" if len(effective) >= MIN_EFFECTIVE_SAMPLES
                              else "insufficient_sample"),
        "cases": [{key: row[key] for key in ("date", "state", "outcomes", "mfe20Pct", "mae20Pct")}
                  for row in effective[-40:]],
        "noFutureLeakage": True, "methodVersion": METHOD_VERSION,
    }


def analyze(rows: Iterable[Dict[str, Any]], *, symbol: str, market: str,
            short_history: Iterable[Dict[str, Any]] = (),
            comparison_rows: Iterable[Dict[str, Any]] = (),
            as_of: Optional[str] = None) -> Dict[str, Any]:
    bars = normalize_bars(rows)
    short_rows = normalize_short_history(short_history)
    short_summary = short_selling_summary(short_rows, as_of)
    comparison = normalize_bars(comparison_rows)
    current_failed = {"state": "NONE", "facts": [], "metrics": {}}
    if len(bars) >= 2:
        current = dict(bars[-1])
        volumes = [_number(row.get("volume")) for row in bars[-20:]]
        clean = [value for value in volumes if value and value > 0]
        if clean and current.get("volume"):
            current["volumeRatio20"] = float(current["volume"]) / (sum(clean) / len(clean))
        current_failed = failed_rally_state(
            bars[-2], current,
            short_change=_number(((short_summary.get("latest") or {}).get("previousDayDifference"))),
            breadth_divergence=_comparison_divergence(bars, comparison, bars[-1]["date"]),
        )
    calibration = calibrate_forecast(bars)
    backtest = failed_rally_backtest(bars, short_history=short_rows,
                                     comparison_rows=comparison)
    return {
        "schemaVersion": SCHEMA_VERSION, "methodVersion": METHOD_VERSION,
        "symbol": symbol, "market": market,
        "asOf": as_of or (bars[-1]["date"] if bars else None),
        "historyCoverage": {"start": bars[0]["date"] if bars else None,
                            "end": bars[-1]["date"] if bars else None,
                            "count": len(bars)},
        "calibration": calibration, "shortSelling": short_summary,
        "failedRally": {**current_failed, "backtest": backtest,
                        "probability": (backtest.get("probability")
                                        if current_failed.get("state") != "NONE" else None)},
        "automaticAiCalls": 0,
    }


def empty_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "snapshots": [],
            "shortSellingHistory": [], "failedRallyOutcomes": [],
            "lastUpdatedAt": None, "methodVersion": METHOD_VERSION}


def normalize_state(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    out = empty_state()
    for key in ("snapshots", "shortSellingHistory", "failedRallyOutcomes"):
        out[key] = [row for row in source.get(key, []) if isinstance(row, dict)]
    out["lastUpdatedAt"] = source.get("lastUpdatedAt")
    return out


def merge_state(local: Dict[str, Any], remote: Dict[str, Any]) -> Dict[str, Any]:
    out = normalize_state(local)
    incoming = normalize_state(remote)
    identities = {"snapshots": "id", "shortSellingHistory": "date",
                  "failedRallyOutcomes": "id"}
    for key, identity in identities.items():
        by_identity = {row.get(identity): row for row in out[key] if row.get(identity) is not None}
        for row in incoming[key]:
            row_id = row.get(identity)
            if row_id not in by_identity:
                out[key].append(row)
                by_identity[row_id] = row
            elif key == "shortSellingHistory" and \
                    int(row.get("revision") or 0) > int(by_identity[row_id].get("revision") or 0):
                by_identity[row_id].update(row)
        out[key].sort(key=lambda row: str(row.get("date") or row.get("asOf") or row.get("id") or ""))
    out["lastUpdatedAt"] = max(str(out.get("lastUpdatedAt") or ""),
                               str(incoming.get("lastUpdatedAt") or "")) or None
    return out


def merge_analysis(state: Dict[str, Any], analysis: Dict[str, Any],
                   latest_bar: Optional[Dict[str, Any]],
                   short_history: Iterable[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    out = normalize_state(state)
    for row in normalize_short_history(short_history):
        existing = next((item for item in out["shortSellingHistory"]
                         if item.get("date") == row["date"]), None)
        if existing is None:
            out["shortSellingHistory"].append(row)
        elif int(row.get("revision") or 0) > int(existing.get("revision") or 0):
            existing.update(row)
    snapshot_body = {
        "symbol": analysis.get("symbol"), "market": analysis.get("market"),
        "asOf": analysis.get("asOf"), "ohlcv": latest_bar,
        "calibration": analysis.get("calibration"),
        "shortSelling": analysis.get("shortSelling"),
        "failedRally": analysis.get("failedRally"),
        "methodVersion": METHOD_VERSION,
    }
    snapshot = {**snapshot_body, "id": "today-" + _hash(snapshot_body)}
    if snapshot["id"] not in {row.get("id") for row in out["snapshots"]}:
        out["snapshots"].append(snapshot)
    for row in (((analysis.get("failedRally") or {}).get("backtest") or {}).get("cases") or []):
        if not isinstance(row, dict) or not row.get("date"):
            continue
        body = {**row, "symbol": analysis.get("symbol"), "market": analysis.get("market"),
                "methodVersion": METHOD_VERSION}
        item = {**body, "id": "failed-rally-" + _hash(body)}
        if item["id"] not in {x.get("id") for x in out["failedRallyOutcomes"]}:
            out["failedRallyOutcomes"].append(item)
    out["snapshots"].sort(key=lambda row: str(row.get("asOf") or row.get("id") or ""))
    out["shortSellingHistory"] = sorted(out["shortSellingHistory"],
                                         key=lambda row: row.get("date") or "")
    out["failedRallyOutcomes"].sort(key=lambda row: str(row.get("date") or row.get("id") or ""))
    out["lastUpdatedAt"] = now_iso
    return out


def state_hash(state: Dict[str, Any]) -> str:
    normalized = normalize_state(state)
    return _hash({key: normalized[key] for key in
                  ("snapshots", "shortSellingHistory", "failedRallyOutcomes")}, 32)


def read_back_verified(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return state_hash(local) == state_hash(remote)


def data_source_audit(short_summary: Dict[str, Any], institutional_status: str) -> List[Dict[str, Any]]:
    latest = short_summary.get("latest") or {}
    return [
        {"seriesId": "weekly_credit_short_balance", "labelJa": "二市場合計信用売り残",
         "frequency": "weekly", "source": "JPX official / Market Ledger",
         "endpointOrFile": "Market Ledger credit.short_balance",
         "publicationTiming": "JPX weekly publication",
         "unit": "JPY", "schema": "market-ledger credit.short_balance",
         "isDailyShortRatio": False},
        {"seriesId": "daily_short_selling_activity", "labelJa": "日次空売り売買代金・比率",
         "frequency": "daily", "source": latest.get("source"), "unit": latest.get("unit"),
         "endpointOrFile": "J-Quants v2 /markets/short-ratio?s33=0050",
         "publicationTiming": short_summary.get("publicationTiming"),
         "latestDate": short_summary.get("latestDate"),
         "historyStart": short_summary.get("historyStart"),
         "coverage": short_summary.get("coverage"), "freshness": short_summary.get("freshness"),
         "status": short_summary.get("status"), "missingReason": short_summary.get("missingReason"),
         "schema": short_summary.get("schemaVersion"), "isWeeklyCreditBalance": False},
        {"seriesId": "reported_institutional_short_positions", "labelJa": "公表大口空売り残高",
         "frequency": "daily disclosures when threshold reports exist",
         "source": "JPX official short-position reports", "unit": "shares / ratio",
         "endpointOrFile": "JPX reported short-position files / existing entry-scout adapter",
         "publicationTiming": "calculation date and publication date retained separately",
         "status": institutional_status, "schema": "entry-scout shortDisclosed",
         "isDailyShortRatio": False, "isWeeklyCreditBalance": False},
    ]
