"""Tests for argus_ai_cost — the AI cost ledger + hard budget stops (v10.50)."""
import datetime as dt
import argus_ai_cost as c


def test_estimate_cost_basic():
    # 1M input @ $1.25 + 1M output @ $10 = $11.25
    assert c.estimate_cost("gpt-5.5", 1_000_000, 1_000_000) == 11.25
    assert c.estimate_cost("gpt-5.5", 0, 0) == 0.0


def test_estimate_cost_grounding_and_unknown_model():
    base = c.estimate_cost("gemini-2.5-pro", 1000, 500)
    withg = c.estimate_cost("gemini-2.5-pro", 1000, 500, grounding=True, grounding_usd=0.035)
    assert round(withg - base, 6) == 0.035
    assert c.estimate_cost("nonexistent-model", 9_999_999, 9_999_999) == 0.0   # honest 0, not fabricated


def test_estimate_cost_bad_inputs_safe():
    assert c.estimate_cost("gpt-5.5", None, "x") == 0.0
    assert c.estimate_cost("gpt-5.5", True, False) == 0.0          # bools are not token counts


def test_budget_check_under_allows():
    ok, why, reserve = c.budget_check(1.0, 10.0, 5.0, 80.0, 2.0)
    assert ok and why is None and reserve is False


def test_budget_check_daily_stop():
    ok, why, _ = c.budget_check(5.0, 10.0, 5.0, 80.0)
    assert not ok and "daily" in why


def test_budget_check_monthly_stop_and_reserve():
    ok, why, _ = c.budget_check(1.0, 80.0, 5.0, 80.0, 2.0)
    assert not ok and "monthly" in why
    # force dips into the reserve up to budget+reserve
    ok2, _, used = c.budget_check(1.0, 80.5, 5.0, 80.0, 2.0, force=True)
    assert ok2 and used is True
    # reserve exhausted → still blocked even with force
    ok3, _, _ = c.budget_check(1.0, 82.0, 5.0, 80.0, 2.0, force=True)
    assert not ok3


def test_budget_zero_is_unlimited():
    ok, why, _ = c.budget_check(999.0, 9999.0, 0, 0)
    assert ok and why is None


def test_keys():
    d = dt.datetime(2026, 6, 22, 16, 5)
    assert c.month_key(d) == "2026-06"
    assert c.day_key(d) == "2026-06-22"


# The price math above is unchanged. These exercise restoration independently
# from the display window and from any AI/provider invocation.
def _record(at='2026-09-12T06:00:00Z', amount=0.3):
    return {'at': at, 'runId': 'prose-test', 'totalUsd': amount, 'rows': []}


def _prior():
    return {'month': '2026-09', 'day': '2026-09-11', 'asOf': '2026-09-11T12:00:00Z',
            'monthSpentUsd': 0.2, 'daySpentUsd': 0.1, 'recentRuns': []}


