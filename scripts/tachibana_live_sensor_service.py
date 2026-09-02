#!/usr/bin/env python3
"""Dedicated single-instance Tachibana background-worker entry point."""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, time as wall_time
from pathlib import Path
import signal
import sys
import threading
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argus_market_clock
from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.models import ErrorClass, TachibanaError
from argus_providers.tachibana.runtime import DEFAULT_SYMBOLS, TachibanaLiveRuntime
from argus_providers.tachibana.singleton import ProcessSingletonLease


_STOP = threading.Event()
_TOKYO = ZoneInfo("Asia/Tokyo")
_LIVE_SENSOR_START = wall_time(7, 55)
_LIVE_SENSOR_END = wall_time(15, 31)
_REAUTH_WINDOW_SECONDS = 15 * 60
_REAUTH_DELAY_SECONDS = 30
_MAX_REAUTHENTICATIONS_PER_WINDOW = 2


def _signal_stop(_signum: int, _frame: object) -> None:
    _STOP.set()


def _safe_log(event: str, **fields: object) -> None:
    print(
        event + " " + json.dumps(fields, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def _symbols() -> tuple[str, ...]:
    raw = os.environ.get(
        "ARGUS_TACHIBANA_SYMBOLS", ",".join(DEFAULT_SYMBOLS)
    )
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def _hold_degraded(classification: str) -> None:
    _safe_log(
        "TACHIBANA_SENSOR_BLOCKED",
        classification=classification,
        automaticReauthentication=False,
        secretLeak=False,
    )
    while not _STOP.wait(300):
        _safe_log(
            "TACHIBANA_SENSOR_HEARTBEAT",
            classification=classification,
            providerHealth="UNAVAILABLE",
            secretLeak=False,
        )


def _scheduled_sensor_start(
    *, now: datetime, force_next_trading_day: bool = False,
) -> datetime | None:
    """Return the next 07:55 live-sensor boundary, or None when active."""
    local = now.astimezone(_TOKYO)
    state = argus_market_clock.market_session(
        argus_market_clock.JP_EQUITY, local
    )
    if (
        not force_next_trading_day
        and state.get("isTradingDay") is True
        and local.time() < _LIVE_SENSOR_START
    ):
        return datetime.combine(local.date(), _LIVE_SENSOR_START, _TOKYO)
    if (
        not force_next_trading_day
        and state.get("isTradingDay") is True
        and _LIVE_SENSOR_START <= local.time() < _LIVE_SENSOR_END
    ):
        return None
    target_date = argus_market_clock.add_trading_days(
        argus_market_clock.JP_EQUITY, local.date(), 1
    )
    return datetime.combine(target_date, _LIVE_SENSOR_START, _TOKYO)


def _wait_for_sensor_start(target: datetime, classification: str) -> bool:
    _safe_log(
        "TACHIBANA_SENSOR_START_SCHEDULED",
        classification=classification,
        nextAttemptAt=target.isoformat(),
        retryPolicy="MARKET_WINDOW_AND_BOUNDED_REAUTHENTICATION",
        secretLeak=False,
    )
    while not _STOP.is_set():
        remaining = (target - datetime.now(_TOKYO)).total_seconds()
        if remaining <= 0:
            return True
        _STOP.wait(min(300.0, remaining))
    return False


def _consume_reauthentication_budget(
    attempts: deque[float], *, now: float,
) -> bool:
    while attempts and now - attempts[0] >= _REAUTH_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _MAX_REAUTHENTICATIONS_PER_WINDOW:
        return False
    attempts.append(now)
    return True


def main() -> int:
    signal.signal(signal.SIGTERM, _signal_stop)
    signal.signal(signal.SIGINT, _signal_stop)
    runtime: TachibanaLiveRuntime | None = None
    teardown = True
    try:
        config = TachibanaConfig.from_env()
        lock_path = os.environ.get(
            "ARGUS_TACHIBANA_SINGLETON_PATH",
            "/tmp/argus-tachibana-live-sensor.lock",
        )
        with ProcessSingletonLease(Path(lock_path)):
            reauthentication_attempts: deque[float] = deque()
            while not _STOP.is_set():
                scheduled = _scheduled_sensor_start(now=datetime.now(_TOKYO))
                if scheduled is not None and not _wait_for_sensor_start(
                    scheduled, "LIVE_MARKET_SENSOR_WINDOW"
                ):
                    break
                runtime = TachibanaLiveRuntime(config, symbols=_symbols())
                try:
                    runtime.start()
                except TachibanaError as exc:
                    classification = exc.classification
                    teardown = runtime.stop()
                    runtime = None
                    next_window = _scheduled_sensor_start(
                        now=datetime.now(_TOKYO)
                    )
                    if next_window is not None:
                        if _wait_for_sensor_start(
                            next_window, classification.value
                        ):
                            continue
                        break
                    if (
                        classification == ErrorClass.SESSION_EXPIRED
                        and _consume_reauthentication_budget(
                            reauthentication_attempts, now=time.monotonic()
                        )
                    ):
                        _safe_log(
                            "TACHIBANA_SENSOR_REAUTH_SCHEDULED",
                            classification=classification.value,
                            delaySeconds=_REAUTH_DELAY_SECONDS,
                            bounded=True,
                            secretLeak=False,
                        )
                        if _STOP.wait(_REAUTH_DELAY_SECONDS):
                            break
                        continue
                    if classification in {
                        ErrorClass.OUTSIDE_HOURS, ErrorClass.MAINTENANCE,
                    }:
                        target = _scheduled_sensor_start(
                            now=datetime.now(_TOKYO),
                            force_next_trading_day=True,
                        )
                        if target is not None and _wait_for_sensor_start(
                            target, classification.value
                        ):
                            continue
                    _hold_degraded(classification.value)
                    break
                except Exception:
                    teardown = runtime.stop()
                    runtime = None
                    _hold_degraded("UNCLASSIFIED_SAFE_FAILURE")
                    break

                _safe_log(
                    "TACHIBANA_SENSOR_STARTED",
                    authority="SHADOW_NON_AUTHORITATIVE",
                    eventEnabled=True,
                    symbolCount=len(runtime.symbols),
                    persistence=False,
                    publicEndpoint=False,
                    secretLeak=False,
                )
                last_classification = ""
                last_cross_validation = 0.0
                accepted = False
                while not _STOP.wait(5):
                    if _scheduled_sensor_start(now=datetime.now(_TOKYO)) is not None:
                        break
                    cross_validate = time.monotonic() - last_cross_validation >= 30
                    snapshot = runtime.acceptance_snapshot(
                        cross_validate=cross_validate
                    )
                    if cross_validate:
                        last_cross_validation = time.monotonic()
                    if snapshot.classification != last_classification:
                        _safe_log(
                            "TACHIBANA_SENSOR_STATE",
                            **snapshot.safe_dict(),
                            secretLeak=False,
                        )
                        last_classification = snapshot.classification
                    if snapshot.accepted and not accepted:
                        _safe_log(
                            "TACHIBANA_PRODUCTION_ACCEPTANCE",
                            **snapshot.safe_dict(),
                            authority="SHADOW_NON_AUTHORITATIVE",
                            executionCapability=False,
                            secretLeak=False,
                        )
                        accepted = True
                    if runtime.terminal_error != ErrorClass.NONE:
                        break
                terminal = runtime.terminal_error
                teardown = runtime.stop()
                runtime = None
                if _STOP.is_set():
                    break
                scheduled = _scheduled_sensor_start(now=datetime.now(_TOKYO))
                if scheduled is not None:
                    if _wait_for_sensor_start(
                        scheduled, "LIVE_MARKET_SENSOR_WINDOW_ENDED"
                    ):
                        continue
                    break
                if terminal == ErrorClass.SESSION_EXPIRED and (
                    _consume_reauthentication_budget(
                        reauthentication_attempts, now=time.monotonic()
                    )
                ):
                    _safe_log(
                        "TACHIBANA_SENSOR_REAUTH_SCHEDULED",
                        classification=terminal.value,
                        logout=teardown,
                        delaySeconds=_REAUTH_DELAY_SECONDS,
                        bounded=True,
                        secretLeak=False,
                    )
                    if _STOP.wait(_REAUTH_DELAY_SECONDS):
                        break
                    continue
                _hold_degraded(
                    terminal.value
                    if terminal != ErrorClass.NONE
                    else "EVENT_TERMINATED"
                )
                break
            return 0
    except TachibanaError as exc:
        _hold_degraded(exc.classification.value)
        return 0
    except Exception:
        _hold_degraded("UNCLASSIFIED_SAFE_FAILURE")
        return 0
    finally:
        if runtime is not None:
            teardown = runtime.stop()
        _safe_log(
            "TACHIBANA_SENSOR_STOPPED",
            logout=teardown,
            secretLeak=False,
        )


if __name__ == "__main__":
    raise SystemExit(main())
