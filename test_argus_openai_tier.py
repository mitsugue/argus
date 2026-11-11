"""2026-11-11 owner 【AIを割引の窓口で】: automatic lanes ask for Flex first."""
from types import SimpleNamespace
import pytest
import argus_openai_tier as tier


class ProviderError(Exception):
    def __init__(self, status, code=None, message=''):
        super().__init__(message)
        self.status_code = status
        self.body = {'error': {'code': code, 'message': message}}


def recorder(*answers):
    sent = []
    def call(kwargs, name):
        sent.append((name, kwargs))
        answer = answers[len(sent) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer
    return sent, call


def test_automatic_lane_asks_flex_with_a_longer_bounded_wait():
    state = tier.TierState()
    sent, call = recorder(SimpleNamespace(service_tier='flex', output_text='ok'))
    tier.create(state, purpose='market_brief', model='m', kwargs={'model':'m', 'timeout':60}, call=call)
    assert sent == [('flex', {'model':'m', 'timeout':300, 'service_tier':'flex'})]
    assert state.view()['counts']['market_brief'] == {'flexRequested':1, 'flexServed':1,
        'flexAnsweredOtherTier':0, 'standardAfterRefusal':0, 'refusals':{}}


@pytest.mark.parametrize('purpose', ['owner_dialogue', 'osint_research', 'entity_profiles', 'benchmark_evaluation'])
def test_button_and_other_lanes_stay_standard(purpose):
    sent, call = recorder(SimpleNamespace(service_tier='default'))
    tier.create(tier.TierState(), purpose=purpose, model='m', kwargs={'timeout':60}, call=call)
    assert sent == [('standard', {'timeout':60})]


def test_switched_off_sends_standard_only():
    sent, call = recorder(SimpleNamespace())
    tier.create(tier.TierState(enabled=False), purpose='news_intel', model='m', kwargs={}, call=call)
    assert [name for name, _ in sent] == ['standard']


def test_resource_unavailable_goes_standard_once():
    state = tier.TierState()
    sent, call = recorder(ProviderError(429, None, 'Resource Unavailable for flex processing'),
                          SimpleNamespace(service_tier='default'))
    tier.create(state, purpose='news_intel', model='m', kwargs={'timeout':60}, call=call)
    assert [name for name, _ in sent] == ['flex', 'standard'] and 'service_tier' not in sent[1][1]
    assert state.view()['counts']['news_intel']['refusals'] == {'resource_unavailable':1}
    # Not remembered: the next request asks Flex again.
    assert state.wants_flex('news_intel', 'm')


@pytest.mark.parametrize('code', ['insufficient_quota', 'organization_spend_limit_exceeded',
                                  'rate_limit_exceeded', 'slow_down', None])
def test_quota_rate_limit_or_unexplained_429_is_not_repeated(code):
    sent, call = recorder(ProviderError(429, code))
    with pytest.raises(ProviderError):
        tier.create(tier.TierState(), purpose='market_brief', model='m', kwargs={}, call=call)
    assert len(sent) == 1


def test_timeout_and_server_errors_are_not_repeated():
    for error in (TimeoutError('slow'), ProviderError(500), ProviderError(408)):
        sent, call = recorder(error)
        with pytest.raises(type(error)):
            tier.create(tier.TierState(), purpose='market_brief', model='m', kwargs={}, call=call)
        assert len(sent) == 1


def test_rejected_request_remembers_the_model_and_tool():
    state = tier.TierState()
    sent, call = recorder(ProviderError(400, None, 'service_tier flex is not available'), SimpleNamespace())
    tier.create(state, purpose='market_position_check', model='m', kwargs={}, call=call, tool_kind='web_search')
    assert [name for name, _ in sent] == ['flex', 'standard']
    assert not state.wants_flex('market_position_check', 'm', 'web_search')
    assert state.wants_flex('market_brief', 'm')          # plain text requests still ask Flex
    assert state.view()['unsupported'] == ['m|web_search']


def test_cost_follows_the_served_tier():
    assert tier.served_cost(0.2, SimpleNamespace(service_tier='flex')) == 0.1
    assert tier.served_cost(0.2, SimpleNamespace(service_tier='default')) == 0.2
    assert tier.served_cost(None, SimpleNamespace(service_tier='flex')) is None


def test_scanner_prose_call_sends_flex_for_the_brief_and_standard_for_the_button(monkeypatch):
    import scanner
    sent = []
    class Responses:
        def create(self, **kw):
            sent.append(kw)
            return SimpleNamespace(service_tier=kw.get('service_tier', 'default'), output_text='{}',
                                   model='gpt-5.6-terra', usage=None, id='r')
    class Client:
        responses = Responses()
        def with_options(self, **kw): return self
    monkeypatch.setattr(scanner, '_OPENAI_TIER', tier.TierState())
    scanner._openai_prose_call(Client(), 'gpt-5.6-terra', 'sys', 'user', purpose='market_brief')
    scanner._openai_prose_call(Client(), 'gpt-5.6-terra', 'sys', 'user', purpose='owner_dialogue')
    assert sent[0]['service_tier'] == 'flex' and sent[0]['timeout'] == 300
    assert 'service_tier' not in sent[1] and sent[1]['timeout'] == 60
