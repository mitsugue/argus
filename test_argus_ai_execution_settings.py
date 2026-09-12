"""Owner execution settings: remove monetary stops without erasing usage."""
import pytest

import argus_ai_gate
import argus_cost_policy as cp
import scanner


@pytest.fixture
def full_execution(monkeypatch):
    monkeypatch.setattr(scanner, '_AI_BUDGET_ENFORCED', False)
    monkeypatch.setattr(scanner, '_AI_FULL_ANALYSIS_ENABLED', True)
    state = cp.default_state('SCHEDULED_AI', event_opt_in=True)
    state['usage'] = [{'provider': 'openai', 'purpose': 'news_intel',
                       'at': scanner._ai_now_iso(), 'estimatedCostUsd': 10000.0}]
    monkeypatch.setattr(scanner, '_COST_POLICY', state)
    monkeypatch.setattr(scanner, '_DURABILITY_PRODUCTION', False)
    return state


def test_runtime_authorization_uses_the_explicit_settings(full_execution):
    result = scanner._cost_policy_authorize('openai', 'entity_profiles',
        estimated_cost_usd=10, estimated_tokens=1000)
    assert result['allowed']
    assert full_execution['usage'][0]['estimatedCostUsd'] == 10000.0


def test_judgment_gate_does_not_apply_old_daily_or_monthly_cap(full_execution, monkeypatch):
    monkeypatch.setattr(scanner, '_AI_JUDGE_ENABLED', True)
    monkeypatch.setattr(scanner, '_is_locked', lambda: False)
    monkeypatch.setattr(scanner, '_AI_JUDGE_ALLOW_COUNTRIES', [])
    monkeypatch.setattr(scanner, '_AI_JUDGE_MIN_INTERVAL', 0)
    monkeypatch.setattr(scanner, '_AI_JUDGE_MAX_RUNS', 64)
    monkeypatch.setattr(scanner, '_ai_cost_restore_once', lambda: None)
    monkeypatch.setattr(scanner, '_ai_cost_roll', lambda *a: None)
    monkeypatch.setattr(scanner, '_AI_COST_STATE', {'daySpentUsd': 10000.0, 'monthSpentUsd': 100000.0})
    monkeypatch.setattr(scanner, '_AI_GATE_STATE', {'date': scanner.datetime.now(scanner.TZ_JST).strftime('%Y-%m-%d'),
        'count': 100, 'lastRunTs': 0, 'failedAttempts': 0})
    with scanner.app.test_request_context('/'):
        ok, result, code = scanner._ai_run_gate()
    assert ok and code == 200
    assert result["runCountToday"] == 101
    assert scanner._AI_COST_STATE['monthSpentUsd'] == 100000.0
    monkeypatch.setattr(scanner, '_AI_FULL_ANALYSIS_ENABLED', False)
    with scanner.app.test_request_context('/'):
        ok, result, code = scanner._ai_run_gate()
    assert not ok and result['reason'] == 'scheduled_scope_required'


def test_entity_call_has_its_own_purpose_and_saved_model_proof(monkeypatch):
    calls = []
    def prose(*args, **kw):
        calls.append(kw['purpose'])
        kw['diagnostic'].update(requestedModel='test-primary', returnedModel='test-primary', outcome='ok')
        return {'businessJa': 'company business'}
    monkeypatch.setattr(scanner, '_openai_prose', prose)
    monkeypatch.setattr(scanner, '_ENTITY_PROFILES', {})
    monkeypatch.setattr(scanner, '_ENTITY_PROFILES_META', {})
    profile = scanner._entity_profile_make('8058', market='JP')
    assert calls == ['entity_profiles']
    assert profile['aiDiagnostic']['returnedModel'] == 'test-primary'


def test_research_reservation_override_keeps_cost_projection():
    args = dict(day_spent=999.0, day_budget=1.0, estimated_max_cost=10.0, reserved=20.0)
    assert not argus_ai_gate.reserve_budget(**args)['allowed']
    result = argus_ai_gate.reserve_budget(**args, enforced=False)
    assert result['allowed'] and result['wouldTotal'] == 1029.0


def test_public_settings_and_news_report_effective_budget(full_execution, monkeypatch):
    monkeypatch.setattr(scanner, '_news_intel_ensure_loaded', lambda: None)
    monkeypatch.setattr(scanner, '_NEWS_INTEL', {'order': [], 'events': {}, 'health': {'status': 'HEALTHY'}})
    with scanner.app.test_client() as client:
        response = client.get('/api/argus/news-intelligence')
    assert response.status_code == 200
    assert response.get_json()['aiBudgetEnforced'] is False


