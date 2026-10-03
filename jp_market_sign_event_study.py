"""Event study of the seven warning conditions (D01-D07) on the Nikkei.

For each condition this answers, on the engine's own history: when did the
condition switch on, what did the index do afterwards, how often was that a
fall compared with any session, and does that hold in a later period that the
earlier periods did not see. It describes the past; it never turns a share
into a probability (``predictiveProbabilities`` is always ``None``) and it
carries no action authority.

Inputs are the condition events the market feature history already records
(``jp_market_features`` state flips, ``value`` +1 when a condition becomes
met, -1 when it stops) and the index closes the comparison already uses.

Point-in-time rules:
- an activation is known at the engine's knowledge time (the latest of
  ``publishedAt``, ``availableFrom`` and the replay ``knownAt``, as the rest
  of the engine reads rows); rows known after the information cutoff are
  ignored;
- for a (series, date) with revisions, the first-known row is used, which is
  what could have been seen at the time;
- the entry is the close of the first exchange session strictly after the
  Japan calendar date the activation became known (an event known after a
  session's close is first actionable at the next close; one known during a
  session is treated the same way, conservatively);
- forward returns use only closes at or before the cutoff.

Distinct activations: an activation whose entry falls within
``COOLDOWN_SESSIONS`` of the previous counted entry is merged into it, so the
20-session outcome windows of counted activations do not overlap.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from jp_market_analog_backtest import wilson_lower_bound
from jp_market_engine import _instant, _knowledge_time

METHOD = "jp-sign-event-study-v1"
SCHEMA_VERSION = "jp-sign-event-study-v1"
HORIZONS = (5, 20)
PRIMARY_HORIZON = 5
COOLDOWN_SESSIONS = 20
MINIMUM_ACTIVATIONS = 20
PERIOD_NAMES = ("design", "confirm", "report")
FAMILIES = ("D01", "D02", "D03", "D04", "D05", "D06", "D07")
JST = timezone(timedelta(hours=9))

# Activation = the transition into the state the product shows as met
# (conditionMet true in jp_market_engine). For D06 that state is a negative
# VIX MACD histogram, which the feature history records as -1 on the
# ``vix_macd_cross`` series.
# ``expects`` is the direction each condition's registered claim points to:
# a thin short balance, a long-heavy 1570 and a PER of 19 or more warn of a
# fall; relative strength (short-cover evidence), foreign inflow
# (confirmation) and a VIX MACD dead cross (recovery) point to a rise. Each
# condition is judged in its own direction, never all as warnings.
ACTIVATION_RULES = {
    "D01": {"seriesId": "d01_short_balance_below_threshold", "value": 1, "expects": "FALL"},
    "D02": {"seriesId": "d02_margin1570_ratio_at_least_one", "value": 1, "expects": "FALL"},
    "D03": {"seriesId": "d03_relative_strength_positive", "value": 1, "expects": "RISE"},
    "D04": {"seriesId": "d04_index_per_at_least_19", "value": 1, "expects": "FALL"},
    "D05": {"seriesId": "d05_foreign_flow_inflow", "value": 1, "expects": "RISE"},
    "D06": {"seriesId": "vix_macd_cross", "value": -1, "expects": "RISE"},
}
# D07 is a per-stock earnings reaction without a market-level activation rule
# in the source, so the feature history emits no events for it.
NOT_EVALUABLE = {"D07": "no_market_level_activation_rule"}


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _first_known_events(condition_rows, cutoff_time):
    """(seriesId, date) -> (known_time, value) for the first-known revision."""
    first: dict[tuple[str, str], tuple[datetime, int]] = {}
    for row in condition_rows:
        if not isinstance(row, Mapping):
            continue
        series, day = row.get("seriesId"), str(row.get("date") or "")[:10]
        value = row.get("value")
        known = _knowledge_time(row)
        if (not isinstance(series, str) or len(day) != 10 or known is None or known > cutoff_time
                or isinstance(value, bool) or value not in (1, -1)):
            continue
        key = (series, day)
        if key not in first or known < first[key][0]:
            first[key] = (known, int(value))
    return first


def _session_after(sessions: Sequence[str], day: str) -> int | None:
    from bisect import bisect_right
    index = bisect_right(sessions, day)
    return index if index < len(sessions) else None


def _forward(closes, sessions, index, horizon):
    if index + horizon >= len(sessions):
        return None
    start, end = closes.get(sessions[index]), closes.get(sessions[index + horizon])
    if not start or not end:
        return None
    return end / start - 1.0


def _metrics(event_indices, baseline_indices, closes, sessions, horizon, expects="FALL"):
    outcomes = [r for r in (_forward(closes, sessions, i, horizon) for i in event_indices) if r is not None]
    base = [r for r in (_forward(closes, sessions, i, horizon) for i in baseline_indices) if r is not None]
    falls = sum(r < 0 for r in outcomes)
    rises = sum(r > 0 for r in outcomes)
    base_falls = sum(r < 0 for r in base)
    base_rises = sum(r > 0 for r in base)
    hits, base_hits = (falls, base_falls) if expects == "FALL" else (rises, base_rises)
    return {
        "evaluated": len(outcomes), "falls": falls,
        "fallShare": _round(falls / len(outcomes)) if outcomes else None,
        "fallShareWilsonLower95": _round(wilson_lower_bound(falls, len(outcomes))),
        "riseShare": _round(rises / len(outcomes)) if outcomes else None,
        "meanReturnPct": _round(statistics.fmean(outcomes) * 100) if outcomes else None,
        "baselineSessions": len(base),
        "baselineFallShare": _round(base_falls / len(base)) if base else None,
        "baselineMeanReturnPct": _round(statistics.fmean(base) * 100) if base else None,
        # In the condition's own direction (``expects``).
        "hits": hits,
        "hitShare": _round(hits / len(outcomes)) if outcomes else None,
        "hitShareWilsonLower95": _round(wilson_lower_bound(hits, len(outcomes))),
        "baselineHitShare": _round(base_hits / len(base)) if base else None,
    }


def _empty_condition(family, status, reason):
    return {"family": family, "seriesId": (ACTIVATION_RULES.get(family) or {}).get("seriesId"),
            "activationValue": (ACTIVATION_RULES.get(family) or {}).get("value"),
            "expects": (ACTIVATION_RULES.get(family) or {}).get("expects"),
            "status": status, "reason": reason, "rawActivations": 0, "activations": 0,
            "overlappingMerged": 0, "firstActivation": None, "lastActivation": None,
            "coverageStart": None, "coverageEnd": None, "horizons": {}, "falseAlarms": 0,
            "falseAlarmShare": None, "periods": [], "predictiveProbabilities": None,
            "actionAuthority": False}


def _condition(family, rule, events, closes, sessions):
    series_events = sorted(((known, day, value) for (series, day), (known, value) in events.items()
                            if series == rule["seriesId"]), key=lambda item: (item[0], item[1]))
    if not series_events:
        return _empty_condition(family, "INSUFFICIENT_SAMPLE", "no_condition_events_in_history")
    # The series is observable from its first recorded flip in either direction;
    # the baseline covers the same span so a short history is not compared with
    # ten years of other sessions.
    def entry(known):
        return _session_after(sessions, known.astimezone(JST).date().isoformat())
    coverage_start = entry(series_events[0][0])
    last_evaluable = max((i for i in range(len(sessions)) if _forward(closes, sessions, i, PRIMARY_HORIZON) is not None),
                         default=None)
    if coverage_start is None or last_evaluable is None or last_evaluable < coverage_start:
        return _empty_condition(family, "INSUFFICIENT_SAMPLE", "no_evaluable_sessions_after_first_event")
    raw, counted, merged = 0, [], 0
    for known, _day, value in series_events:
        if value != rule["value"]:
            continue
        index = entry(known)
        if index is None or not closes.get(sessions[index]):
            continue
        raw += 1
        if counted and index < counted[-1] + COOLDOWN_SESSIONS:
            merged += 1
            continue
        counted.append(index)
    baseline = range(coverage_start, last_evaluable + 1)
    expects = rule.get("expects", "FALL")
    horizons = {str(h): _metrics(counted, baseline, closes, sessions, h, expects) for h in HORIZONS}
    both = [(a, b) for a, b in ((_forward(closes, sessions, i, 5), _forward(closes, sessions, i, 20)) for i in counted)
            if a is not None and b is not None]
    # A false alarm: the expected move showed at neither horizon.
    false_alarms = sum((a >= 0 and b >= 0) if expects == "FALL" else (a <= 0 and b <= 0) for a, b in both)
    span = last_evaluable + 1 - coverage_start
    periods = []
    for number, name in enumerate(PERIOD_NAMES):
        lo = coverage_start + span * number // 3
        hi = coverage_start + span * (number + 1) // 3
        inside = [i for i in counted if lo <= i < hi]
        periods.append({"name": name, "start": sessions[lo] if hi > lo else None,
                        "end": sessions[hi - 1] if hi > lo else None, "activations": len(inside),
                        "horizons": {str(h): _metrics(inside, range(lo, hi), closes, sessions, h, expects)
                                     for h in HORIZONS}})
    primary = horizons[str(PRIMARY_HORIZON)]
    report = periods[-1]["horizons"][str(PRIMARY_HORIZON)]
    if primary["evaluated"] < MINIMUM_ACTIVATIONS:
        status, reason = "INSUFFICIENT_SAMPLE", "fewer_than_20_non_overlapping_activations"
    elif (report["hitShareWilsonLower95"] is not None and report["baselineHitShare"] is not None
          and report["hitShareWilsonLower95"] > report["baselineHitShare"]):
        status, reason = "ABOVE_BASELINE", None
    else:
        status, reason = "NOT_ABOVE_BASELINE", "report_period_wilson_lower_not_above_baseline"
    return {**_empty_condition(family, status, reason),
            "rawActivations": raw, "activations": len(counted), "overlappingMerged": merged,
            "firstActivation": sessions[counted[0]] if counted else None,
            "lastActivation": sessions[counted[-1]] if counted else None,
            "coverageStart": sessions[coverage_start], "coverageEnd": sessions[last_evaluable],
            "horizons": horizons, "falseAlarms": false_alarms,
            "falseAlarmShare": _round(false_alarms / len(both)) if both else None,
            "periods": periods}


def sign_event_study(condition_rows: Sequence[Mapping[str, Any]], closes: Mapping[str, float],
                     session_dates: Sequence[str], *, cutoff: str) -> dict[str, Any]:
    """Per-condition history of activations and what followed them."""
    cutoff_time = _instant(cutoff)
    if cutoff_time is None:
        raise ValueError("valid_information_cutoff_required")
    sessions = list(session_dates)
    if sessions != sorted(set(sessions)):
        raise ValueError("unique_ordered_session_calendar_required")
    cutoff_day = cutoff_time.astimezone(JST).date().isoformat()
    sessions = [day for day in sessions if day <= cutoff_day]
    usable = {day: float(value) for day, value in closes.items()
              if day <= cutoff_day and isinstance(value, (int, float)) and not isinstance(value, bool)
              and value > 0 and value == value and value != float("inf")}
    events = _first_known_events(condition_rows, cutoff_time)
    conditions = {}
    for family in FAMILIES:
        if family in NOT_EVALUABLE:
            conditions[family] = _empty_condition(family, "NOT_EVALUABLE", NOT_EVALUABLE[family])
        else:
            conditions[family] = _condition(family, ACTIVATION_RULES[family], events, usable, sessions)
    return {
        "schemaVersion": SCHEMA_VERSION, "method": METHOD, "informationCutoff": cutoff,
        "status": "AVAILABLE" if usable and events else "UNAVAILABLE",
        "entryRule": "close_of_first_session_after_known_japan_date",
        "activationRule": "transition_into_condition_met",
        "fallDefinition": "forward_close_return_below_zero",
        "hitDefinition": "forward_close_return_in_the_condition_expected_direction",
        "falseAlarmDefinition": "expected_direction_at_neither_5_nor_20_sessions",
        "cooldownSessions": COOLDOWN_SESSIONS, "horizons": list(HORIZONS),
        "primaryHorizon": PRIMARY_HORIZON, "minimumActivations": MINIMUM_ACTIVATIONS,
        "periodRule": "chronological_thirds_of_each_condition_coverage",
        "conditions": conditions,
        "historicalVintageVerified": False, "validationStatus": "UNVALIDATED",
        "predictiveProbabilities": None, "actionAuthority": False, "automaticAiCalls": 0,
    }
