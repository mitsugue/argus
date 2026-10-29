#!/usr/bin/env python3
"""Read the existing event snapshot with bounded startup tolerance; never log its body."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


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
                raw = response.read(8 * 1024 * 1024 + 1)
            if last_status == 200:
                if len(raw) > 8 * 1024 * 1024:
                    return {'status': 'failed', 'errorClass': 'snapshot_too_large', 'attempts': attempts}
                value = json.loads(raw)
                if not isinstance(value, dict):
                    return {'status': 'failed', 'errorClass': 'snapshot_invalid', 'attempts': attempts}
                count = value.get('activeCount', 0)
                if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100000:
                    return {'status': 'failed', 'errorClass': 'snapshot_invalid', 'attempts': attempts}
                output.write_bytes(raw)
                return {'status': 'done', 'activeCount': count, 'attempts': attempts}
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
    result = read_snapshot(url='https://argus-backend-3j2m.onrender.com/api/argus/event-snapshot',
                           token=os.environ.get('ARGUS_ADMIN_TOKEN', ''),
                           output=Path(os.environ['RUNNER_TEMP']) / 'snap.json')
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] == 'done':
        with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as handle:
            handle.write('ACTIVE=' + str(result['activeCount']) + '\n')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
