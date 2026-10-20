"""2026-10-20 (owner): the operational diagnostics say why a start stopped, read-only; the check is unchanged."""
from collections import namedtuple

import pytest

import argus_persistent_storage
import scanner

Usage = namedtuple("Usage", "total used free")


def test_a_failed_check_records_its_reason_and_the_capacity_it_compares(tmp_path, monkeypatch):
    checkpoint = tmp_path / "state.json"; checkpoint.write_bytes(b"x" * 1000)
    wal = tmp_path / "wal.jsonl"; wal.write_bytes(b"y" * 3000)
    monkeypatch.setattr(scanner, "_DURABILITY_PATHS", {"root": str(tmp_path), "checkpoint": str(checkpoint), "wal": str(wal)})
    def refuse(*a, **k):
        raise argus_persistent_storage.PersistentStorageError("persistent_storage_insufficient_space")
    monkeypatch.setattr(argus_persistent_storage, "validate_storage", refuse)
    monkeypatch.setattr(scanner.shutil, "disk_usage", lambda root: Usage(15_000, 14_950, 50))
    assert scanner._validate_durable_storage() is False          # the decision is unchanged
    status = scanner._DURABLE_STORAGE_STATUS
    assert status["valid"] is False and status["errorReason"] == "persistent_storage_insufficient_space"
    assert status["freeBytes"] == 50 and status["totalBytes"] == 15_000
    assert status["requiredFreeBytes"] == argus_persistent_storage.required_free_bytes(checkpoint_bytes=1000, wal_bytes=3000)


def test_an_unmeasurable_capacity_stays_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_DURABILITY_PATHS", {"root": str(tmp_path / "missing")})
    def refuse(*a, **k):
        raise argus_persistent_storage.PersistentStorageError("persistent_root_missing")
    monkeypatch.setattr(argus_persistent_storage, "validate_storage", refuse)
    assert scanner._validate_durable_storage() is False
    assert "freeBytes" not in scanner._DURABLE_STORAGE_STATUS
    assert scanner._DURABLE_STORAGE_STATUS["errorReason"] == "persistent_root_missing"


def test_the_operational_diagnostics_show_the_reason_and_the_bytes(monkeypatch):
    monkeypatch.setattr(scanner, "_DURABLE_STORAGE_STATUS", {
        "valid": False, "runtimeVerified": False, "errorClass": "persistent_storage_unavailable",
        "errorReason": "persistent_storage_insufficient_space", "freeBytes": 50, "requiredFreeBytes": 113,
        "totalBytes": 15_000, "checkpointBytes": 10, "walBytes": 20})
    storage = scanner._operational_diagnostics_snapshot()["storage"]
    assert storage["statusCode"] == "INVALID"
    assert storage["errorReason"] == "PERSISTENT_STORAGE_INSUFFICIENT_SPACE"
    assert (storage["freeBytes"], storage["requiredFreeBytes"], storage["totalBytes"]) == (50, 113, 15_000)


def test_a_valid_store_has_no_reason_and_unmeasured_sizes_are_not_zero(monkeypatch):
    monkeypatch.setattr(scanner, "_DURABLE_STORAGE_STATUS", {"valid": True, "runtimeVerified": True})
    storage = scanner._operational_diagnostics_snapshot()["storage"]
    assert storage["errorReason"] is None and storage["freeBytes"] is None


def test_the_reason_never_carries_a_path():
    import argus_diagnostics_contract as c
    assert c._code("/var/data/secret path") == "UNKNOWN"
    with pytest.raises(c.DiagnosticsContractError):
        c._optional_count(-1)
