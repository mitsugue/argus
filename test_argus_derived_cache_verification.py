"""Bounded read-back retains semantic checks and distrusts writer receipts."""
from copy import deepcopy
import hashlib
import json
import os

import pytest

import argus_index_research_cache as research
import argus_market_artifact_store as artifacts
import argus_persistent_storage as storage
import jp_market_features as features

AT = '2026-08-01T12:00:00Z'
METHOD = 'b' * 64


@pytest.mark.parametrize('value', [
    {'history': {'features': [{'value': -0.0, 'label': '日本株\\\"\n'},
                               {'value': 1.2345678901234567, 'nested': [None, True]}]}},
    {'tuple': (1, {'integerKeys': {2: 'two', 1: 'one'}})},
    [{}, [], {'numeric': [1e-200, 1e200]}],
])
def test_nested_cache_digest_keeps_every_legacy_canonical_byte(value):
    expected = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    assert features._history_digest(value) == research.digest(value) == expected
    assert artifacts.payload_sha256(value) == expected
    assert artifacts.payload_sha256(value, depth=3) == expected


@pytest.mark.parametrize('damage', ['nan', 'infinity', 'mixed_keys', 'cycle', 'unsupported'])
def test_nested_cache_digest_retains_legacy_rejections(damage):
    value = {'history': {'features': [{'value': 1.25}]}}
    row = value['history']['features'][0]
    if damage == 'nan': row['value'] = float('nan')
    elif damage == 'infinity': row['value'] = float('inf')
    elif damage == 'mixed_keys': row[1] = 'one'
    elif damage == 'cycle': row['cycle'] = value
    else: row['value'] = object()
    with pytest.raises((ValueError, TypeError)) as legacy:
        json.dumps(value, sort_keys=True, ensure_ascii=False,
                   allow_nan=False, separators=(',', ':'))
    for calculate in (features._history_digest, research.digest):
        with pytest.raises(type(legacy.value)):
            calculate(value)


def feature_history():
    return dict(schemaVersion='jp-market-feature-history-v1', status='AVAILABLE',
        inputIdentity='a' * 64, cutoffCount=1, historicalVintageVerified=False,
        actionAuthority=False, automaticAiCalls=0, firstCutoff=AT, lastCutoff=AT,
        lastSuccessfulCalculationAt=AT, features=[{'value': 1.25, 'label': '日本株'}],
        conditions=[])


def report_document():
    key = 'comparison:N225:5'
    return research.envelope({key: research.record(key,
        {'comparison': {'values': [1.25, -0.0], 'policy': ('a', 'b')}},
        method=METHOD, at=AT)})


def test_independent_digest_matches_writer_and_unchanged_file(tmp_path):
    doc = report_document()
    original = deepcopy(doc)
    expected = hashlib.sha256(json.dumps(doc, sort_keys=True,
        ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    assert artifacts.payload_sha256(doc) == expected
    path = tmp_path / 'cache.json'
    result = storage.atomic_write_json(str(path), doc, maximum_bytes=research.MAX_BYTES,
                                      file_mode=0o600)
    assert result['snapshotHash'] == expected
    artifacts.verify_file_digest(path, expected, maximum_bytes=research.MAX_BYTES)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert doc == original
    restored, _ = research.load_with_calibration(path, method=METHOD, now=AT)
    assert restored == doc['records']
    next(iter(restored.values()))['payload']['comparison']['values'][0] = 999
    assert doc == original


@pytest.mark.parametrize('damage', ['digest', 'size', 'symlink', 'replacement'])
def test_installed_file_is_checked_independently(tmp_path, monkeypatch, damage):
    path = tmp_path / 'cache.json'
    path.write_bytes(b'{"value":1}')
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    maximum = 100
    if damage == 'digest':
        path.write_bytes(b'{"value":2}')
    elif damage == 'size':
        maximum = 3
    elif damage == 'symlink':
        target = tmp_path / 'other.json'
        path.rename(target)
        path.symlink_to(target)
    else:
        original_stat = artifacts.os.stat
        def replace_before_final_check(name, **kwargs):
            other = tmp_path / 'replacement.json'
            other.write_bytes(b'{"value":1}')
            os.replace(other, path)
            return original_stat(name, **kwargs)
        monkeypatch.setattr(artifacts.os, 'stat', replace_before_final_check)
    with pytest.raises((ValueError, OSError)):
        artifacts.verify_file_digest(path, expected, maximum_bytes=maximum)


@pytest.mark.parametrize('damage', ['schema', 'body', 'record_hash', 'future', 'method'])
def test_write_admission_retains_all_record_checks(tmp_path, damage):
    doc = report_document()
    record = next(iter(doc['records'].values()))
    if damage == 'schema': doc['schemaVersion'] = 'other'
    elif damage == 'body': record['payload']['comparison']['values'][0] = 999
    elif damage == 'record_hash':
        record['sha256'] = '0' * 64
        doc['sha256'] = research.digest(doc['records'])
    method = 'other' if damage == 'method' else METHOD
    now = '2026-07-31T12:00:00Z' if damage == 'future' else AT
    path = tmp_path / 'cache.json'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        research.validate_for_persistence(doc, method=method, now=now)
    if damage in ('method', 'future'):
        assert research.load(path, method=method, now=now) == {}
    else:
        with pytest.raises(ValueError): research.load(path, method=method, now=now)


@pytest.mark.parametrize('damage', ['tuple', 'key', 'future', 'digest', 'method'])
def test_feature_write_admission_keeps_parsed_equality_and_future_checks(damage):
    history = feature_history()
    if damage == 'tuple': history['features'][0]['values'] = (1, 2)
    if damage == 'key': history['features'][0][1] = 'one'
    # Non-string mixed keys cannot be canonically sorted in either path.
    if damage == 'key':
        with pytest.raises((ValueError, TypeError)):
            features.history_cache_envelope(history, method=METHOD)
        return
    doc = features.history_cache_envelope(history, method=METHOD)
    if damage == 'digest': doc['sha256'] = '0' * 64
    now = '2026-07-31T12:00:00Z' if damage == 'future' else AT
    if damage == 'method':
        assert features.validate_history_cache(doc, method='c' * 64, now=now) is None
    else:
        with pytest.raises(ValueError):
            features.validate_history_cache(doc, method=METHOD, now=now)


