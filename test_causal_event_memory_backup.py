"""13.8 §4-7 (2026-10-27): the event memory ledger is copied to the existing
private store and restored when the disk copy is lost."""
import json
import os

import pytest

import argus_causal_event_memory as memory
import argus_causal_event_memory_backup as backup
from test_argus_causal_event_memory import build_event, news


class Store:
    def __init__(self):
        self.files, self.private, self.puts = {}, True, 0

    def require_private(self):
        if not self.private:
            raise ValueError("private_required")

    def get(self, path):
        raw = self.files.get(path)
        return (raw, f"v{hash(raw)}") if raw is not None else (None, None)

    def put(self, path, raw, *, expected_version):
        current = self.files.get(path)
        assert expected_version == (f"v{hash(current)}" if current is not None else None)
        assert len(raw) <= 512 * 1024
        self.files[path] = raw
        self.puts += 1


def _lines(p):
    """A stand-in reader for large synthetic ledgers (one record per line)."""
    if not os.path.exists(p):
        return {"status": "EMPTY", "records": []}
    count = open(p, "rb").read().count(b"\n")
    return {"status": "VERIFIED", "records": [{"recordHash": str(i)} for i in range(count)]}


def test_upload_append_restore_and_conflict(tmp_path):
    raw = "".join(json.dumps({"n": i, "pad": "x" * 30000}) + "\n" for i in range(40)).encode()
    path = str(tmp_path / "memory.jsonl")
    open(path, "wb").write(raw)
    store = Store()
    first = backup.synchronize(path, store, read_ledger=_lines)
    assert first["status"] == "UPLOADED" and first["records"] == 40
    pieces = backup.chunks(raw)
    assert len(pieces) > 1 and all(len(p) <= backup.CHUNK_TARGET for p in pieces) and b"".join(pieces) == raw
    assert backup.synchronize(path, store, read_ledger=_lines)["status"] == "VERIFIED"
    # Append only: the earlier chunks are not written again.
    tail = (json.dumps({"n": 40}) + "\n").encode()
    open(path, "ab").write(tail)
    puts = store.puts
    again = backup.synchronize(path, store, read_ledger=_lines)
    assert again["status"] == "UPLOADED" and again["chunksWritten"] == 1 and store.puts == puts + 2
    # A lost disk copy comes back.
    os.unlink(path)
    assert backup.synchronize(path, store, read_ledger=_lines) == {
        "status": "RESTORED", "records": 41, "bytes": len(raw) + len(tail)}
    assert open(path, "rb").read() == raw + tail
    # A shorter or different ledger is never uploaded over the copy.
    open(path, "wb").write(b'{"other":1}\n')
    assert backup.synchronize(path, store, read_ledger=_lines)["status"] == "CONFLICT"
    # A damaged chunk stops a restore and nothing is installed; the store must be private.
    os.unlink(path)
    damaged = next(k for k in store.files if "/chunks/" in k)
    store.files[damaged] = b"broken\n"
    with pytest.raises(ValueError):
        backup.synchronize(path, store, read_ledger=_lines)
    assert not os.path.exists(path)
    store.private = False
    with pytest.raises(ValueError):
        backup.synchronize(path, store, read_ledger=_lines)


def test_a_ledger_that_does_not_verify_is_not_uploaded(tmp_path):
    path = str(tmp_path / "memory.jsonl")
    open(path, "wb").write(b"x\n")
    store = Store()
    result = backup.synchronize(path, store, read_ledger=lambda p: {"status": "CORRUPT", "reason": "hash_chain_invalid"})
    assert result["status"] == "LOCAL_NOT_VERIFIED" and store.files == {}


def test_a_real_hash_chained_ledger_round_trips(tmp_path):
    path = str(tmp_path / "argus_causal_event_memory.jsonl")
    memory.append_record(path, build_event())
    memory.append_record(path, build_event(news(event_id="second")))
    store = Store()
    assert backup.synchronize(path, store, read_ledger=memory.read_ledger)["status"] == "UPLOADED"
    original = open(path, "rb").read()
    os.unlink(path)
    assert backup.synchronize(path, store, read_ledger=memory.read_ledger)["status"] == "RESTORED"
    assert open(path, "rb").read() == original
    assert memory.read_ledger(path)["status"] == "VERIFIED"


def test_scanner_copies_hourly_and_reloads_after_a_restore(tmp_path, monkeypatch):
    import scanner
    path = str(tmp_path / "argus_causal_event_memory.jsonl")
    memory.append_record(path, build_event())
    monkeypatch.setattr(scanner, "_causal_memory_file", lambda: path)
    monkeypatch.setitem(scanner._CAUSAL_MEMORY, "remoteBackup", None)
    for key in ("loaded", "state", "loadStatus", "lastErrorClass"):      # leave the global memory as found
        monkeypatch.setitem(scanner._CAUSAL_MEMORY, key, scanner._CAUSAL_MEMORY.get(key))
    store = Store()
    assert scanner._causal_memory_backup(store, now_epoch=1_000_000.0)["status"] == "UPLOADED"
    os.unlink(path)
    assert scanner._causal_memory_backup(store, now_epoch=1_000_100.0)["status"] == "UPLOADED", "an hour has not passed"
    restored = scanner._causal_memory_backup(store, now_epoch=1_004_000.0)
    assert restored["status"] == "RESTORED" and os.path.exists(path)
    assert scanner._CAUSAL_MEMORY["loadStatus"] == "VERIFIED"
