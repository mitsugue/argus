"""Pure contract of the derived market artifact files."""
import hashlib
import json
import os
import pathlib
import tempfile

import pytest

import argus_market_artifact_store as store
import argus_persistent_storage as storage


HASH_A = "a" * 64
HASH_B = "b" * 64
AT = "2026-09-28T05:00:00Z"


def _payload(tag="one"):
    return {"current": {"k": {"snapshotId": f"vs-{tag}", "n": 1}},
            "history": [], "lastPublishedAt": AT}


def _write(root, name="verifiedViewSnapshots", state_hash=HASH_A,
           last=None, payload=None):
    return store.write_if_changed(
        root, name, payload or _payload(), state_hash=state_hash, now_iso=AT,
        last_state_hash=last, atomic_write_json=storage.atomic_write_json,
        method_version="m-1", build_sha="c" * 40)


def test_envelope_is_exact_and_payload_hash_bound():
    doc = store.envelope("marketReplay", _payload(), state_hash=HASH_A,
                         written_at=AT, method_version="m", build_sha="d" * 40)
    assert doc["schemaVersion"] == store.SCHEMA
    assert doc["artifact"] == "marketReplay"
    assert doc["payloadSha256"] == hashlib.sha256(json.dumps(
        _payload(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert store.verify(doc, name="marketReplay") == doc
    for name in store.ARTIFACTS:
        assert name in store.MAX_BYTES


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(schemaVersion="x"), "market_artifact_schema_mismatch"),
    (lambda d: d.update(artifact="opsJournal"), "market_artifact_name_mismatch"),
    (lambda d: d.update(stateHash="zz"), "market_artifact_state_hash_invalid"),
    (lambda d: d.update(writtenAt="yesterday"), "market_artifact_written_at_invalid"),
    (lambda d: d.update(payload=[]), "market_artifact_payload_invalid"),
    (lambda d: d["payload"].update(tampered=True), "market_artifact_payload_hash_mismatch"),
])
def test_verify_rejects_every_tampered_field(mutate, code):
    doc = store.envelope("marketReplay", _payload(), state_hash=HASH_A,
                         written_at=AT)
    mutate(doc)
    with pytest.raises(store.ArtifactError, match=f"^{code}$"):
        store.verify(doc, name="marketReplay")


def test_unknown_artifact_name_is_rejected():
    with pytest.raises(store.ArtifactError, match="^market_artifact_unknown$"):
        store.path_for("/tmp", "opsJournal")
    with pytest.raises(store.ArtifactError, match="^market_artifact_unknown$"):
        store.envelope("secrets", {}, state_hash=HASH_A, written_at=AT)


def test_write_is_hash_gated_and_read_back_verified():
    with tempfile.TemporaryDirectory() as root:
        first = _write(root)
        path = pathlib.Path(first["path"])
        assert first["status"] == "written"
        assert first["readBackVerified"] is True
        assert first["bytes"] == path.stat().st_size
        assert (path.stat().st_mode & 0o777) == 0o600
        identity = (path.stat().st_ino, path.stat().st_mtime_ns)

        unchanged = _write(root, last=HASH_A)
        assert unchanged["status"] == "unchanged"
        assert (path.stat().st_ino, path.stat().st_mtime_ns) == identity

        moved = _write(root, state_hash=HASH_B, last=HASH_A,
                       payload=_payload("two"))
        assert moved["status"] == "written"
        loaded = store.load(root, "verifiedViewSnapshots")
        assert loaded["stateHash"] == HASH_B
        assert loaded["payload"] == _payload("two")
        assert loaded["methodVersion"] == "m-1"


def test_missing_file_after_unchanged_hash_is_rewritten():
    with tempfile.TemporaryDirectory() as root:
        first = _write(root)
        os.unlink(first["path"])
        again = _write(root, last=HASH_A)
        assert again["status"] == "written"


def test_load_returns_none_when_absent_and_rejects_corruption():
    with tempfile.TemporaryDirectory() as root:
        assert store.load(root, "assetChartReports") is None
        path = pathlib.Path(store.path_for(root, "assetChartReports"))
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(store.ArtifactError,
                           match="^market_artifact_json_invalid$"):
            store.load(root, "assetChartReports")
        path.write_text(json.dumps({"schemaVersion": "other"}),
                        encoding="utf-8")
        with pytest.raises(store.ArtifactError,
                           match="^market_artifact_schema_mismatch$"):
            store.load(root, "assetChartReports")


def test_symlinked_artifact_is_rejected():
    with tempfile.TemporaryDirectory() as root:
        target = pathlib.Path(root, "target.json")
        target.write_text("{}", encoding="utf-8")
        path = pathlib.Path(store.path_for(root, "marketReplay"))
        path.parent.mkdir(parents=True)
        path.symlink_to(target)
        with pytest.raises(store.ArtifactError,
                           match="^market_artifact_symlink_rejected$"):
            store.load(root, "marketReplay")


def test_oversized_artifact_fails_closed(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        _write(root, name="marketReplay")
        monkeypatch.setitem(store.MAX_BYTES, "marketReplay", 16)
        with pytest.raises(store.ArtifactError,
                           match="^market_artifact_oversized$"):
            store.load(root, "marketReplay")
        with pytest.raises(storage.PersistentStorageError):
            _write(root, name="marketReplay", state_hash=HASH_B, last=HASH_A)


def test_status_projection_is_public_safe_and_complete():
    projection = store.status_projection({
        "marketReplay": {"stateHash": HASH_A, "bytes": 10, "writtenAt": AT,
                         "lastStatus": "written", "path": "/var/data/x",
                         "secret": "never"},
        "junk": {"stateHash": HASH_B},
    })
    assert set(projection["artifacts"]) == set(store.ARTIFACTS)
    row = projection["artifacts"]["marketReplay"]
    assert row == {"stateHash": HASH_A, "bytes": 10, "writtenAt": AT,
                   "lastStatus": "written", "restoreStatus": None,
                   "errorClass": None}
    assert "path" not in json.dumps(projection)
    assert "secret" not in json.dumps(projection)
    assert projection["artifacts"]["chartIntelligence"]["bytes"] == 0
