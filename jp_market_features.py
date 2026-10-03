"""Descriptive, publication-bounded Japan index features for analog comparison.

Series remain distinct. Relative strength and falling short balances do not
observe covering orders. No aggregation of warning and recovery into a buy
score, and no modification of existing decision authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from jp_market_engine import ARGUS_MACD_BASELINE, _knowledge_time, _macd, point_in_time_rows
from jp_market_dynamics import _number, credit_dynamics, normalize_valuation_loss
from jp_market_analogs import FEATURE_DEFINITIONS, FEATURE_MAX_AGE_DAYS, INSTRUMENT


HISTORY_CACHE_SCHEMA = "jp-market-feature-cache-v1"
HISTORY_CACHE_MAX_BYTES = 32 * 1024 * 1024


# Calculation version of the restored feature history (2026-10-02). Bump it
# for any change to how features or condition events are derived from their
# inputs; the parity test pins the canonical-fixture result to this value.
# Until 2026-10-02 the identity hashed the bytes of five module files, so every
# deploy that touched one of them (a comment, an unrelated function in the
# acquisition module) discarded the verified history and replayed ten years.
# Input changes are not method changes: the per-source manifest of each saved
# history already rejects changed inputs.
# v3 (2026-10-03): investor-type rows are known from their official PubDate,
# not from the later import that stamped knownAt (see
# _flow_publication_availability).
FEATURE_HISTORY_METHOD_VERSION = "jp-market-feature-method-v3"


def history_method_parameters() -> dict[str, Any]:
    """Named numerical parameters of the feature calculation, as data."""
    from jp_market_engine import JP_MARKET_ENGINE_D01_THRESHOLD_JPY
    return {
        "featureDefinitions": {key: list(value) for key, value in FEATURE_DEFINITIONS.items()},
        "featureMaxAgeDays": dict(FEATURE_MAX_AGE_DAYS), "instrument": INSTRUMENT,
        "macdBaseline": list(ARGUS_MACD_BASELINE),
        "signConditionIds": dict(SIGN_CONDITION_IDS),
        "signConditionLookbackDays": SIGN_CONDITION_LOOKBACK_DAYS,
        "signThresholds": {"D01": JP_MARKET_ENGINE_D01_THRESHOLD_JPY,
                           "D02": D02_MARGIN_RATIO_THRESHOLD, "D04": D04_INDEX_PER_THRESHOLD},
        "featureInputWindowDays": FEATURE_INPUT_WINDOW_DAYS,
        "lossProxy": [LOSS_PROXY_BASIS, LOSS_PROXY_WEEKS, LOSS_PROXY_MINIMUM_WEEKS],
    }


def _canonical_fixture_inputs() -> dict[str, Any]:
    """Deterministic synthetic inputs that exercise every feature and condition."""
    # Triangle waves from integer arithmetic only: transcendental library
    # functions can differ in the last bit between platforms.
    def wave(index, period):
        phase = (index % period) * 4 / period
        return phase - 1 if phase < 2 else 3 - phase

    start = date(2025, 1, 1)
    days = [start + timedelta(days=i) for i in range(450)]
    sessions = [day for day in days if day.weekday() < 5]

    def series(instrument, base, amplitude, period, *, field="close", unit=None, hour=7, step=0.0):
        rows = []
        for index, day in enumerate(sessions):
            value = round(base + step * index + amplitude * wave(index, period), 6)
            row = {"instrumentId": instrument, "seriesId": field, "date": day.isoformat(),
                   "value": value, "close": value,
                   "availableFrom": f"{day.isoformat()}T{hour:02d}:00:00Z"}
            if unit:
                row["unit"] = unit
            rows.append(row)
        return rows

    fridays = [day for day in days if day.weekday() == 4]
    weekly = lambda day: (day + timedelta(days=6)).isoformat() + "T06:00:00Z"
    credit, margin, flows = [], [], []
    for index, day in enumerate(fridays):
        swing = wave(index, 19)
        credit += [{"instrumentId": "MARKET", "seriesId": "credit.long_balance", "periodEnd": day.isoformat(), "unit": "JPY",
                    "value": 3.5e12 + 4e11 * swing + 1e10 * index, "availableFrom": weekly(day)},
                   {"instrumentId": "MARKET", "seriesId": "credit.short_balance", "periodEnd": day.isoformat(), "unit": "JPY",
                    "value": 8e11 + 2e11 * wave(index + 3, 13), "availableFrom": weekly(day)}]
        margin += [{"instrumentId": "1570", "seriesId": "margin.long_balance", "periodEnd": day.isoformat(), "unit": "SHARES",
                    "value": 1.0e6 + 3e5 * swing, "availableFrom": weekly(day)},
                   {"instrumentId": "1570", "seriesId": "margin.short_balance", "periodEnd": day.isoformat(), "unit": "SHARES",
                    "value": 1.0e6 + 3e5 * wave(index + 4, 16), "availableFrom": weekly(day)}]
        flows.append({"instrumentId": "MARKET", "seriesId": "flow.foreign", "unit": "JPY",
                      "periodEnd": day.isoformat(), "value": 2e11 * wave(index, 11),
                      "availableFrom": weekly(day),
                      # A one-time backfill stamps its import as knownAt.
                      "knownAt": "2026-09-30T00:00:00Z"})
    return {
        "price_series": {
            "nikkei": series(INSTRUMENT, 38000, 2500, 9, step=3.0),
            "sp500": series("SP500_INDEX", 5800, 300, 7, hour=21, step=0.5),
            "vix": series("VIX", 18, 6, 4, hour=22),
            "topix": series("TOPIX_INDEX", 2700, 150, 11, hour=9),
            "usdjpy": series("USDJPY", 150, 4, 6, hour=23),
            "jp10y": series("JP10Y", 0.2, 0.4, 13, field="yield_pct", unit="PERCENT", hour=8),
            "us10y": series("US10Y", 4.2, 0.5, 10, field="yield", unit="PERCENT", hour=22),
            "index_per": series("NIKKEI_225_PER", 19, 1.5, 8),
        },
        "two_market_credit": credit, "margin_1570": margin, "foreign_flow": flows,
        "sq_events": [{"eventId": "jp-monthly-sq-2026-03", "calendarStatus": "RULE_DERIVED",
                       "sqDate": "2026-03-13", "tradingSessionsUntil": 4,
                       "calculatedAt": "2026-03-09T00:00:00+09:00", "knownAt": "2026-03-09T00:00:00+09:00",
                       "sourceRef": "fixture:sq-rule"}],
    }


@lru_cache(maxsize=1)
def history_method_fingerprint() -> str:
    """Result digest of the calculation on the canonical fixture.

    Comments, formatting and unrelated functions do not change it; a changed
    formula, threshold or window that the fixture exercises does. It does not
    replace the explicit version: the parity test pins it, so a formula change
    fails CI until the version is advanced deliberately.
    """
    inputs = _canonical_fixture_inputs()
    cutoffs = ["2026-01-30T23:59:59Z", "2026-02-27T23:59:59Z", "2026-03-09T12:00:00+09:00"]
    loss = [{"instrumentId": "MARKET", "seriesId": "credit.valuation_loss_pct", "periodEnd": "2026-02-20",
             "value": -7.5, "unit": "PERCENT", "signConvention": "negative_is_loss",
             "availableFrom": "2026-02-26T06:00:00Z"}]
    results = [build_market_features(cutoff=at, **inputs) for at in cutoffs]
    results.append(build_market_features(cutoff=cutoffs[-1], valuation_loss=loss, **inputs))
    return _history_digest(results)


def history_method_identity() -> str:
    """Bind restored calculations to the calculation version and parameters.

    The identity is the explicit version, the named parameters and the
    canonical-fixture result. Module bytes are not part of it.
    """
    return _history_digest({"version": FEATURE_HISTORY_METHOD_VERSION,
                            "parameters": history_method_parameters(),
                            "fixtureResult": history_method_fingerprint()})


def _history_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def history_cache_envelope(history, *, method: str) -> dict[str, Any]:
    """Derived cache only; it does not certify historical vintage or skill."""
    from jp_market_engine import _instant
    if (not isinstance(history, dict) or history.get("status") != "AVAILABLE"
            or history.get("schemaVersion") != "jp-market-feature-history-v1"
            or not isinstance(history.get("inputIdentity"), str)
            or len(history["inputIdentity"]) != 64
            or not isinstance(history.get("cutoffCount"), int)
            or not 1 <= history["cutoffCount"] <= 3001
            or history.get("historicalVintageVerified") is not False
            or history.get("actionAuthority") is not False
            or history.get("automaticAiCalls") != 0
            or not isinstance(method, str) or len(method) != 64):
        raise ValueError("feature_cache_identity")
    dates = [_instant(history.get(name)) for name in
             ("firstCutoff", "lastCutoff", "lastSuccessfulCalculationAt")]
    if any(at is None for at in dates) or not dates[0] <= dates[1] <= dates[2]:
        raise ValueError("feature_cache_times")
    groups = [history.get(key) for key in ("features", "conditions")]
    if any(not isinstance(rows, list) for rows in groups) or sum(map(len, groups)) > 60000:
        raise ValueError("feature_cache_history_bound")
    body = {"schemaVersion": HISTORY_CACHE_SCHEMA, "methodIdentity": method,
            "history": history}
    return {**body, "sha256": _history_digest(body)}


def load_history_cache(path, *, method: str, now: str):
    """Read once on the background lane; mismatch never becomes current data."""
    from jp_market_engine import _instant
    target = Path(path)
    if target.is_symlink():
        raise ValueError("feature_cache_symlink")
    with target.open("rb") as handle:
        raw = handle.read(HISTORY_CACHE_MAX_BYTES + 1)
    if len(raw) > HISTORY_CACHE_MAX_BYTES:
        raise ValueError("feature_cache_size_bound")
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get("schemaVersion") != HISTORY_CACHE_SCHEMA:
        raise ValueError("feature_cache_schema")
    expected = history_cache_envelope(doc.get("history"), method=doc.get("methodIdentity"))
    if doc != expected:
        raise ValueError("feature_cache_integrity")
    instant = _instant(now)
    if instant is None or _instant(doc["history"]["lastSuccessfulCalculationAt"]) > instant:
        raise ValueError("feature_cache_future")
    return doc["history"] if doc["methodIdentity"] == method else None


def _source_lists(inputs):
    """Exact source prefixes; no prices, revisions or publication times discarded."""
    lists = {"price_series:" + key: list(rows)
             for key, rows in inputs.get("price_series", {}).items()}
    for key, rows in inputs.items():
        if key != "price_series":
            lists[key] = list(rows)
    return lists


def _effective_knowledge(row, key):
    """Earliest instant at which a row can influence any calculation, or None.

    Every consumer in build_market_features admits a row only through its
    knowledge time (point_in_time_rows, _history); a schedule row also needs
    its own calculation instant. None means it cannot be bounded.
    """
    from jp_market_engine import _instant
    if not isinstance(row, Mapping):
        return None
    known = _knowledge_time(row)
    if key == "sq_events":
        # The schedule consumer requires both instants, never the period.
        calculated = _instant(row.get("calculatedAt"))
        if known is None or calculated is None:
            return None
        return max(known, calculated)
    # The same rows the append rule refuses to bound: no observation date, or
    # a correction without its own receipt.
    if (_instant(str(row.get("periodEnd") or row.get("date") or "")[:10] + "T00:00:00Z") is None
            or (row.get("revision", 0) != 0 and _instant(row.get("knownAt")) is None)):
        return None
    return known


def _known_through_digest(rows, boundary, key):
    """Digest of the rows that any cutoff at or before `boundary` can see.

    Order is preserved; rows that cannot be bounded are always included, so
    this never ignores a row that could affect an earlier cutoff.
    """
    kept = []
    for row in rows:
        known = _effective_knowledge(row, key)
        if known is None or known <= boundary:
            kept.append(row)
    return _history_digest(kept)


# The next request reuses the saved cutoffs up to the last daily cutoff (the
# intraday endpoint is replaced) or up to the saved endpoint itself.
KNOWN_THROUGH_BOUNDARIES = 2


def _known_through_manifest(rows, ordered, key):
    from jp_market_engine import _instant
    return {at: _known_through_digest(rows, _instant(at), key)
            for at in ordered[-KNOWN_THROUGH_BOUNDARIES:]}


def _prefix_reuse_rejection(source, rows, key, boundary):
    """Exact saved prefix plus rows appended after it; a reason token or None."""
    from jp_market_engine import _instant
    count = source.get("count") if isinstance(source, dict) else None
    if type(count) is not int or count < 0 or count > len(rows):
        return "source_prefix_shortened"
    if _history_digest(rows[:count]) != source.get("sha256"):
        return "source_prefix_changed"
    for row in rows[count:]:
        if not isinstance(row, Mapping):
            return "appended_row_invalid"
        known = _knowledge_time(row)
        period = _instant(str(row.get("periodEnd") or row.get("date") or "")[:10] + "T00:00:00Z")
        # The observation date can be old. New knowledge cannot affect an
        # earlier cutoff: point_in_time_rows excludes it before selecting
        # revisions. Require the correction's own receipt, never backdate it.
        if key == "sq_events":
            # A schedule row only matches the cutoff whose JST date it was
            # calculated on; one calculated after the boundary cannot
            # change an earlier cutoff.
            calculated = _instant(row.get("calculatedAt"))
            if calculated is None or calculated <= boundary:
                return "append_can_affect_prior_cutoff"
            continue
        if (known is None or known <= boundary or period is None
                or (row.get("revision", 0) != 0 and _instant(row.get("knownAt")) is None)):
            return "append_can_affect_prior_cutoff"
    return None


def _reusable_cutoffs(history, ordered, sources, *, diagnostic=None):
    from jp_market_engine import _instant

    def reject(reason, source=None):
        if diagnostic is not None:
            diagnostic.update(reason=reason, source=source)
        return []

    if not isinstance(history, dict) or history.get("status") != "AVAILABLE":
        return reject("history_unavailable")
    old = history.get("evaluatedCutoffs")
    manifest = history.get("sourceManifest")
    if not isinstance(old, list) or not isinstance(manifest, dict):
        return reject("legacy_manifest_missing")
    requested = set(ordered)
    shared = [at for at in old if at in requested]
    if not shared or shared != ordered[:len(shared)] or shared != sorted(set(shared), key=_instant):
        return reject("cutoff_prefix_changed")
    boundary = _instant(shared[-1])
    if set(manifest) != set(sources):
        return reject("source_set_changed")
    bounded_sources = []
    for key, rows in sources.items():
        source = manifest[key]
        reason = _prefix_reuse_rejection(source, rows, key, boundary)
        if reason is None:
            continue
        # Rows first knowable after the boundary cannot change any reused
        # cutoff, wherever they sit in the list: an SQ distance stamped with
        # its calculation instant, a VIX session still forming in place, a
        # later receipt. When every row the reused cutoffs can see is
        # identical and in the same order, the reused cutoffs are exactly
        # what a replay would produce.
        known_through = source.get("knownThrough") if isinstance(source, dict) else None
        if (isinstance(known_through, dict) and isinstance(known_through.get(shared[-1]), str)
                and _known_through_digest(rows, boundary, key) == known_through[shared[-1]]):
            bounded_sources.append(key)
            continue
        return reject(reason, key)
    if diagnostic is not None:
        diagnostic.update(reason="unchanged_source_prefix", source=None)
        if bounded_sources:
            diagnostic.update(reason="unchanged_known_inputs", boundedSources=sorted(bounded_sources))
    return shared


# A source that held rows in the verified history and now holds less than
# half of them is a cold cache (a restart before the collection refetches it,
# a failed provider read, a two-year fallback in place of the ten-year store),
# not a revision. Replaying without it changed every market-condition
# candidate twice: once without the series and once more when it returned.
# The verified history is kept unchanged instead, bounded in age so a source
# that is really gone is replayed without, never hidden indefinitely.
WARMING_MINIMUM_ROWS = 20
WARMING_MAX_HOURS = 72


def _warming_sources(history, ordered, sources):
    from jp_market_engine import _instant
    if not isinstance(history, dict) or history.get("status") != "AVAILABLE":
        return []
    manifest = history.get("sourceManifest")
    last = _instant(history.get("lastCutoff"))
    if not isinstance(manifest, dict) or last is None or not isinstance(history.get("latest"), dict):
        return []
    age = (_instant(ordered[-1]) - last).total_seconds()
    if age < 0 or age > WARMING_MAX_HOURS * 3600:
        return []
    warming = []
    for key, source in manifest.items():
        count = source.get("count") if isinstance(source, dict) else None
        if (key in sources and type(count) is int and count >= WARMING_MINIMUM_ROWS
                and len(sources[key]) * 2 < count):
            warming.append(key)
    return sorted(warming)


def _retained_history(history, warming):
    """The verified history unchanged, with the sources it is waiting for."""
    from copy import deepcopy
    keys = ("schemaVersion", "features", "conditions", "latest", "firstCutoff", "lastCutoff",
            "cutoffCount", "evaluatedCutoffs", "sourceManifest")
    retained = {key: deepcopy(history[key]) for key in keys if key in history}
    return {**retained,
            "calculationWork": {"reusedCutoffs": history.get("cutoffCount", 0), "evaluatedCutoffs": 0},
            "reuseDecision": {"reason": "source_warming", "source": warming[0]},
            "sourceWarming": {"sources": warming, "retainedLastCutoff": history.get("lastCutoff")},
            "historicalVintageVerified": False, "actionAuthority": False, "automaticAiCalls": 0}


FOREIGN_FLOW_AVAILABILITY_RULE = "jquants-investor-types-official-pubdate"


def _flow_publication_availability(rows):
    """Read-side rule for the investor-type rows (2026-10-03).

    J-Quants gives every week its official PubDate, stored as availableFrom
    (18:00 JST). The ledger copy also carries knownAt = the import time, and
    the one-time ten-year backfill of 2026-09-30 therefore made every past
    week invisible to every past cutoff (D05 and foreign_flow.net4w had
    history only from September 2026). An original observation (revision 0)
    is known from its publication; the import stays as receivedAt.
    Corrections keep their own receipt. Rows are copied, never mutated.
    Not vintage proof.
    """
    from jp_market_engine import _instant
    result = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        published = row.get("availableFrom") or row.get("publishedAt")
        known = row.get("knownAt")
        if ((row.get("seriesId") or row.get("field")) == "flow.foreign"
                and int(row.get("revision", 0) or 0) == 0 and published and known
                and _instant(published) is not None and _instant(known) is not None
                and _instant(published) < _instant(known)):
            row = {**row, "knownAt": published, "receivedAt": row.get("receivedAt") or known,
                   "availabilityBasis": "OFFICIAL_PUBLICATION_DATE",
                   "availabilityRule": FOREIGN_FLOW_AVAILABILITY_RULE}
        result.append(row)
    return result


def build_feature_history(*, cutoffs: Sequence[str], previous_history=None, **inputs) -> dict[str, Any]:
    """Replay descriptive features without selecting on subsequent outcomes.

    A historical source download is not an archived historical vintage. Keep
    that limitation even when every calculation respects its explicit cutoff.
    Full input references remain in the latest snapshot; historical features
    carry the content digest of those same references to bound cache size.
    """
    from jp_market_engine import _instant
    if not cutoffs or len(cutoffs) > 3001 or any(_instant(at) is None for at in cutoffs):
        raise ValueError("bounded_valid_feature_cutoffs_required")
    ordered = sorted(set(cutoffs), key=_instant)
    if "foreign_flow" in inputs:
        inputs = {**inputs, "foreign_flow": _flow_publication_availability(inputs["foreign_flow"])}
    sources = _source_lists(inputs)
    warming = _warming_sources(previous_history, ordered, sources)
    if warming:
        return _retained_history(previous_history, warming)
    reuse_decision = {}
    reused = _reusable_cutoffs(previous_history, ordered, sources, diagnostic=reuse_decision)
    if len(reused) == len(ordered) and (
            reuse_decision.get("boundedSources")
            or (previous_history.get("latest") or {}).get("informationCutoff") != ordered[-1]):
        # A shortened request can reuse its history but needs its own endpoint.
        # So does a request whose later-known rows changed: the endpoint's
        # audit counts include rows excluded as not yet known.
        reused = reused[:-1]
        reuse_decision["reason"] = "endpoint_not_cached"
    groups = {"features": [], "conditions": []}
    if reused:
        from copy import deepcopy
        retained = set(reused)
        for group in groups:
            groups[group] = deepcopy([row for row in previous_history[group]
                                     if row.get("knownAt") in retained])
    previous = {}
    revisions = {}
    for group, rows in groups.items():
        for row in rows:
            key = (group, row["instrumentId"], row["seriesId"], row["date"])
            body = {k:v for k,v in row.items() if k not in ("revision", "knownAt")}
            previous[key] = _history_digest(body)
            revisions[key] = row["revision"]
    # A changed cutoff must refresh missingness. The exact same cutoff and
    # unchanged eligible inputs can reuse the saved endpoint without recursion.
    pending = ordered[len(reused):]
    latest = None if pending else deepcopy(previous_history["latest"])
    for at in pending:
        latest = build_market_features(cutoff=at, **inputs)
        for group in groups:
            for row in latest[group]:
                key = (group, row["instrumentId"], row["seriesId"], row["date"])
                body = {k: v for k, v in row.items() if k != "inputReferences"}
                digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()
                if previous.get(key) == digest:
                    continue
                revision = revisions.get(key, -1) + 1
                previous[key], revisions[key] = digest, revision
                groups[group].append({**body, "revision": revision, "knownAt": at})
        if sum(map(len, groups.values())) > 60000:
            raise ValueError("market_evidence_history_bound_exceeded")
    return {"schemaVersion": "jp-market-feature-history-v1", **groups,
            "latest": latest, "firstCutoff": ordered[0], "lastCutoff": ordered[-1],
            "cutoffCount": len(ordered), "evaluatedCutoffs": ordered,
            "sourceManifest": {key: {"count": len(rows), "sha256": _history_digest(rows),
                                     "knownThrough": _known_through_manifest(rows, ordered, key)}
                               for key, rows in sources.items()},
            "calculationWork": {"reusedCutoffs": len(reused), "evaluatedCutoffs": len(pending)},
            "reuseDecision": reuse_decision,
            "historicalVintageVerified": False,
            "actionAuthority": False, "automaticAiCalls": 0}


def _day(row):
    return str(row.get("periodEnd") or row.get("date") or "")[:10]


def _history(rows, instrument, cutoff, *, unit=None, allow_negative=False):
    allowed = {"flow.foreign"} if unit == "JPY" else {"close", "yield", "yield_pct"} if unit == "PERCENT" else {"close", "OHLCV_BAR"}
    scoped = [dict(row) for row in rows if isinstance(row, Mapping) and
              row.get("instrumentId") == instrument and (unit is None or row.get("unit") == unit) and
              (row.get("seriesId") or row.get("field") or row.get("kind") or
               ("OHLCV_BAR" if all(key in row for key in ("open", "high", "low", "close", "volume")) else "")) in allowed]
    visible, _ = point_in_time_rows(scoped, cutoff)
    result = []
    for row in visible:
        value = _number(row.get("close", row.get("value")))
        if value is not None and (allow_negative or value > 0):
            result.append({**row, "numericValue": value})
    if len({_day(row) for row in result}) != len(result):
        raise ValueError("ambiguous_series_observation")
    return sorted(result, key=_day)


LOSS_PROXY_BASIS = "ARGUS_PROXY_MARGIN_COST_BASIS_26W"
LOSS_PROXY_WEEKS = 26
LOSS_PROXY_MINIMUM_WEEKS = 8


def margin_cost_basis_loss_proxy(two_market_credit, nikkei_rows, *, cutoff):
    """Estimate the two-market margin buyers' valuation loss in percent.

    Weekly buy balances B_w (JPY) visible at the cutoff; net new buying
    d_w = max(B_w - B_{w-1}, 0) over the trailing 26 weeks is assumed bought
    at the last index close on or before each week end; the loss is
    (cost - latest close) / cost * 100 (positive = loss). None when fewer than
    eight weeks or no net buying. A descriptive proxy, not the official
    figure, not validated against it.
    """
    from jp_market_engine import point_in_time_rows
    longs = [dict(row) for row in two_market_credit if isinstance(row, Mapping)
             and (row.get("instrumentId") or "MARKET") == "MARKET"
             and (row.get("seriesId") or row.get("field")) == "credit.long_balance"]
    visible, _ = point_in_time_rows(longs, cutoff)
    weeks = sorted(((str(row.get("periodEnd") or row.get("date") or "")[:10], row) for row in visible
                    if _number(row.get("value")) is not None and _number(row.get("value")) > 0),
                   key=lambda item: item[0])[-(LOSS_PROXY_WEEKS + 1):]
    closes = [row for row in nikkei_rows if isinstance(row, Mapping) and row.get("numericValue")]
    if len(weeks) < LOSS_PROXY_MINIMUM_WEEKS + 1 or not closes:
        return None
    by_day = sorted(closes, key=_day)
    def close_on_or_before(day):
        candidate = None
        for row in by_day:
            if _day(row) <= day:
                candidate = row
            else:
                break
        return candidate if candidate and (date.fromisoformat(day) - date.fromisoformat(_day(candidate))).days <= 7 else None
    weighted, weight, inputs = 0.0, 0.0, []
    for (previous_day, previous), (day, current) in zip(weeks, weeks[1:]):
        delta = _number(current.get("value")) - _number(previous.get("value"))
        price = close_on_or_before(day)
        if price is None:
            return None
        if delta > 0:
            weighted += delta * price["numericValue"]; weight += delta
        inputs.extend([current, price])
    latest = by_day[-1]
    if weight <= 0 or not weighted:
        return None
    cost = weighted / weight
    return {"lossPct": (cost - latest["numericValue"]) / cost * 100.0, "costBasis": cost,
            "weeks": len(weeks) - 1, "inputs": [weeks[0][1], *inputs, latest]}


SIGN_CONDITION_LOOKBACK_DAYS = 200
# State thresholds, named so the method identity carries them as parameters.
D02_MARGIN_RATIO_THRESHOLD = 1
D04_INDEX_PER_THRESHOLD = 19
FEATURE_INPUT_WINDOW_DAYS = 400
SIGN_CONDITION_IDS = {
    "D01": "d01_short_balance_below_threshold",
    "D02": "d02_margin1570_ratio_at_least_one",
    "D03": "d03_relative_strength_positive",
    "D04": "d04_index_per_at_least_19",
    "D05": "d05_foreign_flow_inflow",
    "D06": "vix_macd_cross",
}


def _sign_transitions(points, predicate, series_id, cutoff_day):
    """Condition events when a Seven Sign state flips, oldest first.

    points: (day, value, inputs) ascending. +1 when the condition becomes met,
    -1 when it stops. Each event is available when all of its inputs were;
    only flips within the lookback before the cutoff are emitted (the one
    point before that window supplies the prior state).
    """
    horizon = (date.fromisoformat(cutoff_day) - timedelta(days=SIGN_CONDITION_LOOKBACK_DAYS)).isoformat()
    window = [p for p in points if p[0] >= horizon]
    earlier = [p for p in points if p[0] < horizon]
    if earlier:
        window = [earlier[-1], *window]
    out, previous = [], None
    for day, value, inputs in window:
        state = bool(predicate(value))
        if previous is not None and state != previous[0]:
            times = [_knowledge_time(row) for row in [*previous[1], *inputs]]
            if all(t is not None for t in times):
                out.append({"instrumentId": INSTRUMENT, "seriesId": series_id, "date": day,
                            "value": 1 if state else -1, "unit": "DIRECTION",
                            "availableFrom": max(times).isoformat(),
                            "sourceRef": "derived:seven-sign-transition:" + series_id,
                            "validationStatus": "UNVALIDATED"})
        previous = (state, inputs)
    return out


def build_market_features(*, cutoff: str, price_series: Mapping[str, Sequence[Mapping[str, Any]]],
                          two_market_credit: Sequence[Mapping[str, Any]] = (),
                          margin_1570: Sequence[Mapping[str, Any]] = (),
                          foreign_flow: Sequence[Mapping[str, Any]] = (),
                          valuation_loss: Sequence[Mapping[str, Any]] = (),
                          sq_events: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    # Each cutoff needs only recent observations of every price series except
    # VIX (its MACD runs over the whole history). Rows dated after the cutoff are
    # never visible (every source's availability is on or after its date), and
    # the longest look-back below is 26 weeks, so passing the last
    # FEATURE_INPUT_WINDOW_DAYS leaves every value unchanged while the ten-year
    # history no longer re-verifies ten years of rows at each of 2,400 cutoffs
    # (2026-10-01: a full recalculation ran for most of an hour in production).
    from jp_market_engine import _instant as _cutoff_instant
    cutoff_date = _cutoff_instant(cutoff).date()
    recent_from = (cutoff_date - timedelta(days=FEATURE_INPUT_WINDOW_DAYS)).isoformat()
    through = (cutoff_date + timedelta(days=1)).isoformat()

    def window(rows, *, whole_history=False):
        return [row for row in rows if isinstance(row, Mapping) and _day(row) <= through
                and (whole_history or _day(row) >= recent_from)]
    # Price series only: the weekly balances also feed the snapshot's audit
    # counts (credit dynamics' point-in-time proof), which must not change.
    price_series = {key: window(rows, whole_history=(key == "vix")) for key, rows in price_series.items()}
    features = []
    conditions = []
    stale_features = set()

    def emit(field, value, inputs, *, period=None, basis=None):
        number = _number(value)
        if number is None or not inputs or field not in FEATURE_DEFINITIONS:
            return
        times = [_knowledge_time(row) for row in inputs]
        if any(value is None for value in times):
            return
        feature_day = period or max(_day(row) for row in inputs)
        from jp_market_engine import _instant
        if (_instant(cutoff).date() - date.fromisoformat(feature_day)).days > FEATURE_MAX_AGE_DAYS[field]:
            stale_features.add(field)
            return
        material = json.dumps(inputs, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        features.append({
            "instrumentId": INSTRUMENT, "seriesId": field,
            "date": period or max(_day(row) for row in inputs), "value": number,
            "unit": FEATURE_DEFINITIONS[field][0],
            "availableFrom": max(times).isoformat(),
            **({"derivationBasis": basis} if basis else {}),
            "sourceRef": "derived:jp-market-inputs:" + hashlib.sha256(material.encode()).hexdigest(),
            "inputReferences": [{"instrumentId": row.get("instrumentId", "MARKET"),
                                 "seriesId": row.get("seriesId", row.get("field", "OHLCV_BAR")),
                                 "date": _day(row), "availableFrom": row.get("availableFrom"),
                                 "knownAt": row.get("knownAt"), "observedAt": row.get("observedAt"),
                                 "value": row.get("numericValue", row.get("value", row.get("close"))),
                                 "sourceRef": row.get("sourceRef", row.get("source")),
                                 "sourceResponseSha256": row.get("sourceResponseSha256"),
                                 "rawId": row.get("rawId"),
                                 "availabilityBasis": row.get("availabilityBasis")}
                                for row in inputs],
            "historicalVintageVerified": False,
        })

    dynamics = {}
    for key, rows, instrument, kind, long_field, short_field in (
            ("twoMarket", two_market_credit, "MARKET", "TWO_MARKET_MARGIN", "credit.long_balance", "credit.short_balance"),
            ("margin1570", margin_1570, "1570", "WEEKLY_MARGIN", "margin.long_balance", "margin.short_balance")):
        derived = credit_dynamics(rows, cutoff=cutoff, instrument_id=instrument, balance_kind=kind,
                                  long_series=long_field, short_series=short_field)
        dynamics[key] = derived
        current, previous = derived["current"], derived["previous"]
        if not current or current["status"] != "AVAILABLE":
            continue
        current_inputs = list(current["sourceRows"].values())
        emit("credit.ratio" if key == "twoMarket" else "margin1570.ratio", current["ratio"], current_inputs)
        if previous and derived["change"].get("isOneWeekChange"):
            inputs = current_inputs + list(previous["sourceRows"].values())
            if key == "twoMarket":
                emit("credit.ratio_change", derived["change"]["ratioChange"], inputs)
            else:
                emit("margin1570.long_change_pct", derived["change"]["longBalanceChangePct"], inputs)
                emit("margin1570.short_change_pct", derived["change"]["shortBalanceChangePct"], inputs)

    loss_rows, _ = point_in_time_rows([dict(row) for row in valuation_loss if isinstance(row, Mapping)
                                      and (row.get("instrumentId") or "MARKET") == "MARKET"
                                      and (row.get("seriesId") or row.get("field")) == "credit.valuation_loss_pct"], cutoff)
    if loss_rows:
        loss = loss_rows[-1]
        normalized = normalize_valuation_loss(loss.get("value"), sign_convention=loss.get("signConvention"), unit=loss.get("unit"))
        emit("credit.loss_pct", normalized["lossPct"], [loss])
    else:
        # No official valuation-loss series is available without a licence
        # (2026-09-30). The requirement allows a proxy that is kept distinct
        # from the official figure: the cost basis of the two-market buy
        # balance is estimated from each week's net new buying at that
        # week's index close over the trailing 26 weeks (the standard margin
        # term); the loss is that basis against the latest close. Labelled
        # ARGUS_PROXY on the feature and in the chart; never an official value.
        proxy = margin_cost_basis_loss_proxy(
            two_market_credit, _history(price_series.get("nikkei", ()), INSTRUMENT, cutoff), cutoff=cutoff)
        if proxy:
            emit("credit.loss_pct", proxy["lossPct"], proxy["inputs"], basis=LOSS_PROXY_BASIS)

    vix = _history(price_series.get("vix", ()), "VIX", cutoff)
    if vix:
        emit("vix.level", vix[-1]["numericValue"], [vix[-1]])
    if len(vix) >= 6:
        emit("vix.change5", vix[-1]["numericValue"] - vix[-6]["numericValue"], vix[-6:])
    if len(vix) >= sum(ARGUS_MACD_BASELINE[:2]):
        macd = _macd([row["numericValue"] for row in vix], ARGUS_MACD_BASELINE)
        emit("vix.macd_histogram", macd[-1]["histogram"], vix)
        for index in range(sum(ARGUS_MACD_BASELINE[:2]), len(vix)):
            previous, current = macd[index - 1]["histogram"], macd[index]["histogram"]
            direction = 1 if previous <= 0 < current else -1 if previous >= 0 > current else None
            if direction:
                inputs = vix[:index + 1]
                conditions.append({"instrumentId": INSTRUMENT, "seriesId": "vix_macd_cross",
                                   "date": _day(vix[index]), "value": direction, "unit": "DIRECTION",
                                   "availableFrom": max(_knowledge_time(row) for row in inputs).isoformat(),
                                   "sourceRef": "derived:vix-macd-12-26-9", "validationStatus": "UNVALIDATED"})

    nikkei = _history(price_series.get("nikkei", ()), INSTRUMENT, cutoff)
    sp500 = _history(price_series.get("sp500", ()), "SP500_INDEX", cutoff)
    if len(nikkei) >= 21 and len(sp500) >= 21:
        jp = nikkei[-1]["numericValue"] / nikkei[-21]["numericValue"] - 1
        us = sp500[-1]["numericValue"] / sp500[-21]["numericValue"] - 1
        emit("relative_jp_us.return20", (jp - us) * 100, nikkei[-21:] + sp500[-21:])

    fx = _history(price_series.get("usdjpy", ()), "USDJPY", cutoff)
    if len(fx) >= 6:
        emit("fx.usdjpy_change5", (fx[-1]["numericValue"] / fx[-6]["numericValue"] - 1) * 100, fx[-6:])
    for key, instrument, field in (("jp10y", "JP10Y", "rate.jp10y_change5"), ("us10y", "US10Y", "rate.us10y_change5")):
        rates = _history(price_series.get(key, ()), instrument, cutoff, unit="PERCENT", allow_negative=True)
        if len(rates) >= 6:
            emit(field, rates[-1]["numericValue"] - rates[-6]["numericValue"], rates[-6:])

    topix = _history(price_series.get("topix", ()), "TOPIX_INDEX", cutoff)
    by_date = {_day(row): row for row in topix}
    if len(nikkei) >= 6 and all(_day(row) in by_date for row in nikkei[-6:]):
        jp_rows = nikkei[-6:]
        topix_rows = [by_date[_day(row)] for row in jp_rows]
        first = jp_rows[0]["numericValue"] / topix_rows[0]["numericValue"]
        last = jp_rows[-1]["numericValue"] / topix_rows[-1]["numericValue"]
        emit("nt.ratio_change5", (last / first - 1) * 100, jp_rows + topix_rows)

    foreign_flow = _flow_publication_availability(foreign_flow)
    flows = [{**dict(row), "instrumentId": row.get("instrumentId") or "MARKET"} for row in foreign_flow if isinstance(row, Mapping) and
             (row.get("seriesId") or row.get("field")) == "flow.foreign"]
    flows = _history(flows, "MARKET", cutoff, unit="JPY", allow_negative=True)
    if len(flows) >= 4:
        recent = flows[-4:]
        gaps = [(date.fromisoformat(_day(right)) - date.fromisoformat(_day(left))).days
                for left, right in zip(recent, recent[1:])]
        if gaps == [7, 7, 7]:
            emit("foreign_flow.net4w", sum(row["numericValue"] for row in recent), recent)

    from jp_market_engine import _instant
    from jp_market_events import JST
    cutoff_time = _instant(cutoff)
    cutoff_jp_date = cutoff_time.astimezone(JST).date().isoformat()
    # The published schedule (VERIFIED) governs whenever it covers the date;
    # the exchange-calendar rule (RULE_DERIVED, 2026-09-30) supplies history
    # only, and its basis travels with the feature's input reference.
    for event in sorted(sq_events, key=lambda event: (event.get("calendarStatus") != "VERIFIED",
                                                     event.get("sqDate", ""))):
        known = _instant(event.get("knownAt"))
        calculated = _instant(event.get("calculatedAt"))
        if event.get("calendarStatus") in ("VERIFIED", "RULE_DERIVED") and known and known <= cutoff_time and \
                calculated and calculated <= cutoff_time and calculated.astimezone(JST).date().isoformat() == cutoff_jp_date and \
                event.get("tradingSessionsUntil") is not None and event.get("sqDate", "") >= cutoff_jp_date:
            # The scheduled date may be in the future, while this distance is
            # an observation calculated at the explicit information cutoff.
            emit("event.sq_sessions", event["tradingSessionsUntil"], [{
                "instrumentId": INSTRUMENT, "seriesId": "sq_schedule", "date": cutoff_time.date().isoformat(),
                "calculationDateJst": cutoff_jp_date, "calendarStatus": event.get("calendarStatus"),
                "availableFrom": cutoff, "sourceRef": event.get("sourceRef"),
                "knownAt": event["knownAt"]}])
            break
    # Seven Sign state flips as condition events (2026-09-30): the analog
    # engine's condition order compares these, not only the VIX MACD cross
    # (D06). D07 has no activation rule in the source and is not emitted.
    from jp_market_engine import JP_MARKET_ENGINE_D01_THRESHOLD_JPY, point_in_time_rows as _pit
    cutoff_day = cutoff_time.date().isoformat()
    # Scan only the lookback plus a margin for the prior state: every cutoff
    # of the ten-year history repeats this, so a full scan would be quadratic.
    scan_from = (cutoff_time.date() - timedelta(days=SIGN_CONDITION_LOOKBACK_DAYS + 60)).isoformat()
    def recent(rows):
        return [dict(r) for r in rows if isinstance(r, Mapping) and _day(r) >= scan_from]
    two_market_credit, margin_1570, foreign_flow = recent(two_market_credit), recent(margin_1570), recent(foreign_flow)
    shorts, _ = _pit([dict(r) for r in two_market_credit if isinstance(r, Mapping)
                      and (r.get("instrumentId") or "MARKET") == "MARKET"
                      and (r.get("seriesId") or r.get("field")) == "credit.short_balance"], cutoff)
    points = sorted(((_day(r), _number(r.get("value")), [r]) for r in shorts if _number(r.get("value")) is not None),
                    key=lambda p: p[0])
    conditions.extend(_sign_transitions(points, lambda v: v < JP_MARKET_ENGINE_D01_THRESHOLD_JPY,
                                        SIGN_CONDITION_IDS["D01"], cutoff_day))
    ratio_points = []
    sides, _ = _pit([dict(r) for r in margin_1570 if isinstance(r, Mapping)
                     and (r.get("seriesId") or r.get("field")) in ("margin.long_balance", "margin.short_balance")], cutoff)
    by_period = {}
    for row in sides:
        by_period.setdefault(_day(row), {})[row.get("seriesId") or row.get("field")] = row
    for day, pair in sorted(by_period.items()):
        long_row, short_row = pair.get("margin.long_balance"), pair.get("margin.short_balance")
        if long_row and short_row and (_number(short_row.get("value")) or 0) > 0 and _number(long_row.get("value")) is not None:
            ratio_points.append((day, _number(long_row["value"]) / _number(short_row["value"]), [long_row, short_row]))
    conditions.extend(_sign_transitions(ratio_points, lambda v: v >= D02_MARGIN_RATIO_THRESHOLD, SIGN_CONDITION_IDS["D02"], cutoff_day))
    if len(nikkei) >= 21 and len(sp500) >= 21:
        us_by_day = {_day(r): r for r in sp500 if _day(r) >= scan_from}
        aligned = [r for r in nikkei if _day(r) >= scan_from and _day(r) in us_by_day]
        rs_points = []
        for index in range(20, len(aligned)):
            jp_now, jp_then = aligned[index], aligned[index - 20]
            us_now, us_then = us_by_day[_day(jp_now)], us_by_day[_day(jp_then)]
            value = (jp_now["numericValue"] / jp_then["numericValue"] - us_now["numericValue"] / us_then["numericValue"]) * 100
            rs_points.append((_day(jp_now), value, [jp_now, jp_then, us_now, us_then]))
        conditions.extend(_sign_transitions(rs_points, lambda v: v > 0, SIGN_CONDITION_IDS["D03"], cutoff_day))
    per_rows = _history([r for r in price_series.get("index_per", ()) if _day(r) >= scan_from], "NIKKEI_225_PER", cutoff)
    conditions.extend(_sign_transitions([(_day(r), r["numericValue"], [r]) for r in per_rows],
                                        lambda v: v >= D04_INDEX_PER_THRESHOLD, SIGN_CONDITION_IDS["D04"], cutoff_day))
    flows, _ = _pit([dict(r) for r in foreign_flow if isinstance(r, Mapping)
                     and (r.get("seriesId") or r.get("field")) == "flow.foreign"], cutoff)
    flow_points = sorted(((_day(r), _number(r.get("value")), [r]) for r in flows if _number(r.get("value")) is not None),
                         key=lambda p: p[0])
    conditions.extend(_sign_transitions(flow_points, lambda v: v > 0, SIGN_CONDITION_IDS["D05"], cutoff_day))
    present = {row["seriesId"] for row in features}
    return {"schemaVersion": "jp-market-feature-snapshot-v1", "informationCutoff": cutoff,
            "features": sorted(features, key=lambda row: row["seriesId"]), "conditions": conditions,
            "creditDynamics": dynamics, "staleFeatures": sorted(stale_features), "missingFeatures": sorted(set(FEATURE_DEFINITIONS) - present),
            "relativeStrengthDefinition": "difference of each direct index's latest 20-session local-currency return",
            "observedCoveringOrders": False, "actionAuthority": False,
            "historicalVintageVerified": False, "validationStatus": "UNVALIDATED"}
