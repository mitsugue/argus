"""13.8 §4-7 (2026-10-27): the event memory ledger is copied to the existing
private store and restored when the disk copy is lost."""
import json
import os
import tracemalloc

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


@pytest.mark.parametrize("case", ["valid", "empty", "missing", "json", "utf8",
                                  "previous", "sequence", "payload", "tail", "bytes", "records"])
def test_stream_verifier_keeps_complete_chain_checks_and_limits(tmp_path, monkeypatch, case):
    path = tmp_path / "stream.jsonl"
    memory.append_record(str(path), build_event())
    memory.append_record(str(path), build_event(news(event_id="synthetic:second")))
    raw = path.read_bytes()
    if case == "empty":
        path.write_bytes(b"")
    elif case == "missing":
        path.unlink()
    elif case == "json":
        path.write_bytes(b"invalid-json\n")
    elif case == "utf8":
        path.write_bytes(b"\xff\n")
    elif case in ("previous", "sequence", "payload"):
        rows = [json.loads(line) for line in raw.splitlines()]
        if case == "previous":
            rows[1]["previousRecordHash"] = "0" * 64
        elif case == "sequence":
            rows[1]["sequence"] = 9
        else:
            rows[1]["payload"]["headline"] = "synthetic:tampered"
        path.write_bytes(b"".join(memory._canonical(row) + b"\n" for row in rows))
    elif case == "tail":
        path.write_bytes(raw + b'{"incomplete":')
    elif case == "bytes":
        monkeypatch.setattr(memory, "MAX_LEDGER_BYTES", len(raw) - 1)
    elif case == "records":
        monkeypatch.setattr(memory, "MAX_LEDGER_RECORDS", 1)
    before = path.read_bytes() if path.exists() else None
    full = memory.read_ledger(str(path))
    streamed = memory.verify_ledger(str(path))
    assert {key: streamed[key] for key in ("status", "reason", "corruptLine")} == {
        key: full[key] for key in ("status", "reason", "corruptLine")}
    assert streamed["recordCount"] == len(full["records"])
    assert streamed["lastRecordHash"] == (full["records"][-1]["recordHash"] if full["records"] else None)
    assert "records" not in streamed
    assert (path.read_bytes() if path.exists() else None) == before


def test_stream_backup_keeps_all_manifest_and_chunk_bytes_and_restored_records(tmp_path):
    path = tmp_path / "source.jsonl"
    for index in range(8):
        memory.append_record(str(path), build_event(news(event_id="synthetic:" + str(index))))
    raw = path.read_bytes()
    retained_reader = lambda file: memory.read_ledger(file)
    first, second = Store(), Store()
    assert backup.synchronize(str(path), first, read_ledger=retained_reader) == backup.synchronize(
        str(path), second, read_ledger=memory.read_ledger)
    assert first.files == second.files
    assert path.read_bytes() == raw
    for index, (store, reader) in enumerate(((first, retained_reader), (second, memory.read_ledger))):
        restored = tmp_path / ("restored-" + str(index) + ".jsonl")
        assert backup.synchronize(str(restored), store, read_ledger=reader)["status"] == "RESTORED"
        assert restored.read_bytes() == raw
        assert len(memory.read_ledger(str(restored))["records"]) == 8


def test_backup_summary_derives_injected_reader_count_and_tail_from_records(tmp_path):
    supplied = {"status": "VERIFIED", "records": [{"recordHash": "actual"}],
                "recordCount": 999, "lastRecordHash": "unverified"}
    result = backup._verify(b"synthetic\n", str(tmp_path), lambda _: supplied)
    assert result["recordCount"] == 1 and result["lastRecordHash"] == "actual"
    assert "records" not in result


def test_backup_chunk_bound_is_checked_before_any_remote_write(tmp_path, monkeypatch):
    path = tmp_path / "bounded.jsonl"
    path.write_bytes(b"x" * (backup.CHUNK_TARGET - 1) + b"\n" + b"y\n")
    monkeypatch.setattr(backup, "MAX_CHUNKS", 1)
    store = Store()
    with pytest.raises(ValueError, match="event_memory_backup_bound"):
        backup.synchronize(str(path), store, read_ledger=_lines)
    assert store.files == {} and store.puts == 0


def test_backup_verification_avoids_retaining_full_parsed_ledger(tmp_path):
    path = tmp_path / "large.jsonl"
    for index in range(64):
        memory.append_record(str(path), build_event(news(event_id="synthetic-memory:" + str(index))))
    raw = path.read_bytes()
    results = []
    for reader in (lambda file: memory.read_ledger(file), memory.read_ledger):
        already_tracing = tracemalloc.is_tracing()
        if not already_tracing:
            tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            baseline = tracemalloc.get_traced_memory()[0]
            result = backup._verify(raw, str(tmp_path), reader)
            results.append((result, tracemalloc.get_traced_memory()[1] - baseline))
        finally:
            if not already_tracing:
                tracemalloc.stop()
    assert results[0][0] == results[1][0]
    assert results[0][0]["recordCount"] == 64
    assert results[1][1] < results[0][1] // 2
    assert path.read_bytes() == raw


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
