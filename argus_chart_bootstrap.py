"""v13.5.42 — boot-time asset chart bootstrap (product boundary).

Why: the asset chart reports are produced one instrument per scheduled tick
and the provider history cache is process-local, so after every deploy the
owner opened 5803 and saw "チャートは次回更新待ち" for hours.  This module
walks the existing, already-proven tick over every target once, right after
the durable-state restore, using the same bounded provider seed the tick
already allows.  Nothing new is fetched from a public GET; no raw tick
warehouse; one daemon thread; single run per process.

The host application (scanner.py, Recovery-frozen) is reached through the
running __main__ module; when the expected functions are absent (tests,
other hosts) the bootstrap declines with HOST_UNSUPPORTED and does nothing.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

import argus_asset_chart_cache

REQUIRED_HOST_ATTRS = ("_osint_restore_once", "_precompute_asset_chart_tick",
                       "_asset_chart_targets", "_ASSET_CHART_REPORTS")
# v13.5.44: optional host seams for the boot warm (each is skipped when absent).
WARM_HOST_ATTRS = ("_sho_pit_inputs", "_jq_price_history", "_DECISION_EVIDENCE_CACHE",
                   "_SD_EXTRA_SYMBOLS", "_JP_SEEN_SYMBOLS", "_JP_WATCHLIST",
                   "_SHO_STATEMENTS_CACHE", "_JP_CACHE", "_JQ_HISTORY_CACHE")
INTEREST_MAX = 24
INTEREST_REFRESH_SECONDS = 600.0
INTEREST_SCAN_SECONDS = 60.0
INTEREST_TTL_SECONDS = 7 * 86400.0
SHO_WARM_SECONDS = 4 * 3600.0
VALUATION_STATEMENT_PAGES = 8        # the issuer's statements history is paginated
# J-Quants V2 (V1 discontinued 2026-06-01): /fins/summary; the V1 path is kept
# last only so a legacy host keeps working.  The first path that answers wins.
STATEMENTS_PATHS = ("/fins/summary", "/fins/statements")
STATEMENTS_CACHE_SECONDS = 4 * 3600.0
VALUATION_STATEMENTS_PER_CYCLE = 6   # bounded provider budget per 10-minute cycle
REFERENCE_JP_HISTORY = ("1321",)         # SIG-03 proxy (1321 vs SPY)
REFERENCE_US_HISTORY = ("SPY",)
DEFAULT_DELAY_SECONDS = 15.0
DEFAULT_PER_SYMBOL_SECONDS = 45.0
DEFAULT_PAUSE_SECONDS = 2.0

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {
    "started": False, "thread": None,
    "summary": {"status": "NOT_STARTED", "targets": 0, "published": 0,
                "unchanged": 0, "skipped": 0, "degraded": 0, "missingBefore": None,
                "missingAfter": None, "startedAt": None, "finishedAt": None},
    "warm": {"status": "NOT_STARTED", "shoWarmedAt": None, "shoSourceStatus": None,
             "interestSymbols": [], "interestWarmedAt": None, "historyWarmed": 0,
             "valuation": None, "cycles": 0, "errorClass": None,
             "curatedWarmedAt": None, "referenceWarmed": 0, "statementsFetched": 0,
             "statementsErrorClass": None, "referenceErrorClass": None,
             "statementsPath": None, "statementsPublished": 0},
    "interest": {},          # JP code -> last seen monotonic clock (product-side registry)
    "statements": {},        # JP code -> list of statement rows (bounded, 4h refresh)
}


def _missing_daily(host: Any, targets: list) -> list:
    store = getattr(host, "_ASSET_CHART_REPORTS")
    missing = []
    for symbol, market in targets:
        try:
            if not argus_asset_chart_cache.current(store, market, symbol, "daily"):
                missing.append((symbol, market))
        except Exception:
            missing.append((symbol, market))
    return missing


def _run(host: Any, *, delay_seconds: float, per_symbol_seconds: float,
         pause_seconds: float, sleeper: Callable[[float], None],
         clock: Callable[[], float]) -> None:
    summary = _STATE["summary"]
    summary["status"] = "RUNNING"
    summary["startedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        sleeper(delay_seconds)
        try:
            host._osint_restore_once()
        except Exception:
            pass
        targets = list(host._asset_chart_targets() or [])
        summary["targets"] = len(targets)
        missing = _missing_daily(host, targets)
        summary["missingBefore"] = len(missing)
        # One full rotation of the tick's own cursor covers every target once.
        for _ in range(len(targets)):
            if not _missing_daily(host, targets):
                break
            try:
                result = host._precompute_asset_chart_tick(
                    deadline_monotonic=clock() + per_symbol_seconds)
            except Exception:
                summary["degraded"] += 1
                result = None
            status = (result or {}).get("status")
            if status == "published":
                summary["published"] += 1
            elif status == "unchanged":
                summary["unchanged"] += 1
            elif status == "degraded":
                summary["degraded"] += 1
            else:
                summary["skipped"] += 1
            sleeper(pause_seconds)
        summary["missingAfter"] = len(_missing_daily(host, targets))
        summary["status"] = "DONE"
        # v13.5.44: the boot warm (SHO inputs, interest history, derived
        # valuation) follows the chart pass in the same daemon thread.
        _warm_loop(host, sleeper=sleeper, now=clock, max_cycles=_STATE.get("warmMaxCycles"))
    except Exception as exc:                       # pragma: no cover - defensive
        summary["status"] = "FAILED"
        summary["errorClass"] = type(exc).__name__
    finally:
        summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _jp_code(value: Any) -> Optional[str]:
    code = str(value or "").strip().upper()
    return code if len(code) == 4 and code[0].isdigit() else None


def scan_interest(host: Any, now: float) -> None:
    """Record the JP codes the owner's device recently sent to public routes
    (decision-evidence subjects, supply-demand extras, watchlist hints) into
    the product-side registry.  The host caches expire within minutes, so the
    registry (7-day TTL, bounded) is what the warm cycle reads."""
    registry = _STATE["interest"]
    cache = getattr(host, "_DECISION_EVIDENCE_CACHE", None)
    if isinstance(cache, dict):
        for key in list(cache.keys()):
            code = _jp_code(key)
            if code:
                registry[code] = now
    extras = getattr(host, "_SD_EXTRA_SYMBOLS", None)
    if isinstance(extras, dict):
        for key, meta in list(extras.items()):
            code = _jp_code(key)
            if code and isinstance(meta, dict) and meta.get("market") == "JP":
                registry[code] = now
    seen = getattr(host, "_JP_SEEN_SYMBOLS", None)
    if isinstance(seen, dict):
        for key in list(seen.keys()):
            code = _jp_code(key)
            if code:
                registry[code] = now
    for code in [c for c, seen_at in registry.items() if now - seen_at > INTEREST_TTL_SECONDS]:
        registry.pop(code, None)


def interest_symbols(host: Any, now: Optional[float] = None) -> list:
    """Bounded JP interest set: 5803, the curated universe, then the registry
    (most recently seen first).  Owner holdings never leave the device; only
    codes the device already sent to public routes are used."""
    if now is not None:
        scan_interest(host, now)
    codes: list = []

    def add(value: Any) -> None:
        code = _jp_code(value)
        if code and code not in codes:
            codes.append(code)

    add("5803")
    for item in getattr(host, "_JP_WATCHLIST", None) or []:
        if isinstance(item, dict):
            add(item.get("symbol"))
    registry = _STATE["interest"]
    for code in sorted(registry, key=lambda c: -registry[c]):
        add(code)
    return codes[:INTEREST_MAX]


def _prices_by_code(host: Any) -> Dict[str, float]:
    prices: Dict[str, float] = {}
    history = getattr(host, "_JQ_HISTORY_CACHE", None)
    if isinstance(history, dict):
        for code, entry in list(history.items()):
            data = entry.get("data") if isinstance(entry, dict) else None
            closes = data.get("closes") if isinstance(data, dict) else None
            if isinstance(closes, list) and closes:
                try:
                    prices[str(code)[:4]] = float(closes[0])      # newest-first
                except (TypeError, ValueError):
                    pass
    watch = getattr(host, "_JP_CACHE", None)
    data = watch.get("data") if isinstance(watch, dict) else None
    for row in (data.get("stocks") if isinstance(data, dict) else None) or []:
        code = _jp_code(row.get("symbol")) if isinstance(row, dict) else None
        try:
            if code and row.get("price") is not None:
                prices[code] = float(row["price"])
        except (TypeError, ValueError):
            pass
    return prices


def _warm_cycle(host: Any, *, sleeper: Callable[[float], None], now: Callable[[], float],
                force_sho: bool) -> None:
    """One bounded warm cycle: SHO inputs (4h), interest history, valuation."""
    import argus_japan_valuation
    warm = _STATE["warm"]
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if force_sho and hasattr(host, "_sho_pit_inputs"):
        try:
            inputs = host._sho_pit_inputs(warm=True) or {}
            warm["shoWarmedAt"] = stamp
            warm["shoSourceStatus"] = dict(inputs.get("sourceStatus") or {})
        except Exception as exc:
            warm["errorClass"] = f"sho_warm:{type(exc).__name__}"
    statements = getattr(host, "_SHO_STATEMENTS_CACHE", None)
    # curated JP watch snapshot: the decision-evidence watch row and the
    # owner's curated quotes read this cache, which is cold after every deploy.
    if hasattr(host, "get_japan_watchlist_snapshot"):
        try:
            host.get_japan_watchlist_snapshot(allow_provider_fetch=True,
                                              record_requested_symbols=False)
            warm["curatedWarmedAt"] = stamp
        except Exception as exc:
            warm["errorClass"] = f"curated:{type(exc).__name__}"
    symbols = interest_symbols(host, now())
    warm["interestSymbols"] = list(symbols)
    warmed = 0
    if hasattr(host, "_jq_price_history"):
        for code in symbols:
            try:
                if host._jq_price_history(code):
                    warmed += 1
            except Exception:
                pass
            sleeper(1.0)
    warm["historyWarmed"] = warmed
    warm["interestWarmedAt"] = stamp
    # SIG-03 proxy inputs (1321 vs SPY) live in the same history caches.
    reference = 0
    for code in REFERENCE_JP_HISTORY:
        try:
            if hasattr(host, "_jq_price_history") and host._jq_price_history(code):
                reference += 1
        except Exception as exc:
            warm["referenceErrorClass"] = f"jp:{type(exc).__name__}"
    for code in REFERENCE_US_HISTORY:
        # The SIG-03 proxy reads the chart history cache, which the Twelve
        # Data fetcher fills; the Finnhub-based fetcher fills a different cache.
        warmed_us = False
        for name in ("_td_price_history", "_us_price_history"):
            fetcher = getattr(host, name, None)
            if fetcher is None:
                continue
            try:
                if fetcher(code):
                    warmed_us = True
                    break
            except Exception as exc:
                warm["referenceErrorClass"] = f"us:{name}:{type(exc).__name__}"
        if warmed_us:
            reference += 1
        elif not warm.get("referenceErrorClass"):
            warm["referenceErrorClass"] = "us:empty"
    warm["referenceWarmed"] = reference
    # SIG-04 derived valuation needs each issuer's latest statements (the
    # 14-day SHO window rarely holds them).  Fetched per code, a bounded
    # number per cycle, retried on later cycles until every interest issuer
    # is covered; refreshed with the 4-hourly SHO warm.
    if hasattr(host, "_jquants_paginated"):
        if force_sho:
            _STATE["statements"].clear()
        pending = [code for code in symbols if code not in _STATE["statements"]]
        for code in pending[:VALUATION_STATEMENTS_PER_CYCLE]:
            paths = ([warm["statementsPath"]] if warm["statementsPath"] else list(STATEMENTS_PATHS))
            for path in paths:
                try:
                    rows = host._jquants_paginated(path, {"code": code},
                                                   max_pages=VALUATION_STATEMENT_PAGES,
                                                   request_timeout=8)
                except Exception as exc:
                    warm["statementsErrorClass"] = f"{path}:{type(exc).__name__}:{str(exc)[:24]}"
                    continue
                if isinstance(rows, list):
                    _STATE["statements"][code] = [row for row in rows if isinstance(row, dict)][-12:]
                    warm["statementsPath"] = path
                    break
            _STATE["statements"].setdefault(code, [])          # do not retry a failing code every cycle
            sleeper(1.0)
        warm["statementsFetched"] = sum(1 for rows in _STATE["statements"].values() if rows)
        # The host's own statements feed (SHO D07) still calls the V1 path and
        # is silently empty; publish the V2 rows into its cache so the earnings
        # event selection sees real disclosures.  Only when we fetched real rows.
        if warm["statementsFetched"] and isinstance(statements, dict):
            merged = []
            for rows in _STATE["statements"].values():
                merged.extend(rows)
            statements["rows"] = merged
            statements["source"] = "jquants_v2_summary_boot"
            statements["fetchedAt"] = stamp
            statements["expires"] = time.time() + STATEMENTS_CACHE_SECONDS
            warm["statementsPublished"] = len(merged)
    try:
        rows = list((statements.get("rows") if isinstance(statements, dict) else None) or [])
        for code_rows in _STATE["statements"].values():
            rows.extend(code_rows)
        universe = [item.get("symbol") for item in (getattr(host, "_JP_WATCHLIST", None) or [])
                    if isinstance(item, dict)] + symbols
        evidence = argus_japan_valuation.compute(rows, _prices_by_code(host),
                                                 computed_at=stamp, universe=universe)
        argus_japan_valuation.publish(evidence)
        warm["valuation"] = {"status": evidence.get("status"),
                             "coverage": evidence.get("coverage"),
                             "medianForwardPer": evidence.get("medianForwardPer")}
    except Exception as exc:
        warm["errorClass"] = f"valuation:{type(exc).__name__}"
    # D07 may report NOT_APPLICABLE only when the statements feed was read
    # for real (our own V2 fetch succeeded); otherwise it stays MISSING.
    argus_japan_valuation.publish_statements_state({
        "warmedAt": stamp if warm["statementsFetched"] else None,
        "rowCount": warm.get("statementsPublished", 0),
        "source": (statements.get("source") if isinstance(statements, dict) else None),
        "path": warm["statementsPath"],
    })
    warm["cycles"] += 1


def _warm_loop(host: Any, *, sleeper: Callable[[float], None], now: Callable[[], float],
               max_cycles: Optional[int]) -> None:
    warm = _STATE["warm"]
    if not any(hasattr(host, name) for name in WARM_HOST_ATTRS):
        warm["status"] = "HOST_UNSUPPORTED"
        return
    warm["status"] = "RUNNING"
    last_sho = None
    cycles = 0
    try:
        while True:
            force = last_sho is None or now() - last_sho >= SHO_WARM_SECONDS
            _warm_cycle(host, sleeper=sleeper, now=now, force_sho=force)
            if force:
                last_sho = now()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            waited = 0.0
            while waited < INTEREST_REFRESH_SECONDS:
                sleeper(INTEREST_SCAN_SECONDS)
                waited += INTEREST_SCAN_SECONDS
                scan_interest(host, now())
        warm["status"] = "DONE"
    except Exception as exc:                        # pragma: no cover - defensive
        warm["status"] = "FAILED"
        warm["errorClass"] = type(exc).__name__


def ensure_started(host: Any = None, *, environ: Optional[Dict[str, str]] = None,
                   delay_seconds: float = DEFAULT_DELAY_SECONDS,
                   per_symbol_seconds: float = DEFAULT_PER_SYMBOL_SECONDS,
                   pause_seconds: float = DEFAULT_PAUSE_SECONDS,
                   sleeper: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic) -> str:
    """Idempotent: start the bootstrap thread once per process."""
    env = os.environ if environ is None else environ
    if str(env.get("ARGUS_CHART_BOOTSTRAP", "1")).strip().lower() in ("0", "false", "off"):
        return "DISABLED"
    host = host if host is not None else sys.modules.get("__main__")
    if host is None or not all(hasattr(host, name) for name in REQUIRED_HOST_ATTRS):
        return "HOST_UNSUPPORTED"
    with _LOCK:
        if _STATE["started"]:
            thread = _STATE["thread"]
            return "RUNNING" if thread is not None and thread.is_alive() else "DONE"
        _STATE["started"] = True
        thread = threading.Thread(
            target=_run, args=(host,),
            kwargs={"delay_seconds": delay_seconds, "per_symbol_seconds": per_symbol_seconds,
                    "pause_seconds": pause_seconds, "sleeper": sleeper, "clock": clock},
            name="argus-chart-bootstrap", daemon=True)
        _STATE["thread"] = thread
        thread.start()
        return "STARTED"


def status() -> Dict[str, Any]:
    return dict(_STATE["summary"])


def warm_status() -> Dict[str, Any]:
    out = dict(_STATE["warm"])
    out["interestRegistrySize"] = len(_STATE["interest"])
    return out


def warm_status_safe() -> Dict[str, Any]:
    """Bounded, symbol-free warm summary for public evidence documents."""
    warm = _STATE["warm"]
    return {
        "status": warm.get("status"), "cycles": warm.get("cycles"),
        "shoWarmedAt": warm.get("shoWarmedAt"), "curatedWarmedAt": warm.get("curatedWarmedAt"),
        "interestWarmedAt": warm.get("interestWarmedAt"),
        "interestCount": len(warm.get("interestSymbols") or []),
        "historyWarmed": warm.get("historyWarmed"), "referenceWarmed": warm.get("referenceWarmed"),
        "statementsFetched": warm.get("statementsFetched"),
        "statementsErrorClass": warm.get("statementsErrorClass"),
        "statementsPath": warm.get("statementsPath"),
        "statementsPublished": warm.get("statementsPublished"),
        "referenceErrorClass": warm.get("referenceErrorClass"),
        "valuation": warm.get("valuation"), "errorClass": warm.get("errorClass"),
        "chart": {"status": _STATE["summary"].get("status"),
                  "missingAfter": _STATE["summary"].get("missingAfter")},
    }


def _reset_for_tests() -> None:
    with _LOCK:
        _STATE["started"] = False
        _STATE["thread"] = None
        _STATE["summary"] = {"status": "NOT_STARTED", "targets": 0, "published": 0,
                             "unchanged": 0, "skipped": 0, "degraded": 0, "missingBefore": None,
                             "missingAfter": None, "startedAt": None, "finishedAt": None}
        _STATE["warm"] = {"status": "NOT_STARTED", "shoWarmedAt": None, "shoSourceStatus": None,
                          "interestSymbols": [], "interestWarmedAt": None, "historyWarmed": 0,
                          "valuation": None, "cycles": 0, "errorClass": None,
                          "curatedWarmedAt": None, "referenceWarmed": 0, "statementsFetched": 0,
                          "statementsErrorClass": None, "referenceErrorClass": None,
                          "statementsPath": None, "statementsPublished": 0}
        _STATE["warmMaxCycles"] = None
        _STATE["interest"] = {}
        _STATE["statements"] = {}