def test_research_estimate_reports_cost_without_enforcing_the_old_cap():
    import argus_research_benchmark as benchmark
    args = dict(gemini_model='baseline', argus_model='primary', evaluator_model='independent',
                pricing={key: {'in': 10000.0, 'out': 10000.0}
                         for key in ('baseline', 'primary', 'independent')}, usd_jpy_ceiling=160.0)
    assert benchmark.estimate_cost(**args)['status'] == 'budget_blocked'
    result = benchmark.estimate_cost(**args, budget_enforced=False)
    assert result['status'] == 'ready'
    assert result['estimatedCostJpy'] > benchmark.HARD_BUDGET_JPY


def test_formal_worker_cost_checks_follow_enforcement_setting():
    # Exercise the actual worker gate expressions without consuming a holdout.
    import ast
    import inspect
    for worker in (scanner._research_benchmark_v2_job_worker, scanner._research_benchmark_job_worker):
        tree = ast.parse(inspect.getsource(worker))
        gates = [node.test for node in ast.walk(tree) if isinstance(node, ast.If)
                 and 'estimatedCostJpy' in ast.unparse(node.test)]
        assert len(gates) == 1
        expression = compile(ast.Expression(gates[0]), '<worker-cost-gate>', 'eval')
        for enforced, status, blocked in ((False, 'ready', False),
                                          (True, 'ready', True),
                                          (False, 'unavailable', True)):
            assert eval(expression, {'_AI_BUDGET_ENFORCED': enforced,
                        'dry': {'status': status, 'estimatedCostJpy': 100000.0}}) is blocked


@pytest.mark.parametrize("supplied_token", ["", "wrong-token", "invalid-credential"] )
def test_rejected_auth_cannot_lock_authorized_analysis(full_execution, monkeypatch, supplied_token):
    monkeypatch.setattr(scanner, '_ARGUS_ADMIN_TOKEN', 'test-owner-secret')
    monkeypatch.setattr(scanner, '_AI_JUDGE_LOCKED_ENV', False)
    monkeypatch.setattr(scanner, '_AI_GATE_STATE', {'failedAttempts': 0, 'softLocked': False})
    monkeypatch.setattr(scanner, 'send_security_alert', lambda event: None)
    with scanner.app.test_request_context('/', headers={'X-ARGUS-ADMIN-TOKEN': supplied_token}):
        for _ in range(10):
            ok, error, code = scanner._require_admin()
            assert not ok and code == 401 and error == {'error': 'unauthorized'}
    assert scanner._AI_GATE_STATE['failedAttempts'] == 10
    assert not scanner._is_locked()
    with scanner.app.test_request_context('/', headers={'X-ARGUS-ADMIN-TOKEN': 'test-owner-secret'}):
        assert scanner._require_admin() == (True, None, 200)
    # An actual operator lock is still effective and is never auto-cleared.
    monkeypatch.setattr(scanner, '_AI_JUDGE_LOCKED_ENV', True)
    assert scanner._is_locked()
    monkeypatch.setattr(scanner, '_AI_JUDGE_LOCKED_ENV', False)
    scanner._AI_GATE_STATE['softLocked'] = True
    assert scanner._is_locked()


def test_auth_probe_traffic_is_still_limited_per_client(monkeypatch):
    monkeypatch.setattr(scanner, '_RL_BUCKETS', {})
    monkeypatch.setattr(scanner, '_RL_MAX', 2)
    with scanner.app.test_request_context('/api/argus/security-status'):
        assert scanner._rate_limit() is None
        assert scanner._rate_limit() is None
        response, code = scanner._rate_limit()
        assert code == 429 and response.get_json()['error'] == 'rate_limited'


