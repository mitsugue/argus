#!/usr/bin/env python3
"""Read the existing event snapshot with bounded startup tolerance; never log its body."""
from __future__ import annotations

import json
import argparse
import datetime as dt
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
LOG_FIELDS = ('eventId', 'eventType', 'symbol', 'market', 'severity', 'lifecycleState',
              'recommendedPosture', 'detectedAt', 'reasonJa')


def _validate(value):
    if not isinstance(value, dict) or value.get('schemaVersion') != 'event-store-v1':
        raise ValueError('snapshot_invalid')
    active, log, count = value.get('active'), value.get('log'), value.get('activeCount')
    if (not isinstance(active, list) or not isinstance(log, list) or len(log) > 200
            or type(count) is not int or not 0 <= count <= 100000 or count != len(active)
            or any(not isinstance(row, dict) for row in active + log)
            or not isinstance(value.get('snapshotAt'), str) or not value['snapshotAt']):
        raise ValueError('snapshot_invalid')
    return value


def _read(path):
    with path.open('rb') as handle:
        raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError('snapshot_too_large')
    return raw, _validate(json.loads(raw))


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def stage_snapshot(source, root, day):
    """Stage the existing private snapshot and append-only daily history, without network I/O.

    A timestamp-only poll does not replace the previous receipt. Full envelopes,
    including dossier revisions, remain in the snapshot; short daily rows retain
    their existing format. Empty startup state cannot clear the saved history.
    """
    if dt.date.fromisoformat(day).isoformat() != day:
        raise ValueError('day_invalid')
    target, daily = root / 'snapshot.json', root / 'log' / (day + '.jsonl')
    if any(p.is_symlink() for p in (source, root, root / 'log', target, daily)):
        raise ValueError('path_invalid')
    raw, value = _read(source)
    if not value['active'] and not value['log']:
        return {'status': 'empty', 'appendedRows': 0}
    semantic = lambda snap: {k: v for k, v in snap.items() if k != 'snapshotAt'}
    if target.exists() and _canonical(semantic(_read(target)[1])) == _canonical(semantic(value)):
        return {'status': 'unchanged', 'appendedRows': 0}
    seen, last_line = set(), ''
    if daily.exists():
        with daily.open(encoding='utf-8') as handle:
            for line in handle:
                last_line = line
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('history_invalid')
                seen.add(_canonical(row))
    rows = []
    for event in value['active'] + value['log']:
        row = _canonical({k: event.get(k) for k in LOG_FIELDS})
        if row not in seen:
            seen.add(row)
            rows.append(row)
    # Validate all inputs before changing either file. A failed staging step is
    # never committed/pushed by the workflow; existing daily bytes are not edited.
    _canonical(value)
    daily.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with daily.open('a', encoding='utf-8') as handle:
            if last_line and not last_line.endswith('\n'):
                handle.write('\n')
            handle.write('\n'.join(rows) + '\n')
    target.write_bytes(raw)
    return {'status': 'changed', 'activeCount': value['activeCount'],
            'logCount': len(value['log']), 'appendedRows': len(rows)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_open(req, *, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout)


def read_snapshot(*, url, token, output, timeout=240, request=_safe_open,
                  clock=time.monotonic, sleep=time.sleep):
    if not token:
        return {'status': 'failed', 'errorClass': 'admin_token_missing', 'attempts': 0}
    deadline = clock() + timeout
    attempts = 0
    last_status = None
    while clock() < deadline:
        attempts += 1
        req = urllib.request.Request(url, headers={'X-ARGUS-ADMIN-TOKEN': token})
        try:
            with request(req, timeout=max(1, min(15, deadline - clock()))) as response:
                last_status = response.status
                raw = response.read(MAX_SNAPSHOT_BYTES + 1)
            if last_status == 200:
                if len(raw) > MAX_SNAPSHOT_BYTES:
                    return {'status': 'failed', 'errorClass': 'snapshot_too_large', 'attempts': attempts}
                value = _validate(json.loads(raw))
                _canonical(value)
                count = value['activeCount']
                output.write_bytes(raw)
                return {'status': 'done', 'activeCount': count, 'logCount': len(value['log']),
                        'attempts': attempts}
        except urllib.error.HTTPError as exc:
            last_status = exc.code
        except (OSError, urllib.error.URLError, TimeoutError):
            last_status = None
        except (UnicodeDecodeError, ValueError):
            return {'status': 'failed', 'errorClass': 'snapshot_invalid', 'attempts': attempts}
        if last_status is not None and (300 <= last_status < 400 or 400 <= last_status < 500 and last_status != 429):
            return {'status': 'failed', 'errorClass': 'snapshot_rejected',
                    'httpStatus': last_status, 'attempts': attempts}
        sleep(max(0, min(15, deadline - clock())))
    return {'status': 'failed', 'errorClass': 'snapshot_timeout',
            'httpStatus': last_status, 'attempts': attempts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--ledger-root', type=Path, default=Path('ledger/events'))
    parser.add_argument('--day')
    args = parser.parse_args()
    if args.stage:
        try:
            result = stage_snapshot(args.stage, args.ledger_root, args.day or '')
        except (OSError, UnicodeError, ValueError):
            print(json.dumps({'status': 'failed', 'errorClass': 'snapshot_stage_invalid'}))
            return 1
        print(json.dumps(result))
        return 0
    result = read_snapshot(url='https://argus-backend-3j2m.onrender.com/api/argus/event-snapshot',
                           token=os.environ.get('ARGUS_ADMIN_TOKEN', ''),
                           output=Path(os.environ['RUNNER_TEMP']) / 'snap.json')
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] == 'done':
        with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as handle:
            handle.write('ACTIVE=' + str(result['activeCount']) + '\n')
            handle.write('STATE_ITEMS=' + str(result['activeCount'] + result['logCount']) + '\n')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
