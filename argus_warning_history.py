"""Current warning rules measured independently of the legacy support rules.

Uses the existing event-study statistics, calendar and input caches. Historical
downloads are not archived vintages and cannot certify predictive validity.
"""
from collections.abc import Mapping
from datetime import date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from argus_warning_conditions import RULE_VERSION
from jp_market_engine import _instant, _knowledge_time, _sha256
from jp_market_sign_event_study import (_condition, _empty_condition, _first_known_events,
                                       FAMILIES, HORIZONS, COOLDOWN_SESSIONS, MINIMUM_ACTIVATIONS)

METHOD = "jp-warning-event-study-v2"


def _number(value):
    try:
        return float(value) if type(value) in (int, float) and isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _first(rows, series, cutoff):
    first = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("seriesId") not in series:
            continue
        day = str(row.get("periodEnd") or row.get("date") or "")
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        known, value = _knowledge_time(row), _number(row.get("value"))
        if known is None or known > cutoff or value is None:
            continue
        key = (row["seriesId"], day)
        if key not in first or known < first[key][0]:
            first[key] = (known, value)
    return first


def _transitions(points, family):
    events, previous, last_period = [], None, ""
    for known, day, met in sorted(points):
        # A late older publication cannot overwrite the latest known period.
        if day <= last_period:
            continue
        if previous is not None and previous[0] != met:
            available = max(known, previous[1]).isoformat()
            events.append({"seriesId": f"{RULE_VERSION}.{family}", "date": day,
                           "value": 1 if met else -1, "availableFrom": available})
        previous, last_period = (met, known), day
    return events


def warning_event_study(*, credit_rows=(), margin_rows=(), foreign_rows=(), vix_features=(),
                        closes, session_dates, cutoff):
    limit = _instant(cutoff)
    if limit is None:
        raise ValueError("warning_study_cutoff_required")
    if session_dates != sorted(set(session_dates)) or len(session_dates) > 3001:
        raise ValueError("warning_study_calendar_required")
    if sum(len(rows) for rows in (credit_rows, margin_rows, foreign_rows, vix_features)) > 60000:
        raise ValueError("warning_study_input_bound")
    points = {family: [] for family in ("D01", "D02", "D05", "D06")}
    for (_, day), (known, value) in _first(credit_rows, {"credit.short_balance"}, limit).items():
        if value >= 0:
            points["D01"].append((known, day, value < 800_000_000_000))
    balances = _first(margin_rows, {"margin.standardized.long_balance", "margin.standardized.short_balance"}, limit)
    for day in {key[1] for key in balances}:
        long = balances.get(("margin.standardized.long_balance", day))
        short = balances.get(("margin.standardized.short_balance", day))
        if long and short and long[1] >= 0 and short[1] > 0:
            points["D02"].append((max(long[0], short[0]), day, long[1] / short[1] >= 1))
    for (_, day), (known, value) in _first(foreign_rows, {"flow.foreign"}, limit).items():
        points["D05"].append((known, day, value < 0))
    for (_, day), (known, value) in _first(vix_features, {"vix.macd_histogram"}, limit).items():
        points["D06"].append((known, day, value > 0))
    rows = [row for family, values in points.items() for row in _transitions(values, family)]
    events = _first_known_events(rows, limit)
    # The caller supplies official sessions and completed cached index closes.
    jst = ZoneInfo('Asia/Tokyo')
    sessions = [day for day in session_dates
                if datetime.combine(date.fromisoformat(day), time(15, 30), jst) <= limit]
    allowed = set(sessions)
    usable = {day: n for day, value in closes.items()
              if day in allowed and (n := _number(value)) is not None and n > 0}
    conditions = {}
    for family in FAMILIES:
        rule = {"seriesId": f"{RULE_VERSION}.{family}", "value": 1, "expects": "FALL"}
        result = (_condition(family, rule, events, usable, sessions) if family in points else
                  _empty_condition(family, "NOT_EVALUABLE", "warning_numeric_rule_not_defined"))
        primary = result.get("horizons", {}).get("5", {})
        conditions[family] = {**result, "seriesId": rule["seriesId"], "activationValue": 1,
                              "expects": "FALL", "ruleId": rule["seriesId"],
                              "evaluated": primary.get("evaluated", 0)}
    body = {"schemaVersion": METHOD, "informationCutoff": cutoff, "ruleVersion": RULE_VERSION,
            "method": METHOD, "conditions": conditions, "horizons": list(HORIZONS),
            "minimumActivations": MINIMUM_ACTIVATIONS, "cooldownSessions": COOLDOWN_SESSIONS,
            "entryRule": "close_of_first_session_after_known_japan_date",
            "historicalVintageVerified": False, "validationStatus": "UNVALIDATED",
            "sourceDigest": _sha256({"credit": credit_rows, "margin": margin_rows, "foreign": foreign_rows,
                                     "vixFeatures": vix_features, "closes": usable, "sessions": sessions}),
            "predictiveProbabilities": None, "actionAuthority": False, "automaticAiCalls": 0,
            "legacySupportResultsReused": False}
    return {**body, "artifactId": "jp-warning-performance-" + _sha256(body)}


def performance_for(report, family, cutoff):
    from jp_market_engine import _content_id_valid
    if (not isinstance(report, Mapping) or report.get("schemaVersion") != METHOD
            or report.get("informationCutoff") != cutoff or report.get("ruleVersion") != RULE_VERSION
            or report.get("actionAuthority") is not False or report.get("predictiveProbabilities") is not None
            or report.get("validationStatus") != "UNVALIDATED"
            or report.get("historicalVintageVerified") is not False
            or report.get("legacySupportResultsReused") is not False
            or not _content_id_valid(report, "jp-warning-performance-")):
        return None
    conditions = report.get("conditions")
    row = conditions.get(family) if isinstance(conditions, Mapping) else None
    return row if (isinstance(row, Mapping) and row.get("ruleId") == f"{RULE_VERSION}.{family}"
                   and row.get("expects") == "FALL" and row.get("actionAuthority") is False
                   and row.get("predictiveProbabilities") is None) else None
