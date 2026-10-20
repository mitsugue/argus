"""2026-10-20 (owner): abandoned recovery-pair copies and work directories are removed at start
under the existing safety rules; incident evidence is untouched; counts and sizes are recorded first."""
import json
import os
import time

import argus_persistent_storage as storage

CHECKPOINT = "argus_osint_memory.json"
SIDECAR = "argus_remote_recovery.json"
HEX = "0123456789abcdef0123456789abcdef"
OLD = time.time() - 2 * 86400


def make(path, size, mtime=OLD):
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def staging(tmp_path, *, probe=lambda pid, **k: False, cleanup=True, now=None):
    return storage.reconcile_abandoned_recovery_staging(
        str(tmp_path), checkpoint_name=CHECKPOINT, sidecar_name=SIDECAR,
        cleanup=cleanup, now=now, owner_probe=probe)


def test_old_unowned_copies_are_removed_and_counted_first(tmp_path, capsys):
    pair = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.recovery-pair-checkpoint", 900)
    lock = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.recovery-pair-checkpoint.writer.lock", 0)
    cand = make(tmp_path / f"{SIDECAR}.7.{HEX}.candidate", 100)
    inner = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.recovery-pair-checkpoint.7.{HEX}.v1338-tmp", 50)
    out = staging(tmp_path)
    assert out["detectedCount"] == 4 and out["detectedBytes"] == 1050
    assert out["removedCount"] == 4 and out["removedBytes"] == 1050
    assert not any(p.exists() for p in (pair, lock, cand, inner))
    logged = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert logged == {"event": "abandoned_recovery_staging", "detectedCount": 4, "detectedBytes": 1050,
                      "eligibleCount": 4, "eligibleBytes": 1050}


def test_incident_evidence_and_unmarked_temps_are_never_touched(tmp_path):
    evidence = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.tmp", 500)              # pre-hotfix evidence
    unmarked = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.recovery-pair-checkpoint.7.{HEX}.tmp", 40)
    out = staging(tmp_path)
    assert out["detectedCount"] == 0 and evidence.exists() and unmarked.exists()
    assert storage.reconcile_abandoned_checkpoint_temps(str(tmp_path / CHECKPOINT), cleanup=True)["removedCount"] == 0


def test_a_live_or_young_or_unprovable_copy_stays(tmp_path):
    live = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.recovery-pair-checkpoint", 10)
    assert staging(tmp_path, probe=lambda pid, **k: True)["removedCount"] == 0 and live.exists()
    assert staging(tmp_path, probe=lambda pid, **k: None)["removedCount"] == 0 and live.exists()
    young = make(tmp_path / f"{SIDECAR}.8.{HEX}.candidate", 10, mtime=time.time())
    out = staging(tmp_path, probe=lambda pid, **k: pid == 7)
    assert out["removedCount"] == 0 and young.exists() and live.exists()


def test_without_cleanup_only_counts(tmp_path):
    pair = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.recovery-pair-checkpoint", 10)
    out = staging(tmp_path, cleanup=False)
    assert out["eligibleCount"] == 1 and out["removedCount"] == 0 and pair.exists()


def work(tmp_path, name, *, mtime=OLD):
    directory = tmp_path / name
    (directory / "sub").mkdir(parents=True)
    a = make(directory / "archive.ndjson", 300, mtime)
    b = make(directory / "sub" / "H", 200, mtime)
    os.utime(directory / "sub", (mtime, mtime)); os.utime(directory, (mtime, mtime))
    return directory, (a, b)


def test_old_unused_work_directories_are_removed(tmp_path, capsys):
    directory, _ = work(tmp_path, ".analysis-recovery-abc")
    other, _ = work(tmp_path, ".analysis-compact-def")
    keep = tmp_path / "market_analysis_history.sqlite3"; make(keep, 10)
    out = storage.reconcile_abandoned_work_directories(str(tmp_path), cleanup=True, open_inodes=lambda: set())
    assert out["detectedCount"] == 2 and out["detectedBytes"] == 1000 and out["removedCount"] == 2
    assert not directory.exists() and not other.exists() and keep.exists()
    assert '"event": "abandoned_work_directories"' in capsys.readouterr().out


