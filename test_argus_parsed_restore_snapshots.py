"""Private parsed-input lifetime keeps the original per-pointer restore truth."""
import copy
import weakref

import pytest

import argus_verified_snapshot as snapshots
from test_argus_verified_snapshot import candidate, payload


AT = '2026-07-23T07:00:00Z'


def store_of(*rows):
    store = snapshots.empty_store()
    for row in rows:
        key = snapshots.snapshot_key(row['kind'], row['instrument'], row['horizon'])
        store['current'][key] = row
    store['history'] = [{'key':'retained', 'snapshotId':'old', 'replacedAt':AT}]
    store['lastPublishedAt'] = AT
    return store


def old_restore(local, incoming):
    out = copy.deepcopy(local)
    for row in snapshots.normalize_store(incoming)['current'].values():
        out, _ = snapshots.publish_atomic(out, row, now_iso=AT)
    return out


def consume_restore(local, incoming):
    out = copy.deepcopy(local)
    for row in snapshots._consume_parsed_restore_snapshots(incoming):
        out, _ = snapshots.publish_atomic(out, row, now_iso=AT)
        key = snapshots.snapshot_key(row['kind'], row['instrument'], row['horizon'])
        if out['current'].get(key, {}).get('snapshotId') == row['snapshotId']:
            assert out['current'][key] is not row
            assert out['current'][key]['payload'] is not row['payload']
    return out


def test_complete_lookup_is_checked_before_private_parse_is_consumed(monkeypatch):
    parsed = store_of(candidate(), candidate(symbol='SPY'))
    parsed['current']['corrupt'] = {'schemaVersion':'invalid'}
    before = copy.deepcopy(parsed)
    seen = []
    verifier = snapshots.verify_snapshot
    def checked(value, **kwargs):
        assert parsed == before
        seen.append(value)
        return verifier(value, **kwargs)
    monkeypatch.setattr(snapshots, 'verify_snapshot', checked)
    iterator = snapshots._consume_parsed_restore_snapshots(parsed)
    first = next(iterator)
    assert len(seen) == 3
    assert first == next(iter(before['current'].values()))
    assert parsed['current'] == {}
    assert parsed['history'] == before['history']
    assert parsed['lastPublishedAt'] == before['lastPublishedAt']
    assert len(list(iterator)) == 1


def test_consumed_snapshot_is_released_before_restoration_finishes():
    class Tracked(dict):
        pass
    first = Tracked(candidate())
    reference = weakref.ref(first)
    parsed = store_of(first, candidate(symbol='SPY'), candidate(symbol='QQQ'))
    del first
    iterator = snapshots._consume_parsed_restore_snapshots(parsed)
    yielded = next(iterator)
    assert reference() is yielded
    del yielded
    following = next(iterator)
    assert reference() is None
    assert following['instrument'] == 'SPY'
    assert len(list(iterator)) == 1


@pytest.mark.parametrize('case', ['normal','older','quality','same','bad_hash','bad_key','future'])
def test_old_serialized_restore_oracle_and_source_metadata_are_preserved(case):
    local_row = candidate(generated_at='2026-07-23T06:03:00Z')
    row = candidate(generated_at='2026-07-23T06:04:00Z', dataset_hash='new')
    if case == 'older':
        row = candidate(generated_at='2026-07-23T06:01:00Z')
    elif case == 'quality':
        row = candidate(generated_at='2026-07-23T06:04:00Z', quality='partial')
    elif case == 'same':
        row = copy.deepcopy(local_row)
    elif case == 'bad_hash':
        row['payloadHash'] = 'corrupt'
    elif case == 'future':
        row = candidate(generated_at='2099-07-23T06:04:00Z')
    incoming = store_of(row, candidate(symbol='SPY'))
    if case == 'bad_key':
        incoming['current']['wrong'] = incoming['current'].pop(next(iter(incoming['current'])))
    original = copy.deepcopy(incoming)
    local = store_of(local_row)
    expected = old_restore(local, original)
    actual = consume_restore(local, incoming)
    assert actual == expected
    assert snapshots.state_hash(actual) == snapshots.state_hash(expected)
    assert incoming['current'] == {}
    assert incoming['history'] == original['history']
    assert local == store_of(local_row)


def test_numeric_json_readback_and_independent_destination_are_still_required():
    body = payload()
    body['precise'] = 123.123456789
    incoming = store_of(candidate(body=body))
    original = copy.deepcopy(incoming)
    actual = consume_restore(snapshots.empty_store(), incoming)
    assert actual == old_restore(snapshots.empty_store(), original)
    row = next(iter(actual['current'].values()))
    assert row['payload']['precise'] == 123.123456789
    row['payload']['indicators']['bars'][0]['close'] = 999
    assert next(iter(original['current'].values()))['payload']['indicators']['bars'][0]['close'] == 101.0


def test_original_order_keeps_current_limit_and_tie_behavior():
    incoming = store_of(*(candidate(symbol=f'S{number:02}') for number in range(snapshots.MAX_CURRENT+3)))
    original = copy.deepcopy(incoming)
    actual = consume_restore(snapshots.empty_store(), incoming)
    assert actual == old_restore(snapshots.empty_store(), original)
    assert len(actual['current']) == snapshots.MAX_CURRENT


@pytest.mark.parametrize('value', [None, [], 1, {}, {'current':None}])
def test_empty_or_nonmapping_private_parses_keep_empty_lookup_behavior(value):
    assert list(snapshots._consume_parsed_restore_snapshots(value)) == []


def test_validation_failure_does_not_consume_a_partial_parse():
    incoming = store_of(candidate())
    incoming['current']['cycle'] = {'schemaVersion':snapshots.SCHEMA_VERSION}
    # The original verifier's exception remains observable before any consume.
    from unittest import mock
    before = copy.deepcopy(incoming)
    with mock.patch.object(snapshots, 'verify_snapshot', side_effect=ValueError('verify_failed')):
        with pytest.raises(ValueError, match='verify_failed'):
            list(snapshots._consume_parsed_restore_snapshots(incoming))
    assert incoming == before