def _now():
    return dt.datetime(2026, 9, 12, 16, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def test_late_restore_keeps_disjoint_calls_and_is_idempotent():
    state = c.record_accounting(None, _record(), 'a' * 32)
    merged = c.import_legacy_snapshot(state, _prior())
    assert c.accounting_totals(merged, _now())['monthSpentUsd'] == 0.5
    assert c.accounting_totals(merged, _now())['daySpentUsd'] == 0.3
    assert c.import_legacy_snapshot(merged, _prior()) == merged
    remote = {'accounting': merged}
    newer = c.record_accounting(merged, _record(amount=0.4), 'a' * 32)
    assert c.import_legacy_snapshot(newer, remote) == newer
    assert c.accounting_totals(newer, _now())['monthSpentUsd'] == 0.9


def test_restoration_commutes_across_independent_writers():
    import itertools
    states = [c.record_accounting(None, _record(amount=i / 10), char * 32)
              for i, char in enumerate('abc', 1)]
    outcomes = []
    for order in itertools.permutations(states):
        merged = None
        for state in order:
            merged = c.merge_accounting(merged, state)
        outcomes.append(merged)
    assert all(x == outcomes[0] for x in outcomes)
    assert c.accounting_totals(outcomes[0], _now())['monthSpentUsd'] == 0.6


def test_more_than_500_calls_and_restart_do_not_trim_cumulative_cost():
    state = c.import_legacy_snapshot(None, _prior())
    for _ in range(520):
        state = c.record_accounting(state, _record(amount=0.01), 'a' * 32)
    import json
    restored = json.loads(json.dumps(state))
    restored = c.record_accounting(restored, _record(amount=0.01), 'b' * 32)
    totals = c.accounting_totals(restored, _now())
    assert totals['recordedMonthCalls'] == 521
    assert totals['monthSpentUsd'] == 5.41
    assert totals['daySpentUsd'] == 5.21
    assert len(totals['recentRuns']) == 20
    assert len(restored['recent']) == 50
    assert totals['displayWindowAffectsTotals'] is False


def test_jst_midnight_and_month_rollover_preserve_old_buckets():
    state = c.record_accounting(None, _record('2026-09-30T14:59:59Z', 0.3), 'a' * 32)
    state = c.record_accounting(state, _record('2026-09-30T15:00:00Z', 0.4), 'a' * 32)
    september = c.accounting_totals(state, dt.datetime.fromisoformat('2026-09-30T23:59:59+09:00'))
    october = c.accounting_totals(state, dt.datetime.fromisoformat('2026-10-01T00:00:00+09:00'))
    assert september['monthSpentUsd'] == 0.3
    assert october['monthSpentUsd'] == 0.4
    assert len(state['writers']) == 2


def test_malformed_or_conflicting_saved_cost_never_resets_live_state():
    import copy
    import pytest
    state = c.record_accounting(None, _record(), 'a' * 32)
    before = copy.deepcopy(state)
    corrupt = copy.deepcopy(state); next(iter(corrupt['writers'].values()))['micros'] += 1
    with pytest.raises(ValueError, match='prefix_conflict'):
        c.merge_accounting(state, corrupt)
    for value in [float('nan'), -1, True]:
        with pytest.raises(ValueError):
            c.record_accounting(state, _record(amount=value), 'b' * 32)
    with pytest.raises(ValueError):
        c.import_legacy_snapshot(state, {})
    assert state == before


def test_legacy_reported_baselines_are_not_claimed_as_reconstructed_history():
    prior = _prior(); prior['recentRuns'] = [_record('2026-09-11T11:00:00Z', 0.05)] * 2
    state = c.import_legacy_snapshot(None, prior)
    assert len(state['recent']) == 2
    totals = c.accounting_totals(state, _now())
    assert totals['monthSpentUsd'] == 0.2
    assert totals['historicalCallsReconstructed'] is False
    assert totals['recordedMonthCalls'] == 0


def _runtime(monkeypatch, tmp_path):
    import scanner
    from collections import deque
    monkeypatch.setattr(scanner, '_COST_POLICY', scanner.argus_cost_policy.default_state('SCHEDULED_AI', True))
    monkeypatch.setattr(scanner, '_COST_POLICY_DURABLE', {'enabled': True, 'lastError': None})
    monkeypatch.setattr(scanner, '_cost_policy_durable_path', lambda: str(tmp_path / 'cost.json'))
    monkeypatch.setattr(scanner, '_cost_policy_checkpoint_after_write', lambda _: None)
    monkeypatch.setattr(scanner, '_AI_COST_STATE', {'restoredMonth': None, 'runs': deque(maxlen=50)})
    monkeypatch.setattr(scanner, '_AI_COST_RESTORE_STATE', {'lastTry': 0.0, 'lastError': None})
    monkeypatch.setattr(scanner, '_AI_COST_WRITER_ID', 'a' * 32)
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 12, 7, tzinfo=dt.timezone.utc).astimezone(tz)
    monkeypatch.setattr(scanner, 'datetime', Clock)
    return scanner


def test_runtime_prose_before_restore_and_public_snapshot_overlap(monkeypatch, tmp_path):
    import io, json
    scanner = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(scanner.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(_prior()).encode()))
    scanner._ai_record_prose_cost('gpt-6-astra', 10, 10, 0.3, purpose='market_brief')
    scanner._ai_cost_restore_once()
    saved = scanner._ai_cost_snapshot()
    assert saved['monthSpentUsd'] == 0.5
    assert saved['daySpentUsd'] == 0.3
    assert saved['accountingStatus']['recordedMonthCalls'] == 1
    scanner._AI_COST_STATE['restoredMonth'] = None
    scanner._AI_COST_RESTORE_STATE['lastTry'] = 0
    monkeypatch.setattr(scanner.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(saved).encode()))
    scanner._ai_record_prose_cost('gpt-6-astra', 10, 10, 0.4, purpose='market_brief')
    scanner._ai_cost_restore_once()
    assert scanner._ai_cost_snapshot()['monthSpentUsd'] == 0.9
    assert scanner._ai_cost_snapshot()['accountingStatus']['recordedMonthCalls'] == 2


def test_runtime_concurrent_writes_and_restart_preserve_each_call(monkeypatch, tmp_path):
    import concurrent.futures, json
    scanner = _runtime(monkeypatch, tmp_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.01), range(32)))
    live = scanner._ai_cost_snapshot()
    assert live['daySpentUsd'] == 0.32
    assert live['accountingStatus']['recordedMonthCalls'] == 32
    saved = json.loads((tmp_path / 'cost.json').read_text())
    assert saved['legacyAiCost'] == live['accounting']
    scanner._COST_POLICY.clear(); scanner._COST_POLICY.update(scanner.argus_cost_policy.default_state('SCHEDULED_AI', True))
    scanner._cost_policy_restore_durable()
    assert scanner._ai_cost_snapshot()['accounting'] == live['accounting']
    monkeypatch.setattr(scanner, '_AI_COST_WRITER_ID', 'b' * 32)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.01)
    assert scanner._ai_cost_snapshot()['daySpentUsd'] == 0.33
    # The existing full checkpoint serializes normalized costPolicy. A stale
    # copy can be restored repeatedly without replacing the newer local prefix.
    restored = scanner.argus_cost_policy.normalize_state(saved)['legacyAiCost']
    with scanner._COST_POLICY_LOCK:
        scanner._COST_POLICY['legacyAiCost'] = c.merge_accounting(scanner._COST_POLICY['legacyAiCost'], restored)
    assert scanner._ai_cost_snapshot()['daySpentUsd'] == 0.33


