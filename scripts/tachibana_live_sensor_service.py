#!/usr/bin/env python3
"""Dedicated single-instance Tachibana background-worker entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.models import ErrorClass, TachibanaError
from argus_providers.tachibana.runtime import DEFAULT_SYMBOLS, TachibanaLiveRuntime
from argus_providers.tachibana.singleton import ProcessSingletonLease


_STOP = threading.Event()


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
            runtime = TachibanaLiveRuntime(config, symbols=_symbols())
            try:
                runtime.start()
            except TachibanaError as exc:
                _hold_degraded(exc.classification.value)
                return 0
            except Exception:
                _hold_degraded("UNCLASSIFIED_SAFE_FAILURE")
                return 0

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
