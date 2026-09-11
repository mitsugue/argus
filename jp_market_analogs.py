"""Japan index analog selection, separate from subsequent reference paths.

Only explicit, past-bounded snapshots reach the selector. Its API accepts no
forward outcomes. Scores are distances, never probabilities. This descriptive
candidate method has no trading authority or demonstrated predictive benefit.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from jp_market_engine import _instant, point_in_time_rows

SCHEMA_VERSION = "jp-market-analogs-v1"
INSTRUMENT = "NIKKEI_225_INDEX"
# Explicit physical-unit scales are a versioned research specification, not
# calibrated prediction parameters. Changes require a new policy identity.
FEATURE_DEFINITIONS = {
    "credit.ratio": ("RATIO", 2.0),
    "credit.ratio_change": ("RATIO", .5),
    "credit.loss_pct": ("PERCENT", 10.0),
    "margin1570.ratio": ("RATIO", 2.0),
    "margin1570.long_change_pct": ("PERCENT", 20.0),
    "margin1570.short_change_pct": ("PERCENT", 20.0),
    "relative_jp_us.return20": ("PERCENT", 5.0),
    "vix.level": ("INDEX_POINTS", 10.0),
    "vix.change5": ("INDEX_POINTS", 5.0),
    "vix.macd_histogram": ("INDEX_POINTS", 2.0),
    "foreign_flow.net4w": ("JPY", 1_000_000_000_000.0),
    "fx.usdjpy_change5": ("PERCENT", 3.0),
    "rate.jp10y_change5": ("PERCENTAGE_POINTS", .2),
    "rate.us10y_change5": ("PERCENTAGE_POINTS", .3),
    "nt.ratio_change5": ("PERCENT", 2.0),
    "event.sq_sessions": ("TRADING_SESSIONS", 20.0),
}


FEATURE_MAX_AGE_DAYS = {key: (35 if key.startswith(("credit.", "margin1570.")) else
                              42 if key.startswith("foreign_flow.") else 5)
                        for key in FEATURE_DEFINITIONS}


def _policy_material(policy):
    return {**asdict(policy), "features": FEATURE_DEFINITIONS,
            "maximumFeatureAgeDays": FEATURE_MAX_AGE_DAYS}


@dataclass(frozen=True)
class AnalogPolicy:
    policy_id: str = "jp-index-shape-state-order-reaction-research-v1"
    lookback_sessions: int = 20
    maximum_candidates: int = 3
    minimum_separation_sessions: int = 20
    maximum_distance: float = .75
    shape_scale_pct: float = 5.0

    def __post_init__(self):
        for value, lower, upper in ((self.lookback_sessions, 5, 120),
                                    (self.maximum_candidates, 1, 10),
                                    (self.minimum_separation_sessions, 1, 252)):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise ValueError("invalid_analog_policy_bound")
        if not self.policy_id or not all(math.isfinite(v) and v > 0 for v in
                                        (self.maximum_distance, self.shape_scale_pct)):
            raise ValueError("invalid_analog_policy_scale")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _period(row: Mapping[str, Any]) -> str:
    return str(row.get("periodEnd") or row.get("date") or "")[:10]


def _identity(row: Mapping[str, Any]) -> str:
    return str(row.get("instrumentId") or row.get("instrument") or "")


def _field(row: Mapping[str, Any]) -> str:
    return str(row.get("seriesId") or row.get("field") or row.get("kind") or
               ("OHLCV_BAR" if all(key in row for key in ("open", "high", "low", "close", "volume")) else ""))


def _receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("publishedAt", "availableFrom", "knownAt",
                                     "observedAt", "sourceRef", "source", "revision",
                                     "availabilityBasis", "vintageStatus") if key in row}


def _visible(rows: Iterable[Mapping[str, Any]], cutoff: str) -> list[dict[str, Any]]:
    # Keep the temporal verifier common with the existing evidence engine.
    return point_in_time_rows(rows, cutoff)[0]


def build_episode(*, cutoff: str, bars: Sequence[Mapping[str, Any]],
                  state_rows: Sequence[Mapping[str, Any]] = (),
                  condition_rows: Sequence[Mapping[str, Any]] = (),
                  reaction_rows: Sequence[Mapping[str, Any]] = (),
                  policy: AnalogPolicy = AnalogPolicy()) -> dict[str, Any]:
    """Freeze information available at one anchor, including its provenance.

    State rows are already derived, unit-labelled observations for this index.
    A reaction is a measured return after a material event but BEFORE this
    anchor. Absence of reaction evidence does not mean the market had no events.
    """
    source = [dict(row) for row in bars if isinstance(row, Mapping) and _identity(row) == INSTRUMENT]
    visible = _visible(source, cutoff)
    prices = []
    for row in visible:
        if _field(row) not in {"OHLCV_BAR", "close"}:
            continue
        value = _finite(row.get("close", row.get("value")))
        if value is None or value <= 0:
            # Do not bridge over a present but invalid bar as if it were a
            # contiguous set of exchange sessions.
            prices.append({"date": _period(row), "close": None})
        else:
            prices.append({"date": _period(row), "close": value, **_receipt(row)})
    prices.sort(key=lambda row: row["date"])
    window = prices[-policy.lookback_sessions - 1:]
    if len({row["date"] for row in window}) != len(window):
        raise ValueError("ambiguous_price_observation")
    enough = len(window) == policy.lookback_sessions + 1 and all(row["close"] for row in window)
    anchor = window[-1]["date"] if window else None
    first = window[0]["date"] if window else None
    # Shared knowledge time can be later than the anchor session. No feature
    # with an observation date after that session enters its comparison.
    states: dict[str, Any] = {}
    for row in _visible([dict(r) for r in state_rows if isinstance(r, Mapping)
                         and _identity(r) == INSTRUMENT], cutoff):
        field = _field(row)
        definition = FEATURE_DEFINITIONS.get(field)
        value = _finite(row.get("value"))
        if definition and anchor and _period(row) <= anchor and value is not None \
                and row.get("unit") == definition[0] and (date.fromisoformat(anchor) -
                    date.fromisoformat(_period(row))).days <= FEATURE_MAX_AGE_DAYS[field]:
            states[field] = {"value": value, "unit": definition[0],
                             "date": _period(row), **_receipt(row)}
    conditions = []
    for row in _visible([dict(r) for r in condition_rows if isinstance(r, Mapping)
                         and _identity(r) == INSTRUMENT], cutoff):
        value = _finite(row.get("value"))
        if first and anchor and first <= _period(row) <= anchor and value in (-1, 1):
            conditions.append({"condition": _field(row), "direction": int(value),
                               "date": _period(row), **_receipt(row)})
    reactions: dict[str, Any] = {}
    for row in _visible([dict(r) for r in reaction_rows if isinstance(r, Mapping)
                         and _identity(r) == INSTRUMENT], cutoff):
        value = _finite(row.get("value"))
        if first and anchor and first <= _period(row) <= anchor and value is not None \
                and row.get("unit") == "PERCENT" and row.get("eventId") \
                and row.get("eventType") and not isinstance(row.get("reactionWindowSessions"), bool) \
                and row.get("reactionWindowSessions") in (1, 3, 5):
            key = str(row["eventType"]) + ":" + str(row["reactionWindowSessions"])
            reactions[key] = {"value": value, "date": _period(row),
                              "eventId": row["eventId"], "unit": "PERCENT", **_receipt(row)}
    body = {
        "schemaVersion": SCHEMA_VERSION, "instrumentId": INSTRUMENT,
        "cutoff": cutoff, "anchorDate": anchor, "window": window,
        "status": "AVAILABLE" if enough else "INSUFFICIENT_PRICE_HISTORY",
        "states": states, "conditions": conditions, "reactions": reactions,
        "policyHash": _hash(_policy_material(policy)),
        "historicalVintageVerified": False,
    }
    return {**body, "snapshotId": _hash(body)}


def _verify_episode(episode: Mapping[str, Any], policy: AnalogPolicy) -> None:
    body = {key: value for key, value in episode.items() if key != "snapshotId"}
    if episode.get("snapshotId") != _hash(body):
        raise ValueError("episode_content_changed")
    if episode.get("instrumentId") != INSTRUMENT or episode.get("policyHash") != _hash(_policy_material(policy)):
        raise ValueError("episode_policy_or_instrument_mismatch")


def _shape(episode: Mapping[str, Any]) -> list[float]:
    window = episode["window"]
    anchor = window[-1]["close"]
    return [row["close"] / anchor * 100 for row in window]


def _sequence(episode: Mapping[str, Any]) -> list[tuple[str, ...]]:
    # Conditions within the same session are simultaneous, not a fabricated
    # intraday order inferred from field sorting.
    days: dict[str, set[str]] = {}
    for row in episode["conditions"]:
        days.setdefault(row["date"], set()).add(row["condition"] + ":" + str(row["direction"]))
    return [tuple(sorted(tokens)) for _, tokens in sorted(days.items())]


def _edit_distance(left: Sequence[Any], right: Sequence[Any]) -> float:
    previous = list(range(len(right) + 1))
    for i, item in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (item != other)))
        previous = current
    return previous[-1] / max(len(left), len(right), 1)


def select_episodes(current: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], *,
                    session_dates: Sequence[str], policy: AnalogPolicy = AnalogPolicy()) -> dict[str, Any]:
    """Rank a sealed past-only set. Forward paths are attached in another call."""
    _verify_episode(current, policy)
    if list(session_dates) != sorted(set(session_dates)):
        raise ValueError("unique_ordered_session_calendar_required")
    positions = {day: index for index, day in enumerate(session_dates)}
    if current["status"] == "AVAILABLE" and current["anchorDate"] not in positions:
        raise ValueError("current_anchor_missing_from_calendar")
    scored = []
    if current["status"] == "AVAILABLE":
        current_index = positions[current["anchorDate"]]
        if [row["date"] for row in current["window"]] != list(
                session_dates[current_index - policy.lookback_sessions:current_index + 1]):
            raise ValueError("current_window_missing_exchange_sessions")
        current_shape = _shape(current)
        for candidate in candidates:
            _verify_episode(candidate, policy)
            anchor = candidate["anchorDate"]
            if candidate["status"] != "AVAILABLE" or anchor not in positions:
                continue
            if positions[current["anchorDate"]] - positions[anchor] < policy.lookback_sessions + 1:
                continue
            candidate_cutoff = _instant(candidate["cutoff"])
            if candidate_cutoff is None or candidate_cutoff.date().isoformat() != anchor \
                    or candidate_cutoff >= _instant(current["cutoff"]):
                continue
            anchor_index = positions[anchor]
            if [row["date"] for row in candidate["window"]] != list(
                    session_dates[anchor_index - policy.lookback_sessions:anchor_index + 1]):
                continue
            shape = _shape(candidate)
            shape_distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(current_shape, shape)) /
                                       len(shape)) / policy.shape_scale_pct
            common = sorted(set(current["states"]) & set(candidate["states"]))
            state_deltas = {key: abs(current["states"][key]["value"] -
                                    candidate["states"][key]["value"]) / FEATURE_DEFINITIONS[key][1]
                            for key in common}
            state_distance = math.sqrt(sum(v * v for v in state_deltas.values()) / len(common)) if common else None
            current_order, past_order = _sequence(current), _sequence(candidate)
            order_distance = _edit_distance(current_order, past_order) if current_order and past_order else None
            common_reactions = sorted(set(current["reactions"]) & set(candidate["reactions"]))
            reaction_distance = (math.sqrt(sum((current["reactions"][key]["value"] -
                                               candidate["reactions"][key]["value"]) ** 2
                                              for key in common_reactions) / len(common_reactions)) / 5
                                 if common_reactions else None)
            distances = {"priceShape": shape_distance, "marketState": state_distance,
                         "conditionOrder": order_distance, "materialReaction": reaction_distance}
            available = [v for v in distances.values() if v is not None]
            distance = sum(available) / len(available)
            missing = sorted(set(FEATURE_DEFINITIONS) - set(common))
            complete = not missing and order_distance is not None and reaction_distance is not None
            if distance > policy.maximum_distance:
                continue
            differences = [{"feature": key, "scaledAbsoluteDifference": value}
                           for key, value in sorted(state_deltas.items(), key=lambda item: (-item[1], item[0]))[:3]]
            if not differences:
                differences = [{"feature": "marketState", "status": "NOT_COMPARABLE"}]
            scored.append({
                "snapshotId": candidate["snapshotId"], "anchorDate": anchor,
                "distance": distance, "componentDistances": distances,
                "comparisonKind": "MARKET_ANALOG" if complete else "PARTIAL_COMPARISON",
                "missingFeatures": missing,
                "missingGroups": [key for key, value in distances.items() if value is None],
                "similarityReasons": sorted((key for key, value in distances.items() if value is not None),
                                            key=lambda key: (distances[key], key)),
                "importantDifferences": differences,
                "limitations": ["historical_vintage_not_verified",
                                "measured_feature_similarity_does_not_establish_equal_context"],
                "historicalVintageVerified": False,
            })
    selected = []
    for candidate in sorted(scored, key=lambda row: (row["comparisonKind"] != "MARKET_ANALOG",
                                                        row["distance"], row["anchorDate"], row["snapshotId"])):
        if any(abs(positions[candidate["anchorDate"]] - positions[other["anchorDate"]]) <
               policy.minimum_separation_sessions for other in selected):
            continue
        selected.append(candidate)
        if len(selected) == policy.maximum_candidates:
            break
    body = {
        "schemaVersion": SCHEMA_VERSION, "policy": asdict(policy),
        "currentSnapshotId": current["snapshotId"], "informationCutoff": current["cutoff"],
        "candidateCount": len(candidates),
        "admittedCount": len(scored), "selected": selected,
        "status": ("MARKET_ANALOGS_AVAILABLE" if any(row["comparisonKind"] == "MARKET_ANALOG" for row in selected)
                   else "PARTIAL_COMPARISONS_ONLY" if selected else "NO_STRONG_ANALOG"),
        "actionAuthority": False, "predictiveProbability": None,
        "validationStatus": "UNVALIDATED", "outcomesUsedForSelection": False,
    }
    return {**body, "selectionId": _hash(body)}


def reference_path(episode: Mapping[str, Any], *, later_bars: Sequence[Mapping[str, Any]],
                   display_cutoff: str, session_dates: Sequence[str], horizon_sessions: int = 5,
                   policy: AnalogPolicy = AnalogPolicy()) -> dict[str, Any]:
    """Display an already selected past outcome. It cannot change selection."""
    _verify_episode(episode, policy)
    if isinstance(horizon_sessions, bool) or horizon_sessions not in (1, 5, 10, 20):
        raise ValueError("unsupported_reference_horizon")
    if episode["status"] != "AVAILABLE":
        return {"status": "UNAVAILABLE", "comparison": [], "subsequentReference": []}
    anchor_price = episode["window"][-1]["close"]
    comparison = [{"offsetSessions": index - policy.lookback_sessions,
                   "date": row["date"], "value": row["close"] / anchor_price * 100}
                  for index, row in enumerate(episode["window"])]
    visible = _visible([dict(row) for row in later_bars if isinstance(row, Mapping) and
                        _identity(row) == INSTRUMENT], display_cutoff)
    if list(session_dates) != sorted(set(session_dates)) or episode["anchorDate"] not in session_dates:
        raise ValueError("reference_exchange_calendar_required")
    expected_dates = list(session_dates[session_dates.index(episode["anchorDate"]) + 1:])[:horizon_sessions]
    later = sorted((row for row in visible if _period(row) > episode["anchorDate"] and
                    _field(row) in {"OHLCV_BAR", "close"}), key=_period)[:horizon_sessions]
    subsequent = [{"offsetSessions": 0, "date": episode["anchorDate"], "value": 100.0}]
    for index, row in enumerate(later, 1):
        value = _finite(row.get("close", row.get("value")))
        if value is None or value <= 0 or index > len(expected_dates) or _period(row) != expected_dates[index - 1]:
            break
        subsequent.append({"offsetSessions": index, "date": _period(row),
                           "value": value / anchor_price * 100})
    return {"status": "AVAILABLE" if len(subsequent) == horizon_sessions + 1 else "PARTIAL",
            "snapshotId": episode["snapshotId"], "anchorDate": episode["anchorDate"],
            "displayCutoff": display_cutoff,
            "scale": "ANCHOR_100", "scaleFormula": "past close / past anchor close * 100",
            "comparison": comparison, "subsequentReference": subsequent,
            "subsequentReferenceIsPrediction": False, "horizonSessions": horizon_sessions}