def test_write_failure_keeps_prior_file_and_live_usage_visible(monkeypatch, tmp_path):
    scanner = _runtime(monkeypatch, tmp_path)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.1)
    prior = (tmp_path / 'cost.json').read_bytes()
    def fail(*a, **kw):
        raise OSError('simulated_write_failure')
    monkeypatch.setattr(scanner.os, 'replace', fail)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.2)
    assert (tmp_path / 'cost.json').read_bytes() == prior
    assert scanner._ai_cost_snapshot()['daySpentUsd'] == 0.3
    assert scanner._COST_POLICY_DURABLE['lastError'] == 'OSError'


def test_failed_remote_restore_is_reported_and_read_does_not_retry(monkeypatch, tmp_path):
    import json
    scanner = _runtime(monkeypatch, tmp_path)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.3)
    prior = json.dumps(scanner._COST_POLICY, sort_keys=True)
    def fail(*a, **kw):
        raise TimeoutError('simulated_timeout')
    monkeypatch.setattr(scanner.urllib.request, 'urlopen', fail)
    scanner._ai_cost_restore_once()
    assert scanner._ai_cost_snapshot()['restoreError'] == 'TimeoutError'
    assert scanner._AI_COST_STATE['restoredMonth'] is None
    assert json.dumps(scanner._COST_POLICY, sort_keys=True) == prior


def test_remote_restore_while_another_cost_finishes_keeps_both(monkeypatch, tmp_path):
    import threading, io, json
    scanner = _runtime(monkeypatch, tmp_path)
    entered, release = threading.Event(), threading.Event()
    def response(*a, **kw):
        entered.set()
        assert release.wait(5)
        return io.BytesIO(json.dumps(_prior()).encode())
    monkeypatch.setattr(scanner.urllib.request, 'urlopen', response)
    worker = threading.Thread(target=scanner._ai_cost_restore_once)
    worker.start(); assert entered.wait(5)
    try:
        scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.3)
    finally:
        release.set(); worker.join(5)
    assert not worker.is_alive()
    assert scanner._ai_cost_snapshot()['monthSpentUsd'] == 0.5
    persisted = json.loads((tmp_path / 'cost.json').read_text())
    assert persisted['legacyAiCost'] == scanner._ai_cost_snapshot()['accounting']


def test_corrupt_durable_file_keeps_memory_and_reports_error(monkeypatch, tmp_path):
    scanner = _runtime(monkeypatch, tmp_path)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.3)
    (tmp_path / 'cost.json').write_text('{bad')
    assert scanner._cost_policy_restore_durable() == 0
    snapshot = scanner._ai_cost_snapshot()
    assert snapshot['daySpentUsd'] == 0.3
    assert snapshot['accountingDurability']['lastError'] == 'JSONDecodeError'


def test_full_checkpoint_cost_capture_is_detached_and_retains_accounting(monkeypatch, tmp_path):
    scanner = _runtime(monkeypatch, tmp_path)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.3)
    checkpoint = scanner._cost_policy_checkpoint_snapshot()
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.4)
    assert c.accounting_totals(checkpoint['legacyAiCost'], _now())['daySpentUsd'] == 0.3
    assert scanner._ai_cost_snapshot()['daySpentUsd'] == 0.7
    # The freeze hook used by the existing encrypted full checkpoint preserves
    # the exact prefix; later local restoration merges rather than overwrites it.
    import inspect
    assert '_cost_policy_checkpoint_snapshot' in inspect.getsource(scanner._osint_persist_locked)


def test_pre_upgrade_baseline_import_uses_existing_startup_restore(monkeypatch, tmp_path):
    import json
    scanner = _runtime(monkeypatch, tmp_path)
    scanner._ai_record_prose_cost('gpt-6-astra', 1, 1, 0.3)
    (tmp_path / 'ai_cost_migration_baseline.json').write_text(json.dumps(_prior()))
    scanner._cost_policy_restore_durable()
    assert scanner._ai_cost_snapshot()['monthSpentUsd'] == 0.5
    scanner._cost_policy_restore_durable()
    assert scanner._ai_cost_snapshot()['monthSpentUsd'] == 0.5
    assert scanner._cost_policy_checkpoint_snapshot()['legacyAiCost']['legacyMonths']['2026-09']['micros'] == 200000
    (tmp_path / 'ai_cost_migration_baseline.json').write_text('{bad')
    scanner._cost_policy_restore_durable()
    assert scanner._ai_cost_snapshot()['monthSpentUsd'] == 0.5
    assert scanner._ai_cost_snapshot()['accountingDurability']['migrationError'] == 'JSONDecodeError'
