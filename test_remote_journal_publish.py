import json
import shutil
import subprocess
import sys
from pathlib import Path

import argus_remote_journal as journal
import argus_state_journal
import pytest

from scripts.prepare_remote_journal_publish import prepare, verify_committed


NOW = "2026-07-27T00:00:00Z"


def _snapshot(*, generated_at=NOW, padding=""):
    event = argus_state_journal.event(
        event_type="mission_recovered",
        aggregate_type="mission",
        aggregate_id="publish-test",
        sequence=1,
        occurred_at=generated_at,
        payload={},
    )
    return {
        "schemaVersion": journal.SCHEMA_V3,
        "generatedAt": generated_at,
        "padding": padding,
        "outcomes": [],
        "missionTickDurability": {"walAppliedSequence": 41},
        **journal.snapshot_journal_section(
            events=[event], meta={}, now_iso=generated_at
        ),
    }


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _paths(tmp_path, snapshot):
    source_full = tmp_path / "runner" / "memory.json"
    source_readback = tmp_path / "runner" / "readback.json"
    ledger_full = tmp_path / "ledger" / "osint" / "memory.json"
    ledger_readback = tmp_path / "ledger" / "osint" / "readback.json"
    _write(source_full, snapshot)
    _write(source_readback, journal.compact_readback_snapshot(snapshot))
    return source_full, source_readback, ledger_full, ledger_readback


def test_oversized_snapshot_retains_full_and_publishes_verified_receipt(tmp_path):
    old = _snapshot(generated_at="2026-07-26T00:00:00Z")
    new = _snapshot(padding="x" * 2048)
    source_full, source_readback, ledger_full, ledger_readback = _paths(
        tmp_path, new
    )
    _write(ledger_full, old)
    _write(ledger_readback, journal.compact_readback_snapshot(old))
    original_full = ledger_full.read_bytes()

    result = prepare(
        source_full=source_full,
        source_readback=source_readback,
        ledger_full=ledger_full,
        ledger_readback=ledger_readback,
        full_snapshot_soft_limit=512,
    )

    assert result["status"] == "prepared"
    assert result["fullSnapshotPublished"] is False
    assert result["fullSnapshotRetained"] is True
    assert result["readbackPublished"] is True
    assert ledger_full.read_bytes() == original_full
    verified = verify_committed(
        readback_path=ledger_readback,
        expected_hash=result["expectedHash"],
    )
    assert verified["status"] == "verified"
    assert verified["actualHash"] == new["integrityManifest"]["manifestHash"]


def test_small_snapshot_preserves_legacy_full_restore_contract(tmp_path):
    old = _snapshot(generated_at="2026-07-26T00:00:00Z")
    new = _snapshot()
    source_full, source_readback, ledger_full, ledger_readback = _paths(
        tmp_path, new
    )
    _write(ledger_full, old)

    result = prepare(
        source_full=source_full,
        source_readback=source_readback,
        ledger_full=ledger_full,
        ledger_readback=ledger_readback,
        full_snapshot_soft_limit=1024 * 1024,
    )

    assert result["fullSnapshotPublished"] is True
    assert json.loads(ledger_full.read_text())["generatedAt"] == NOW
    assert journal.verify_compact_readback_snapshot(
        json.loads(ledger_readback.read_text())
    )


def test_stale_snapshot_changes_neither_remote_artifact(tmp_path):
    current = _snapshot()
    stale = _snapshot(generated_at="2026-07-26T00:00:00Z")
    source_full, source_readback, ledger_full, ledger_readback = _paths(
        tmp_path, stale
    )
    _write(ledger_full, current)
    _write(ledger_readback, journal.compact_readback_snapshot(current))
    before_full = ledger_full.read_bytes()
    before_readback = ledger_readback.read_bytes()

    result = prepare(
        source_full=source_full,
        source_readback=source_readback,
        ledger_full=ledger_full,
        ledger_readback=ledger_readback,
    )

    assert result["status"] == "stale"
    assert ledger_full.read_bytes() == before_full
    assert ledger_readback.read_bytes() == before_readback


def test_exact_manifest_is_idempotent(tmp_path):
    snapshot = _snapshot()
    source_full, source_readback, ledger_full, ledger_readback = _paths(
        tmp_path, snapshot
    )
    _write(ledger_full, snapshot)
    _write(ledger_readback, journal.compact_readback_snapshot(snapshot))

    result = prepare(
        source_full=source_full,
        source_readback=source_readback,
        ledger_full=ledger_full,
        ledger_readback=ledger_readback,
    )

    assert result["status"] == "already_committed"
    assert result["readbackPublished"] is False


def test_tampered_compact_receipt_is_rejected(tmp_path):
    snapshot = _snapshot()
    source_full, source_readback, ledger_full, ledger_readback = _paths(
        tmp_path, snapshot
    )
    receipt = json.loads(source_readback.read_text())
    receipt["missionTickDurability"]["walAppliedSequence"] = 999
    _write(source_readback, receipt)

    with pytest.raises(ValueError, match="compact_readback_not_verifiable"):
        prepare(
            source_full=source_full,
            source_readback=source_readback,
            ledger_full=ledger_full,
            ledger_readback=ledger_readback,
        )


def test_committed_hash_mismatch_is_rejected(tmp_path):
    snapshot = _snapshot()
    _, source_readback, _, _ = _paths(tmp_path, snapshot)
    with pytest.raises(
        ValueError, match="committed_compact_readback_hash_mismatch"
    ):
        verify_committed(
            readback_path=source_readback, expected_hash="0" * 16
        )


def test_copied_cli_runs_after_workflow_switches_to_ledger_branch(tmp_path):
    snapshot = _snapshot()
    source_full, source_readback, ledger_full, ledger_readback = _paths(
        tmp_path, snapshot
    )
    runner = tmp_path / "runner-bin"
    runner.mkdir()
    root = Path(__file__).resolve().parent
    shutil.copyfile(
        root / "scripts" / "prepare_remote_journal_publish.py",
        runner / "prepare_remote_journal_publish.py",
    )
    shutil.copyfile(
        root / "argus_remote_journal.py", runner / "argus_remote_journal.py"
    )
    ledger_full.parent.mkdir(parents=True, exist_ok=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(runner / "prepare_remote_journal_publish.py"),
            "prepare",
            "--source-full",
            str(source_full),
            "--source-readback",
            str(source_readback),
            "--ledger-full",
            str(ledger_full),
            "--ledger-readback",
            str(ledger_readback),
        ],
        cwd=tmp_path / "ledger",
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout)["status"] == "prepared"
    assert journal.verify_compact_readback_snapshot(
        json.loads(ledger_readback.read_text())
    )
