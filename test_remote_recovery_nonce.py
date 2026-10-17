"""AES-GCM recovery nonce reservation safety and rollback regressions."""
from __future__ import annotations

import base64
import json
import multiprocessing
import os
from pathlib import Path
import stat
import types
from unittest import mock

import pytest

import argus_persistent_storage as storage
import argus_remote_recovery as recovery


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner
from test_remote_recovery_publish import _pair


KEY = bytes(range(32))
NEXT_KEY = bytes(reversed(range(32)))
KEY_ID = "nonce-current-v1"
RENAMED_KEY_ID = "nonce-current-renamed-v1"
NEXT_KEY_ID = "nonce-current-v2"


def _encoded_key(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _key_env(*, current_id=KEY_ID, current=KEY,
             previous_id=None, previous=None):
    value = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": current_id,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(current),
    }
    if previous_id is not None:
        value.update({
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": previous_id,
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY": _encoded_key(previous),
        })
    return value


def _paths(root):
    return storage.configured_paths({
        "ARGUS_PERSISTENT_ROOT": str(root),
        "ARGUS_REMOTE_RECOVERY_FILE": str(Path(root) / "recovery.json"),
        "ARGUS_REMOTE_RECOVERY_NONCE_STATE_FILE": str(
            Path(root) / "nonce-state.json"),
        "ARGUS_CHECKPOINT_TEMP_DIR": str(root),
    }, production=False)


def _install_paths(root):
    configured = _paths(root)
    scanner._DURABILITY_PATHS = configured
    scanner._REMOTE_RECOVERY_FILE = configured["recovery"]
    return configured


def _reserve_worker(root, start, result):
    try:
        os.environ.update(_key_env())
        _install_paths(root)
        start.wait()
        result.put(("ok", int.from_bytes(
            scanner._next_remote_recovery_nonce(KEY_ID), "big")))
    except Exception as exc:  # pragma: no cover - surfaced in parent assertion
        result.put(("error", type(exc).__name__, str(exc)))


def _write_state(path, counters):
    value = {
        "schemaVersion": scanner._REMOTE_RECOVERY_NONCE_STATE_LEGACY_SCHEMA,
        "keyMaterialCounters": dict(counters),
    }
    storage.atomic_write_json(
        str(path), value, temp_directory=str(path.parent),
        maximum_bytes=scanner._REMOTE_RECOVERY_NONCE_STATE_MAX_BYTES)
    return value


def _activate_test_authority():
    """Model the boot-only genesis boundary for reservation unit tests."""
    handle = scanner._acquire_remote_recovery_nonce_lock(
        scanner._DURABILITY_PATHS["recoveryNonceState"])
    try:
        scanner._load_remote_recovery_nonce_authority(
            handle, recovery.configured_keys(), allow_activation=True)
    finally:
        scanner._release_remote_recovery_nonce_lock(handle)


@pytest.fixture
def nonce_runtime(tmp_path):
    saved_paths = scanner._DURABILITY_PATHS
    saved_recovery = scanner._REMOTE_RECOVERY_FILE
    configured = _install_paths(tmp_path)
    try:
        with mock.patch.dict(os.environ, _key_env(), clear=False):
            _activate_test_authority()
            yield configured
    finally:
        scanner._DURABILITY_PATHS = saved_paths
        scanner._REMOTE_RECOVERY_FILE = saved_recovery


def test_encrypt_payload_requires_an_explicit_reserved_nonce():
    with pytest.raises(TypeError):
        recovery.encrypt_payload({}, KEY, key_identifier=KEY_ID)
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_json_invalid|recovery_nonce_invalid"):
        recovery.encrypt_payload(
            {}, KEY, key_identifier=KEY_ID, nonce=None)


def test_concurrent_processes_reserve_distinct_durable_counters(
        nonce_runtime, tmp_path):
    context = multiprocessing.get_context("fork")
    start = context.Event()
    result = context.Queue()
    workers = [context.Process(
        target=_reserve_worker, args=(str(tmp_path), start, result))
        for _ in range(8)]
    for worker in workers:
        worker.start()
    start.set()
    observed = [result.get(timeout=30) for _ in workers]
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0
    assert all(item[0] == "ok" for item in observed), observed
    assert sorted(item[1] for item in observed) == list(range(1, 9))
    state = scanner._read_remote_recovery_nonce_state(
        nonce_runtime["recoveryNonceState"], missing_ok=False)
    assert list(state["keyMaterialCounters"].values()) == [8]


