"""Cost-triggered full checkpoints at most once per interval (owner decision 2026-10-16).

The usage ledger is fsynced on every write. Only the full checkpoint it
requests (the remote-recovery copy, about 19 s each and 24 times in 50 minutes
on one CPU) is limited, and skipped when another full checkpoint has started
since the request.
"""
import threading
import time

import pytest

import scanner


@pytest.fixture
def checkpoints(monkeypatch):
    saves = []

    def persist():
        started = time.monotonic()
        saves.append(started)
        scanner._FULL_CHECKPOINT_STATE["lastVerifiedStartedMonotonic"] = started
        return {"verified": True}

    monkeypatch.setattr(scanner, "_osint_persist", persist)
    monkeypatch.setitem(scanner._COST_CHECKPOINT_STATE, "running", False)
    monkeypatch.setitem(scanner._COST_CHECKPOINT_STATE, "pending", False)
    monkeypatch.setitem(scanner._COST_CHECKPOINT_STATE, "skippedAsCovered", 0)
    return saves


def _wait_idle(timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with scanner._COST_CHECKPOINT_LOCK:
            if not scanner._COST_CHECKPOINT_STATE["running"]:
                return True
        time.sleep(0.01)
    return False


def test_the_production_interval_is_fifteen_minutes():
    source = open(scanner.__file__, encoding="utf-8").read()
    assert "_COST_CHECKPOINT_MIN_INTERVAL_SEC = 900.0" in source


def test_requests_inside_the_interval_wait_for_one_later_checkpoint(monkeypatch, checkpoints):
    monkeypatch.setattr(scanner, "_COST_CHECKPOINT_MIN_INTERVAL_SEC", 0.4)
    scanner._cost_policy_checkpoint_after_write(True)
    assert _wait_idle()
    assert len(checkpoints) == 1                     # the first one is immediate
    for _ in range(5):                               # five more settlements
        scanner._cost_policy_checkpoint_after_write(True)
    time.sleep(0.1)
    assert len(checkpoints) == 1                     # still inside the interval
    assert _wait_idle()
    assert len(checkpoints) == 2                     # coalesced into one
    assert checkpoints[1] - checkpoints[0] >= 0.39


def test_a_full_checkpoint_started_after_the_request_covers_it(monkeypatch, checkpoints):
    monkeypatch.setattr(scanner, "_COST_CHECKPOINT_MIN_INTERVAL_SEC", 0.5)
    scanner._cost_policy_checkpoint_after_write(True)
    assert _wait_idle() and len(checkpoints) == 1
    scanner._cost_policy_checkpoint_after_write(True)   # waits for the interval
    time.sleep(0.05)
    # A mission tick (another caller) completes a verified checkpoint meanwhile.
    scanner._FULL_CHECKPOINT_STATE["lastVerifiedStartedMonotonic"] = time.monotonic()
    with scanner._COST_CHECKPOINT_CONDITION:
        scanner._COST_CHECKPOINT_CONDITION.notify_all()
    assert _wait_idle()
    assert len(checkpoints) == 1
    assert scanner._COST_CHECKPOINT_STATE["skippedAsCovered"] == 1


def test_an_unwritten_ledger_still_saves_synchronously(monkeypatch, checkpoints):
    monkeypatch.setattr(scanner, "_COST_CHECKPOINT_MIN_INTERVAL_SEC", 900.0)
    scanner._COST_CHECKPOINT_STATE["lastCostCheckpointMonotonic"] = time.monotonic()
    scanner._cost_policy_checkpoint_after_write(False)
    assert len(checkpoints) == 1                     # never deferred


def test_a_checkpoint_between_two_requests_does_not_cover_the_later_one(monkeypatch, checkpoints):
    """Audit 2026-10-17: coverage was judged against the first request only."""
    monkeypatch.setattr(scanner, "_COST_CHECKPOINT_MIN_INTERVAL_SEC", 0.5)
    scanner._cost_policy_checkpoint_after_write(True)
    assert _wait_idle() and len(checkpoints) == 1
    scanner._cost_policy_checkpoint_after_write(True)   # first request, waits
    time.sleep(0.05)
    # Another caller's checkpoint starts after the first request ...
    scanner._FULL_CHECKPOINT_STATE["lastVerifiedStartedMonotonic"] = time.monotonic()
    time.sleep(0.02)
    scanner._cost_policy_checkpoint_after_write(True)   # ... and a later settlement follows it
    assert _wait_idle()
    assert len(checkpoints) == 2                        # the later rows are still saved
    assert scanner._COST_CHECKPOINT_STATE["skippedAsCovered"] == 0


def test_the_deferred_time_is_the_time_actually_waited(monkeypatch, checkpoints):
    monkeypatch.setattr(scanner, "_COST_CHECKPOINT_MIN_INTERVAL_SEC", 0.4)
    monkeypatch.setitem(scanner._COST_CHECKPOINT_STATE, "deferredSeconds", 0.0)
    scanner._cost_policy_checkpoint_after_write(True)
    assert _wait_idle()
    started = time.monotonic()
    for _ in range(4):                                  # early wake-ups while waiting
        scanner._cost_policy_checkpoint_after_write(True)
        with scanner._COST_CHECKPOINT_CONDITION:
            scanner._COST_CHECKPOINT_CONDITION.notify_all()
        time.sleep(0.05)
    assert _wait_idle()
    assert scanner._COST_CHECKPOINT_STATE["deferredSeconds"] <= time.monotonic() - started + 0.05
