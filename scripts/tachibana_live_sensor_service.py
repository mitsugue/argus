#!/usr/bin/env python3
"""Dedicated single-instance Tachibana background-worker entry point."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time as wall_time, timedelta
from pathlib import Path
import signal
import sys
import threading
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.models import ErrorClass, TachibanaError
from argus_providers.tachibana.runtime import DEFAULT_SYMBOLS, TachibanaLiveRuntime
from argus_providers.tachibana.singleton import ProcessSingletonLease


_STOP = threading.Event()
_TOKYO = ZoneInfo("Asia/Tokyo")
_AUTH_BLACKOUT_START = wall_time(3, 25)
_AUTH_RESUME = wall_time(5, 35)
_DAILY_SESSION_ERRORS = {
    ErrorClass.OUTSIDE_HOURS,
    ErrorClass.MAINTENANCE,
    ErrorClass.SESSION_EXPIRED,
}


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


def _scheduled_auth_time(
    *, now: datetime, last_attempt_date: date | None,
) -> datetime | None:
    """Return a bounded operating-day auth time, or None when allowed."""
    local = now.astimezone(_TOKYO)
    candidate = datetime.combine(local.date(), _AUTH_RESUME, _TOKYO)
    operating_date = (
        local.date() - timedelta(days=1)
        if local.time() < _AUTH_BLACKOUT_START
        else local.date()
    )
    if last_attempt_date == operating_date:
        return candidate + timedelta(days=1)
    if _AUTH_BLACKOUT_START <= local.time() < _AUTH_RESUME:
        return candidate
    return None


def _wait_for_scheduled_auth(target: datetime, classification: str) -> bool:
    _safe_log(
        "TACHIBANA_SENSOR_AUTH_SCHEDULED",
        classification=classification,
        nextAttemptAt=target.isoformat(),
        retryPolicy="AT_MOST_ONCE_PER_PROVIDER_OPERATING_DAY",
        secretLeak=False,
    )
    while not _STOP.is_set():
        remaining = (target - datetime.now(_TOKYO)).total_seconds()
        if remaining <= 0:
            return True
        _STOP.wait(min(300.0, remaining))
    return False


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
            last_attempt_date: date | None = None
            while not _STOP.is_set():
                scheduled = _scheduled_auth_time(
                    now=datetime.now(_TOKYO),
                    last_attempt_date=last_attempt_date,
                )
                if scheduled is not None and not _wait_for_scheduled_auth(
                    scheduled, "OFFICIAL_AUTH_WINDOW"
                ):
                    break
                attempt_time = datetime.now(_TOKYO)
                last_attempt_date = (
                    attempt_time.date() - timedelta(days=1)
                    if attempt_time.time() < _AUTH_BLACKOUT_START
                    else attempt_time.date()
                )
                runtime = TachibanaLiveRuntime(config, symbols=_symbols())
                try:
                    runtime.start()
                except TachibanaError as exc:
                    classification = exc.classification
                    teardown = runtime.stop()
                    runtime = None
                    if classification in _DAILY_SESSION_ERRORS:
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
                if terminal in _DAILY_SESSION_ERRORS:
                    _safe_log(
                        "TACHIBANA_SENSOR_DAILY_SESSION_ENDED",
                        classification=terminal.value,
                        logout=teardown,
                        secretLeak=False,
                    )
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