def test_total_authority_and_sidecar_loss_never_reactivates_same_key(
        nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    for key in ("recoveryNonceState", "recoveryNonceHistory",
                "recoveryNonceHistoryHead"):
        Path(nonce_runtime[key]).unlink()
    Path(nonce_runtime["recoveryNonceState"] +
         ".reservation.lock").unlink()
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_nonce_history_missing"):
        scanner._next_remote_recovery_nonce(KEY_ID)


def test_restart_and_key_id_rename_continue_same_material_domain(
        nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    # Simulate a fresh process configuration using a different identifier but
    # exactly the same AES key material.
    with mock.patch.dict(os.environ, _key_env(
            current_id=RENAMED_KEY_ID), clear=False):
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            RENAMED_KEY_ID), "big") == 2
    encoded = Path(nonce_runtime["recoveryNonceState"]).read_text(
        encoding="utf-8")
    assert KEY_ID not in encoded and RENAMED_KEY_ID not in encoded
    assert _encoded_key(KEY) not in encoded


def test_state_and_sidecar_loss_recovers_from_private_history_after_restart(
        nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    Path(nonce_runtime["recoveryNonceState"]).unlink()
    assert not Path(nonce_runtime["recovery"]).exists()
    # Simulated restart + operational key-ID rename, same AES material.
    with mock.patch.dict(os.environ, _key_env(
            current_id=RENAMED_KEY_ID), clear=False):
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            RENAMED_KEY_ID), "big") == 2
    for key in ("recoveryNonceState", "recoveryNonceHistory",
                "recoveryNonceHistoryHead"):
        assert stat.S_IMODE(Path(nonce_runtime[key]).stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(
        nonce_runtime["recoveryNonceState"] +
        ".reservation.lock").stat().st_mode) == 0o600


def test_key_unset_does_not_activate_nonce_files(tmp_path):
    configured = _paths(tmp_path)
    with mock.patch.dict(os.environ, {}, clear=True):
        assert recovery.configured_keys()["status"] == "not_configured"
    assert not any(Path(configured[key]).exists() for key in (
        "recoveryNonceState", "recoveryNonceHistory",
        "recoveryNonceHistoryHead"))
    assert not Path(
        configured["recoveryNonceState"] + ".reservation.lock").exists()


def test_next_nonce_never_implicitly_activates_clean_storage(tmp_path):
    configured = _install_paths(tmp_path)
    with mock.patch.dict(os.environ, _key_env(), clear=False), \
            pytest.raises(recovery.RecoveryBundleError,
                          match="recovery_nonce_history_missing"):
        scanner._next_remote_recovery_nonce(KEY_ID)
    assert not any(Path(configured[key]).exists() for key in (
        "recoveryNonceState", "recoveryNonceHistory",
        "recoveryNonceHistoryHead"))


def test_rotation_encrypts_only_with_current_and_retains_previous_domain(
        nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    with mock.patch.dict(os.environ, _key_env(
            current_id=NEXT_KEY_ID, current=NEXT_KEY,
            previous_id=KEY_ID, previous=KEY), clear=False):
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            NEXT_KEY_ID), "big") == 1
        with pytest.raises(recovery.RecoveryBundleError,
                           match="recovery_nonce_current_key_required"):
            scanner._next_remote_recovery_nonce(KEY_ID)
    state = scanner._read_remote_recovery_nonce_state(
        nonce_runtime["recoveryNonceState"], missing_ok=False)
    assert sorted(state["keyMaterialCounters"].values()) == [1, 1]


