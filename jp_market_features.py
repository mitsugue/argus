"""Descriptive, publication-bounded Japan index features for analog comparison.

Series remain distinct. Relative strength and falling short balances do not
observe covering orders. No aggregation of warning and recovery into a buy
score, and no modification of existing decision authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from jp_market_engine import ARGUS_MACD_BASELINE, _knowledge_time, _macd, point_in_time_rows
from jp_market_dynamics import _number, credit_dynamics, normalize_valuation_loss
from jp_market_analogs import FEATURE_DEFINITIONS, FEATURE_MAX_AGE_DAYS, INSTRUMENT


HISTORY_CACHE_SCHEMA = "jp-market-feature-cache-v1"
HISTORY_CACHE_MAX_BYTES = 32 * 1024 * 1024


def history_method_identity() -> str:
    """Bind restored calculations to all four numerical implementations."""
    root = Path(__file__).resolve().parent
    files = ("jp_market_features.py", "jp_market_engine.py",
             "jp_market_dynamics.py", "jp_market_analogs.py")
    material = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in files}
    return _history_digest(material)


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
    for key, rows in sources.items():
        source = manifest[key]
        count = source.get("count") if isinstance(source, dict) else None
        if type(count) is not int or count < 0 or count > len(rows):
            return reject("source_prefix_shortened", key)
        if _history_digest(rows[:count]) != source.get("sha256"):
            return reject("source_prefix_changed", key)
        for row in rows[count:]:
            if not isinstance(row, Mapping):
                return reject("appended_row_invalid", key)
            known = _knowledge_time(row)
            period = _instant(str(row.get("periodEnd") or row.get("date") or "")[:10] + "T00:00:00Z")
            # The observation date can be old. New knowledge cannot affect an
            # earlier cutoff: point_in_time_rows excludes it before selecting
            # revisions. Require the correction's own receipt, never backdate it.
            if (key == "sq_events" or known is None or known <= boundary or period is None
                    or (row.get("revision", 0) != 0 and _instant(row.get("knownAt")) is None)):
                return reject("append_can_affect_prior_cutoff", key)
    if diagnostic is not None:
        diagnostic.update(reason="unchanged_source_prefix", source=None)
    return shared


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
    sources = _source_lists(inputs)
    reuse_decision = {}
    reused = _reusable_cutoffs(previous_history, ordered, sources, diagnostic=reuse_decision)
    if len(reused) == len(ordered) and (previous_history.get("latest") or {}).get("informationCutoff") != ordered[-1]:
        # A shortened request can reuse its history but needs its own endpoint.
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
            "sourceManifest": {key: {"count": len(rows), "sha256": _history_digest(rows)}
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


def build_market_features(*, cutoff: str, price_series: Mapping[str, Sequence[Mapping[str, Any]]],
                          two_market_credit: Sequence[Mapping[str, Any]] = (),
                          margin_1570: Sequence[Mapping[str, Any]] = (),
                          foreign_flow: Sequence[Mapping[str, Any]] = (),
                          valuation_loss: Sequence[Mapping[str, Any]] = (),
                          sq_events: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    features = []
    conditions = []
    stale_features = set()

    def emit(field, value, inputs, *, period=None):
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
    for event in sorted(sq_events, key=lambda event: event.get("sqDate", "")):
        known = _instant(event.get("knownAt"))
        calculated = _instant(event.get("calculatedAt"))
        if event.get("calendarStatus") == "VERIFIED" and known and known <= cutoff_time and \
                calculated and calculated <= cutoff_time and calculated.astimezone(JST).date().isoformat() == cutoff_jp_date and \
                event.get("tradingSessionsUntil") is not None and event.get("sqDate", "") >= cutoff_jp_date:
            # The scheduled date may be in the future, while this distance is
            # an observation calculated at the explicit information cutoff.
            emit("event.sq_sessions", event["tradingSessionsUntil"], [{
                "instrumentId": INSTRUMENT, "seriesId": "sq_schedule", "date": cutoff_time.date().isoformat(),
                "calculationDateJst": cutoff_jp_date,
                "availableFrom": cutoff, "sourceRef": event.get("sourceRef"),
                "knownAt": event["knownAt"]}])
            break
    present = {row["seriesId"] for row in features}
    return {"schemaVersion": "jp-market-feature-snapshot-v1", "informationCutoff": cutoff,
            "features": sorted(features, key=lambda row: row["seriesId"]), "conditions": conditions,
            "creditDynamics": dynamics, "staleFeatures": sorted(stale_features), "missingFeatures": sorted(set(FEATURE_DEFINITIONS) - present),
            "relativeStrengthDefinition": "difference of each direct index's latest 20-session local-currency return",
            "observedCoveringOrders": False, "actionAuthority": False,
            "historicalVintageVerified": False, "validationStatus": "UNVALIDATED"}
