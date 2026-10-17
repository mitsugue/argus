"""Bounded epoch rollover tests for the private recovery nonce anchor."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from unittest import mock

import pytest

import argus_remote_nonce_anchor as anchor


DOMAIN = "a" * 64


def _validate_counters(value, *, allow_empty=False):
    if not isinstance(value, dict) or (not value and not allow_empty):
        raise ValueError("invalid")
    for key, counter in value.items():
        if len(key) != 64 or not isinstance(counter, int) or counter < 1:
            raise ValueError("invalid")
    return dict(value)


def _history(generation, previous, counter):
    body = {
        "schemaVersion": "argus-remote-recovery-nonce-history-v1",
        "generation": generation,
        "previousRecordHash": previous,
        "keyMaterialCounters": {DOMAIN: counter},
    }
    body["recordHash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode()).hexdigest()
    return body


def _append(path, history, maximum):
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    with path.open("r+b", buffering=0) as handle:
        return anchor.append(
            handle, history, path=str(path), maximum_bytes=maximum,
            validate_counters=_validate_counters)


def _read(path, maximum):
    with path.open("rb", buffering=0) as handle:
        return anchor.read(
            handle, maximum_bytes=maximum,
            validate_counters=_validate_counters)


def test_tiny_cap_rolls_v1_to_v2_without_resetting_counter(tmp_path):
    path = tmp_path / "anchor"
    maximum = len(anchor.V1_HEADER) + 2 * anchor.RECORD_BYTES
    first = _history(0, None, 1)
    second = _history(1, first["recordHash"], 2)
    third = _history(2, second["recordHash"], 3)

    assert _append(path, first, maximum)["formatVersion"] == 1
    assert _append(path, second, maximum)["formatVersion"] == 1
    rolled = _append(path, third, maximum)

    assert rolled["formatVersion"] == 2
    assert rolled["epoch"] == 1
    assert rolled["baseGeneration"] == 2
    assert rolled["generation"] == 2
    assert rolled["counters"] == {DOMAIN: 3}
    assert path.stat().st_size == anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_multiple_epoch_rollovers_keep_absolute_generation(tmp_path):
    path = tmp_path / "anchor"
    maximum = anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    previous = None
    observed = []
    for generation in range(6):
        history = _history(generation, previous, generation + 1)
        current = _append(path, history, maximum)
        observed.append((current["epoch"], current["generation"],
                         current["counters"][DOMAIN]))
        previous = history["recordHash"]
    assert observed == [
        (0, 0, 1), (1, 1, 2), (2, 2, 3),
        (3, 3, 4), (4, 4, 5), (5, 5, 6)]


def test_failed_replace_leaves_prior_epoch_authoritative(tmp_path):
    path = tmp_path / "anchor"
    maximum = anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    first = _history(0, None, 1)
    second = _history(1, first["recordHash"], 2)
    _append(path, first, maximum)
    before = path.read_bytes()

    with mock.patch.object(os, "replace", side_effect=OSError("crash")), \
            pytest.raises(OSError, match="crash"):
        _append(path, second, maximum)
    assert path.read_bytes() == before
    current = _read(path, maximum)
    assert current["generation"] == 0
    assert current["counters"] == {DOMAIN: 1}


def test_post_replace_failure_never_restores_old_epoch(tmp_path):
    path = tmp_path / "anchor"
    maximum = anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    first = _history(0, None, 1)
    second = _history(1, first["recordHash"], 2)
    _append(path, first, maximum)

    with mock.patch.object(
            anchor, "_fsync_directory", side_effect=OSError("crash")), \
            pytest.raises(OSError, match="crash"):
        _append(path, second, maximum)
    current = _read(path, maximum)
    assert current["formatVersion"] == 2
    assert current["generation"] == 1
    assert current["counters"] == {DOMAIN: 2}


def test_rolled_back_epoch_is_detectable_by_newer_mirror_generation(tmp_path):
    path = tmp_path / "anchor"
    maximum = anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    first = _history(0, None, 1)
    second = _history(1, first["recordHash"], 2)
    _append(path, first, maximum)
    old_inode = path.read_bytes()
    current = _append(path, second, maximum)
    assert current["generation"] == 1

    path.write_bytes(old_inode)
    path.chmod(0o600)
    rolled_back = _read(path, maximum)
    # The module reports absolute generation; scanner's existing exact mirror
    # equality check therefore rejects this as history rollback.
    assert rolled_back["generation"] == 0
    assert rolled_back["recordHash"] != second["recordHash"]


@pytest.mark.parametrize("field", ["epoch", "base_generation",
                                    "previous_epoch_digest",
                                    "base_record_hash"])
def test_corrupt_v2_epoch_header_fails_closed(tmp_path, field):
    path = tmp_path / "anchor"
    maximum = anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    first = _history(0, None, 1)
    second = _history(1, first["recordHash"], 2)
    _append(path, first, maximum)
    _append(path, second, maximum)
    encoded = bytearray(path.read_bytes())
    offset = len(anchor.V2_HEADER)
    positions = {
        "epoch": offset,
        "base_generation": offset + 8,
        "previous_epoch_digest": offset + 16,
        "base_record_hash": offset + 48,
    }
    encoded[positions[field]] ^= 1
    path.write_bytes(encoded)
    path.chmod(0o600)
    with pytest.raises(anchor.AnchorError):
        _read(path, maximum)


def test_v2_mode_drift_fails_on_append_readback(tmp_path):
    path = tmp_path / "anchor"
    maximum = anchor.V2_HEADER_BYTES + anchor.RECORD_BYTES
    first = _history(0, None, 1)
    second = _history(1, first["recordHash"], 2)
    _append(path, first, maximum)
    real_replace = os.replace

    def replace_then_drift(source, destination):
        real_replace(source, destination)
        os.chmod(destination, 0o644)

    with mock.patch.object(os, "replace", side_effect=replace_then_drift), \
            pytest.raises(anchor.AnchorError,
                          match="permissions_invalid"):
        _append(path, second, maximum)


def test_v2_generation_overflow_fails_closed(tmp_path):
    path = tmp_path / "anchor"
    meta = struct.pack(">QQ", 1, (1 << 64) - 1) + bytes(64)
    path.write_bytes(anchor.V2_HEADER + meta + bytes(anchor.RECORD_BYTES))
    path.chmod(0o600)
    with pytest.raises(anchor.AnchorError):
        _read(path, len(path.read_bytes()))
