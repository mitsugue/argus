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
    'pit_official', 'pit_feature_history', 'pit_feature_sources', 'pit_feature_ledger',
    'pit_feature_reconcile', 'pit_feature_build', 'pit_feature_persist', 'pit_research', 'pit_backup'))

RESEARCH_KEYS = frozenset(
    [f'chart:{index}:{interval}' for index in ('N225', 'NDX', 'SPX', 'TOPIX')
     for interval in ('daily', 'weekly')]
    + [f'comparison:N225:{horizon}' for horizon in (1, 5, 10, 20)])


def _private_stamp(value):
    if isinstance(value, str) and len(value) <= 40:
        try:
            if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None:
                return value
        except ValueError:
            pass
    return None


def _private_seconds(value):
    return round(value, 3) if (type(value) in (int, float) and
        0 <= value <= 86400 and math.isfinite(value)) else None


def private_timing_record(body, *, include_run_context=False):
    """Closed scalar projection of the SAME tracked response; never returned on stdout."""
    stamp, seconds = _private_stamp, _private_seconds
    stages = []
    rows = body.get('completedStages')
    for row in (rows if isinstance(rows, list) else [])[:len(STAGES)]:
        if (isinstance(row, dict) and isinstance(row.get('stage'), str)
                and row['stage'] in STAGES and seconds(row.get('elapsedSeconds')) is not None):
            stages.append({'stage': row['stage'], 'elapsedSeconds': seconds(row['elapsedSeconds'])})
    projection = {'schemaVersion': 'argus-collect-timing-v1', 'available': bool(stages),
            'status': body.get('status') if body.get('status') in ('running', 'done', 'failed') else None,
            'startedAt': stamp(body.get('startedAt')), 'finishedAt': stamp(body.get('finishedAt')),
            'stage': body.get('stage') if isinstance(body.get('stage'), str) and body['stage'] in STAGES else None,
            'stageElapsedSeconds': seconds(body.get('stageElapsedSeconds')), 'completedStages': stages}
    if include_run_context:
        projection.update(schemaVersion='argus-collect-timing-v2',
            trigger=body.get('trigger') if body.get('trigger') in ('request', 'resident') else None,
            previousFinishedAt=stamp(body.get('previousFinishedAt')),
            stageStartedAt=stamp(body.get('stageStartedAt')))
    return projection