def test_installed_sidecar_activates_history_and_rejects_legacy_rollback(
        nonce_runtime):
    _compact, sidecar = _pair()
    recovery_path = Path(nonce_runtime["recovery"])
    recovery_path.write_text(
        json.dumps(sidecar, sort_keys=True, separators=(",", ":")),
        encoding="utf-8")
    installed_counter = int.from_bytes(recovery._b64_decode(
        sidecar["recovery"]["nonce"], "recovery_nonce_invalid"), "big")
    floor = scanner._authenticated_installed_recovery_nonce_floor(
        recovery.configured_keys())
    scanner._seed_authenticated_remote_recovery_nonce_floor(
        floor, recovery.configured_keys())
    assert int.from_bytes(scanner._next_remote_recovery_nonce(
        KEY_ID, authenticated_remote_floor=floor), "big") == \
        installed_counter + 1

    domain = scanner._remote_recovery_nonce_domain(KEY)
    state_path = Path(nonce_runtime["recoveryNonceState"])
    _write_state(state_path, {domain: installed_counter - 1})
    # The replaceable state is repaired from authenticated private history.
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == \
        installed_counter + 2


def test_installed_sidecar_floor_survives_same_material_key_id_rename(
        nonce_runtime):
    _compact, sidecar = _pair()
    Path(nonce_runtime["recovery"]).write_text(
        json.dumps(sidecar, sort_keys=True, separators=(",", ":")),
        encoding="utf-8")
    installed_counter = int.from_bytes(recovery._b64_decode(
        sidecar["recovery"]["nonce"], "recovery_nonce_invalid"), "big")
    domain = scanner._remote_recovery_nonce_domain(KEY)
    floor = scanner._authenticated_installed_recovery_nonce_floor(
        recovery.configured_keys())
    scanner._seed_authenticated_remote_recovery_nonce_floor(
        floor, recovery.configured_keys())
    with mock.patch.dict(os.environ, _key_env(
            current_id=RENAMED_KEY_ID), clear=False):
        assert int.from_bytes(scanner._next_remote_recovery_nonce(
            RENAMED_KEY_ID, authenticated_remote_floor=floor), "big") == \
            installed_counter + 1


def test_failed_post_replace_readback_consumes_reservation(nonce_runtime):
    real_write = scanner._write_remote_recovery_nonce_state
    calls = 0

    def fail_state_write(path, history):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise recovery.RecoveryBundleError(
                "recovery_nonce_state_changed")
        return real_write(path, history)

    with mock.patch.object(
            scanner, "_write_remote_recovery_nonce_state",
            side_effect=fail_state_write):
        with pytest.raises(recovery.RecoveryBundleError,
                           match="recovery_nonce_state_changed"):
            scanner._next_remote_recovery_nonce(KEY_ID)
    # The first call never returned a nonce, but its fsynced reservation is
    # still consumed.  A restart must advance instead of retrying it.
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 2


def test_history_loss_is_fail_closed(nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    Path(nonce_runtime["recoveryNonceHistory"]).unlink()
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_nonce_history_(missing|rollback)"):
        scanner._next_remote_recovery_nonce(KEY_ID)


def test_derived_head_loss_repairs_from_exact_anchor_and_history(
        nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    Path(nonce_runtime["recoveryNonceHistoryHead"]).unlink()
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 2
    assert Path(nonce_runtime["recoveryNonceHistoryHead"]).is_file()


def test_history_and_head_rollback_are_rejected_by_monotonic_anchor(
        nonce_runtime):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    history_path = Path(nonce_runtime["recoveryNonceHistory"])
    head_path = Path(nonce_runtime["recoveryNonceHistoryHead"])
    prior_history = history_path.read_bytes()
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 2
    history_path.write_bytes(prior_history)
    history_path.chmod(0o600)
    # Keep current head: simultaneous history/head rollback by one filesystem
    # administrator is outside the two-file mirror threat boundary; the
    # append-only anchor prevents ordinary state/sidecar loss and either
    # private mirror rolling back independently.
    head_path.chmod(0o600)
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_nonce_history_rollback"):
        scanner._next_remote_recovery_nonce(KEY_ID)


@pytest.mark.parametrize("private_path", [
    "recoveryNonceState", "recoveryNonceHistory",
    "recoveryNonceHistoryHead",
])
def test_private_nonce_file_permission_drift_is_fail_closed(
        nonce_runtime, private_path):
    assert int.from_bytes(
        scanner._next_remote_recovery_nonce(KEY_ID), "big") == 1
    Path(nonce_runtime[private_path]).chmod(0o644)
    with pytest.raises(recovery.RecoveryBundleError,
                       match="recovery_nonce_(state_permissions_invalid|"
                             "history)"):
        scanner._next_remote_recovery_nonce(KEY_ID)
