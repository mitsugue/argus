# -*- coding: utf-8 -*-
"""Deterministic Market Context Replay.

All calculations are provider-agnostic, public-safe and stdlib-only.  A replay
uses information whose ``availableFrom`` is no later than the replay date,
groups overlapping observations into one episode, and never calls an LLM.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import argus_today_intelligence
import argus_market_data_truth


SCHEMA_VERSION = "argus-market-replay-v1"
OLD_METHOD_VERSION = "market-context-replay-v1"
METHOD_VERSION = "market-context-replay-v3-pit-bound"
FEATURE_VERSION = "replay-features-past-window-v1"
REACTION_VERSION = "reaction-classification-v1"
EXTREME_VERSION = "ledger-extremes-fixed-thresholds-v2-standard-excursion"
HORIZONS = (1, 5, 20)
COOLDOWN_TRADING_DAYS = 5
MAX_EPISODES = 40
MAX_CONTEXTS = 32
MAX_CONTEXT_HISTORY = 1024
MIN_REGIME_SAMPLE = 20
EXTREME_THRESHOLDS = (1, 5, 10, 90, 95, 99)
METRIC_DEFINITION = {
    "mae": "min(0, minimum forward low return during the selected horizon)",
    "mfe": "max(0, maximum forward high return during the selected horizon)",
    "direction": "long",
    "unit": "percent",
}
AUXILIARY_INPUT_SCHEMA = "argus-replay-auxiliary-input-v1"
MAX_AUXILIARY_INPUT_BYTES = 512 * 1024
# Chart intelligence carries up to 260 PIT-bound bars with date, available,
# known, and observed timestamps, plus bounded event/calibration metadata. Keep
# the audit above that real repository shape and fail closed rather than
# silently truncating when a malformed/hostile payload exceeds the bound.
MAX_AUXILIARY_TEMPORAL_PATHS = 2048

# These fields describe when a fact entered the information set, rather than a
# future schedule.  A sealed auxiliary payload may contain a future event date
# that was already announced, but it may never contain an observation/knowledge
# timestamp from after the replay cutoff.
_AUXILIARY_KNOWLEDGE_TIME_KEYS = frozenset({
    "asOf", "availableFrom", "createdAt", "generatedAt", "ingestedAt",
    "knownAt", "observedAt", "publishedAt", "receivedAt", "reportedAt",
    "sourceTimestamp", "updatedAt",
})
_AUXILIARY_HISTORY_CONTAINERS = frozenset({
    "bars", "history", "observations", "outcomes", "series",
})


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


def _auxiliary_time(value: Any, *, date_only: bool = False) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty_auxiliary_time")
    if date_only or len(text) == 10:
        parsed = datetime.fromisoformat(text[:10] + "T23:59:59.999999+00:00")
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("auxiliary_time_timezone_required")
    return parsed.astimezone(timezone.utc)


def _auxiliary_temporal_proof(value: Dict[str, Any], *, kind: str,
                              cutoff: datetime) -> Dict[str, Any]:
    """Mechanically audit explicit nested knowledge/history timestamps.

    ``date`` is temporal only inside a history-like container or an OHLC row;
    this deliberately does not reject a future scheduled event whose existence
    was already known at the cutoff.  Explicit knowledge timestamps are always
    bounded, wherever they occur.
    """
    checked: List[str] = []
    future: List[str] = []
    malformed: List[str] = []
    overflow = False
    timestamp_count = 0

    def visit(node: Any, path: Tuple[str, ...]) -> None:
        nonlocal overflow, timestamp_count
        if overflow:
            return
        if isinstance(node, dict):
            is_ohlc = bool(set(node) & {"open", "high", "low", "close"})
            in_history = any(part in _AUXILIARY_HISTORY_CONTAINERS
                             for part in path)
            for raw_key, child in node.items():
                key = str(raw_key)
                child_path = path + (key,)
                should_check = key in _AUXILIARY_KNOWLEDGE_TIME_KEYS
                date_only = False
                if key == "date" and (is_ohlc or in_history):
                    should_check = True
                    date_only = True
                if kind == "calibration" and key in {
                        "historyEnd", "sampleEnd", "trainingEnd"}:
                    should_check = True
                    date_only = True
                if should_check and child not in (None, ""):
                    if timestamp_count >= MAX_AUXILIARY_TEMPORAL_PATHS:
                        overflow = True
                        return
                    timestamp_count += 1
                    label = ".".join(child_path)
                    try:
                        parsed = _auxiliary_time(child, date_only=date_only)
                    except (TypeError, ValueError, OverflowError):
                        malformed.append(label)
                    else:
                        checked.append(label)
                        if parsed > cutoff:
                            future.append(label)
                visit(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, path + (str(index),))

    visit(value, ())
    return {
        "policyId": "replay-auxiliary-nested-time-v2-overflow-closed",
        "checkedTimestampCount": len(checked),
        "futureTimestampPaths": future,
        "malformedTimestampPaths": malformed,
        "temporalPathOverflow": overflow,
        "verified": not future and not malformed and not overflow,
    }


def seal_auxiliary_input(value: Dict[str, Any], *, kind: str,
                         known_at: str) -> Dict[str, Any]:
    """Bind a current auxiliary payload to when it first entered the replay.

    A seal makes a chart/calibration payload eligible at that cutoff; it does
    not rewrite any inner timestamps. Reusing the sealed current payload for an
    older replay is mechanically rejected.
    """
    if not isinstance(value, dict) or kind not in ("chart_report", "calibration"):
        raise ValueError("invalid_auxiliary_input")
    parsed = datetime.fromisoformat(str(known_at).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("auxiliary_known_at_timezone_required")
    body = copy.deepcopy(value)
    body.pop("_pointInTimeReceipt", None)
    temporal = _auxiliary_temporal_proof(
        body, kind=kind, cutoff=parsed.astimezone(timezone.utc))
    if not temporal["verified"]:
        raise ValueError("auxiliary_nested_time_invalid")
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_AUXILIARY_INPUT_BYTES:
        raise ValueError("auxiliary_input_too_large")
    body["_pointInTimeReceipt"] = {
        "schemaVersion": AUXILIARY_INPUT_SCHEMA,
        "kind": kind,
        "knownAt": parsed.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"),
        "contentHash": hashlib.sha256(raw).hexdigest(),
    }
    return body


def _admit_auxiliary_input(value: Optional[Dict[str, Any]], *, kind: str,
                           cutoff: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    if not source:
        return {}, {"kind": kind, "status": "ABSENT", "admitted": False,
                    "futureInputAdmitted": False, "contentHash": None,
                    "knownAt": None}
    body = copy.deepcopy(source)
    receipt = body.pop("_pointInTimeReceipt", None)
    proof = {"kind": kind, "status": "EXCLUDED_UNBOUND", "admitted": False,
             "futureInputAdmitted": False, "contentHash": None,
             "knownAt": None, "temporalIntegrity": False,
             "temporalProof": None}
    if not isinstance(receipt, dict) or set(receipt) != {
            "schemaVersion", "kind", "knownAt", "contentHash"} or \
            receipt.get("schemaVersion") != AUXILIARY_INPUT_SCHEMA or \
            receipt.get("kind") != kind:
        return {}, proof
    try:
        known = datetime.fromisoformat(
            str(receipt.get("knownAt")).replace("Z", "+00:00"))
        limit = datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
        if known.tzinfo is None or limit.tzinfo is None:
            raise ValueError("timezone_required")
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        proof["status"] = "EXCLUDED_MALFORMED"
        return {}, proof
    digest = hashlib.sha256(raw).hexdigest()
    proof.update({"knownAt": known.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"), "contentHash": digest})
    if len(raw) > MAX_AUXILIARY_INPUT_BYTES or \
            digest != receipt.get("contentHash"):
        proof["status"] = "EXCLUDED_INTEGRITY_FAILURE"
        return {}, proof
    if known > limit:
        proof["status"] = "EXCLUDED_FUTURE"
        return {}, proof
    temporal = _auxiliary_temporal_proof(
        body, kind=kind, cutoff=limit.astimezone(timezone.utc))
    proof.update({"temporalProof": temporal,
                  "temporalIntegrity": bool(temporal["verified"])})
    if not temporal["verified"]:
        proof["status"] = "EXCLUDED_TEMPORAL_FAILURE"
        return {}, proof
    proof.update({"status": "ADMITTED", "admitted": True})
    return body, proof


def _dataset_hash_from_bars(bars: Sequence[Dict[str, Any]]) -> str:
    return _hash([{
        "date": row["date"],
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "volume": row.get("volume"),
        "availableFrom": row["availableFrom"],
        "knownAt": row.get("knownAt"),
        "observedAt": row.get("observedAt"),
        "revision": row.get("revision", 0),
        "source": row.get("source"),
        "sourceId": row.get("sourceId"),
        "datasetId": row.get("datasetId"),
        "adjusted": row.get("adjusted"),
    } for row in bars])


def dataset_hash(rows: Iterable[Dict[str, Any]]) -> str:
    """Return the public cache-key hash without running Replay analysis."""
    source = list(rows or [])
    visible, _ = argus_market_data_truth.point_in_time_rows(
        source, "9999-12-31T23:59:59.999999Z")
    normalized = argus_today_intelligence.normalize_bars(visible)
    metadata = {
        str(row.get("date") or row.get("Date") or "")[:10]: row
        for row in visible if isinstance(row, dict)
    }
    for bar in normalized:
        raw = metadata.get(bar["date"], {})
        bar["knownAt"] = raw.get("knownAt")
        bar["sourceId"] = raw.get("sourceId") or raw.get("sourceRef")
        bar["datasetId"] = raw.get("datasetId")
    return _dataset_hash_from_bars(normalized)


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
    width = (high - low) / 10 if high > low else 0.0
    counts = [0] * 10
    for value in clean:
        index = (min(9, max(0, int((value - low) / width)))
                 if width > 0 else 0)
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


def _outcome(bars: Sequence[Dict[str, Any]], index: int,
             horizon: int = 20) -> Dict[str, Any]:
    """Calculate close returns plus standard long-direction excursions.

    Missing/zero prices never become zero returns. Excursions are calculated
    independently for the selected 1D/5D/20D horizon.
    """
    start = _number((bars[index] if 0 <= index < len(bars) else {}).get("close"))
    empty = {
        "1": None, "5": None, "20": None, "mfe": None, "mae": None,
        "reactionClass": "unavailable", "reactionDelayDays": None,
    }
    if start is None or start <= 0 or horizon not in HORIZONS:
        return empty
    future = list(bars[index + 1:index + 21])
    close_changes = []
    for row in future:
        close = _number(row.get("close"))
        if close is None:
            close_changes.append(None)
        else:
            close_changes.append((close / start - 1) * 100)
    complete_changes = [value for value in close_changes if value is not None]
    atr_pct = float((argus_today_intelligence._feature(bars, index) or {})
                    .get("atrPct") or .01)
    reaction, delay = (("unavailable", None)
                       if len(complete_changes) != len(future) or not future
                       else _classify_reaction(
                           complete_changes, max(.3, atr_pct * 100 * .35)))

    def close_return(day: int) -> Optional[float]:
        return (close_changes[day - 1]
                if len(close_changes) >= day else None)

    excursion_rows = future[:horizon]
    highs = [_number(row.get("high")) for row in excursion_rows]
    lows = [_number(row.get("low")) for row in excursion_rows]
    mfe = (max(0.0, max((value / start - 1) * 100 for value in highs
                        if value is not None))
           if len(excursion_rows) == horizon and all(value is not None for value in highs)
           else None)
    mae = (min(0.0, min((value / start - 1) * 100 for value in lows
                        if value is not None))
           if len(excursion_rows) == horizon and all(value is not None for value in lows)
           else None)
    return {
        "1": _round(close_return(1), 3),
        "5": _round(close_return(5), 3),
        "20": _round(close_return(20), 3),
        "mfe": _round(mfe, 3),
        "mae": _round(mae, 3),
        "reactionClass": reaction, "reactionDelayDays": delay,
    }


def _episode_index(bars: Sequence[Dict[str, Any]],
                   horizon: int = 20) -> Dict[str, Any]:
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
            "outcomes": _outcome(bars, feature["index"], horizon),
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
                 episodes: Sequence[Dict[str, Any]], *, pit_proven: bool) -> Dict[str, Any]:
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
            "noFutureLeakage": bool(pit_proven)}


def _calibration_curve(episodes: Sequence[Dict[str, Any]], horizon: int, *,
                       pit_proven: bool) -> Dict[str, Any]:
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
            "walkForward": True, "noFutureLeakage": bool(pit_proven)}


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


def _history_points_with_proof(series: Dict[str, Any], as_of: str
                               ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    visible, proof = argus_market_data_truth.point_in_time_rows(
        series.get("history") or [], as_of)
    points: List[Dict[str, Any]] = []
    for raw in visible:
        if not isinstance(raw, dict):
            continue
        date = str(raw.get("date") or raw.get("periodEnd") or raw.get("asOf") or "")[:10]
        available = str(raw.get("availableFrom") or raw.get("publishedAt") or "")[:10]
        value = _number(raw.get("value", raw.get("latestValue")))
        if len(date) == 10 and len(available) == 10 and value is not None:
            points.append({
                "date": date, "availableFrom": available,
                "knownAt": raw.get("knownAt"), "revision": raw.get("revision", 0),
                "value": value,
            })
    return (sorted(points, key=lambda row: (
        str(row.get("knownAt") or ""), row["date"])), proof)


def _history_points(series: Dict[str, Any], as_of: str) -> List[Dict[str, Any]]:
    return _history_points_with_proof(series, as_of)[0]


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
    publication_proofs: List[Dict[str, Any]] = []
    raw_total = 0
    for series in series_rows:
        points, point_proof = _history_points_with_proof(series, as_of)
        proof_ok, proof_reason = argus_market_data_truth.verify_point_in_time_proof(
            point_proof)
        publication_proofs.append({
            "seriesId": str(series.get("seriesId") or ""),
            "proofDigest": point_proof.get("proofDigest"),
            "verified": proof_ok,
            "reason": proof_reason,
            "excludedFutureCount": point_proof.get("excludedFutureCount"),
            "excludedUnknownKnowledgeTimeCount": point_proof.get(
                "excludedUnknownKnowledgeTimeCount"),
        })
        if not points:
            # A current/latest scalar has no historical publication timestamp
            # and must never be backdated into a replay.
            continue
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
        "publicationTimeIntegrity": all(
            row["verified"] for row in publication_proofs),
        "latestValueFallbackUsed": False,
        "publicationProofs": publication_proofs,
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
    requested_as_of = now_iso or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pit_rows, pit_proof = argus_market_data_truth.point_in_time_rows(
        list(rows or []), requested_as_of)
    as_of = str(pit_proof["cutoff"])
    bars = argus_today_intelligence.normalize_bars(pit_rows)
    metadata = {
        str(row.get("date") or row.get("Date") or "")[:10]: row
        for row in pit_rows
    }
    for bar in bars:
        raw = metadata.get(bar["date"], {})
        bar["knownAt"] = raw.get("knownAt")
        bar["sourceId"] = raw.get("sourceId") or raw.get("sourceRef")
        bar["datasetId"] = raw.get("datasetId")
    episode_index = _episode_index(bars, horizon)
    episodes = episode_index["episodes"]
    distributions = {
        key: _distribution((row.get("outcomes") or {}).get(key) for row in episodes)
        for key in ("1", "5", "20", "mfe", "mae", "reactionDelayDays")
    }
    admitted_chart, chart_input_proof = _admit_auxiliary_input(
        chart_report, kind="chart_report", cutoff=as_of)
    admitted_calibration, calibration_input_proof = _admit_auxiliary_input(
        calibration, kind="calibration", cutoff=as_of)
    selected_calibration = ((admitted_calibration.get("horizons") or {})
                            .get(str(horizon)) or {})
    extremes = _ledger_extremes(ledger or {}, bars, as_of)
    dataset_hash = _dataset_hash_from_bars(bars)
    outcome_hash = _hash([{
        "id": row.get("episodeId"), "outcomes": row.get("outcomes"),
    } for row in episodes])
    bar_pit_verified, pit_reason = argus_market_data_truth.verify_point_in_time_proof(
        pit_proof)
    auxiliary_temporal_integrity = all(
        not row.get("admitted") or row.get("temporalIntegrity") is True
        for row in (chart_input_proof, calibration_input_proof))
    pit_verified = bool(
        bar_pit_verified and extremes.get("publicationTimeIntegrity") and
        auxiliary_temporal_integrity)
    pit_binding = {
        "policyId": argus_market_data_truth.PIT_POLICY_ID,
        "proofDigest": pit_proof.get("proofDigest"),
        "filterProof": pit_proof,
        "sourceDatasetDigest": pit_proof.get("admittedDatasetDigest"),
        "normalizedDatasetHash": dataset_hash,
        "normalizedRowCount": len(bars),
        "revisionSelection": pit_proof.get("revisionSelection"),
        "verified": pit_verified,
        "verificationReason": pit_reason,
        "auxiliaryInputs": [chart_input_proof, calibration_input_proof],
        "excludedAuxiliaryInputCount": sum(
            1 for row in (chart_input_proof, calibration_input_proof)
            if row.get("status", "").startswith("EXCLUDED_")),
        "ledgerPublicationTimeIntegrity": bool(
            extremes.get("publicationTimeIntegrity")),
        "auxiliaryTemporalIntegrity": auxiliary_temporal_integrity,
    }
    pit_binding["bindingDigest"] = _hash(pit_binding, 64)
    calibration_curve = _calibration_curve(
        episodes, horizon, pit_proven=pit_verified)
    calibration_hash = _hash({
        "curve": calibration_curve, "source": selected_calibration,
        "sourceReceipt": calibration_input_proof})
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
        "derivedMetricMigration": {
            "oldMethodVersion": OLD_METHOD_VERSION,
            "newMethodVersion": METHOD_VERSION,
            "metricDefinition": dict(METRIC_DEFINITION),
            "recomputedAt": as_of,
            "sourceDatasetHash": dataset_hash,
            "rawObservationsModified": False,
        },
        "currentFeatures": episode_index.get("currentFeatures"),
        "currentRegime": episode_index.get("currentRegime"),
        "similarEpisodes": {
            key: value for key, value in episode_index.items()
            if key not in ("currentFeatures", "currentRegime")},
        "eventStudy": _event_study(bars, episodes, pit_proven=pit_verified),
        "outcomeDistributions": distributions,
        "calibrationCurve": calibration_curve,
        "regimeAnalysis": _regime_analysis(episodes, horizon),
        "extremes": extremes,
        "changeConditions": _change_conditions(admitted_chart),
        "probabilityQuality": {
            "modelBrier": selected_calibration.get("modelBrier"),
            "baselineBrier": selected_calibration.get("baselineBrier"),
            "brierSkill": selected_calibration.get("brierSkill"),
            "effectiveSample": selected_calibration.get("effectiveSampleCount"),
            "calibrationIntegrity": selected_calibration.get("calibrationIntegrity"),
            "evaluationPeriod": {
                "start": admitted_calibration.get("historyStart"),
                "end": admitted_calibration.get("historyEnd")},
            "datasetHash": selected_calibration.get("calibrationDatasetHash")
            or dataset_hash,
        },
        "automaticAiCalls": 0,
        "computation": {
            "mode": "deterministic_background_cache",
            "cacheKey": f"{market}:{symbol}:{horizon}:{METHOD_VERSION}:{dataset_hash}",
            "noFutureLeakage": bool(pit_verified),
            "noFutureLeakageProof": pit_binding,
            "publicationTimeIntegrity": bool(
                extremes.get("publicationTimeIntegrity")),
        },
    }
    context["contextId"] = "replay-" + _hash({
        "instrumentId": context["instrumentId"], "horizon": horizon,
        "methodVersion": METHOD_VERSION, "datasetHash": dataset_hash,
        "asOf": as_of, "pitBindingDigest": pit_binding["bindingDigest"]})
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
                             key=lambda row: str(row.get("asOf") or row["contextId"]))[-MAX_CONTEXTS:]
    history = [row for row in source.get("contextHistory", [])
               if isinstance(row, dict) and row.get("contextId")]
    by_history = {row["contextId"]: row for row in history}
    out["contextHistory"] = sorted(
        by_history.values(), key=lambda row: str(row.get("asOf") or row["contextId"]))[-MAX_CONTEXT_HISTORY:]
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
        "derivedMetricMigration": context.get("derivedMetricMigration"),
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
                candidates, key=lambda row: (
                    row.get("methodVersion") == METHOD_VERSION,
                    str(row.get("asOf") or "")))
    return result


def state_hash(state: Dict[str, Any]) -> str:
    normalized = normalize_state(state)
    return _hash({"contexts": normalized["contexts"],
                  "contextHistory": normalized["contextHistory"]})


def read_back_verified(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return state_hash(local) == state_hash(remote)