def private_runtime_record(body, expected):
    """Latest global research scalars, not an assertion of collection CPU ownership."""
    body = body if isinstance(body, dict) else {}
    expected = expected if isinstance(expected, dict) else {}
    collect = body.get('intelCollect')
    collect = collect if isinstance(collect, dict) else {}
    current = collect.get('currentRun')
    current = private_timing_record(current if isinstance(current, dict) else {}, include_run_context=True)
    research = body.get('indexResearch')
    research = research if isinstance(research, dict) else {}
    raw_outcomes = research.get('outcomes')
    raw_outcomes = raw_outcomes if isinstance(raw_outcomes, dict) else {}
    outcomes = {}
    for key in sorted(RESEARCH_KEYS):
        row = raw_outcomes.get(key)
        if not isinstance(row, dict):
            continue
        outcomes[key] = {
            'status': row.get('status') if row.get('status') in
                ('live', 'stale', 'available', 'unavailable', 'expected_skip',
                 'missing', 'insufficient_data', 'exception') else None,
            'elapsedSeconds': _private_seconds(row.get('elapsedSeconds')),
            'cpuSeconds': _private_seconds(row.get('cpuSeconds')),
            'calibrationStatus': row.get('calibrationStatus') if row.get('calibrationStatus') in
                ('REUSED', 'CALCULATED', 'NOT_EVALUABLE') else None}
    bounds = {key: _private_stamp(expected.get(key)) for key in ('startedAt', 'finishedAt')}
    research_bounds = {key: _private_stamp(research.get(key))
                       for key in ('lastStartedAt', 'lastCompletedAt')}
    within = None
    if all(bounds.values()) and all(research_bounds.values()):
        start, finish = (datetime.fromisoformat(bounds[key].replace('Z', '+00:00'))
                         for key in ('startedAt', 'finishedAt'))
        rstart, rfinish = (datetime.fromisoformat(research_bounds[key].replace('Z', '+00:00'))
                           for key in ('lastStartedAt', 'lastCompletedAt'))
        within = start <= rstart <= rfinish <= finish
    def rss(value):
        return value if type(value) in (int, float) and 0 <= value <= 65536 and math.isfinite(value) else None
    return {'schemaVersion': 'argus-collect-private-runtime-v1',
        'available': any(row['cpuSeconds'] is not None or row['elapsedSeconds'] is not None
                         for row in outcomes.values()), 'scope': 'LATEST_GLOBAL_RESEARCH_OBSERVATION',
        'expectedCollection': bounds, 'observedCollection': current,
        'collectionTimingBoundsMatch': bool(all(bounds.values()) and all(
            bounds[key] == current.get(key) for key in bounds)),
        'researchWindowWithinExpectedCollection': within,
        'research': {**research_bounds, 'outcomes': outcomes,
            'status': research.get('status') if research.get('status') in
                ('NOT_RUN', 'RUNNING', 'AVAILABLE', 'PARTIAL', 'FAILED') else None,
            'persistenceStatus': 'VERIFIED' if research.get('persistenceStatus') == 'VERIFIED' else None},
        'currentRssMib': rss(body.get('currentRssMib')), 'peakRssMib': rss(body.get('peakRssMib')),
        'memoryObservation': _private_memory_record(body)}


def _private_memory_record(body):
    """Closed OS/startup scalars from the already existing single GET."""
    def mapping(value):
        return value if isinstance(value, dict) else {}
    def number(value):
        return value if type(value) is int and 0 <= value < 2**63 else None
    def resident_mib(value):
        value = number(value)
        return value if value is not None and value <= 65536 else None
    def hex_id(value, length):
        return value if type(value) is str and len(value) == length and all(
            c in '0123456789abcdef' for c in value) else None
    operations = mapping(body.get('operationAttribution'))
    sample = mapping(operations.get('currentMemory'))
    process = mapping(sample.get('process'))
    group = mapping(sample.get('cgroup'))
    group_stat = mapping(group.get('stat'))
    events = mapping(group.get('events'))
    allocator = mapping(sample.get('allocatorMetrics'))
    identity = mapping(operations.get('processIdentity'))
    restore = mapping(operations.get('startupRestore'))
    policy = mapping(mapping(body.get('allocatorReclaim')).get('startupPolicy'))
    python = mapping(policy.get('pythonAllocator'))
    startup_rss = mapping(body.get('startupRss'))
    name = python.get('allocatorName')
    version = policy.get('backendVersion')
    valid_version = (type(version) is str and len(version) <= 30
                     and len(version.split('.')) == 3
                     and all(part.isascii() and part.isdigit() for part in version.split('.')))
    return {'schemaVersion': 'argus-private-memory-observation-v1',
        'capturedAt': _private_stamp(sample.get('capturedAt')),
        'backendSha': hex_id(policy.get('backendBuildSha'), 40),
        'backendVersion': version if valid_version else None,
        'processInstanceId': hex_id(identity.get('instanceId'), 32), 'pid': number(identity.get('pid')),
        'swapBytes': number(mapping(sample.get('smapsRollup')).get('swapBytes')),
        'restoration': {
            'state': restore.get('state') if restore.get('state') in
                ('bootstrapping', 'loading_local', 'loading_remote', 'reconciling', 'ready', 'ready_degraded', 'failed_safe') else None,
            'outcome': restore.get('outcome') if restore.get('outcome') in
                ('restored', 'no_prior_state', 'corrupt_last_known_good', 'persistent_storage_unavailable') else None,
            'integrityStatus': restore.get('integrityStatus') if restore.get('integrityStatus') in
                ('ok', 'unknown', 'corrupt_ignored') else None,
            **{key: _private_stamp(restore.get(key)) for key in ('startedAt', 'completedAt', 'lastRestoreAt')}},
        'allocatorName': name if name in ('malloc', 'pymalloc', 'malloc_debug', 'pymalloc_debug', 'UNAVAILABLE') else None,
        'startupRssMib': {key: resident_mib(startup_rss.get(key)) for key in ('beforeRestoreMib', 'afterRestoreMib')},
        'process': {key: number(process.get(key)) for key in ('vmRssBytes', 'vmHwmBytes', 'rssAnonBytes', 'rssFileBytes')},
        'cgroup': {**{key: number(group.get(key)) for key in ('memoryCurrentBytes', 'memoryPeakBytes', 'memoryMaxBytes')},
                   'stat': {key: number(group_stat.get(key)) for key in ('anon', 'file', 'kernel')},
                   'events': {key: number(events.get(key)) for key in ('low', 'high', 'max', 'oom', 'oom_kill', 'oom_group_kill')}},
        'allocator': {key: number(allocator.get(key)) for key in ('arenaBytes', 'allocatedBytes', 'freeBytes', 'mmapBytes')}}


