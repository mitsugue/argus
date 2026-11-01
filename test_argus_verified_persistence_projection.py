"""Read-only worker projection keeps verification and owned public APIs."""
import copy
import json

import pytest

import argus_market_artifact_store as artifacts
import argus_persistent_storage as storage
import argus_verified_snapshot as snapshots
from test_argus_verified_snapshot import boundary_store, candidate, payload


def legacy_hash(value):
    return snapshots._sha(snapshots.normalize_store(value))


@pytest.mark.parametrize('damage', [None, 'payload', 'key', 'future', 'schema'])
def test_projection_retains_all_normalization_and_digest_checks(damage):
    source = boundary_store()
    key = next(iter(source['current']))
    row = source['current'][key]
    if damage == 'payload': row['payload']['indicators']['bars'][0]['close'] = 999
    elif damage == 'key': source['current']['wrong'] = source['current'].pop(key)
    elif damage == 'future': row['generatedAt'] = '2099-01-01T00:00:00Z'
    elif damage == 'schema': row['schemaVersion'] = 'unsupported'
    original = copy.deepcopy(source)
    view = snapshots._normalize_store_shared(source)
    owned = snapshots.normalize_store(source)
    assert type(view) is dict
    assert not snapshots._has_normalized_store_provenance(view)
    assert view == owned
    expected = legacy_hash(source)
    assert snapshots._state_hash_for_persistence(source) == expected
    assert snapshots._state_hash_for_persistence(view) == expected
    assert snapshots.state_hash(source) == expected
    assert source == original
    if damage is not None:
        assert key not in view['current']


@pytest.mark.parametrize('value', [
    {'value': '日本株 🌐 quote"\\\n'},
    {'value': [None, True, False, -0.0, 1e-100, 1e100]},
    {'value': ('tuple', {2: 'two', 1: 'one'})},
])
def test_history_codec_and_order_match_original_hash(value):
    source = {'history': [value, {'last': 1}]}
    original = copy.deepcopy(source)
    assert snapshots._state_hash_for_persistence(source) == legacy_hash(source)
    assert source == original
    source['history'].reverse()
    assert snapshots._state_hash_for_persistence(source) == legacy_hash(source)


@pytest.mark.parametrize('damage', ['nan', 'infinity', 'unsupported', 'cycle', 'surrogate'])
def test_projection_hash_keeps_original_encoding_rejections(damage):
    row = {'value': 1.25}
    if damage == 'nan': row['value'] = float('nan')
    elif damage == 'infinity': row['value'] = float('inf')
    elif damage == 'unsupported': row['value'] = object()
    elif damage == 'cycle': row['value'] = row
    else: row['value'] = '\ud800'
    source = {'history': [row]}
    with pytest.raises((ValueError, TypeError, UnicodeEncodeError, RecursionError)) as original:
        legacy_hash(source)
    with pytest.raises(type(original.value)):
        snapshots._state_hash_for_persistence(source)


def test_every_hash_reverifies_snapshots_and_never_trusts_projection(monkeypatch):
    source = boundary_store()
    view = snapshots._normalize_store_shared(source)
    original_verify = snapshots.verify_snapshot
    calls = []
    def verify(value, **kwargs):
        calls.append(value)
        return original_verify(value, **kwargs)
    monkeypatch.setattr(snapshots, 'verify_snapshot', verify)
    first = snapshots._state_hash_for_persistence(view)
    assert len(calls) == len(source['current'])
    next(iter(view['current'].values()))['payloadHash'] = 'corrupted'
    second = snapshots._state_hash_for_persistence(view)
    assert len(calls) == 2 * len(source['current'])
    assert first != second
    assert second == snapshots.state_hash(view)


def test_default_owned_normalization_and_untrusted_fallback_are_unchanged():
    source = boundary_store()
    owned = snapshots.normalize_store(source)
    first = next(iter(source['current']))
    assert snapshots._has_normalized_store_provenance(owned)
    owned['current'][first]['payload']['indicators']['bars'][0]['close'] = 999
    assert source['current'][first]['payload']['indicators']['bars'][0]['close'] != 999
    view = snapshots._normalize_store_shared(source)
    events = []
    expected = snapshots.state_hash(source)
    assert snapshots.state_hash_normalized(view,
        diagnostic_observer=lambda phase, data: events.append((phase, data))) == expected
    assert events[0] == ('normalized_input_fallback', {'reason':'untrusted_provenance'})


def test_observer_phase_order_and_hostile_callback_do_not_change_truth():
    source = boundary_store()
    original = copy.deepcopy(source)
    events = []
    def observe(phase, data):
        events.append((phase, copy.deepcopy(data)))
        data['secret'] = 'observer-only'
        raise RuntimeError('observer failure')
    assert snapshots._state_hash_for_persistence(source,
        diagnostic_observer=observe) == legacy_hash(source)
    assert [phase for phase, _ in events] == [
        'hash_enter', 'internal_normalize_complete', 'stable_tree_ready',
        'canonical_string_ready', 'utf8_bytes_ready', 'hash_complete']
    assert source == original
    assert 'observer-only' not in json.dumps(events)


def test_artifact_bytes_and_full_restore_equal_owned_copy(tmp_path):
    source = boundary_store()
    before = copy.deepcopy(source)
    hashes = []
    for mode in ('owned', 'projection'):
        view = snapshots.normalize_store(source) if mode == 'owned' else snapshots._normalize_store_shared(source)
        digest = snapshots.state_hash_normalized(view) if mode == 'owned' else snapshots._state_hash_for_persistence(view)
        root = str(tmp_path/mode)
        artifacts.write_if_changed(root, 'verifiedViewSnapshots', view,
            state_hash=digest, now_iso='2026-07-23T07:00:00Z', last_state_hash=None,
            atomic_write_json=storage.atomic_write_json)
        from pathlib import Path
        hashes.append(Path(artifacts.path_for(root, 'verifiedViewSnapshots')).read_bytes())
        loaded = artifacts.load(root, 'verifiedViewSnapshots')['payload']
        assert loaded == view
        assert snapshots.state_hash(loaded) == digest
    assert hashes[0] == hashes[1]
    assert source == before


def test_publication_replaces_pointers_without_mutating_pinned_write(tmp_path):
    first = candidate()
    key = snapshots.snapshot_key(first['kind'], first['instrument'], first['horizon'])
    source = snapshots.empty_store()
    source['current'][key] = first
    source['lastPublishedAt'] = first['verifiedAt']
    view = snapshots._normalize_store_shared(source)
    before = copy.deepcopy(view)
    digest = snapshots._state_hash_for_persistence(view)
    second = candidate(dataset_hash='data-b', body=payload(dataset_hash='data-b'),
                       generated_at='2026-07-23T06:02:00Z')
    def write(path, value, **kwargs):
        updated, status = snapshots.publish_atomic(source, second)
        assert status == 'published'
        source.clear()
        source.update(updated)
        return storage.atomic_write_json(path, value, **kwargs)
    artifacts.write_if_changed(str(tmp_path), 'verifiedViewSnapshots', view,
        state_hash=digest, now_iso='2026-07-23T07:00:00Z', last_state_hash=None,
        atomic_write_json=write)
    assert view == before
    assert source['current'][key] == second
    loaded = artifacts.load(str(tmp_path), 'verifiedViewSnapshots')['payload']
    assert loaded == before
    assert snapshots.state_hash(loaded) == digest
