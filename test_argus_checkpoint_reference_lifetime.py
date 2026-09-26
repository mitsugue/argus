"""Synthetic keyed saves: decoded records must not outlive their last use."""
import inspect
import tempfile
import weakref
from unittest import mock

from test_remote_recovery_publish import (
    scanner, storage, scanner_storage, _key_environment,
    _reset_recovery_targets, _append_verified_cycle,
    _activate_clean_legacy_nonce_authority, _advance_nonce_floor_to_33,
)


def test_checkpoint_reference_lifetime():
    class TrackedCheckpoint(dict):
        pass

    references = []
    observations = []
    real_load = storage.load_checkpoint
    real_boundary = scanner._remote_recovery_crash_boundary

    def load(*args, **kwargs):
        result = real_load(*args, **kwargs)
        if inspect.currentframe().f_back.f_code.co_name == \
                '_verified_checkpoint_preserving_legacy_until_pair':
            result = TrackedCheckpoint(result)
            references.append(weakref.ref(result))
        return result

    def boundary(name):
        if name in ('after_complete_pair', 'before_candidate_checkpoint_staging',
                    'after_candidate_pair_verification', 'before_pair_cleanup'):
            observations.append({'boundary': name,
                                 'loaded': len(references),
                                 'alive': sum(ref() is not None for ref in references)})
        return real_boundary(name)

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, '_CHECKPOINT_V2_STAGE1_ENABLED', False):
        _reset_recovery_targets()
        _append_verified_cycle(paths, sequence=1)
        _activate_clean_legacy_nonce_authority(paths)
        with mock.patch.object(storage, 'load_checkpoint', load), \
                mock.patch.object(scanner, '_remote_recovery_crash_boundary', boundary):
            assert scanner._osint_persist()['verified'] is True
            _advance_nonce_floor_to_33()
            _append_verified_cycle(paths, sequence=2)
            assert scanner._osint_persist()['verified'] is True
        # The final canonical checkpoint remains independently readable.
        canonical = storage.load_checkpoint(paths['checkpoint'], require_seal=True)
        scanner._verify_local_recovery_sidecar(canonical, allow_legacy_migration=False)
        assert len(observations) == 4
        assert all(ref() is None for ref in references)
    assert [item["boundary"] for item in observations] == [
        "after_complete_pair", "before_candidate_checkpoint_staging",
        "after_candidate_pair_verification", "before_pair_cleanup",
    ]
    assert [item["loaded"] for item in observations] == [3, 4, 5, 6]
    assert [item["alive"] for item in observations] == [0, 0, 0, 0]
