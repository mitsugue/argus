#!/usr/bin/env python3
"""Warm fixed ARGUS readers with the existing server-only operational credential.

Only fixed paths on the established backend are eligible. Neither response
bodies nor credentials are emitted; redirects and failed reads stop the job.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request

BACKEND = 'https://argus-backend-3j2m.onrender.com'
RUNTIME_PATHS = (
    '/api/argus/decision-evidence?symbols=1321,1306,SPY,QQQ',
    '/api/argus/important-events', '/api/argus/events',
    '/api/argus/dashboard-events', '/api/argus/market-ledger',
    '/api/argus/news-intelligence',
)
CHART_PATHS = tuple(
    '/api/argus/chart-intelligence?symbol=' + symbol + '&market=' + market + '&horizon=' + horizon
    for symbol, market in (('1321', 'JP'), ('1306', 'JP'), ('SPY', 'US'), ('QQQ', 'US'))
    for horizon in ('1D', '5D', '20D')
)


class WarmReadFailure(ValueError):
    """Only allowlisted diagnostics; never carry exception text or documents."""
    def __init__(self, index, *, kind, phase, elapsed_ms, status):
        super().__init__('warm_read_failed:' + str(index))
        self.diagnostic = {'index': index, 'kind': kind, 'phase': phase,
                           'elapsedMs': elapsed_ms}
        if type(status) is int and 100 <= status <= 599:
            self.diagnostic['httpStatus'] = status


def _failure_kind(error, phase, status):
    if isinstance(error, urllib.error.HTTPError):
        return 'HTTP_ERROR'
    if isinstance(error, TimeoutError) or (isinstance(error, urllib.error.URLError)
            and isinstance(error.reason, TimeoutError)):
        return 'TIMEOUT'
    if isinstance(error, urllib.error.URLError):
        return 'URL_ERROR'
    if phase == 'VALIDATE_RESPONSE':
        return 'HTTP_ERROR' if status != 200 else 'UNEXPECTED_RESPONSE_URL'
    if isinstance(error, OSError):
        return 'TRANSPORT_ERROR'
    return 'INTERNAL_ERROR'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def warm(group, token, *, open_request=None, now=time.monotonic):
    if group not in ('runtime', 'charts') or not token:
        raise ValueError('warm_configuration')
    paths = RUNTIME_PATHS if group == 'runtime' else CHART_PATHS
    open_request = open_request or urllib.request.build_opener(NoRedirect()).open
    results = []
    for index, path in enumerate(paths):
        started = now()
        phase, status = 'OPEN', None
        try:
            request = urllib.request.Request(BACKEND + path, method='GET', headers={
                'X-ARGUS-ADMIN-TOKEN': token, 'Accept': 'application/json',
                'Cache-Control': 'no-store',
            })
            with open_request(request, timeout=120) as response:
                phase = 'VALIDATE_RESPONSE'
                status = int(response.status)
                if status != 200 or response.geturl() != BACKEND + path:
                    raise ValueError('warm_response')
                phase = 'DRAIN_BODY'
                # Drain without retaining large market documents in memory.
                while response.read(65536):
                    pass
            results.append({'index': index, 'status': status,
                            'elapsedMs': round((now() - started) * 1000)})
        except Exception as error:
            # urllib errors may include request/header/body values. Classify
            # types and numeric status only, never str(error), headers or URLs.
            kind = _failure_kind(error, phase, status)
            if isinstance(error, urllib.error.HTTPError):
                status = error.code
            raise WarmReadFailure(index, kind=kind, phase=phase,
                elapsed_ms=max(0, round((now() - started) * 1000)), status=status) from None
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', required=True, choices=('runtime', 'charts'))
    args = parser.parse_args()
    try:
        results = warm(args.group, os.environ.get('ARGUS_ADMIN_TOKEN', ''))
    except ValueError as error:
        result = {'status': 'failed', 'code': str(error)}
        if isinstance(error, WarmReadFailure):
            result['diagnostic'] = error.diagnostic
        print(json.dumps(result))
        return 1
    print(json.dumps({'status': 'completed', 'reads': results}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
