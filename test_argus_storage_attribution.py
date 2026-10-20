"""2026-10-20 (owner): the persistent disk is attributed stat-only; nothing is read, changed or named."""
import json
import os

import argus_storage_attribution as a
import scanner


def tree(tmp_path):
    (tmp_path / "state.json").write_bytes(b"c" * 100)
    (tmp_path / "state.json.123.0123456789abcdef0123456789abcdef.tmp").write_bytes(b"t" * 300)
    (tmp_path / "wal.jsonl").write_bytes(b"w" * 50)
    (tmp_path / "market_analysis_history.sqlite3").write_bytes(b"h" * 70)
    blobs = tmp_path / "artifact_store"; blobs.mkdir()
    (blobs / "secret-looking-name").write_bytes(b"x" * 4000)
    (blobs / "chart.bin").write_bytes(b"y" * 2000)
    (tmp_path / "argus_checkpoint_v2").mkdir(); (tmp_path / "argus_checkpoint_v2" / "g1").write_bytes(b"v" * 10)
    return a.attribute(str(tmp_path), checkpoint=str(tmp_path / "state.json"), wal=str(tmp_path / "wal.jsonl"))


def test_groups_follow_the_earlier_attribution_and_split_the_unexplained(tmp_path):
    out = tree(tmp_path)
    g = out["groups"]
    assert g["activeLegacyCheckpoint"]["logicalBytes"] == 100 and g["checkpointTemp"]["logicalBytes"] == 300
    assert g["missionWal"]["logicalBytes"] == 50 and g["analysisHistoryDb"]["logicalBytes"] == 70
    assert g["checkpointV2"]["files"] == 1 and g["otherFiles"]["files"] == 2
    assert out["otherFilesByTopDirectory"]["artifact_store"]["logicalBytes"] == 6000
    assert set(out["otherFilesByKind"]) == {"noExtension", "bin"}
    assert out["complete"] is True and out["availableBytes"] is not None


def test_no_file_name_leaves_and_nothing_changes(tmp_path):
    tree(tmp_path)
    def snapshot():
        return sorted((root, name, os.stat(os.path.join(root, name)).st_mtime_ns, os.stat(os.path.join(root, name)).st_size)
                      for root, _, names in os.walk(tmp_path) for name in names)
    before = snapshot()
    out = json.dumps(a.attribute(str(tmp_path), checkpoint=str(tmp_path / "state.json"), wal=str(tmp_path / "wal.jsonl")))
    assert "secret-looking-name" not in out and "chart.bin" not in out
    assert snapshot() == before                     # nothing written, moved or deleted


def test_a_bounded_walk_says_it_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "MAX_ENTRIES", 2)
    out = tree(tmp_path)
    assert out["complete"] is False and out["boundedStopped"] is True


def test_the_owner_route_adds_it_only_on_request(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    monkeypatch.setattr(scanner, "_DURABILITY_PATHS", {"root": str(tmp_path), "checkpoint": str(tmp_path / "s"), "wal": str(tmp_path / "w")})
    with scanner.app.test_client() as c:
        plain = c.get("/api/argus/admin/memory-attribution", headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
        asked = c.get("/api/argus/admin/memory-attribution?storage-groups=1", headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
        denied = c.get("/api/argus/admin/memory-attribution?storage-groups=1")
    assert "storageAttribution" not in plain and asked["storageAttribution"]["schemaVersion"] == a.SCHEMA
    assert denied.status_code in (401, 503) and "storageAttribution" not in (denied.get_json() or {})
