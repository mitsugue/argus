"""Weekly size check of the private history backup (2026-10-20).

Reads, with the private-repository token: the repository's on-disk size and
the v2/v3 manifests of the market-analysis history. Writes the numbers to a
local file (the workflow stores it in the private repository) and prints only
whether a threshold is crossed. Exit 1 when either v3 bound or the repository
reaches 70% (GitHub's recommended maximum on-disk size is 10 GB), so the
failure notice reaches the owner without anyone having to remember the date.

2026-10-21: the same weekly run also records the production's local copy of
the history (file size from the stat-only disk breakdown, the local form's
edition counts, and the persistent disk's free and required bytes), read once
from the owner-only diagnostic. It adds no threshold: the disk-free lamp is the
warning; this keeps the weekly series. A missing admin token or a failed read
is recorded as unmeasured, never as zero.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import argus_analysis_history_parts as v3  # noqa: E402

REPOSITORY = 'mitsugue/argus-l2b-private'
BACKEND = 'https://argus-backend-3j2m.onrender.com'
V2_STORED_LIMIT = 128 * 1024 * 1024


def _get(path, token, opener=urllib.request.urlopen):
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + path,
                                     headers={'Authorization': 'Bearer ' + token,
                                              'Accept': 'application/vnd.github+json'})
    try:
        with opener(request, timeout=30) as response:
            return json.loads(response.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _file(path, token, opener=urllib.request.urlopen):
    value = _get('/contents/' + path, token, opener)
    if value is None:
        return None
    return base64.b64decode(value['content'].replace('\n', ''))


def measure(token, opener=urllib.request.urlopen):
    metadata = _get('', token, opener) or {}
    repository_bytes = int(metadata.get('size') or 0) * 1024
    out = {'repositoryBytes': repository_bytes, 'v3': None, 'v2': None}
    head = _file(v3.PREFIX + '/head.json', token, opener)
    if head is not None:
        manifest = v3.manifest_from(_file(v3.PREFIX + '/manifests/' + json.loads(head)['manifestSha256'] + '.json',
                                          token, opener))
        out['v3'] = {'counts': manifest['counts'], **v3.capacity(manifest, repository_bytes)}
    old = _file('market-analysis/v2/head.json', token, opener)
    if old is not None:
        manifest = json.loads(_file('market-analysis/v2/manifests/' + json.loads(old)['manifestSha256'] + '.json',
                                    token, opener))
        out['v2'] = {'counts': manifest.get('counts'), 'storedBytes': manifest.get('storedBytes'),
                     'storedShare': round(manifest.get('storedBytes', 0) / V2_STORED_LIMIT, 4)}
    repository = v3.capacity(None, repository_bytes)
    out['repositoryShare'] = repository['repositoryShare']
    out['warning'] = bool(repository['repositoryWarning'] or (out['v3'] or {}).get('warning'))
    return out


def _admin(path, token, opener):
    request = urllib.request.Request(BACKEND + path, headers={'X-ARGUS-ADMIN-TOKEN': token})
    with opener(request, timeout=150) as response:
        return json.loads(response.read(16 * 1024 * 1024))


def measure_local(token, opener=urllib.request.urlopen):
    """The production's local history copy; counts and bytes only, no record body."""
    if not token:
        return {'measured': False, 'reason': 'admin_token_not_configured'}
    try:
        attribution = _admin('/api/argus/admin/memory-attribution?storage-groups=1', token, opener)
        operational = _admin('/api/argus/admin/diagnostics/operational', token, opener)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {'measured': False, 'reason': 'read_failed:' + type(exc).__name__}
    groups = ((attribution.get('storageAttribution') or {}).get('groups')) or {}
    database = groups.get('analysisHistoryDb') or {}
    form = attribution.get('analysisHistoryForm') or {}
    storage = operational.get('storage') or {}
    return {'measured': 'logicalBytes' in database,
            'analysisHistoryBytes': database.get('logicalBytes'),
            'analysisHistoryAllocatedBytes': database.get('allocatedBytes'),
            'views': form.get('views'), 'formStatus': form.get('status'),
            'skeletonBytes': form.get('skeletonBytes'), 'partStoredBytes': form.get('partStoredBytes'),
            'freeBytes': storage.get('freeBytes'), 'requiredFreeBytes': storage.get('requiredFreeBytes'),
            'totalBytes': storage.get('totalBytes')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    token = os.environ.get('PRIVATE_DIAGNOSTICS_TOKEN', '')
    if not token:
        print('history capacity: token not configured'); return 1
    result = measure(token)
    result['local'] = measure_local(os.environ.get('ARGUS_ADMIN_TOKEN', ''))
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print('history capacity: ' + ('OVER 70% — decide to thin, move or raise the bound' if result['warning']
                                  else 'within threshold'))
    return 1 if result['warning'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
