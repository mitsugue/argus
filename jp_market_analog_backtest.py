"""Walk-forward validation of the Nikkei analog forecast (2026-09-30).

The chart's computed forecast is the median of the selected past episodes'
subsequent paths, with their quartiles as a band. This module measures, on
the engine's own ten-year history and without any information after each
evaluation date, how often that forecast's direction matched what followed,
against a naive always-the-majority rule, and how often the realized value
fell inside the band. It never turns a frequency into a probability.

Point-in-time rules:
- the evaluated date's episode and every candidate episode are the sealed
  episodes the comparison already builds (each built from rows visible at its
  own cutoff);
- a candidate is eligible only when its whole subsequent path had closed by
  the evaluated date (position difference at least lookback + 1 > horizon);
- the per-series yardstick is recomputed each calendar year from state rows
  known before that year starts.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Callable, Mapping, Sequence

from jp_market_analogs import (AnalogPolicy, _sequence, _shape, component_distances,
                               robust_feature_scales)
from jp_market_engine import _knowledge_time, _instant

METHOD = "jp-analog-walk-forward-v1"
HORIZONS = (1, 5, 10, 20)
EVALUATION_STEP_SESSIONS = 5
MINIMUM_PRIOR_CANDIDATES = 250
MINIMUM_DIRECTIONAL_EVALUATIONS = 100
BAND_COVERAGE_RANGE = (0.35, 0.65)
MAXIMUM_EVALUATIONS = 600


def wilson_lower_bound(hits: int, total: int, z: float = 1.959963984540054) -> float | None:
    if total <= 0:
        return None
    p = hits / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / (1 + z * z / total)


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def _classify(change: float, threshold: float) -> str:
    return "up" if change > threshold else "down" if change < -threshold else "flat"


def yearly_policies(state_rows: Sequence[Mapping[str, Any]], years: Sequence[str],
                    base: AnalogPolicy) -> dict[str, AnalogPolicy]:
    """One policy per calendar year whose yardsticks use only rows known
    before 1 January of that year."""
    out = {}
    for year in sorted(set(years)):
        boundary = _instant(f"{year}-01-01T00:00:00Z")
        known = [row for row in state_rows if isinstance(row, Mapping)
                 and (_knowledge_time(row) or boundary) < boundary]
        scales = robust_feature_scales(known)
        out[year] = AnalogPolicy.with_scales(scales, maximum_candidates=base.maximum_candidates,
                                             maximum_distance=base.maximum_distance,
                                             lookback_sessions=base.lookback_sessions,
                                             minimum_separation_sessions=base.minimum_separation_sessions,
                                             shape_scale_pct=base.shape_scale_pct)
    return out



def horizon_metrics(records, h, *, step=EVALUATION_STEP_SESSIONS, flat_threshold_pct=.5):
    """Non-overlapping metrics for one horizon over evaluation records."""
    stride = max(1, math.ceil(h / step))
    rows = [r["horizons"][h] for r in records[::stride] if h in r["horizons"]]
    directional = [r for r in rows if _classify(r["forecast"] - 100, flat_threshold_pct) != "flat"]
    hits = sum(_classify(r["forecast"] - 100, flat_threshold_pct) == _classify(r["realized"] - 100, flat_threshold_pct)
               for r in directional)
    realized_classes = [_classify(r["realized"] - 100, flat_threshold_pct) for r in directional]
    naive = (max(realized_classes.count(k) for k in ("up", "down", "flat")) / len(realized_classes)
             if realized_classes else None)
    covered = sum(r["lower"] <= r["realized"] <= r["upper"] for r in rows)
    hit_rate = hits / len(directional) if directional else None
    lower = wilson_lower_bound(hits, len(directional))
    coverage = covered / len(rows) if rows else None
    mae = statistics.fmean(abs(r["forecast"] - r["realized"]) for r in rows) if rows else None
    naive_mae = statistics.fmean(abs(100 - r["realized"]) for r in rows) if rows else None
    reasons = []
    if len(directional) < MINIMUM_DIRECTIONAL_EVALUATIONS:
        reasons.append("too_few_independent_evaluations")
    if lower is None or naive is None or lower <= naive:
        reasons.append("direction_not_better_than_naive_majority")
    if coverage is None or not BAND_COVERAGE_RANGE[0] <= coverage <= BAND_COVERAGE_RANGE[1]:
        reasons.append("band_coverage_outside_35_65_percent")
    return {
        "evaluations": len(rows), "directionalEvaluations": len(directional), "hits": hits,
        "hitRate": hit_rate, "hitRateWilsonLower95": lower, "naiveMajorityRate": naive,
        "bandCoverage": coverage, "meanAbsoluteError": mae, "naiveNoChangeMeanAbsoluteError": naive_mae,
        "validationStatus": "VALIDATED" if not reasons else "UNVALIDATED", "reasons": reasons,
    }


# Relative component weights tried by the search (price shape fixed at 1 as
# the reference; material reactions are absent from the history today).
WEIGHT_GRID = tuple((("priceShape", 1.0), ("marketState", m), ("conditionOrder", c))
                    for m in (0.5, 1.0, 2.0) for c in (0.0, 0.5, 1.0, 2.0))


def _select(scored, policy):
    scored.sort()
    chosen = []
    for _, _, _, cpos in scored:
        if any(abs(cpos - other) < policy.minimum_separation_sessions for other in chosen):
            continue
        chosen.append(cpos)
        if len(chosen) == policy.maximum_candidates:
            break
    return chosen


def _forecast_rows(chosen, pos, closes, session_dates, last_position):
    base_close = closes[session_dates[pos]]
    out = {}
    for h in HORIZONS:
        outcomes = []
        for cpos in chosen:
            if cpos + h <= last_position and cpos + h < pos:
                start, end = closes.get(session_dates[cpos]), closes.get(session_dates[cpos + h])
                if start and end:
                    outcomes.append(end / start * 100)
        if len(outcomes) < 2:
            continue
        out[h] = {"forecast": statistics.median(outcomes), "lower": _quantile(outcomes, .25),
                  "upper": _quantile(outcomes, .75),
                  "realized": closes[session_dates[pos + h]] / base_close * 100}
    return out


def weight_search(candidates, closes, session_dates, *, policy: AnalogPolicy, state_rows=(),
                  grid=WEIGHT_GRID, choice_horizon: int = 5, flat_threshold_pct: float = .5,
                  step: int = EVALUATION_STEP_SESSIONS, minimum_prior: int = MINIMUM_PRIOR_CANDIDATES,
                  maximum_evaluations: int = MAXIMUM_EVALUATIONS) -> dict[str, Any]:
    """Choose component weights on the first half of the evaluation dates and
    report them on the second half, which the choice never saw.

    The weights are adopted only when the held-out half meets the same
    validation rule as walk_forward for the choice horizon; otherwise the
    original equal weights stay and the result says why. Component distances
    are computed once per (evaluation, candidate) and only re-weighted.
    """
    from jp_market_analogs import weighted_distance
    positions = {day: index for index, day in enumerate(session_dates)}
    ordered = sorted((c for c in candidates if c.get("status") == "AVAILABLE" and c["anchorDate"] in positions),
                     key=lambda c: positions[c["anchorDate"]])
    prepared = [(positions[c["anchorDate"]], c, _shape(c), _sequence(c)) for c in ordered]
    last_position = len(session_dates) - 1
    max_h = max(HORIZONS)
    policies = yearly_policies(state_rows, [c["anchorDate"][:4] for c in ordered], policy) if state_rows else {}
    eligible = [i for i, (pos, c, _, _) in enumerate(prepared)
                if i >= minimum_prior and pos + max_h <= last_position
                and all(session_dates[pos + k] in closes for k in range(0, max_h + 1))]
    evaluation_indices = eligible[::step][-maximum_evaluations:]
    weight_policies = [AnalogPolicy(**{**{k: getattr(policy, k) for k in ("policy_id", "lookback_sessions",
                       "maximum_candidates", "minimum_separation_sessions", "maximum_distance", "shape_scale_pct",
                       "state_scales")}, "component_weights": weights}) for weights in grid]
    records = {index: [] for index in range(len(grid))}
    for i in evaluation_indices:
        pos, current, shape, order = prepared[i]
        year_policy = policies.get(current["anchorDate"][:4], policy)
        parts = []
        for j in range(i):
            cpos, candidate, cshape, corder = prepared[j]
            if pos - cpos < year_policy.lookback_sessions + 1:
                continue
            item = component_distances(current, candidate, year_policy, current_shape=shape,
                                       candidate_shape=cshape, current_order=order, candidate_order=corder)
            parts.append((item["distances"], item["complete"], candidate["anchorDate"], cpos))
        for index, weighted_policy in enumerate(weight_policies):
            scored = []
            for distances, complete, anchor, cpos in parts:
                distance = weighted_distance(distances, weighted_policy)
                if distance <= year_policy.maximum_distance:
                    scored.append((not complete, distance, anchor, cpos))
            chosen = _select(scored, year_policy)
            records[index].append({"anchorDate": current["anchorDate"],
                                   "horizons": _forecast_rows(chosen, pos, closes, session_dates, last_position)})
    if not evaluation_indices:
        return {"method": METHOD + "-weight-search", "status": "INSUFFICIENT_HISTORY", "adopted": False}
    split = len(evaluation_indices) // 2
    def score(index):
        metrics = horizon_metrics(records[index][:split], choice_horizon, step=step, flat_threshold_pct=flat_threshold_pct)
        if metrics["hitRateWilsonLower95"] is None or metrics["naiveMajorityRate"] is None:
            return (-1.0, index)
        return (metrics["hitRateWilsonLower95"] - metrics["naiveMajorityRate"], -index)
    best = max(range(len(grid)), key=score)
    equal = next((index for index, weights in enumerate(grid) if all(v == 1.0 for _, v in weights)), None)
    held_out = {str(h): horizon_metrics(records[best][split:], h, step=step, flat_threshold_pct=flat_threshold_pct)
                for h in HORIZONS}
    return {
        "method": METHOD + "-weight-search", "status": "AVAILABLE", "gridSize": len(grid),
        "chosenWeights": dict(grid[best]), "choiceHorizon": choice_horizon,
        "trainStart": records[best][0]["anchorDate"], "trainEnd": records[best][split - 1]["anchorDate"],
        "testStart": records[best][split]["anchorDate"], "testEnd": records[best][-1]["anchorDate"],
        "train": horizon_metrics(records[best][:split], choice_horizon, step=step, flat_threshold_pct=flat_threshold_pct),
        "test": held_out,
        "equalWeightsTest": (horizon_metrics(records[equal][split:], choice_horizon, step=step,
                                             flat_threshold_pct=flat_threshold_pct) if equal is not None else None),
        "adopted": held_out[str(choice_horizon)]["validationStatus"] == "VALIDATED",
        "predictiveProbabilities": None,
    }


def walk_forward(candidates: Sequence[Mapping[str, Any]], closes: Mapping[str, float],
                 session_dates: Sequence[str], *, policy: AnalogPolicy,
                 state_rows: Sequence[Mapping[str, Any]] = (), flat_threshold_pct: float = .5,
                 step: int = EVALUATION_STEP_SESSIONS, minimum_prior: int = MINIMUM_PRIOR_CANDIDATES,
                 maximum_evaluations: int = MAXIMUM_EVALUATIONS,
                 policy_for_year: Callable[[str], AnalogPolicy] | None = None) -> dict[str, Any]:
    """Evaluate the forecast rule at every `step`-th eligible date.

    candidates: the sealed, complete-window episodes of the comparison, any
    order. closes: session date -> close. Returns per-horizon metrics and a
    status per horizon (VALIDATED only when the directional hit rate's 95%
    Wilson lower bound exceeds the naive majority rate over at least
    MINIMUM_DIRECTIONAL_EVALUATIONS non-overlapping evaluations and the band
    covered the realized value between 35% and 65% of the time).
    """
    positions = {day: index for index, day in enumerate(session_dates)}
    ordered = sorted((c for c in candidates if c.get("status") == "AVAILABLE" and c["anchorDate"] in positions),
                     key=lambda c: positions[c["anchorDate"]])
    prepared = [(positions[c["anchorDate"]], c, _shape(c), _sequence(c)) for c in ordered]
    last_position = len(session_dates) - 1
    max_h = max(HORIZONS)
    if policy_for_year is None:
        policies = yearly_policies(state_rows, [c["anchorDate"][:4] for c in ordered], policy) if state_rows else {}
        policy_for_year = lambda year: policies.get(year, policy)
    eligible_indices = [i for i, (pos, c, _, _) in enumerate(prepared)
                        if i >= minimum_prior and pos + max_h <= last_position
                        and all(session_dates[pos + k] in closes for k in range(0, max_h + 1))]
    evaluation_indices = eligible_indices[::step][-maximum_evaluations:]
    records = []
    for i in evaluation_indices:
        pos, current, shape, order = prepared[i]
        year_policy = policy_for_year(current["anchorDate"][:4])
        scored = []
        for j in range(i):
            cpos, candidate, cshape, corder = prepared[j]
            if pos - cpos < year_policy.lookback_sessions + 1:
                continue
            parts = component_distances(current, candidate, year_policy, current_shape=shape,
                                        candidate_shape=cshape, current_order=order, candidate_order=corder)
            if parts["distance"] <= year_policy.maximum_distance:
                scored.append((not parts["complete"], parts["distance"], candidate["anchorDate"], cpos))
        scored.sort()
        chosen = []
        for _, _, _, cpos in scored:
            if any(abs(cpos - other) < year_policy.minimum_separation_sessions for other in chosen):
                continue
            chosen.append(cpos)
            if len(chosen) == year_policy.maximum_candidates:
                break
        base_close = closes[session_dates[pos]]
        row = {"anchorDate": current["anchorDate"], "selected": len(chosen), "horizons": {}}
        for h in HORIZONS:
            outcomes = []
            for cpos in chosen:
                start, end = closes.get(session_dates[cpos]), closes.get(session_dates[cpos + h]) \
                    if cpos + h <= last_position else None
                if start and end and cpos + h < pos:
                    outcomes.append(end / start * 100)
            if len(outcomes) < 2:
                continue
            median = statistics.median(outcomes)
            lower, upper = _quantile(outcomes, .25), _quantile(outcomes, .75)
            realized = closes[session_dates[pos + h]] / base_close * 100
            row["horizons"][h] = {"forecast": median, "lower": lower, "upper": upper, "realized": realized}
        records.append(row)
    result = {"method": METHOD, "policyId": policy.policy_id, "step": step,
              "evaluationStart": records[0]["anchorDate"] if records else None,
              "evaluationEnd": records[-1]["anchorDate"] if records else None,
              "evaluatedDates": len(records), "flatThresholdPct": flat_threshold_pct,
              "scaleRule": "yearly robust yardsticks from rows known before each year",
              "horizons": {}, "historicalVintageVerified": False, "actionAuthority": False,
              "predictiveProbabilities": None,
              "records": [{"anchorDate": r["anchorDate"], "selected": r["selected"],
                           "horizons": {str(h): v for h, v in r["horizons"].items()}} for r in records]}
    for h in HORIZONS:
        result["horizons"][str(h)] = horizon_metrics(records, h, step=step, flat_threshold_pct=flat_threshold_pct)
    return result