def test_work_directories_in_use_young_or_unprovable_stay(tmp_path):
    directory, (a, _) = work(tmp_path, ".analysis-recovery-abc")
    st = os.stat(a)
    assert storage.reconcile_abandoned_work_directories(
        str(tmp_path), cleanup=True, open_inodes=lambda: {(st.st_dev, st.st_ino)})["removedCount"] == 0
    assert storage.reconcile_abandoned_work_directories(
        str(tmp_path), cleanup=True, open_inodes=lambda: None)["removedCount"] == 0
    young, _ = work(tmp_path, ".analysis-compact-new", mtime=time.time())
    out = storage.reconcile_abandoned_work_directories(str(tmp_path), cleanup=True, open_inodes=lambda: set())
    assert directory.exists() is False and young.exists()          # only the old unused one went


def test_a_symlink_inside_keeps_the_directory(tmp_path):
    directory, _ = work(tmp_path, ".analysis-recovery-abc")
    target = make(tmp_path / "outside", 5)
    os.symlink(target, directory / "link")
    out = storage.reconcile_abandoned_work_directories(str(tmp_path), cleanup=True, open_inodes=lambda: set())
    assert out["removedCount"] == 0 and directory.exists() and target.exists()


def test_owner_released_incident_evidence_is_recorded_then_removed(tmp_path, capsys):
    import hashlib
    evidence = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.tmp", 700, mtime=storage.INCIDENT_EVIDENCE_RELEASE_BEFORE - 86400)
    expected = hashlib.sha256(evidence.read_bytes()).hexdigest()
    newer = make(tmp_path / f"{CHECKPOINT}.8.{HEX}.tmp", 300)       # after the cutoff: still evidence
    out = storage.reconcile_abandoned_checkpoint_temps(
        str(tmp_path / CHECKPOINT), cleanup=True, owner_probe=lambda *a, **k: False,
        release_incident_evidence=True)
    assert not evidence.exists() and newer.exists()
    assert out["releasedIncidentEvidenceCount"] == 1 and out["releasedIncidentEvidenceBytes"] == 700
    released = [r for r in out["entries"] if r["classification"] == "released_incident_evidence"][0]
    assert released["sha256"] == expected and released["removed"] is True
    logged = json.loads([l for l in capsys.readouterr().out.splitlines() if "incident_evidence_release" in l][0])
    assert logged["sha256"] == expected and logged["bytes"] == 700


def test_released_evidence_still_needs_no_owner(tmp_path):
    evidence = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.tmp", 700, mtime=storage.INCIDENT_EVIDENCE_RELEASE_BEFORE - 86400)
    for probe in (lambda *a, **k: True, lambda *a, **k: None):
        out = storage.reconcile_abandoned_checkpoint_temps(
            str(tmp_path / CHECKPOINT), cleanup=True, owner_probe=probe, release_incident_evidence=True)
        assert out["releasedIncidentEvidenceCount"] == 0 and evidence.exists()


def test_without_the_release_the_no_read_contract_stays(tmp_path):
    from unittest import mock
    evidence = make(tmp_path / f"{CHECKPOINT}.7.{HEX}.tmp", 700, mtime=storage.INCIDENT_EVIDENCE_RELEASE_BEFORE - 86400)
    with mock.patch.object(storage.os, "open", side_effect=AssertionError("opened")):
        out = storage.reconcile_abandoned_checkpoint_temps(
            str(tmp_path / CHECKPOINT), cleanup=True, owner_probe=lambda *a, **k: False)
    assert out["retainedIncidentEvidenceCount"] == 1 and evidence.exists()
