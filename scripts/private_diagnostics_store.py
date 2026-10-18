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
import urllib.error
import urllib.request

REPOSITORY = 'mitsugue/argus-l2b-private'
PREFIX = 'diagnostics'
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 20
_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')


def destinations(kind, run_id, files):
    if not _NAME.match(kind or '') or not re.fullmatch(r'[0-9]{1,20}', str(run_id or '')):
        raise ValueError('invalid_diagnostics_destination')
    if not files or len(files) > MAX_FILES:
        raise ValueError('diagnostics_file_count')
    out = []
    for path in files:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('diagnostics_file_invalid')
        name = path.name
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', name):
            raise ValueError('diagnostics_file_name')
        out.append((path, f'{PREFIX}/{kind}/{run_id}/{name}'))
    return out


def store(kind, run_id, files, token, *, opener=urllib.request.urlopen):
    if not token:
        raise ValueError('private_token_missing')
    for path, destination in destinations(kind, run_id, files):
        body = json.dumps({'message': f'diagnostics {kind} {run_id}', 'branch': 'main',
                           'content': base64.b64encode(path.read_bytes()).decode()}).encode()
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/contents/{destination}',
            data=body, method='PUT', headers={'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with opener(request, timeout=60) as response:
                if response.status not in (200, 201):
                    raise ValueError('private_store_failed')
        except urllib.error.HTTPError:
            raise ValueError('private_store_failed') from None
    return len(files)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args(argv)
    files = []
    for raw in args.paths:
        path = Path(raw)
        files.extend(sorted(p for p in path.iterdir() if p.is_file()) if path.is_dir() else [path])
    try:
        count = store(args.kind, args.run_id, [f for f in files if f.exists()],
                      os.environ.get('PRIVATE_DIAGNOSTICS_TOKEN', ''))
    except (ValueError, OSError) as exc:
        print(f'private diagnostics: not stored ({exc})')
        return 1
    print(f'private diagnostics: stored {count} file(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
