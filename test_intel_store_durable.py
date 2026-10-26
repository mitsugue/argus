"""13.8 §4-7 (2026-10-27): the RSS intel store lives on the persistent disk, so a
deploy no longer drops it; an old /tmp copy is read once when no new one exists."""
import json
import os

import argus_persistent_storage
import scanner


def test_the_store_file_is_under_the_persistent_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGUS_PERSISTENT_ROOT", str(tmp_path))
    assert scanner._intel_store_file() == os.path.join(os.path.realpath(tmp_path), "argus_intel_store.json")
    production = argus_persistent_storage.configured_paths({}, production=True)["root"]
    assert production == os.path.realpath("/var/data")


def test_restore_prefers_the_durable_copy_and_reads_the_old_one_once(monkeypatch, tmp_path):
    durable, legacy = tmp_path / "durable.json", tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"store": [{"id": "old"}], "last": {"collected": 1}}))
    monkeypatch.setattr(scanner, "_INTEL_STORE_FILE", str(durable))
    monkeypatch.setattr(scanner, "_INTEL_STORE_LEGACY_FILE", str(legacy))
    monkeypatch.setattr(scanner, "_INTEL_STORE", [])
    scanner._intel_restore()
    assert scanner._INTEL_STORE == [{"id": "old"}]
    scanner._intel_persist()
    assert json.loads(durable.read_text())["store"] == [{"id": "old"}]
    durable.write_text(json.dumps({"store": [{"id": "new"}]}))
    scanner._INTEL_STORE[:] = []
    scanner._intel_restore()
    assert scanner._INTEL_STORE == [{"id": "new"}]
