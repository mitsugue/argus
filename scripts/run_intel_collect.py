#!/usr/bin/env python3
"""Follow one admin collection through cold-start warming; never retry its work."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import math
from datetime import datetime
from pathlib import Path
import tempfile
from urllib.error import URLError

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.workflow_http import request_json


STAGES = frozenset(('news_feeds', 'news_translation', 'news_ranking', 'news_persist',
    'investor_types', 'calendar', 'jsf', 'jp_watchlist', 'us_watchlist', 'extra_symbols',
    'owner_watchlist', 'market_inputs', 'fiscal_inputs', 'pit_restore', 'pit_vix_nikkei',
    'pit_fx_sp500', 'pit_macro_history', 'pit_credit', 'pit_future_valuation', 'pit_level_map',
    'pit_targets_internals', 'pit_margin', 'pit_statements', 'pit_earnings', 'pit_vix_analog',
    'pit_official', 'pit_feature_history', 'pit_research', 'pit_backup'))


def private_timing_record(body):
    """Closed scalar projection of the SAME tracked response; never returned on stdout."""
    def stamp(value):
        if isinstance(value, str) and len(value) <= 40:
            try:
                if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None:
                    return value
            except ValueError:
                pass
        return None
    def seconds(value):
        return round(value, 3) if (type(value) in (int, float) and
            0 <= value <= 86400 and math.isfinite(value)) else None
    stages = []
    rows = body.get('completedStages')
    for row in (rows if isinstance(rows, list) else [])[:len(STAGES)]:
        if (isinstance(row, dict) and isinstance(row.get('stage'), str)
                and row['stage'] in STAGES and seconds(row.get('elapsedSeconds')) is not None):
            stages.append({'stage': row['stage'], 'elapsedSeconds': seconds(row['elapsedSeconds'])})
    return {'schemaVersion': 'argus-collect-timing-v1', 'available': bool(stages),
            'status': body.get('status') if body.get('status') in ('running', 'done', 'failed') else None,
            'startedAt': stamp(body.get('startedAt')), 'finishedAt': stamp(body.get('finishedAt')),
            'stage': body.get('stage') if isinstance(body.get('stage'), str) and body['stage'] in STAGES else None,
            'stageElapsedSeconds': seconds(body.get('stageElapsedSeconds')), 'completedStages': stages}


def save_private_timing(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('timing_path_invalid')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def run(*, base: str, token: str, timeout: float = 900, request=request_json,
        clock=time.monotonic, sleep=time.sleep, request_id: str | None = None,
        private_timing=None) -> dict:
    if not token:
        return {"status": "failed", "errorClass": "admin_token_missing"}
    run_id = request_id or uuid.uuid4().hex
    url = base.rstrip("/") + "/api/argus/institutional-intelligence/collect"
    headers = {"X-ARGUS-ADMIN-TOKEN": token, "Content-Type": "application/json"}
    deadline = clock() + timeout
    started = False
    last_error = None
    while clock() < deadline:
        payload = {"requestId": run_id, "statusOnly" if started else "async": True}
        # If the initial connection is lost, submit the SAME identity again.
        # The server either starts it once or returns its existing record.
        try:
            code, raw = request(url=url, method="POST", headers=headers,
                                data=json.dumps(payload), timeout=max(1, min(30, int(deadline - clock()))))
            body = json.loads(raw)
        except (OSError, URLError, TimeoutError, ValueError):
            last_error = "collect_transport_or_json_error"
        else:
            if code in (401, 403, 404) or (400 <= code < 500 and code != 429):
                return {"status": "failed", "runId": run_id, "httpStatus": code,
                        "errorClass": "collect_run_missing_or_rejected"}
            if 200 <= code < 300:
                if not isinstance(body, dict) or body.get("status") not in ("running", "done", "failed"):
                    return {"status": "failed", "errorClass": "collect_tracking_protocol_missing"}
                received_id = body.get("runId")
                if not isinstance(received_id, str) or not received_id or (started and received_id != run_id):
                    return {"status": "failed", "errorClass": "collect_run_identity_mismatch"}
                run_id, started = received_id, True
                if private_timing is not None:
                    private_timing(private_timing_record(body))
                if body["status"] in ("done", "failed"):
                    # Persist only bounded status/counts, no provider payloads.
                    result = body.get("result") or {}
                    failed_feeds = result.get("failedFeeds") or []
                    all_feeds_failed = bool(result.get("feeds")) and len(failed_feeds) >= result["feeds"]
                    return {"status": "failed" if all_feeds_failed else body["status"], "runId": run_id,
                            "startedAt": body.get("startedAt"), "finishedAt": body.get("finishedAt"),
                            "errorClass": "all_intel_feeds_unavailable" if all_feeds_failed else body.get("errorClass"),
                            "collected": result.get("collected"), "stored": result.get("stored"),
                            "failedFeedCount": len(failed_feeds), "feedCount": result.get("feeds"),
                            # 2026-10-19: the public feed names (no payload), so a failing feed can be named.
                            "failedFeeds": [str(name)[:40] for name in failed_feeds[:25]],
                            # 2026-10-20: why each failed feed failed — fixed codes only, no page content.
                            "failedFeedReasons": [
                                {"feed": str(row.get("feed"))[:40],
                                 "httpStatus": row.get("httpStatus") if isinstance(row.get("httpStatus"), int) else None,
                                 "errorClass": str(row.get("errorClass") or "")[:60] or None,
                                 "elapsedSeconds": row.get("elapsedSeconds") if isinstance(row.get("elapsedSeconds"), (int, float)) else None}
                                for row in (result.get("perFeed") or [])[:40]
                                if isinstance(row, dict) and row.get("ok") is False][:25],
                            "supplyDemandWarm": result.get("supplyDemandWarm"),
                            "jpMarketEngineInputWarm": result.get("jpMarketEngineInputWarm")}
            else:
                last_error = "collect_http_transient"
        sleep(max(0, min(5, deadline - clock())))
    return {"status": "failed", "runId": run_id,
            "errorClass": "collect_poll_timeout", "lastErrorClass": last_error}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://argus-backend-3j2m.onrender.com")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument('--private-timing-output', type=Path)
    args = parser.parse_args(argv)
    saved = {'ok': False, 'available': False}
    def observe(value):
        try:
            save_private_timing(args.private_timing_output, value)
            saved.update(ok=True, available=value['available'])
        except (OSError, ValueError):
            saved.update(ok=False, available=False)
    result = run(base=args.base, token=os.environ.get("ARGUS_ADMIN_TOKEN", ""), timeout=args.timeout,
                 private_timing=observe if args.private_timing_output else None)
    if args.private_timing_output:
        result.update(privateTimingSaved=saved['ok'], privateTimingAvailable=saved['available'])
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
