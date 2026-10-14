"""Bounded in-process EPS collection diagnostics; no price, I/O or clock."""
from datetime import date, datetime
import re

SCHEMA = "level-map-acquisition-diagnostic-v1"
LIMIT = 20
OUTCOMES = frozenset(("STARTED", "NO_VALUATION_ROWS", "INPUT_INCOMPLETE",
                      "INVALID_ESTIMATE", "STORED_ORIGINAL", "STORED_CORRECTION",
                      "ALREADY_SAVED"))
WARM_STATUSES = frozenset(("NOT_RUN", "NOT_CONFIGURED", "PRICES_COLD", "FAILED",
                           "AVAILABLE", "WAITING_FOR_CURRENT_ESTIMATE",
                           "WAITING_FOR_ESTIMATE"))


def begin(*, current_only, attempted_at, cursor):
    return {"mode": "CURRENT" if current_only else "HISTORICAL",
            "phase": "PREPARING", "attemptedAt": attempted_at,
            "cursorBefore": cursor, "cursorAfter": cursor,
            "selectedDates": None, "outcomes": {}}


def selected(record, days):
    record.update(phase="READING", selectedDates=list(days)[:LIMIT])


def outcome(record, day, status, coverage=None):
    if day not in (record.get("selectedDates") or ()) or not isinstance(status, str) or status not in OUTCOMES:
        return
    coverage = coverage if isinstance(coverage, dict) else {}
    record["outcomes"][day] = {
        "date": day, "status": status,
        "missingMarketCap": coverage.get("missingMarketCap"),
        "missingEarnings": coverage.get("missingEarnings")}


def finish(record, *, cursor, warm_status, error_class=None):
    record.update(phase="FAILED" if error_class else "FINISHED",
                  cursorAfter=cursor, warmStatus=warm_status,
                  errorClass=error_class)


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return value if date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _instant(value):
    if not isinstance(value, str) or len(value) > 40 or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _count(value, limit):
    return value if type(value) is int and 0 <= value <= limit else None


def _enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else None


def _view(raw):
    if not isinstance(raw, dict):
        return None
    raw = dict(raw)
    values = raw.get("selectedDates")
    selection_observed = isinstance(values, (list, tuple))
    days = tuple(values[:LIMIT]) if selection_observed else ()
    safe_days = [day for day in days if _day(day) is not None]
    selection_valid = (selection_observed and len(values) <= LIMIT
                       and len(safe_days) == len(days)
                       and len(set(safe_days)) == len(safe_days))
    outcomes = raw.get("outcomes")
    outcomes = outcomes if isinstance(outcomes, dict) else {}
    rows = []
    if selection_valid:
        for day in safe_days:
            item = outcomes.get(day)
            item = dict(item) if isinstance(item, dict) else {}
            rows.append({"date": day,
                         "status": _enum(item.get("status"), OUTCOMES),
                         "missingMarketCap": _count(item.get("missingMarketCap"), 225),
                         "missingEarnings": _count(item.get("missingEarnings"), 225)})
    error = raw.get("errorClass")
    return {"mode": raw.get("mode") if raw.get("mode") in ("CURRENT", "HISTORICAL") else None,
            "phase": raw.get("phase") if raw.get("phase") in ("PREPARING", "READING", "FINISHED", "FAILED") else None,
            "attemptedAt": _instant(raw.get("attemptedAt")),
            "cursorBefore": _day(raw.get("cursorBefore")),
            "cursorAfter": _day(raw.get("cursorAfter")),
            "warmStatus": _enum(raw.get("warmStatus"), WARM_STATUSES),
            "errorClass": error if error in (None, "TimeoutError", "ReadTimeout", "HTTPError",
                                             "ConnectionError", "ValueError", "KeyError", "OSError",
                                             "TypeError", "LevelMapError") else "OTHER_ERROR",
            "selectionObserved": selection_observed,
            "selectionValid": selection_valid,
            "selectedCount": len(safe_days) if selection_valid else None,
            "outcomes": rows}


def projection(state, *, worker_active=False):
    state = dict(state) if isinstance(state, dict) else {}
    records = state.get("acquisitionDiagnostics")
    records = dict(records) if isinstance(records, dict) else {}
    eps = state.get("eps")
    return {"schemaVersion": SCHEMA, "workerActive": worker_active is True,
            "loaded": state.get("loaded") is True,
            "admittedEstimateCount": len(eps) if isinstance(eps, dict) else None,
            "currentCursor": _day(state.get("epsBackfillCursor")),
            "historical": _view(records.get("HISTORICAL")),
            "current": _view(records.get("CURRENT")),
            "diagnosticOnly": True, "collectionStartedByRead": False,
            "historicalOriginalsOrReceiptTimesChanged": False}
