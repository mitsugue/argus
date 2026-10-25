"""2026-10-20: the history synchronisation writes v3 first and v2 only until v3 holds everything."""
import json

import pytest

import argus_analysis_history as history
import argus_analysis_history_backup as backup
import argus_analysis_history_parts as parts
import scanner


@pytest.fixture
def wired(tmp_path, monkeypatch):
    path = tmp_path / 'history.sqlite'
    history.initialize(str(path))
    monkeypatch.setattr(scanner, '_market_brief_history_path', lambda: str(path))
    monkeypatch.setenv('ARGUS_LAYER2B_PRIVATE_REPO', 'owner/private-history')
    monkeypatch.setenv('ARGUS_LAYER2B_PRIVATE_TOKEN', 'test-only-token')
    monkeypatch.setattr(scanner, '_gh_private_headers', lambda: {})
    monkeypatch.setattr(backup, 'GitHubStore', lambda **kwargs: object())
    monkeypatch.setattr(scanner, '_MARKET_BRIEF_HISTORY_REMOTE',
                        {"status": "NOT_RUN", "lastVerifiedAt": None, "lastAttemptAt": None, "headVersion": None})
    calls = []
    def v2(local_path, remote, *, last_verified_head=None):
        calls.append('v2')
        return {'status': 'VERIFIED', 'headVersion': 'sha-v2', 'restoredCounts': None,
                'counts': {'views': 1, 'outcomes': 0}}
    monkeypatch.setattr(backup, 'synchronize', v2)
    return calls


def _v3(complete):
    def sync(local_path, remote):
        return {'status': 'VERIFIED', 'complete': complete, 'counts': {'views': 1, 'outcomes': 0, 'parts': 3},
                'written': {'packs': 1, 'views': 1, 'outcomes': 0}, 'restoredCounts': None,
                'capacity': parts.capacity({'storedBytes': 10, 'rawBytes': 20})}
    return sync


def test_v2_is_no_longer_written_once_v3_holds_every_record(wired, monkeypatch):
    monkeypatch.setattr(parts, 'synchronize', _v3(True))
    scanner._market_brief_history_sync()
    status = scanner._market_brief_history_remote_status()
    assert wired == [] and status['status'] == 'VERIFIED' and status['formatVersion'] == 3
    assert status['v3']['complete'] is True and status['v3']['capacity']['warning'] is False
    assert status['v2'] == 'READ_ONLY_SUPERSEDED_BY_V3'
    assert 'test-only-token' not in json.dumps(status)


def test_v2_is_not_written_while_v3_migrates_successfully(wired, monkeypatch):
    """2026-10-20: v2 timed out after every restart and its failure slowed the v3 migration to 30 minutes."""
    monkeypatch.setattr(parts, 'synchronize', _v3(False))
    scanner._market_brief_history_sync()
    status = scanner._MARKET_BRIEF_HISTORY_REMOTE
    assert wired == [] and status['v3']['complete'] is False
    assert status['status'] == 'VERIFIED' and status['v2'] == 'READ_ONLY_V3_MIGRATING' and status['errorClass'] is None


def test_a_v3_failure_keeps_the_v2_backup_running_and_visible(wired, monkeypatch):
    def broken(local_path, remote):
        raise ValueError('history_v3_pack_integrity')
    monkeypatch.setattr(parts, 'synchronize', broken)
    scanner._market_brief_history_sync()
    assert wired == ['v2']
    assert scanner._MARKET_BRIEF_HISTORY_REMOTE['v3'] ['status'] == 'FAILED'
    assert scanner._MARKET_BRIEF_HISTORY_REMOTE['v3']['errorClass'] == 'ValueError'


def test_the_backup_runs_on_its_own_cadence_not_only_after_a_brief():
    import inspect
    source = inspect.getsource(scanner)
    assert 'target=_analysis_history_backup_tick' in source
    assert 'name="market-brief-history-sync-resident"' in source
    # the call keeps its own interval and lock
    body = inspect.getsource(scanner._market_brief_history_sync)
    assert '_MARKET_BRIEF_HISTORY_SYNC_LOCK.acquire(blocking=False)' in body and 'interval' in body


@pytest.fixture
def settled_run(wired, monkeypatch):
    """2026-10-25: an unchanged history skips the remote read for up to six hours."""
    runs = []
    v3 = _v3(True)

    def counted(local_path, remote):
        runs.append(local_path)
        return v3(local_path, remote)

    monkeypatch.setattr(parts, 'synchronize', counted)
    monkeypatch.setattr(scanner, '_ANALYSIS_HISTORY_FORM', {"status": "NOT_RUN"})
    monkeypatch.setattr(scanner, '_analysis_history_form_step', lambda path: scanner._ANALYSIS_HISTORY_FORM.update(
        status="CONVERTED", verifiedAll={"checked": 1}))
    fingerprint = {"value": ((1, 1), (None, 0))}
    monkeypatch.setattr(scanner, '_market_brief_history_fingerprint', lambda path: fingerprint["value"])
    clock = {"now": 1000.0}
    monkeypatch.setattr(scanner.time, 'monotonic', lambda: clock["now"])
    return runs, fingerprint, clock


def test_an_unchanged_history_does_not_read_the_remote_again(settled_run):
    runs, _fingerprint, clock = settled_run
    scanner._market_brief_history_sync()
    clock["now"] += 601
    scanner._market_brief_history_sync()
    assert len(runs) == 1
    assert scanner._MARKET_BRIEF_HISTORY_REMOTE['status'] == 'VERIFIED'
    assert scanner._MARKET_BRIEF_HISTORY_REMOTE['unchangedSkips'] == 1


def test_a_new_record_is_synchronised_on_the_next_round(settled_run):
    runs, fingerprint, clock = settled_run
    scanner._market_brief_history_sync()
    fingerprint["value"] = ((2, 2), (None, 0))
    clock["now"] += 601
    scanner._market_brief_history_sync()
    assert len(runs) == 2


def test_the_remote_is_verified_again_after_six_hours(settled_run):
    runs, _fingerprint, clock = settled_run
    scanner._market_brief_history_sync()
    clock["now"] += scanner._MARKET_BRIEF_HISTORY_RECHECK_SEC
    scanner._market_brief_history_sync()
    assert len(runs) == 2


def test_an_unconverted_or_unverified_form_keeps_running(settled_run, monkeypatch):
    runs, _fingerprint, clock = settled_run
    monkeypatch.setattr(scanner, '_analysis_history_form_step', lambda path: scanner._ANALYSIS_HISTORY_FORM.update(
        status="CONVERTING"))
    scanner._market_brief_history_sync()
    clock["now"] += 601
    scanner._market_brief_history_sync()
    assert len(runs) == 2


def test_the_fingerprint_reads_counts_without_bodies(tmp_path):
    path = tmp_path / 'history.sqlite'
    history.initialize(str(path))
    assert scanner._market_brief_history_fingerprint(str(path)) == ((None, 0), (None, 0))
    assert scanner._market_brief_history_fingerprint(str(tmp_path / 'missing.sqlite')) is None
