# -*- coding: utf-8 -*-
"""Deterministic Market Context Replay.

All calculations are provider-agnostic, public-safe and stdlib-only.  A replay
uses information whose ``availableFrom`` is no later than the replay date,
groups overlapping observations into one episode, and never calls an LLM.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import argus_today_intelligence


SCHEMA_VERSION = "argus-market-replay-v1"
METHOD_VERSION = "market-context-replay-v1"
FEATURE_VERSION = "replay-features-past-window-v1"
REACTION_VERSION = "reaction-classification-v1"
EXTREME_VERSION = "ledger-extremes-fixed-thresholds-v1"
HORIZONS = (1, 5, 20)
COOLDOWN_TRADING_DAYS = 5
MAX_EPISODES = 40
MIN_REGIME_SAMPLE = 20
EXTREME_THRESHOLDS = (1, 5, 10, 90, 95, 99)


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None else round(value, digits)


def _hash(value: Any, length: int = 32) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def _dataset_hash_from_bars(bars: Sequence[Dict[str, Any]]) -> str:
    return _hash([{
        "date": row["date"], "close": row["close"],
        "availableFrom": row["availableFrom"],
    } for row in bars])


def dataset_hash(rows: Iterable[Dict[str, Any]]) -> str:
    """Return the public cache-key hash without running Replay analysis."""
    return _dataset_hash_from_bars(
        argus_today_intelligence.normalize_bars(rows))


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    low, high = int(math.floor(pos)), int(math.ceil(pos))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _distribution(values: Iterable[Optional[float]]) -> Dict[str, Any]:
    clean = [float(value) for value in values if _number(value) is not None]
    if not clean:
        return {"count": 0, "q10": None, "q25": None, "median": None,
                "q75": None, "q90": None, "min": None, "max": None,
                "histogram": []}
    low, high = min(clean), max(clean)
    width = (high - low) / 10 if high > low else 1.0
    counts = [0] * 10
    for value in clean:
        index = min(9, max(0, int((value - low) / width)))
        counts[index] += 1
    return {
        "count": len(clean),
        "q10": _round(_quantile(clean, .10), 3),
        "q25": _round(_quantile(clean, .25), 3),
        "median": _round(_quantile(clean, .50), 3),
        "q75": _round(_quantile(clean, .75), 3),
        "q90": _round(_quantile(clean, .90), 3),
        "min": _round(low, 3), "max": _round(high, 3),
        "histogram": [
            {"from": _round(low + index * width, 3),
             "to": _round(low + (index + 1) * width, 3),
             "count": count}
            for index, count in enumerate(counts)
        ],
    }


def _past_z(features: Sequence[Dict[str, float]], index: int,
            key: str, window: int = 252) -> float:
    """Past-only standardisation; the current observation is not in training."""
    values = [row[key] for row in features[max(0, index - window):index]
              if key in row]
    if len(values) < 8:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    deviation = math.sqrt(variance)
    return (features[index][key] - mean) / deviation if deviation > 1e-12 else 0.0


def _feature_rows(bars: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw: List[Dict[str, float]] = []
    indexed: List[Tuple[int, Dict[str, float]]] = []
    for index in range(len(bars)):
        feature = argus_today_intelligence._feature(bars, index)
        if feature is None:
            raw.append({})
            continue
        raw.append(feature)
        indexed.append((index, feature))
    keys = ("trend20", "momentum5", "atrPct", "closeLocation", "volumeRatio")
    result: List[Dict[str, Any]] = []
    for index, feature in indexed:
        # Standardisation sees only features that existed before this bar.
        z = {key: _past_z(raw, index, key) for key in keys}
        result.append({
            "index": index, "date": bars[index]["date"], "raw": feature, "z": z,
            "family": ("uptrend" if feature["trend20"] >= .01 else
                       "downtrend" if feature["trend20"] <= -.01 else "range"),
            "volatility": ("high_volatility" if feature["atrPct"] >= .025 else
                           "low_volatility" if feature["atrPct"] <= .012 else
                           "normal_volatility"),
        })
    return result


def _distance(left: Dict[str, float], right: Dict[str, float]) -> float:
    keys = ("trend20", "momentum5", "atrPct", "closeLocation", "volumeRatio")
    return math.sqrt(sum((left.get(key, 0.0) - right.get(key, 0.0)) ** 2
                         for key in keys) / len(keys))


def _classify_reaction(changes: Sequence[float], threshold: float) -> Tuple[str, Optional[int]]:
    """Fixed v1 boundaries: immediate 0–1, short delay 2–5, medium 6–20."""
    if not changes:
        return "no_reaction", None
    first_up = next((index + 1 for index, value in enumerate(changes)
                     if value >= threshold), None)
    first_down = next((index + 1 for index, value in enumerate(changes)
                       if value <= -threshold), None)
    final = changes[-1]
    if max(abs(value) for value in changes) < threshold:
        return "no_reaction", None
    if final >= threshold:
        if first_down is not None and first_down < (first_up or 999):
            return "reverse_then_up", first_up
        return ("immediate_up" if (first_up or 99) <= 1 else "delayed_up"), first_up
    if final <= -threshold:
        if first_up is not None and first_up < (first_down or 999):
            return "reverse_then_down", first_down
        return ("immediate_down" if (first_down or 99) <= 1 else "delayed_down"), first_down
    peak = max(changes)
    trough = min(changes)
    if peak >= threshold and final <= threshold * .25:
        return "failed_breakout", first_up
    if trough <= -threshold and final >= -threshold * .25:
        return "failed_breakdown", first_down
    return "range", min(value for value in (first_up, first_down) if value is not None)


def _outcome(bars: Sequence[Dict[str, Any]], index: int) -> Dict[str, Any]:
    start = float(bars[index]["close"])
    future = bars[index + 1:index + 21]
    changes = [(float(row["close"]) / start - 1) * 100 for row in future]
    atr_pct = float((argus_today_intelligence._feature(bars, index) or {})
                    .get("atrPct") or .01)
    reaction, delay = _classify_reaction(
        changes, max(.3, atr_pct * 100 * .35))
    return {
        "1": _round(changes[0], 3) if len(changes) >= 1 else None,
        "5": _round(changes[4], 3) if len(changes) >= 5 else None,
        "20": _round(changes[19], 3) if len(changes) >= 20 else None,
        "mfe": _round(max((float(row["high"]) / start - 1) * 100
                          for row in future), 3) if future else None,
        "mae": _round(min((float(row["low"]) / start - 1) * 100
                          for row in future), 3) if future else None,
        "reactionClass": reaction, "reactionDelayDays": delay,
    }


def _episode_index(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    features = _feature_rows(bars)
    if not features:
        return {"rawOccurrenceCount": 0, "effectiveSampleCount": 0,
                "episodes": [], "currentFeatures": {}}
    current = features[-1]
    candidates: List[Dict[str, Any]] = []
    for feature in features[:-20]:
        distance = _distance(current["z"], feature["z"])
        candidates.append({
            "index": feature["index"], "date": feature["date"],
            "family": feature["family"], "volatility": feature["volatility"],
            "distance": distance,
            "similarityPct": _round(100 / (1 + distance), 1),
            "features": feature["raw"],
            "dataCoverage": "price_volume",
            "outcomes": _outcome(bars, feature["index"]),
        })
    raw_count = len(candidates)
    # One best observation per rolling cooldown window, then nearest 40.
    grouped: List[Dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda row: row["index"]):
        if grouped and candidate["index"] - grouped[-1]["index"] <= COOLDOWN_TRADING_DAYS:
            if candidate["distance"] < grouped[-1]["distance"]:
                grouped[-1] = candidate
            continue
        grouped.append(candidate)
    selected = sorted(grouped, key=lambda row: (row["distance"], row["date"]))[:MAX_EPISODES]
    for rank, row in enumerate(selected, 1):
        row["rank"] = rank
        row["episodeId"] = "episode-" + _hash({
            "date": row["date"], "family": row["family"],
            "method": METHOD_VERSION,
        }, 20)
        row["episodeStart"] = row["date"]
        row["episodePeak"] = row["outcomes"].get("mfe")
    return {
        "rawOccurrenceCount": raw_count,
        "groupedEpisodeCount": len(grouped),
        "effectiveSampleCount": len(selected),
        "cooldownTradingDays": COOLDOWN_TRADING_DAYS,
        "similarityMethod": "past-window z-score euclidean",
        "featureVersion": FEATURE_VERSION,
        "currentFeatures": current["raw"],
        "currentRegime": {
            "trend": current["family"], "volatility": current["volatility"]},
        "episodes": selected,
    }


def _event_study(bars: Sequence[Dict[str, Any]],
                 episodes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    paths: Dict[int, List[float]] = {day: [] for day in range(-20, 21)}
    for episode in episodes:
        index = int(episode["index"])
        if index < 20 or index + 20 >= len(bars):
            continue
        base = float(bars[index]["close"])
        for day in range(-20, 21):
            paths[day].append((float(bars[index + day]["close"]) / base - 1) * 100)
    points = []
    for day in range(-20, 21):
        values = paths[day]
        points.append({
            "day": day, "sample": len(values),
            "q10": _round(_quantile(values, .10), 3),
            "q25": _round(_quantile(values, .25), 3),
            "median": _round(_quantile(values, .50), 3),
            "q75": _round(_quantile(values, .75), 3),
            "q90": _round(_quantile(values, .90), 3),
        })
    return {"window": [-20, 20], "points": points,
            "noFutureLeakage": True}


def _calibration_curve(episodes: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    """Expanding, past-only directional calibration in 10 bins."""
    bins: Dict[int, Dict[str, Any]] = {
        index: {"predictions": [], "observed": []} for index in range(10)}
    previous: List[Dict[str, Any]] = []
    for episode in sorted(episodes, key=lambda row: row["date"]):
        outcome = _number((episode.get("outcomes") or {}).get(str(horizon)))
        if outcome is None:
            continue
        up_count = sum(1 for row in previous
                       if _number((row.get("outcomes") or {}).get(str(horizon))) is not None
                       and float(row["outcomes"][str(horizon)]) > 0)
        predicted = (up_count + 1) / (len(previous) + 2)
        index = min(9, int(predicted * 10))
        bins[index]["predictions"].append(predicted)
        bins[index]["observed"].append(1.0 if outcome > 0 else 0.0)
        previous.append(episode)
    points = []
    for index, values in bins.items():
        count = len(values["predictions"])
        if not count:
            continue
        points.append({
            "bin": index, "sample": count,
            "predicted": _round(_mean(values["predictions"]), 3),
            "observed": _round(_mean(values["observed"]), 3),
            "smallSample": count < 10,
        })
    return {"horizon": horizon, "points": points, "ideal": [[0, 0], [1, 1]],
            "walkForward": True, "noFutureLeakage": True}


def _regime_analysis(episodes: Sequence[Dict[str, Any]], horizon: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    groups = ("uptrend", "downtrend", "range", "high_volatility",
              "low_volatility", "normal_volatility")
    for group in groups:
        selected = [row for row in episodes
                    if row.get("family") == group or row.get("volatility") == group]
        values = [_number((row.get("outcomes") or {}).get(str(horizon)))
                  for row in selected]
        clean = [float(value) for value in values if value is not None]
        rows.append({
            "regime": group, "effectiveSample": len(clean),
            "eligible": len(clean) >= MIN_REGIME_SAMPLE,
            "medianReturnPct": _round(_quantile(clean, .5), 3)
            if len(clean) >= MIN_REGIME_SAMPLE else None,
            "upRatePct": _round(100 * sum(value > 0 for value in clean) / len(clean), 1)
            if len(clean) >= MIN_REGIME_SAMPLE else None,
        })
    return rows


def _history_points(series: Dict[str, Any], as_of: str) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    for raw in series.get("history") or []:
        if not isinstance(raw, dict):
            continue
        date = str(raw.get("date") or raw.get("periodEnd") or raw.get("asOf") or "")[:10]
        available = str(raw.get("availableFrom") or raw.get("publishedAt") or date)[:10]
        value = _number(raw.get("value", raw.get("latestValue")))
        if len(date) == 10 and value is not None and available <= as_of[:10]:
            points.append({"date": date, "availableFrom": available, "value": value})
    return sorted(points, key=lambda row: (row["availableFrom"], row["date"]))


def _price_outcome_after(bars: Sequence[Dict[str, Any]], date: str) -> Dict[str, Any]:
    index = next((idx for idx, row in enumerate(bars) if row["date"] >= date), None)
    if index is None or index + 20 >= len(bars):
        return {"1": None, "5": None, "20": None, "mfe": None, "mae": None,
                "reactionDelayDays": None}
    return _outcome(bars, index)


def _ledger_extremes(ledger: Dict[str, Any], bars: Sequence[Dict[str, Any]],
                     as_of: str) -> Dict[str, Any]:
    series_rows = [row for row in (ledger.get("table") or []) if isinstance(row, dict)]
    summaries: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    raw_total = 0
    for series in series_rows:
        points = _history_points(series, as_of)
        if not points:
            current = _number(series.get("latestValue"))
            if current is None:
                continue
            points = [{"date": as_of[:10], "availableFrom": as_of[:10], "value": current}]
        values = [float(row["value"]) for row in points]
        current = values[-1]
        mean = sum(values) / len(values)
        deviation = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        percentile = 100 * sum(value <= current for value in values) / len(values)
        local_peak = len(values) >= 3 and current >= max(values[-min(13, len(values)):])
        local_bottom = len(values) >= 3 and current <= min(values[-min(13, len(values)):])
        flags = ([f"percentile_gte_{level}" for level in (90, 95, 99)
                  if percentile >= level] +
                 [f"percentile_lte_{level}" for level in (10, 5, 1)
                  if percentile <= level] +
                 (["local_peak"] if local_peak else []) +
                 (["local_bottom"] if local_bottom else []))
        summaries.append({
            "seriesId": str(series.get("seriesId") or ""),
            "labelJa": str(series.get("labelJa") or series.get("seriesId") or ""),
            "unit": series.get("unit"),
            "currentValue": _round(current, 3),
            "change1": _round(current - values[-2], 3) if len(values) >= 2 else None,
            "cumulative4": _round(current - values[-5], 3) if len(values) >= 5 else None,
            "cumulative13": _round(current - values[-14], 3) if len(values) >= 14 else None,
            "rollingPercentile": _round(percentile, 1),
            "zScore": _round((current - mean) / deviation, 3) if deviation > 0 else 0.0,
            "localPeak": local_peak, "localBottom": local_bottom,
            "extremeFamily": flags[-1] if flags else None,
            "history": points[-60:],
            "source": series.get("source"),
        })
        raw: List[Dict[str, Any]] = []
        for index, point in enumerate(points):
            training = [float(row["value"]) for row in points[:index + 1]]
            rank = 100 * sum(value <= point["value"] for value in training) / len(training)
            crossed = any((rank >= threshold if threshold >= 50 else rank <= threshold)
                          for threshold in EXTREME_THRESHOLDS)
            peak = index >= 2 and point["value"] >= max(training[max(0, index - 12):])
            bottom = index >= 2 and point["value"] <= min(training[max(0, index - 12):])
            if crossed or peak or bottom:
                raw.append({"index": index, "date": point["date"],
                            "availableFrom": point["availableFrom"],
                            "percentile": rank,
                            "family": ("local_peak" if peak else "local_bottom" if bottom
                                       else "upper_extreme" if rank >= 90 else "lower_extreme")})
        grouped: List[Dict[str, Any]] = []
        raw_total += len(raw)
        for event in raw:
            if grouped and event["index"] - grouped[-1]["lastIndex"] <= 1:
                grouped[-1]["lastIndex"] = event["index"]
                grouped[-1]["endDate"] = event["date"]
                if abs(event["percentile"] - 50) > abs(grouped[-1]["percentile"] - 50):
                    grouped[-1].update({key: event[key] for key in
                                       ("date", "availableFrom", "percentile", "family")})
                continue
            grouped.append({**event, "lastIndex": event["index"],
                            "startDate": event["date"], "endDate": event["date"]})
        for event in grouped[-20:]:
            body = {
                "seriesId": series.get("seriesId"), "date": event["date"],
                "availableFrom": event["availableFrom"], "family": event["family"],
                "methodVersion": EXTREME_VERSION,
            }
            events.append({
                **body, "episodeId": "extreme-" + _hash(body, 20),
                "percentile": _round(event["percentile"], 1),
                "outcomes": _price_outcome_after(bars, event["availableFrom"]),
            })
    return {
        "methodVersion": EXTREME_VERSION,
        "thresholds": list(EXTREME_THRESHOLDS),
        "rawOccurrenceCount": raw_total,
        "effectiveEpisodeCount": len(events),
        "series": summaries, "events": events[-100:],
        "publicationTimeIntegrity": True,
    }


def _change_conditions(chart_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    bars = ((chart_report.get("indicators") or {}).get("bars") or [])
    close = _number((bars[-1] if bars else {}).get("close"))
    zones = [zone for zone in (chart_report.get("zones") or [])
             if isinstance(zone, dict) and zone.get("status") != "broken"]
    supports = sorted((zone for zone in zones
                       if close is not None and _number(zone.get("center")) is not None
                       and float(zone["center"]) < close),
                      key=lambda zone: float(zone["center"]), reverse=True)
    resistances = sorted((zone for zone in zones
                          if close is not None and _number(zone.get("center")) is not None
                          and float(zone["center"]) > close),
                         key=lambda zone: float(zone["center"]))
    result: List[Dict[str, Any]] = []
    if resistances:
        result.append({"triggerType": "upside_close_break",
                       "price": _round(float(resistances[0]["upper"]), 3),
                       "event": None, "timeframe": "daily",
                       "requiredConfirmation": "daily_close",
                       "status": "watching",
                       "sourceId": resistances[0].get("id")})
    if supports:
        result.append({"triggerType": "downside_close_break",
                       "price": _round(float(supports[0]["lower"]), 3),
                       "event": None, "timeframe": "daily",
                       "requiredConfirmation": "daily_close",
                       "status": "watching",
                       "sourceId": supports[0].get("id")})
    events = chart_report.get("eventMarkers") or []
    if events:
        result.append({"triggerType": "event_passed",
                       "price": None, "event": events[0].get("labelJa"),
                       "timeframe": "event",
                       "requiredConfirmation": "official_result",
                       "status": "scheduled",
                       "sourceId": events[0].get("id")})
    return result[:3]


def build_context(rows: Iterable[Dict[str, Any]], *, symbol: str, market: str,
                  horizon: int, chart_report: Optional[Dict[str, Any]] = None,
                  ledger: Optional[Dict[str, Any]] = None,
                  calibration: Optional[Dict[str, Any]] = None,
                  now_iso: Optional[str] = None) -> Dict[str, Any]:
    if horizon not in HORIZONS:
        raise ValueError("unsupported_horizon")
    bars = argus_today_intelligence.normalize_bars(rows)
    as_of = now_iso or (bars[-1]["date"] if bars else
                        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    episode_index = _episode_index(bars)
    episodes = episode_index["episodes"]
    distributions = {
        key: _distribution((row.get("outcomes") or {}).get(key) for row in episodes)
        for key in ("1", "5", "20", "mfe", "mae", "reactionDelayDays")
    }
    selected_calibration = (((calibration or {}).get("horizons") or {})
                            .get(str(horizon)) or {})
    extremes = _ledger_extremes(ledger or {}, bars, as_of)
    dataset_hash = _dataset_hash_from_bars(bars)
    outcome_hash = _hash([{
        "id": row.get("episodeId"), "outcomes": row.get("outcomes"),
    } for row in episodes])
    calibration_curve = _calibration_curve(episodes, horizon)
    calibration_hash = _hash({
        "curve": calibration_curve, "source": selected_calibration})
    context = {
        "schemaVersion": SCHEMA_VERSION, "methodVersion": METHOD_VERSION,
        "featureVersion": FEATURE_VERSION, "reactionVersion": REACTION_VERSION,
        "instrumentId": f"{market}:{symbol}:ETF", "symbol": symbol,
        "market": market, "horizon": horizon, "asOf": as_of,
        "historyCoverage": {
            "start": bars[0]["date"] if bars else None,
            "end": bars[-1]["date"] if bars else None,
            "count": len(bars)},
        "datasetHash": dataset_hash, "outcomeHash": outcome_hash,
        "calibrationHash": calibration_hash,
        "currentFeatures": episode_index.get("currentFeatures"),
        "currentRegime": episode_index.get("currentRegime"),
        "similarEpisodes": {
            key: value for key, value in episode_index.items()
            if key not in ("currentFeatures", "currentRegime")},
        "eventStudy": _event_study(bars, episodes),
        "outcomeDistributions": distributions,
        "calibrationCurve": calibration_curve,
        "regimeAnalysis": _regime_analysis(episodes, horizon),
        "extremes": extremes,
        "changeConditions": _change_conditions(chart_report or {}),
        "probabilityQuality": {
            "modelBrier": selected_calibration.get("modelBrier"),
            "baselineBrier": selected_calibration.get("baselineBrier"),
            "brierSkill": selected_calibration.get("brierSkill"),
            "effectiveSample": selected_calibration.get("effectiveSampleCount"),
            "calibrationIntegrity": selected_calibration.get("calibrationIntegrity"),
            "evaluationPeriod": {
                "start": (calibration or {}).get("historyStart"),
                "end": (calibration or {}).get("historyEnd")},
            "datasetHash": selected_calibration.get("calibrationDatasetHash")
            or dataset_hash,
        },
        "automaticAiCalls": 0,
        "computation": {
            "mode": "deterministic_background_cache",
            "cacheKey": f"{market}:{symbol}:{horizon}:{METHOD_VERSION}:{dataset_hash}",
            "noFutureLeakage": True, "publicationTimeIntegrity": True,
        },
    }
    context["contextId"] = "replay-" + _hash({
        "instrumentId": context["instrumentId"], "horizon": horizon,
        "methodVersion": METHOD_VERSION, "datasetHash": dataset_hash})
    return context


def empty_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "methodVersion": METHOD_VERSION,
            "contexts": [], "contextHistory": [], "lastUpdatedAt": None}


def normalize_state(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    out = empty_state()
    contexts = [row for row in source.get("contexts", []) if isinstance(row, dict)
                and row.get("contextId") and row.get("instrumentId")
                and int(row.get("horizon") or 0) in HORIZONS]
    # Keep only the latest heavy context per instrument/horizon.  Every prior
    # calculation remains append-only as a compact cryptographic receipt below.
    by_slot: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
    for row in contexts:
        slot = (str(row["instrumentId"]), int(row["horizon"]),
                str(row.get("methodVersion") or METHOD_VERSION))
        if slot not in by_slot or str(row.get("asOf") or "") > \
                str(by_slot[slot].get("asOf") or ""):
            by_slot[slot] = row
    out["contexts"] = sorted(by_slot.values(),
                             key=lambda row: str(row.get("asOf") or row["contextId"]))
    history = [row for row in source.get("contextHistory", [])
               if isinstance(row, dict) and row.get("contextId")]
    by_history = {row["contextId"]: row for row in history}
    out["contextHistory"] = sorted(
        by_history.values(), key=lambda row: str(row.get("asOf") or row["contextId"]))
    out["lastUpdatedAt"] = source.get("lastUpdatedAt")
    return out


def merge_state(local: Dict[str, Any], remote: Dict[str, Any]) -> Dict[str, Any]:
    left, right = normalize_state(local), normalize_state(remote)
    by_id = {row["contextId"]: row for row in left["contexts"]}
    for row in right["contexts"]:
        by_id.setdefault(row["contextId"], row)
    left["contexts"] = normalize_state({"contexts": list(by_id.values())})["contexts"]
    history = {row["contextId"]: row for row in left["contextHistory"]}
    history.update({row["contextId"]: row for row in right["contextHistory"]})
    left["contextHistory"] = sorted(
        history.values(), key=lambda row: str(row.get("asOf") or row["contextId"]))
    left["lastUpdatedAt"] = max(str(left.get("lastUpdatedAt") or ""),
                                str(right.get("lastUpdatedAt") or "")) or None
    return left


def merge_context(state: Dict[str, Any], context: Dict[str, Any],
                  now_iso: str) -> Dict[str, Any]:
    out = normalize_state(state)
    receipt = {
        "contextId": context.get("contextId"),
        "instrumentId": context.get("instrumentId"),
        "horizon": context.get("horizon"), "asOf": context.get("asOf"),
        "methodVersion": context.get("methodVersion"),
        "datasetHash": context.get("datasetHash"),
        "outcomeHash": context.get("outcomeHash"),
        "calibrationHash": context.get("calibrationHash"),
        "episodeCount": ((context.get("similarEpisodes") or {})
                         .get("effectiveSampleCount")),
    }
    if receipt["contextId"] not in {row.get("contextId") for row in out["contextHistory"]}:
        out["contextHistory"].append(receipt)
    slot = (context.get("instrumentId"), int(context.get("horizon") or 0),
            context.get("methodVersion"))
    existing_index = next((index for index, row in enumerate(out["contexts"])
                           if (row.get("instrumentId"), int(row.get("horizon") or 0),
                               row.get("methodVersion")) == slot), None)
    if existing_index is None:
        out["contexts"].append(context)
    elif str(context.get("asOf") or "") >= \
            str(out["contexts"][existing_index].get("asOf") or ""):
        out["contexts"][existing_index] = context
    out["lastUpdatedAt"] = now_iso
    return out


def latest_contexts(state: Dict[str, Any], instrument_id: str) -> Dict[str, Any]:
    contexts = [row for row in normalize_state(state)["contexts"]
                if row.get("instrumentId") == instrument_id]
    result: Dict[str, Any] = {}
    for horizon in HORIZONS:
        candidates = [row for row in contexts if int(row.get("horizon") or 0) == horizon]
        if candidates:
            result[str(horizon)] = max(
                candidates, key=lambda row: str(row.get("asOf") or ""))
    return result


def state_hash(state: Dict[str, Any]) -> str:
    normalized = normalize_state(state)
    return _hash({"contexts": normalized["contexts"],
                  "contextHistory": normalized["contextHistory"]})


def read_back_verified(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return state_hash(local) == state_hash(remote)
