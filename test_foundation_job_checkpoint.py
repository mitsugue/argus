import copy
from pathlib import Path

import argus_foundation_job_checkpoint as checkpoint
import argus_foundation_jobs as jobs


NOW = "2026-07-29T01:00:00Z"


def _state(status="running", updated=NOW):
    state = jobs.empty_state()
    started = jobs.start_job(
        state,
        job_type="JQUANTS_BREADTH_INCREMENTAL",
        now_iso=updated,
        parameters={"from": "2026-07-28", "to": "2026-07-28"},
    )
    state = started["state"]
    state["jobs"][0]["status"] = status
    return state


def test_envelope_is_integrity_bound():
    payload = checkpoint.envelope(_state(), saved_at=NOW)
    assert checkpoint.verify(payload)
    tampered = copy.deepcopy(payload)
    tampered["state"]["jobs"][0]["status"] = "completed"
    assert not checkpoint.verify(tampered)


def test_restore_marks_orphaned_worker_resumable_failure():
    payload = checkpoint.envelope(_state(), saved_at=NOW)
    restored = checkpoint.restored_state(payload, jobs.empty_state())
    assert restored["activeJobId"] is None
    assert restored["jobs"][0]["status"] == "failed"
    assert restored["jobs"][0]["errorClass"] == \
        "process_restarted_resume_required"


def test_older_sidecar_cannot_roll_back_newer_job_state():
    current = _state(status="completed", updated="2026-07-29T02:00:00Z")
    old = checkpoint.envelope(
        _state(status="failed", updated="2026-07-29T01:00:00Z"),
        saved_at=NOW,
    )
    restored = checkpoint.restored_state(old, current)
    assert restored["jobs"][0]["status"] == "completed"


def test_breadth_child_never_requests_full_checkpoint_while_alive():
    source = (Path(__file__).parent / "scanner.py").read_text(encoding="utf-8")
    remote_update = source.split(
        "    def remote_update(target_job_id", 1
    )[1].split("    def mirrored_commit", 1)[0]
    assert '"persist": False' in remote_update
    supervisor_tail = source.split(
        "    final = _foundation_job(job_id) or {}", 1
    )[1].split("\ndef _journal_reverify_worker", 1)[0]
    assert "_foundation_job_update(job_id, status=\"completed\"" in supervisor_tail
