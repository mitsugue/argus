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
SHO_WARM_SECONDS = 4 * 3600.0
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
             "valuation": None, "cycles": 0, "errorClass": None},
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


def interest_symbols(host: Any) -> list:
    """Bounded JP interest set: symbols the owner's device already asked for
    (decision-evidence subjects, supply-demand extras, watchlist hints) plus
    the curated universe.  Owner holdings never leave the device; only the
    codes the device already sent to public routes are used."""
    codes: list = []

    def add(value: Any) -> None:
        code = _jp_code(value)
        if code and code not in codes:
            codes.append(code)

    add("5803")
    for item in getattr(host, "_JP_WATCHLIST", None) or []:
        if isinstance(item, dict):
            add(item.get("symbol"))
    cache = getattr(host, "_DECISION_EVIDENCE_CACHE", None)
    if isinstance(cache, dict):
        for key in list(cache.keys()):
            add(key)
    extras = getattr(host, "_SD_EXTRA_SYMBOLS", None)
    if isinstance(extras, dict):
        for key, meta in list(extras.items()):
            if isinstance(meta, dict) and meta.get("market") == "JP":
                add(key)
    seen = getattr(host, "_JP_SEEN_SYMBOLS", None)
    if isinstance(seen, dict):
        for key in list(seen.keys()):
            add(key)
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
    if isinstance(statements, dict):
        argus_japan_valuation.publish_statements_state({
            "warmedAt": stamp if warm["shoWarmedAt"] else None,
            "rowCount": len(statements.get("rows") or []),
            "source": statements.get("source"),
        })
    symbols = interest_symbols(host)
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
    try:
        rows = (statements.get("rows") if isinstance(statements, dict) else None) or []
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
            sleeper(INTEREST_REFRESH_SECONDS)
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
    return dict(_STATE["warm"])


def _reset_for_tests() -> None:
    with _LOCK:
        _STATE["started"] = False
        _STATE["thread"] = None
        _STATE["summary"] = {"status": "NOT_STARTED", "targets": 0, "published": 0,
                             "unchanged": 0, "skipped": 0, "degraded": 0, "missingBefore": None,
                             "missingAfter": None, "startedAt": None, "finishedAt": None}
        _STATE["warm"] = {"status": "NOT_STARTED", "shoWarmedAt": None, "shoSourceStatus": None,
                          "interestSymbols": [], "interestWarmedAt": None, "historyWarmed": 0,
                          "valuation": None, "cycles": 0, "errorClass": None}
        _STATE["warmMaxCycles"] = None
