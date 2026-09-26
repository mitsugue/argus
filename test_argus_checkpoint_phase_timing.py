"""Checkpoint timing stays bounded, private, and non-authoritative."""
import json
import threading
from unittest import mock

import pytest
import scanner
import argus_memory_attribution as memory
from test_argus_memory_attribution import _sample


@pytest.fixture
def recording(monkeypatch):
    recorder = memory.MemoryAttributionRecorder(4)
    recorder.begin('observed', {}, initial_sample=_sample(100))
    monkeypatch.setattr(scanner, '_MEMORY_ATTRIBUTION', recorder)
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, 'memoryAttributionRecordId', 'observed')
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, 'memoryAttributionThreadId', threading.get_ident())
    return recorder


def finish(recorder):
    return recorder.complete('observed')['metadata']


def test_timings_are_inclusive_accumulated_and_preserve_return_identity(recording):
    secret = {'private_payload': ['never serialize me']}
    inner = scanner._checkpoint_phase_timed('seal')(lambda value: value)
    outer = scanner._checkpoint_phase_timed('transaction')(lambda value: inner(value))
    with mock.patch.object(scanner.time, 'monotonic_ns', side_effect=[0, 1000, 4000, 9000, 10000, 15000]):
        assert outer(secret) is secret
        assert inner(secret) is secret
    metadata = finish(recording)
    assert metadata['checkpointTiming_transactionMicros'] == 9
    assert metadata['checkpointTiming_sealMicros'] == 8
    assert metadata['checkpointTiming_sealCount'] == 2
    assert metadata['checkpointTiming_sealFailures'] == 0
    assert 'private_payload' not in json.dumps(metadata)


def test_exception_identity_and_failed_count(recording):
    error = ValueError('sensitive exception text')
    @scanner._checkpoint_phase_timed('sidecar_verify')
    def failing():
        raise error
    with pytest.raises(ValueError) as raised:
        failing()
    assert raised.value is error
    metadata = finish(recording)
    assert metadata['checkpointTiming_sidecar_verifyFailures'] == 1
    assert 'sensitive' not in json.dumps(metadata)


@pytest.mark.parametrize('failure', ['clock', 'recorder'])
def test_diagnostic_failures_cannot_change_business_result_or_exception(recording, failure):
    target = scanner.time if failure == 'clock' else recording
    method = 'monotonic_ns' if failure == 'clock' else 'record_checkpoint_timing'
    value = object()
    error = RuntimeError('original')
    def fail():
        raise error
    with mock.patch.object(target, method, side_effect=OSError('diagnostic only')):
        assert scanner._checkpoint_phase_timed('seal')(lambda: value)() is value
        with pytest.raises(RuntimeError) as raised:
            scanner._checkpoint_phase_timed('seal')(fail)()
        assert raised.value is error


def test_other_thread_and_no_record_do_not_attribute(recording, monkeypatch):
    results = []
    decorated = scanner._checkpoint_phase_timed('seal')(lambda: 42)
    thread = threading.Thread(target=lambda: results.append(decorated()))
    thread.start(); thread.join()
    monkeypatch.setitem(scanner._MISSION_TICK_CONTEXT, 'memoryAttributionRecordId', None)
    assert decorated() == 42
    assert results == [42]
    assert not any(k.startswith('checkpointTiming_') for k in finish(recording))


def test_fixed_names_invalid_values_and_saturation(recording):
    for phase, elapsed, failed in [('private name', 1, False), ('seal', -1, False),
                                  ('seal', True, False), ('seal', 1, 'private')]:
        recording.record_checkpoint_timing('observed', phase, elapsed, failed)
    recording.record_checkpoint_timing('missing', 'seal', 1, False)
    recording.record_checkpoint_timing('observed', 'seal', 2**60, False)
    recording.record_checkpoint_timing('observed', 'seal', 1, True)
    metadata = finish(recording)
    assert len(metadata) == 3
    assert metadata['checkpointTiming_sealMicros'] == 2**53-1
    assert metadata['checkpointTiming_sealCount'] == 2
    assert metadata['checkpointTiming_sealFailures'] == 1


def test_all_registered_scanner_boundaries_are_wrapped():
    for name in ('_timed_checkpoint_seal', '_timed_verified_checkpoint',
                 '_recovery_phase_a_prepare_checkpoint',
                 '_verified_checkpoint_preserving_legacy_until_pair',
                 '_resolve_authoritative_local_recovery_checkpoint',
                 '_mint_post_genesis_checkpoint_capability',
                 '_consume_post_genesis_checkpoint_capability',
                 '_persist_remote_recovery_sidecar', '_verify_local_recovery_sidecar',
                 '_install_recovery_checkpoint_generation'):
        assert getattr(scanner, name).__wrapped__.__name__ == name
