#!/usr/bin/env python3
"""Bounded, secret-safe live acceptance command for the Tachibana sensor."""

from __future__ import annotations

import json
import os
from datetime import datetime, time as wall_time, timezone
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argus_market_clock
from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.models import ErrorClass, TachibanaError
from argus_providers.tachibana.runtime import DEFAULT_SYMBOLS, TachibanaLiveRuntime
from argus_providers.tachibana.singleton import ProcessSingletonLease


_TOKYO = ZoneInfo("Asia/Tokyo")
_EARLIEST_LIVE_START = wall_time(7, 55)
_LATEST_PREOPEN_START = wall_time(9, 0)
_AFTERNOON_LIVE_START = wall_time(12, 0)
_LATEST_AFTERNOON_PREOPEN_START = wall_time(12, 30)


def _timeout() -> int:
    try:
        value = int(os.environ.get("ARGUS_TACHIBANA_ACCEPTANCE_SECONDS", "5400"))
    except ValueError:
        raise TachibanaError(ErrorClass.CONFIGURATION) from None
    if not 30 <= value <= 7200:
        raise TachibanaError(ErrorClass.CONFIGURATION)
    return value


def _symbols() -> tuple[str, ...]:
    raw = os.environ.get(
        "ARGUS_TACHIBANA_SYMBOLS", ",".join(DEFAULT_SYMBOLS)
    )
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def _live_start_guard(now: datetime | None = None) -> str | None:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = argus_market_clock.market_session(
        argus_market_clock.JP_EQUITY, current
    )
    local = current.astimezone(_TOKYO)
    if state.get("isTradingDay") is not True:
        return "JPX_TRADING_DAY_CLOSED"
    if local.time() < _EARLIEST_LIVE_START:
        return "LIVE_START_GUARD_BEFORE_0755"
    if local.time() < _LATEST_PREOPEN_START:
        return None
    if local.time() < _AFTERNOON_LIVE_START:
        return "WAIT_FOR_AFTERNOON_PREOPEN"
    if local.time() < _LATEST_AFTERNOON_PREOPEN_START:
        return None
    return "PREOPEN_START_WINDOWS_MISSED"


def _initial_read_failure(runtime: object) -> str | None:
    read_diagnostics = getattr(runtime, "initial_read_diagnostics_safe_dict", None)
    if not callable(read_diagnostics):
        return None
    diagnostics = read_diagnostics()
    if not isinstance(diagnostics, dict):
        return None
    for name in ("providerDate", "priceBaseline"):
        diagnostic = diagnostics.get(name)
        if not isinstance(diagnostic, dict):
            continue
        stage = diagnostic.get("stage")
        classification = diagnostic.get("classification")
        if (
            isinstance(stage, str)
            and classification not in {"NOT_ATTEMPTED", "IN_PROGRESS", "PASS"}
        ):
            return stage
    return None


def main() -> int:
    runtime: TachibanaLiveRuntime | None = None
    teardown = True
    classification = "UNCLASSIFIED_SAFE_FAILURE"
    snapshot: dict[str, object] | None = None
    auth_diagnostic: dict[str, object] | None = None
    initial_read_diagnostics: dict[str, object] | None = None
    try:
        guarded = _live_start_guard()
        if guarded is not None:
            classification = guarded
            raise TachibanaError(ErrorClass.DISABLED)
        config = TachibanaConfig.from_env()
        lock_path = os.environ.get(
            "ARGUS_TACHIBANA_SINGLETON_PATH",
            "/tmp/argus-tachibana-live-sensor.lock",
        )
        with ProcessSingletonLease(Path(lock_path)):
            runtime = TachibanaLiveRuntime(config, symbols=_symbols())
            runtime.start()
            accepted = runtime.wait_for_acceptance(timeout_seconds=_timeout())
            snapshot = accepted.safe_dict()
            classification = accepted.classification
    except TachibanaError as exc:
        if classification == "UNCLASSIFIED_SAFE_FAILURE":
            if runtime is not None:
                auth_diagnostic = runtime.session.auth_diagnostic.safe_dict()
                diagnostic_class = auth_diagnostic.get("classification")
                read_failure = _initial_read_failure(runtime)
                if read_failure is not None:
                    classification = read_failure
                elif isinstance(diagnostic_class, str):
                    classification = diagnostic_class
                else:
                    classification = exc.classification.value
            else:
                classification = exc.classification.value
    except Exception:
        classification = "UNCLASSIFIED_SAFE_FAILURE"
    finally:
        if runtime is not None:
            if auth_diagnostic is None:
                auth_diagnostic = runtime.session.auth_diagnostic.safe_dict()
            read_diagnostics = getattr(
                runtime, "initial_read_diagnostics_safe_dict", None
            )
            if callable(read_diagnostics):
                initial_read_diagnostics = read_diagnostics()
            teardown = runtime.stop()

    result = {
        "classification": classification,
        "authDiagnostic": auth_diagnostic,
        "initialReads": initial_read_diagnostics,
        "logout": teardown,
        "secretLeak": False,
        "snapshot": snapshot,
    }
    passed = bool(snapshot and snapshot.get("accepted") and teardown)
    print(
        f"TACHIBANA_LIVE_ACCEPTANCE={'PASS' if passed else 'BLOCKED'} "
        + json.dumps(result, sort_keys=True, separators=(",", ":"))
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
