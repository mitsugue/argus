"""Put diagnostic files in the owner's private repository (2026-10-18).

The public repository's run logs and artifacts can be read by anyone, so the
production snapshots behind these diagnostics never go there. This prints
only how many files were stored, never their contents or the response.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

REPOSITORY = 'mitsugue/argus-l2b-private'
PREFIX = 'diagnostics'
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 20
_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')


def destinations(kind, run_id, files, *, run_attempt=1):
    if not _NAME.match(kind or '') or not re.fullmatch(r'[0-9]{1,20}', str(run_id or '')):
        raise ValueError('invalid_diagnostics_destination')
    if not files or len(files) > MAX_FILES:
        raise ValueError('diagnostics_file_count')
    if type(run_attempt) not in (int, str) or not re.fullmatch(r'[1-9][0-9]{0,8}', str(run_attempt)):
        raise ValueError('invalid_diagnostics_attempt')
    prefix = f'{PREFIX}/{kind}/{run_id}'
    if int(run_attempt) > 1:
        prefix += f'/attempt-{run_attempt}'
    out = []
    for path in files:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('diagnostics_file_invalid')
        name = path.name
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', name):
            raise ValueError('diagnostics_file_name')
        out.append((path, f'{prefix}/{name}'))
    return out


class PrivateStoreError(ValueError):
    def __init__(self, failure_code):
        super().__init__('private_store_failed')
        self.failure_code = failure_code


def http_failure_code(status):
    if type(status) is int and status in (400, 401, 403, 404, 409, 422, 429):
        return f'HTTP_{status}'
    if type(status) is int and 500 <= status <= 599:
        return 'HTTP_5XX'
    return 'HTTP_OTHER'


def _remaining(deadline, maximum=60):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PrivateStoreError('DEADLINE')
    return min(maximum, remaining)


def _create(request, opener, deadline):
    try:
        with opener(request, timeout=_remaining(deadline)) as response:
            if response.status not in (200, 201):
                raise PrivateStoreError(http_failure_code(response.status))
    except urllib.error.HTTPError as exc:
        raise PrivateStoreError(http_failure_code(exc.code)) from None


def _existing_after_conflict(request, raw, opener, deadline):
    headers = {key: value for key, value in request.header_items()
               if key.lower() in ('authorization', 'x-github-api-version')}
    headers['Accept'] = 'application/vnd.github.raw+json'
    current = urllib.request.Request(request.full_url + '?ref=main', headers=headers)
    try:
        with opener(current, timeout=_remaining(deadline, 15)) as response:
            if response.status == 404:
                return False
            if response.status != 200:
                raise PrivateStoreError(http_failure_code(response.status))
            existing = response.read(MAX_BYTES + 1)
            _remaining(deadline)
            if existing != raw:
                raise PrivateStoreError('IMMUTABLE_CONFLICT')
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise PrivateStoreError(http_failure_code(exc.code)) from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _open(request, *, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def store(kind, run_id, files, token, *, run_attempt=1, opener=_open):
    if not token:
        raise ValueError('private_token_missing')
    for path, destination in destinations(kind, run_id, files, run_attempt=run_attempt):
        deadline = time.monotonic() + 60
        raw = path.read_bytes()
        body = json.dumps({'message': f'diagnostics {kind} {run_id}', 'branch': 'main',
                           'content': base64.b64encode(raw).decode()}).encode()
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/contents/{destination}',
            data=body, method='PUT', headers={'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            _create(request, opener, deadline)
        except PrivateStoreError as exc:
            if exc.failure_code != 'HTTP_409':
                raise
            # Another writer can advance main between Contents API commits.
            # Resolve this observed conflict once, without a sha/overwrite PUT.
            if not _existing_after_conflict(request, raw, opener, deadline):
                _create(request, opener, deadline)
    return len(files)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--run-attempt', type=int,
                        default=os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args(argv)
    files = []
    for raw in args.paths:
        path = Path(raw)
        files.extend(sorted(p for p in path.iterdir() if p.is_file()) if path.is_dir() else [path])
    try:
        count = store(args.kind, args.run_id, [f for f in files if f.exists()],
                      os.environ.get('PRIVATE_DIAGNOSTICS_TOKEN', ''), run_attempt=args.run_attempt)
    except (ValueError, OSError) as exc:
        code = exc.failure_code if isinstance(exc, PrivateStoreError) else None
        if code is not None:
            print(f'private diagnostics: not stored (private_store_failed; {code})')
        else:
            known = {'invalid_diagnostics_destination', 'diagnostics_file_count',
                     'invalid_diagnostics_attempt', 'diagnostics_file_invalid',
                     'diagnostics_file_name', 'private_token_missing'}
            reason = str(exc) if isinstance(exc, ValueError) and str(exc) in known else (
                'private_transport_failed' if isinstance(exc, OSError) else 'private_store_failed')
            print(f'private diagnostics: not stored ({reason})')
        return 1
    print(f'private diagnostics: stored {count} file(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
