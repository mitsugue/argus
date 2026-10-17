"""Bounded public readiness check before scheduled macro work; no POST replay."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error

try:
    from scripts.workflow_http import request_json, classify_response, SUCCESS
except ModuleNotFoundError:
    from workflow_http import request_json, classify_response, SUCCESS


def wait_ready(url: str) -> bool:
    for attempt in range(1, 6):
        retry = False
        reason = 'not_ready'
        try:
            code, raw = request_json(url=url, method='GET', timeout=20)
            result = classify_response(code, raw)
            body = result.get('body')
            valid = isinstance(body, dict) and body.get('schemaVersion') == 'argus-public-readiness-v1'
            if code == 200 and valid and result['outcome'] == SUCCESS \
                    and body.get('ready') is True and body.get('status') == 'ready':
                print(json.dumps({'status': 'ready', 'attempt': attempt}))
                return True
            retry = code in (408, 425, 500, 502, 503, 504) or (
                code == 200 and valid and body.get('status') == 'not_ready'
                and body.get('ready') is False)
            reason = 'not_ready' if code == 200 and valid else f'http_or_contract_{code}'
        except (urllib.error.URLError, OSError, TimeoutError):
            retry = True
            reason = 'transport_failure'
        print(json.dumps({'status': 'waiting' if retry else 'failed',
                          'attempt': attempt, 'reason': reason}))
        if not retry or attempt == 5:
            return False
        time.sleep(30)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    return 0 if wait_ready(args.url) else 1


if __name__ == '__main__':
    raise SystemExit(main())
