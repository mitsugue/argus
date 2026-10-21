"""2026-10-20: the weekly capacity check fails at 70% so the owner is told without remembering."""
import base64
import io
import json

import argus_analysis_history_parts as v3
from scripts import history_capacity_check as check


def opener_for(files, size_kb):
    def opener(request, timeout=None):
        assert request.headers['Authorization'] == 'Bearer test-only'
        path = request.full_url.split(check.REPOSITORY, 1)[1]
        if path == '':
            body = {'size': size_kb, 'private': True}
        elif path.startswith('/contents/') and path[len('/contents/'):] in files:
            body = {'content': base64.b64encode(files[path[len('/contents/'):]]).decode()}
        else:
            raise check.urllib.error.HTTPError(request.full_url, 404, 'missing', {}, None)
        return io.BytesIO(json.dumps(body).encode())
    return opener


def v3_files(stored):
    manifest = {'schemaVersion': v3.SCHEMA, 'scope': 'PUBLIC_MARKET', 'actionAuthority': False, 'codec': 'zlib',
                'segments': [], 'packs': [{'sha256': 'a' * 64, 'bytes': stored, 'rawBytes': stored * 4,
                                           'rawSha256': 'b' * 64, 'views': 1, 'outcomes': 0, 'parts': 1}],
                'counts': {'views': 1, 'outcomes': 0, 'parts': 1}, 'storedBytes': stored,
                'rawBytes': stored * 4, 'latestRecordId': 'c' * 64}
    raw = v3._encode(manifest); sha = v3._digest(raw)
    return {v3.PREFIX + '/head.json': json.dumps({'schemaVersion': v3.SCHEMA, 'manifestSha256': sha}).encode(),
            v3.PREFIX + '/manifests/' + sha + '.json': raw}


def test_small_backup_is_within_threshold(monkeypatch):
    result = check.measure('test-only', opener_for(v3_files(1000), size_kb=3_000_000))
    assert result['warning'] is False and result['v3']['counts']['views'] == 1
    assert result['repositoryBytes'] == 3_000_000 * 1024 and result['v2'] is None


def test_repository_over_seventy_percent_of_the_recommended_size_warns():
    size_kb = int(v3.REPOSITORY_RECOMMENDED_BYTES * 0.71 / 1024)
    assert check.measure('test-only', opener_for(v3_files(1000), size_kb))['warning'] is True


def test_v3_bound_over_seventy_percent_warns(monkeypatch):
    monkeypatch.setattr(v3, 'MAX_STORED_BYTES', 1300)
    assert check.measure('test-only', opener_for(v3_files(1000), size_kb=10))['warning'] is True


def test_no_token_is_a_failed_check_not_a_pass(monkeypatch, tmp_path):
    monkeypatch.delenv('PRIVATE_DIAGNOSTICS_TOKEN', raising=False)
    assert check.main(['--output', str(tmp_path / 'c.json')]) == 1


def admin_opener(attribution, operational, seen):
    def opener(request, timeout=None):
        assert request.headers['X-argus-admin-token'] == 'admin-test-only'
        seen.append(request.full_url.split(check.BACKEND, 1)[1])
        if 'memory-attribution' in request.full_url:
            return io.BytesIO(json.dumps(attribution).encode())
        return io.BytesIO(json.dumps(operational).encode())
    return opener


def test_local_history_size_is_recorded_from_the_owner_diagnostic():
    seen = []
    attribution = {'storageAttribution': {'groups': {'analysisHistoryDb': {'files': 1, 'logicalBytes': 170_000_000,
                                                                           'allocatedBytes': 171_000_000}}},
                   'analysisHistoryForm': {'views': 799, 'status': 'CONVERTED', 'skeletonBytes': 134, 'partStoredBytes': 23,
                                           'lastFailureReasons': []}}
    operational = {'storage': {'freeBytes': 13_000_000_000, 'requiredFreeBytes': 116_000_000, 'totalBytes': 20_000_000_000}}
    local = check.measure_local('admin-test-only', admin_opener(attribution, operational, seen))
    assert local['measured'] is True and local['analysisHistoryBytes'] == 170_000_000 and local['views'] == 799
    assert local['freeBytes'] == 13_000_000_000
    assert seen == ['/api/argus/admin/memory-attribution?storage-groups=1', '/api/argus/admin/diagnostics/operational']


def test_local_history_unmeasured_is_never_zero():
    assert check.measure_local('') == {'measured': False, 'reason': 'admin_token_not_configured'}
    def failing(request, timeout=None):
        raise check.urllib.error.URLError('down')
    assert check.measure_local('admin-test-only', failing)['measured'] is False
    missing = check.measure_local('admin-test-only', admin_opener({}, {}, []))
    assert missing['measured'] is False and missing['analysisHistoryBytes'] is None