def _capture_private_runtime(*, base, headers, expected, request, clock, deadline, sink):
    unavailable = {'schemaVersion': 'argus-collect-private-runtime-v1', 'available': False}
    value = {**unavailable, 'errorClass': 'runtime_budget_exhausted'}
    try:
        remaining = deadline - clock()
        if remaining > 0:
            code, raw = request(url=base.rstrip('/') + '/api/argus/admin/memory-attribution',
                method='GET', headers=headers, data=None, timeout=min(15, remaining))
            value = {**unavailable, 'errorClass': 'runtime_response_unavailable'}
            if 200 <= code < 300 and len(raw) <= 1024 * 1024:
                value = private_runtime_record(json.loads(raw), expected)
    except (OSError, URLError, TimeoutError, ValueError, TypeError):
        value = {**unavailable, 'errorClass': 'runtime_transport_or_json_error'}
    try:
        sink(value)
    except Exception:
        # Auxiliary readback cannot retry or alter the completed collection.
        pass


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
        private_timing=None, private_runtime=None) -> dict:
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
                    private_timing(private_timing_record(body, include_run_context=True))
                if body["status"] in ("done", "failed"):
                    # Persist only bounded status/counts, no provider payloads.
                    result = body.get("result") or {}
                    failed_feeds = result.get("failedFeeds") or []
                    all_feeds_failed = bool(result.get("feeds")) and len(failed_feeds) >= result["feeds"]
                    if private_runtime is not None:
                        _capture_private_runtime(base=base, headers=headers, expected=body,
                            request=request, clock=clock, deadline=deadline, sink=private_runtime)
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
    runtime_saved = {'ok': False, 'available': False}
    def observe(value):
        try:
            save_private_timing(args.private_timing_output, value)
            saved.update(ok=True, available=value['available'])
        except (OSError, ValueError):
            saved.update(ok=False, available=False)
    def observe_runtime(value):
        try:
            path = args.private_timing_output.with_name(args.private_timing_output.stem + '-runtime.json')
            save_private_timing(path, value)
            runtime_saved.update(ok=True, available=value['available'])
        except (OSError, ValueError):
            runtime_saved.update(ok=False, available=False)
    result = run(base=args.base, token=os.environ.get("ARGUS_ADMIN_TOKEN", ""), timeout=args.timeout,
                 private_timing=observe if args.private_timing_output else None,
                 private_runtime=observe_runtime if args.private_timing_output else None)
    if args.private_timing_output:
        result.update(privateTimingSaved=saved['ok'], privateTimingAvailable=saved['available'])
        result.update(privateRuntimeSaved=runtime_saved['ok'], privateRuntimeAvailable=runtime_saved['available'])
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
