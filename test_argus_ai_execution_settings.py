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
    monkeypatch.setattr(scanner, '_AI_GATE_STATE', {'date': '', 'count': 0, 'lastRunTs': 0, 'failedAttempts': 0})
    with scanner.app.test_request_context('/'):
        ok, result, code = scanner._ai_run_gate()
    assert ok and code == 200
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
