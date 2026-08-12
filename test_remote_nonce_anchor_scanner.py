"""Scanner wiring coverage for bounded nonce-anchor epoch rollover."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import types
from unittest import mock

import pytest


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner
import argus_remote_recovery as recovery


DOMAIN = "b" * 64


def test_scanner_rollover_keeps_lock_inode_and_absolute_counter(tmp_path):
    state_path = str(tmp_path / "nonce-state.json")
    lock = scanner._acquire_remote_recovery_nonce_lock(state_path)
    try:
        stable_inode = os.fstat(lock.fileno()).st_ino
        maximum = scanner._REMOTE_RECOVERY_NONCE_ANCHOR_HEADER_BYTES + \
            scanner._REMOTE_RECOVERY_NONCE_LOCK_RECORD_BYTES
        previous = None
        with mock.patch.object(
                scanner, "_REMOTE_RECOVERY_NONCE_LOCK_MAX_BYTES", maximum):
            for generation in range(5):
                history = scanner._build_remote_recovery_nonce_history(
                    generation, previous, {DOMAIN: generation + 1})
                current = scanner._append_remote_recovery_nonce_lock_anchor(
                    lock, history)
                assert current["generation"] == generation
                assert current["counters"] == {DOMAIN: generation + 1}
                assert os.fstat(lock.fileno()).st_ino == stable_inode
                previous = history["recordHash"]
            assert current["epoch"] == 4
    finally:
        scanner._release_remote_recovery_nonce_lock(lock)

    anchor_path = Path(state_path + ".reservation.lock.anchor")
    assert anchor_path.is_file()
    assert stat.S_IMODE(anchor_path.stat().st_mode) == 0o600

    # A new process acquires the same lock path and resumes from the v2 epoch,
    # not generation zero or the terminal record left in the legacy v1 inode.
    lock = scanner._acquire_remote_recovery_nonce_lock(state_path)
    try:
        with mock.patch.object(
                scanner, "_REMOTE_RECOVERY_NONCE_LOCK_MAX_BYTES", maximum):
            restored = scanner._remote_recovery_nonce_lock_anchor(lock)
        assert restored["generation"] == 4
        assert restored["counters"] == {DOMAIN: 5}
    finally:
        scanner._release_remote_recovery_nonce_lock(lock)


def test_scanner_missing_successor_epoch_exposes_rollback_to_mirrors(tmp_path):
    state_path = str(tmp_path / "nonce-state.json")
    maximum = scanner._REMOTE_RECOVERY_NONCE_ANCHOR_HEADER_BYTES + \
        scanner._REMOTE_RECOVERY_NONCE_LOCK_RECORD_BYTES
    lock = scanner._acquire_remote_recovery_nonce_lock(state_path)
    try:
        first = scanner._build_remote_recovery_nonce_history(
            0, None, {DOMAIN: 1})
        second = scanner._build_remote_recovery_nonce_history(
            1, first["recordHash"], {DOMAIN: 2})
        with mock.patch.object(
                scanner, "_REMOTE_RECOVERY_NONCE_LOCK_MAX_BYTES", maximum):
            scanner._append_remote_recovery_nonce_lock_anchor(lock, first)
            scanner._append_remote_recovery_nonce_lock_anchor(lock, second)
            Path(state_path + ".reservation.lock.anchor").unlink()
            rolled_back = scanner._remote_recovery_nonce_lock_anchor(lock)
        assert rolled_back["generation"] == 0
        assert rolled_back["recordHash"] != second["recordHash"]
    finally:
        scanner._release_remote_recovery_nonce_lock(lock)


def _install_nonce_paths(root):
    configured = scanner.argus_persistent_storage.configured_paths({
        "ARGUS_PERSISTENT_ROOT": str(root),
        "ARGUS_REMOTE_RECOVERY_NONCE_STATE_FILE": str(root / "state.json"),
        "ARGUS_CHECKPOINT_TEMP_DIR": str(root),
    }, production=False)
    scanner._DURABILITY_PATHS = configured
    return configured


@mock.patch.object(scanner, "_verify_installed_remote_recovery_nonce_floor")
def test_exact_anchor_history_repairs_head_crash_window(
        _verify_floor, tmp_path):
    saved = scanner._DURABILITY_PATHS
    configured = _install_nonce_paths(tmp_path)
    lock = scanner._acquire_remote_recovery_nonce_lock(
        configured["recoveryNonceState"])
    try:
        first = scanner._build_remote_recovery_nonce_history(
            0, None, {DOMAIN: 1})
        scanner._write_remote_recovery_nonce_history(
            configured["recoveryNonceHistory"], first)
        scanner._write_remote_recovery_nonce_history_head(
            configured["recoveryNonceHistoryHead"], first)
        scanner._append_remote_recovery_nonce_lock_anchor(lock, first)
        scanner._write_remote_recovery_nonce_state(
            configured["recoveryNonceState"], first)

        second = scanner._build_remote_recovery_nonce_history(
            1, first["recordHash"], {DOMAIN: 2})
        scanner._append_remote_recovery_nonce_lock_anchor(lock, second)
        scanner._write_remote_recovery_nonce_history(
            configured["recoveryNonceHistory"], second)
        # Simulate death before the derived head and cache replace.
        loaded, head, state = scanner._load_remote_recovery_nonce_authority(
            lock, {"status": "configured"}, allow_activation=False)
        assert loaded == second
        assert head == scanner._build_remote_recovery_nonce_history_head(
            second)
        assert state["keyMaterialCounters"] == {DOMAIN: 2}
    finally:
        scanner._release_remote_recovery_nonce_lock(lock)
        scanner._DURABILITY_PATHS = saved


@mock.patch.object(scanner, "_verify_installed_remote_recovery_nonce_floor")
def test_future_or_divergent_head_is_never_repaired(
        _verify_floor, tmp_path):
    saved = scanner._DURABILITY_PATHS
    configured = _install_nonce_paths(tmp_path)
    lock = scanner._acquire_remote_recovery_nonce_lock(
        configured["recoveryNonceState"])
    try:
        first = scanner._build_remote_recovery_nonce_history(
            0, None, {DOMAIN: 1})
        second = scanner._build_remote_recovery_nonce_history(
            1, first["recordHash"], {DOMAIN: 2})
        scanner._write_remote_recovery_nonce_history(
            configured["recoveryNonceHistory"], first)
        scanner._write_remote_recovery_nonce_history_head(
            configured["recoveryNonceHistoryHead"], second)
        scanner._append_remote_recovery_nonce_lock_anchor(lock, first)
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_nonce_history_rollback"):
            scanner._load_remote_recovery_nonce_authority(
                lock, {"status": "configured"}, allow_activation=False)
    finally:
        scanner._release_remote_recovery_nonce_lock(lock)
        scanner._DURABILITY_PATHS = saved
