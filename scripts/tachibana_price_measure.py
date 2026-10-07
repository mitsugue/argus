"""Local-only price shadow measurement; opt-in, one login, no price/body output."""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.price_runtime import TachibanaPriceRuntime
from argus_providers.tachibana.models import Freshness
from argus_providers.tachibana.usage_policy import initialize_blocked_policy


def memory_sample():
    # Linux peak RSS is KiB, macOS is bytes; current container usage includes the web server.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 2 if sys.platform == 'darwin' else 1024)
    container = None
    for name in ('/sys/fs/cgroup/memory.current', '/sys/fs/cgroup/memory/memory.usage_in_bytes'):
        try:
            container = int(Path(name).read_text()) / 1024 ** 2
            break
        except (OSError, ValueError): pass
    return {'processPeakMiB': round(peak, 3), 'containerMiB': round(container, 3) if container is not None else None}


def measure_runtime(runtime, *, seconds=300, sleeper=time.sleep, monotonic=time.monotonic):
    before = memory_sample(); peaks = dict(before); durations = []; fresh = 0; samples = 0
    error = None; stop_ok = None
    started = monotonic()
    try:
        runtime.start()  # One login; later refreshes use the same session.
        while monotonic() - started < seconds:
            tick = monotonic()
            runtime.refresh()
            durations.append(monotonic() - tick)
            rows = list(runtime._price_observations.values())
            fresh += sum(row.freshness == Freshness.FRESH for row in rows)
            samples += len(rows)
            current = memory_sample()
            for key in peaks:
                if current[key] is not None: peaks[key] = max(peaks[key] or 0, current[key])
            sleeper(10)
    except Exception as exc:
        error = getattr(getattr(exc, 'classification', None), 'value', 'SAFE_FAILURE')
    finally:
        try: stop_ok = runtime.stop()
        except Exception: stop_ok = False
    ordered = sorted(durations)
    return {'mode': 'SHADOW', 'measuredAt': datetime.now(timezone.utc).isoformat(),
            'seconds': round(monotonic() - started, 3), 'symbolCount': len(runtime.symbols),
            'samples': samples, 'freshSamples': fresh, 'memoryBefore': before, 'memoryPeak': peaks,
            'readSecondsP95': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 4) if ordered else None,
            'errorClass': error, 'logoutSucceeded': stop_ok, 'displayEnabled': False,
            'placementDecision': 'PENDING_PRODUCTION_MEASUREMENT_REVIEW'}


def main():
    parser = argparse.ArgumentParser(description='立花の影測定。結果はローカルだけに保存してください。')
    parser.add_argument('--execute-shadow', action='store_true')
    parser.add_argument('--initialize-blocked-policy', action='store_true')
    parser.add_argument('--exclusive-owner-session', action='store_true')
    parser.add_argument('--nikkei-confirmed', action='store_true')
    parser.add_argument('--symbols', default='')
    parser.add_argument('--policy-path')
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if args.initialize_blocked_policy:
        if args.execute_shadow or not args.policy_path or not args.exclusive_owner_session:
            parser.error('初期化は測定と分け、専有確認と永続保存先を指定してください')
        result = initialize_blocked_policy(Path(args.policy_path), lambda: datetime.now(timezone.utc))
        print(json.dumps({**result, 'enabledChanged': False}, ensure_ascii=False))
        return 0
    if not args.execute_shadow:
        print(json.dumps({'status': 'NOT_RUN', 'networkCalls': 0, 'enabledChanged': False}))
        return 0
    if not args.exclusive_owner_session or not args.policy_path or not 30 <= args.seconds <= 900:
        parser.error('他端末停止・永続保存先・30〜900秒の測定時間が必要です')
    symbols = tuple(part.strip().upper() for part in args.symbols.split(',') if part.strip())
    if '101' in symbols and not args.nikkei_confirmed:
        parser.error('指数は本人の試験結果を確認してから指定してください')
    # The environment flag stays false. Only this explicit one-off shadow runner is enabled.
    config = replace(TachibanaConfig.from_env(), enabled=True, max_symbols=64,
                     max_read_attempts=1, websocket_enabled=False)
    runtime = TachibanaPriceRuntime(config, symbols=symbols, policy_path=args.policy_path)
    print(json.dumps(measure_runtime(runtime, seconds=args.seconds), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
