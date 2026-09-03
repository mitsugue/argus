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
DEFAULT_DELAY_SECONDS = 15.0
DEFAULT_PER_SYMBOL_SECONDS = 45.0
DEFAULT_PAUSE_SECONDS = 2.0

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {
    "started": False, "thread": None,
    "summary": {"status": "NOT_STARTED", "targets": 0, "published": 0,
                "unchanged": 0, "skipped": 0, "degraded": 0, "missingBefore": None,
                "missingAfter": None, "startedAt": None, "finishedAt": None},
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
    except Exception as exc:                       # pragma: no cover - defensive
        summary["status"] = "FAILED"
        summary["errorClass"] = type(exc).__name__
    finally:
        summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


def _reset_for_tests() -> None:
    with _LOCK:
        _STATE["started"] = False
        _STATE["thread"] = None
        _STATE["summary"] = {"status": "NOT_STARTED", "targets": 0, "published": 0,
                             "unchanged": 0, "skipped": 0, "degraded": 0, "missingBefore": None,
                             "missingAfter": None, "startedAt": None, "finishedAt": None}
