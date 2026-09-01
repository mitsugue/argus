#!/usr/bin/env python3
"""Bounded, secret-safe live acceptance command for the Tachibana sensor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.models import ErrorClass, TachibanaError
from argus_providers.tachibana.runtime import DEFAULT_SYMBOLS, TachibanaLiveRuntime
from argus_providers.tachibana.singleton import ProcessSingletonLease


def _timeout() -> int:
    try:
        value = int(os.environ.get("ARGUS_TACHIBANA_ACCEPTANCE_SECONDS", "180"))
    except ValueError:
        raise TachibanaError(ErrorClass.CONFIGURATION) from None
    if not 30 <= value <= 900:
        raise TachibanaError(ErrorClass.CONFIGURATION)
    return value


def _symbols() -> tuple[str, ...]:
    raw = os.environ.get(
        "ARGUS_TACHIBANA_SYMBOLS", ",".join(DEFAULT_SYMBOLS)
    )
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def main() -> int:
    runtime: TachibanaLiveRuntime | None = None
    teardown = True
    classification = "UNCLASSIFIED_SAFE_FAILURE"
    snapshot: dict[str, object] | None = None
    try:
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
        classification = exc.classification.value
    except Exception:
        classification = "UNCLASSIFIED_SAFE_FAILURE"
    finally:
        if runtime is not None:
            teardown = runtime.stop()

    result = {
        "classification": classification,
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
