"""Point-in-time backfill of the ARGUS index valuation proxy.

Why this module exists
----------------------
The live proxy lane (``argus_index_valuation_proxy`` plus its scanner glue)
reconstructs the index-based PER only for sessions on or after the as-of date
of the one weight table the owner has placed on the server, and keeps at most
60 of them. D04 (index PER at least 19) and the analog search therefore see no
valuation before that table. This module rebuilds the same quantity for past
sessions, strictly as it could have been computed on each date:

* factors: only a factor set *in force* on the date (a month-end weight table
  whose as-of is on or before the date and not older than a bound, or a set
  rolled back from that table through a declared list of factor events);
* forecast EPS: only statements disclosed strictly before the date, and for
  the earliest fiscal year whose annual result was not yet disclosed;
* closes: the raw closes of that session, in the share units of that session.

The arithmetic is ``argus_index_valuation_proxy.proxy_valuation`` itself, so
the formula is shared with the live lane, not copied. Every point carries its
method, basis, coverage and a rule-derived availability, and nothing here
touches the network, the clock or the disk.

What it does not promise
------------------------
* It is not the official series and never claims to be.
* It does not prove the forecast vintage J-Quants serves today equals what was
  disclosed then (``historicalVintageVerified`` stays False).
* A factor set rolled back through events is only as complete as the event
  list; a missing event shows up as a jump in ``impliedDivisor``.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union

import argus_index_valuation_proxy as proxy

SCHEMA = "argus-index-valuation-backfill-v1"
METHOD = "PIT_STATEMENT_FORECAST_EPS_V1"
EPS_KIND = "PROXY_FROM_PIT_STATEMENT_FORECAST_EPS"
AVAILABILITY_BASIS = "RECONSTRUCTED_SCHEDULED_PUBLICATION"
SOURCE_REF = "argus:index-valuation-backfill:jquants-statements+factor-sets"

#: A month-end table stays in force until the next one; 40 calendar days
#: covers one month plus a holiday-shifted month end, never two months.
MAX_WEIGHT_TABLE_AGE_DAYS = 40
#: Below this share of the factor-weighted price sum carrying a forecast the
#: point is kept but marked unusable (production measured 203 of 225 members
#: with a forecast; the covered price share is the quantity that matters to
#: FORECAST_COVERED_ONLY).
MINIMUM_FORECAST_PRICE_SHARE = 0.80
#: A forecast for a fiscal year that ended this long ago with no annual
#: result on file is a data hole, not a forecast still in force.
STALE_FISCAL_YEAR_DAYS = 183

SPLIT_POLICIES = ("ADJUST_FORECAST_DISCLOSED_BEFORE_EX_DATE", "NONE")
FACTOR_SPLIT_RULES = ("UNCHANGED", "SCALE_BY_SPLIT_RATIO")

_CODE_KEYS = ("LocalCode", "Code", "code")
_DISC_DATE_KEYS = ("DiscDate", "DisclosedDate", "disclosedDate")
_DISC_TIME_KEYS = ("DiscTime", "DisclosedTime", "disclosedTime")
_PERIOD_TYPE_KEYS = ("CurPerType", "TypeOfCurrentPeriod")
_DOC_TYPE_KEYS = ("DocType", "TypeOfDocument")
_FY_END_KEYS = ("CurFYEn", "CurrentFiscalYearEndDate")
_NEXT_FY_END_KEYS = ("NxtFYEn", "NxFYEn", "NextFiscalYearEndDate")
_FORECAST_KEYS = ("FEPS", "ForecastEarningsPerShare")
_NEXT_FORECAST_KEYS = ("NxFEPS", "NextYearForecastEarningsPerShare")
_ACTUAL_KEYS = ("EPS", "EarningsPerShare")


def _field(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _day(value: Any) -> Optional[str]:
    text = str(value or "").strip().replace("/", "-")[:10]
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return _dt.date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _days_between(earlier: str, later: str) -> int:
    return (_dt.date.fromisoformat(later) - _dt.date.fromisoformat(earlier)).days


def code_key(code: Any) -> str:
    """Same rule as the live lane: a five-character code ending in 0 is the
    ordinary share of the four-character code the weight table uses."""
    text = str(code or "").strip().upper()
    return text[:4] if len(text) == 5 and text.endswith("0") else text


def _add_year(day: str) -> str:
    date = _dt.date.fromisoformat(day)
    try:
        return date.replace(year=date.year + 1).isoformat()
    except ValueError:                       # 29 February
        return date.replace(year=date.year + 1, day=28).isoformat()


# ── statements → forecast EPS in force on a date ────────────────────────────

def statement_index(rows: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Compact per-code disclosure entries, ordered by disclosure.

    Only the fields the point-in-time choice needs are kept, so the index of
    ten years of statements for the members stays a few megabytes at most.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for seq, row in enumerate(rows or ()):
        if not isinstance(row, Mapping):
            continue
        code = code_key(_field(row, _CODE_KEYS))
        disclosed = _day(_field(row, _DISC_DATE_KEYS))
        if not code or disclosed is None:
            continue
        period = str(_field(row, _PERIOD_TYPE_KEYS) or "").upper()
        doc = str(_field(row, _DOC_TYPE_KEYS) or "")
        fy_end = _day(_field(row, _FY_END_KEYS))
        next_fy_end = _day(_field(row, _NEXT_FY_END_KEYS))
        forecast = proxy._finite(_field(row, _FORECAST_KEYS))
        next_forecast = proxy._finite(_field(row, _NEXT_FORECAST_KEYS))
        actual = proxy._finite(_field(row, _ACTUAL_KEYS))
        annual = period == "FY" or doc.startswith("FYFinancialStatements")
        if next_fy_end is None and next_forecast is not None and annual and fy_end:
            next_fy_end = _add_year(fy_end)
        if forecast is None and next_forecast is None and not (annual and actual is not None):
            continue
        out.setdefault(code, []).append({
            "disclosed": disclosed, "time": str(_field(row, _DISC_TIME_KEYS) or "99:99")[:8],
            "seq": seq, "annual": annual, "fyEnd": fy_end, "nextFyEnd": next_fy_end,
            "forecast": forecast, "nextForecast": next_forecast, "actual": actual})
    for entries in out.values():
        entries.sort(key=lambda e: (e["disclosed"], e["time"], e["seq"]))
    return out


def _split_multiplier(splits: Optional[Mapping[str, Sequence[Any]]], code: str,
                      after: str, until: str) -> float:
    """Product of the J-Quants adjustment factors (0.5 for a 1:2 split) of
    ex-dates in (after, until]; converts per-share values of ``after`` into
    the share units of ``until``."""
    multiplier = 1.0
    for item in (splits or {}).get(code, ()) or ():
        ex_date, factor = _day(item[0]), proxy._finite(item[1])
        if ex_date and factor and factor > 0 and after < ex_date <= until:
            multiplier *= factor
    return multiplier


def eps_in_force(entries: Sequence[Mapping[str, Any]], date: str, *,
                 splits: Optional[Mapping[str, Sequence[Any]]] = None, code: str = "",
                 split_policy: str = SPLIT_POLICIES[0]) -> Dict[str, Any]:
    """Forecast and actual EPS of one issuer as disclosed strictly before ``date``.

    The forecast is the latest disclosed one for the earliest fiscal year
    whose annual result had not been disclosed yet (the same roll a "current
    fiscal year" consensus makes at the annual result). Same-day disclosures
    are excluded, so a point never uses a release that may follow its close.
    """
    if split_policy not in SPLIT_POLICIES:
        raise proxy.ProxyError("unknown_split_policy")
    usable = [e for e in entries if e["disclosed"] < date]
    by_year: Dict[str, Mapping[str, Any]] = {}
    values: Dict[str, float] = {}
    reported = set()
    latest_actual: Optional[Mapping[str, Any]] = None
    for entry in usable:
        if entry["fyEnd"] and entry["forecast"] is not None:
            by_year[entry["fyEnd"]], values[entry["fyEnd"]] = entry, entry["forecast"]
        if entry["nextFyEnd"] and entry["nextForecast"] is not None:
            by_year[entry["nextFyEnd"]], values[entry["nextFyEnd"]] = entry, entry["nextForecast"]
        if entry["annual"] and entry["fyEnd"]:
            reported.add(entry["fyEnd"])
            if entry["actual"] is not None:
                latest_actual = entry
    open_years = sorted(year for year in by_year if year not in reported
                        and _days_between(year, date) <= STALE_FISCAL_YEAR_DAYS)
    out: Dict[str, Any] = {"forecast": None, "actual": None, "fiscalYearEnd": None,
                           "forecastDisclosed": None, "splitAdjusted": False}
    if open_years:
        year = open_years[0]
        source = by_year[year]
        factor = (_split_multiplier(splits, code, source["disclosed"], date)
                  if split_policy == SPLIT_POLICIES[0] else 1.0)
        out.update(forecast=values[year] * factor, fiscalYearEnd=year,
                   forecastDisclosed=source["disclosed"], splitAdjusted=factor != 1.0)
    if latest_actual is not None:
        factor = (_split_multiplier(splits, code, latest_actual["disclosed"], date)
                  if split_policy == SPLIT_POLICIES[0] else 1.0)
        out["actual"] = latest_actual["actual"] * factor
    return out


# ── factor sets in force ─────────────────────────────────────────────────────

def weight_table_factor_set(derived: Mapping[str, Any]) -> Dict[str, Any]:
    """A factor set from ``proxy.derive_factors``: in force from its as-of for
    at most MAX_WEIGHT_TABLE_AGE_DAYS. Only codes and factors are kept."""
    as_of = _day(derived.get("asOf"))
    factors = {str(c): float(f) for c, f in (derived.get("factors") or {}).items()}
    if as_of is None or not factors:
        raise proxy.ProxyError("factor_set_incomplete")
    return {"origin": "WEIGHT_TABLE", "validFrom": as_of, "validUntil": None,
            "anchorAsOf": as_of, "factors": factors}


def backroll_factor_sets(anchor: Mapping[str, Any], events: Iterable[Mapping[str, Any]], *,
                         complete_since: str) -> List[Dict[str, Any]]:
    """Factor sets before ``anchor`` obtained by undoing declared events.

    Each event is ``{"effectiveDate", "code", "factorBefore", "factorAfter"}``
    (``None`` before = joined, ``None`` after = removed): a constituent change,
    a factor change at a periodic review, or a split under a rule that scales
    the factor. The list must be complete from ``complete_since`` to the
    anchor; an event whose ``factorAfter`` disagrees with the state being
    undone is refused, which is how an incomplete list is caught.
    """
    current = dict(anchor["factors"])
    upper = anchor["validFrom"]
    since = _day(complete_since)
    if since is None or since > upper:
        raise proxy.ProxyError("factor_events_complete_since")
    ordered = sorted((dict(e) for e in events or ()), key=lambda e: _day(e.get("effectiveDate")) or "",
                     reverse=True)
    sets: List[Dict[str, Any]] = []
    for event in ordered:
        effective = _day(event.get("effectiveDate"))
        code = code_key(event.get("code"))
        if effective is None or not code:
            raise proxy.ProxyError("factor_event_shape")
        if effective > upper or effective <= since:
            continue                          # outside the declared window
        after, before = event.get("factorAfter"), event.get("factorBefore")
        held = current.get(code)
        if (after is None) != (held is None) or (after is not None and abs(float(after) - held) > 1e-9):
            raise proxy.ProxyError("factor_event_inconsistent")
        if effective < upper:
            sets.append({"origin": "EVENT_BACKROLL", "validFrom": effective, "validUntil": upper,
                         "anchorAsOf": anchor["validFrom"], "factors": dict(current)})
            upper = effective
        if before is None:
            current.pop(code, None)
        else:
            current[code] = float(before)
    sets.append({"origin": "EVENT_BACKROLL", "validFrom": since, "validUntil": upper,
                 "anchorAsOf": anchor["validFrom"], "factors": dict(current)})
    return sets


def factor_set_in_force(date: str, factor_sets: Iterable[Mapping[str, Any]],
                        max_age_days: int = MAX_WEIGHT_TABLE_AGE_DAYS) -> Optional[Mapping[str, Any]]:
    """The set in force on ``date``: an event-rolled interval containing it,
    else the latest weight table not after it and not older than the bound."""
    best: Optional[Mapping[str, Any]] = None
    for item in factor_sets or ():
        start, until = item["validFrom"], item.get("validUntil")
        if start > date:
            continue
        if item["origin"] == "EVENT_BACKROLL":
            if until is not None and date < until:
                return item
            continue
        if _days_between(start, date) <= max_age_days and (best is None or start > best["validFrom"]):
            best = item
    return best


# ── one session, and many ────────────────────────────────────────────────────

def available_from(date: str) -> str:
    """Rule-derived availability: the next calendar day 00:00Z (09:00 JST),
    the same conservative publication rule the other condition series use."""
    return (_dt.date.fromisoformat(date) + _dt.timedelta(days=1)).isoformat() + "T00:00:00Z"


def _empty_point(date: str, status: str, **extra: Any) -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA, "method": METHOD, "basis": proxy.PROXY_BASIS,
            "basisLabelJa": proxy.BASIS_LABEL_JA, "epsKind": EPS_KIND, "date": date,
            "status": status, "usable": False, "epsVariant": proxy.RECOMMENDED_VARIANT,
            "per": None, "indexEps": None, "availableFrom": available_from(date),
            "knownAt": available_from(date), "availabilityBasis": AVAILABILITY_BASIS,
            "historicalVintageVerified": False, "validationStatus": "UNVALIDATED",
            "actionAuthority": False, "sourceRef": SOURCE_REF, **extra}


def rebuild_point(date: str, *, factor_sets: Sequence[Mapping[str, Any]], closes: Mapping[str, Any],
                  index_close: Any, statements: Mapping[str, Sequence[Mapping[str, Any]]],
                  splits: Optional[Mapping[str, Sequence[Any]]] = None,
                  split_policy: str = SPLIT_POLICIES[0], factor_split_rule: str = "UNCHANGED",
                  max_age_days: int = MAX_WEIGHT_TABLE_AGE_DAYS,
                  minimum_forecast_price_share: float = MINIMUM_FORECAST_PRICE_SHARE) -> Dict[str, Any]:
    """The proxy for one past session, or a point that says why there is none.

    ``closes`` maps code → raw close of ``date``; ``statements`` is the output
    of :func:`statement_index`; ``splits`` maps code → [(exDate, adjFactor)].
    """
    day = _day(date)
    if day is None:
        raise proxy.ProxyError("backfill_date")
    if factor_split_rule not in FACTOR_SPLIT_RULES:
        raise proxy.ProxyError("unknown_factor_split_rule")
    chosen = factor_set_in_force(day, factor_sets, max_age_days)
    if chosen is None:
        return _empty_point(day, "NO_FACTORS_IN_FORCE")
    index = proxy._finite(index_close)
    if index is None or index <= 0:
        return _empty_point(day, "NO_INDEX_CLOSE", factorsAsOf=chosen["validFrom"])
    factors: Dict[str, float] = {}
    split_since_factors = 0
    for code, factor in chosen["factors"].items():
        if chosen["origin"] == "WEIGHT_TABLE":
            multiplier = _split_multiplier(splits, code, chosen["validFrom"], day)
            if multiplier != 1.0:
                split_since_factors += 1
                if factor_split_rule == "SCALE_BY_SPLIT_RATIO":
                    factor = factor / multiplier
        factors[code] = factor
    forecast_eps: Dict[str, float] = {}
    actual_eps: Dict[str, float] = {}
    split_adjusted = 0
    latest_disclosure = None
    price_sum = covered_price_sum = 0.0
    for code, factor in factors.items():
        eps = eps_in_force(statements.get(code, ()), day, splits=splits, code=code,
                           split_policy=split_policy)
        if eps["forecast"] is not None:
            forecast_eps[code] = eps["forecast"]
            split_adjusted += int(eps["splitAdjusted"])
            latest_disclosure = max(latest_disclosure or "", eps["forecastDisclosed"])
        if eps["actual"] is not None:
            actual_eps[code] = eps["actual"]
        close = proxy._finite(closes.get(code))
        if close is not None and close > 0:
            price_sum += close * factor
            if code in forecast_eps:
                covered_price_sum += close * factor
    if price_sum <= 0:
        return _empty_point(day, "NO_PRICES", factorsAsOf=chosen["validFrom"])
    body = proxy.proxy_valuation(
        factors={"factors": factors, "asOf": chosen["validFrom"]}, closes=closes,
        forecast_eps=forecast_eps, actual_eps=actual_eps, index_close=index, date=day,
        available_from=available_from(day), known_at=available_from(day), source_ref=SOURCE_REF)
    coverage = dict(body["coverage"])
    for key in ("missingPrice", "missingForecastEps"):
        coverage[key + "Count"] = len(coverage.pop(key, []) or [])
    share = covered_price_sum / price_sum
    coverage.update(forecastPriceShare=round(share, 4),
                    memberForecastRatio=round(coverage["withForecastEps"] / len(factors), 4),
                    splitAdjustedForecasts=split_adjusted,
                    membersWithSplitSinceFactors=split_since_factors)
    recommended = body["variants"][proxy.RECOMMENDED_VARIANT]
    usable = recommended.get("per") is not None and share >= minimum_forecast_price_share
    status = ("AVAILABLE" if usable else
              "NON_POSITIVE_EPS" if recommended.get("per") is None else "LOW_FORECAST_COVERAGE")
    return _empty_point(
        day, status, usable=usable, per=recommended.get("per"), indexEps=recommended.get("indexEps"),
        indexClose=index, impliedDivisor=body["impliedDivisor"], variants=body["variants"],
        coverage=coverage, factorsAsOf=chosen["validFrom"], factorOrigin=chosen["origin"],
        factorAgeDays=_days_between(chosen["validFrom"], day),
        latestForecastDisclosureUsed=latest_disclosure or None,
        splitPolicy=split_policy, factorSplitRule=factor_split_rule)


ClosesSource = Union[Mapping[str, Mapping[str, Any]], Callable[[str], Mapping[str, Any]]]


def backfill(dates: Iterable[str], *, factor_sets: Sequence[Mapping[str, Any]], closes: ClosesSource,
             index_close_by_date: Mapping[str, Any], statements: Mapping[str, Sequence[Mapping[str, Any]]],
             **options: Any) -> List[Dict[str, Any]]:
    """One point per date, oldest first. ``closes`` is a mapping date → closes
    or a callable returning one date's closes, so a caller can hold a single
    session of prices in memory at a time. A date with no factor set in force
    is answered without asking for its closes."""
    points: List[Dict[str, Any]] = []
    for date in sorted({d for d in (_day(x) for x in dates) if d}):
        if factor_set_in_force(date, factor_sets, options.get("max_age_days", MAX_WEIGHT_TABLE_AGE_DAYS)) is None:
            points.append(_empty_point(date, "NO_FACTORS_IN_FORCE"))
            continue
        day_closes = closes(date) if callable(closes) else (closes.get(date) or {})
        points.append(rebuild_point(date, factor_sets=factor_sets, closes=day_closes or {},
                                    index_close=index_close_by_date.get(date),
                                    statements=statements, **options))
    return points


def month_end_sessions(sessions: Iterable[str]) -> List[str]:
    """The last session of each calendar month present in ``sessions``."""
    last: Dict[str, str] = {}
    for value in sessions or ():
        day = _day(value)
        if day and day > last.get(day[:7], ""):
            last[day[:7]] = day
    return sorted(last.values())


def index_per_rows(points: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Usable points in the row shape the D04 condition reader consumes."""
    return [{"instrumentId": "NIKKEI_225_PER", "seriesId": "close", "date": p["date"],
             "value": p["per"], "availableFrom": p["availableFrom"], "sourceRef": p["sourceRef"],
             "derivationBasis": p["basis"], "method": p["method"]}
            for p in points or () if p.get("usable") and isinstance(p.get("per"), float) and p["per"] > 0]


def summary(points: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Counts by status and the usable span: what a coverage table reports."""
    statuses: Dict[str, int] = {}
    for point in points or ():
        statuses[point["status"]] = statuses.get(point["status"], 0) + 1
    usable = [p["date"] for p in points or () if p.get("usable")]
    return {"schemaVersion": SCHEMA, "method": METHOD, "points": len(points or ()),
            "usable": len(usable), "firstUsable": min(usable) if usable else None,
            "lastUsable": max(usable) if usable else None, "byStatus": statuses,
            "historicalVintageVerified": False}