@pytest.mark.parametrize('primary_status,checker_status,full,expected', [
    ('live', 'not_enabled_by_role_policy', True, 'live'),
    ('unavailable', 'not_enabled_by_role_policy', True, 'partial'),
    ('partial', 'not_enabled_by_role_policy', True, 'partial'),
    ('live', 'unavailable', True, 'partial'),
    ('live', 'live', False, 'live'),
    ('live', 'unavailable', False, 'partial'),
])
def test_execution_status_tracks_required_primary_without_hiding_failures(
        monkeypatch, primary_status, checker_status, full, expected):
    import copy
    monkeypatch.setattr(scanner, '_AI_FULL_ANALYSIS_ENABLED', full)
    monkeypatch.setattr(scanner, '_AI_RESULT_CACHE', {'data': None, 'expires': 0})
    monkeypatch.setattr(scanner, '_AI_LAST_RUN', {'oaiModel': 'actual-primary',
        'gemModel': 'actual-support',
        'oaiDiagnostic': {'requestedModel': 'requested-primary', 'returnedModel': 'actual-primary'}})
    rules = {'status': 'partial', 'labels': [{'symbol': '8058'}]}
    output = {'labels': [{'symbol': '8058', 'reasonJa': '観測された変化の説明'}]}
    monkeypatch.setattr(scanner, '_build_ai_snapshot', lambda: ({}, rules))
    monkeypatch.setattr(scanner, '_openai_judge', lambda _: (output, primary_status))
    monkeypatch.setattr(scanner, '_gemini_check', lambda *args: (None, checker_status, False))
    monkeypatch.setattr(scanner, '_arbitrate_ai', lambda *args: [{'symbol': '8058', 'ruleAction': 'WAIT'}])
    monkeypatch.setattr(scanner, '_ai_record_cost', lambda *args: {'totalUsd': 0.12})
    persisted = []
    monkeypatch.setattr(scanner, '_ai_persist_latest', lambda value: persisted.append(copy.deepcopy(value)))
    result = scanner._execute_ai_judgment()
    assert result['status'] == expected
    assert result['providerExecutions']['checker']['required'] is (not full)
    assert result['providerExecutions']['primary']['status'] == primary_status
    assert result['models']['primary'] == ('actual-primary' if primary_status == 'live' else None)
    assert result['models']['checker'] == ('actual-support' if checker_status == 'live' else None)
    assert result['analysisCoverage']['complete'] is True
    assert persisted == [result], 'saved payload must include final usage and actual model fields'
    assert result['costEstimateUsd'] == 0.12


@pytest.mark.parametrize('primary_labels', [[], [{'symbol': '8058'}],
    [{'symbol': '8058', 'reasonJa': '説明'}, {'symbol': '8058', 'reasonJa': '重複'}]])
def test_incomplete_symbol_output_cannot_be_live(monkeypatch, primary_labels):
    monkeypatch.setattr(scanner, '_AI_FULL_ANALYSIS_ENABLED', True)
    monkeypatch.setattr(scanner, '_AI_RESULT_CACHE', {'data': None, 'expires': 0})
    monkeypatch.setattr(scanner, '_AI_LAST_RUN', {})
    monkeypatch.setattr(scanner, '_build_ai_snapshot', lambda: ({}, {
        'status': 'live', 'labels': [{'symbol': '8058'}]}))
    monkeypatch.setattr(scanner, '_openai_judge', lambda _: ({'labels': primary_labels}, 'live'))
    monkeypatch.setattr(scanner, '_gemini_check', lambda *a: (None, 'not_enabled_by_role_policy', False))
    monkeypatch.setattr(scanner, '_arbitrate_ai', lambda *a: [])
    monkeypatch.setattr(scanner, '_ai_record_cost', lambda *a: {'totalUsd': 0.12})
    monkeypatch.setattr(scanner, '_ai_persist_latest', lambda *a: None)
    result = scanner._execute_ai_judgment()
    assert result['status'] == 'partial'
    assert result['analysisCoverage']['complete'] is False


def test_primary_mode_checker_is_explicit_non_call(monkeypatch):
    monkeypatch.setattr(scanner, '_AI_FULL_ANALYSIS_ENABLED', True)
    monkeypatch.setattr(scanner, '_AI_LAST_RUN', {'gemUsage': (100, 200), 'gemModel': 'earlier-model'})
    def unexpected(*args, **kwargs):
        raise AssertionError('role-disabled checker must not authorize, bill, or call a provider')
    monkeypatch.setattr(scanner, '_cost_policy_authorize', unexpected)
    assert scanner._gemini_check({}, {}) == (None, 'not_enabled_by_role_policy', False)
    assert scanner._AI_LAST_RUN['gemUsage'] is None
    assert scanner._AI_LAST_RUN['gemModel'] is None


@pytest.mark.parametrize('primary_key,expected', [('configured', 'no_cached_result'), ('', 'missing_keys')])
def test_primary_mode_truth_does_not_require_support_key(monkeypatch, primary_key, expected):
    monkeypatch.setattr(scanner, '_AI_FULL_ANALYSIS_ENABLED', True)
    monkeypatch.setattr(scanner, '_AI_JUDGE_ENABLED', True)
    monkeypatch.setattr(scanner, '_OPENAI_API_KEY', primary_key)
    monkeypatch.setattr(scanner, 'GEMINI_API_KEY', '')
    monkeypatch.setattr(scanner, '_AI_RESULT_CACHE', {'data': None, 'expires': 0})
    result = scanner._ai_judgment_truth(allow_restore=False)
    assert result['status'] == expected
    assert result['publicGetStatus'] == expected
