"""A read cannot recompose or demote an accepted market edition."""
import pytest
import scanner

@pytest.mark.parametrize('age', [0, 301, 3600])
def test_existing_edition_read_never_recomposes_or_changes_timestamp(monkeypatch, age):
    brief = {'unifiedStatus':'GENERATED','generatedAt':'2026-10-07T00:00:00Z'}
    monkeypatch.setattr(scanner, '_MARKET_BRIEF', {'data':brief,'composedAt':scanner.time.time()-age})
    monkeypatch.setattr(scanner, '_market_brief_refresh', lambda **kw: pytest.fail('GET recomposed'))
    with scanner.app.test_request_context('/api/argus/market-brief'):
        value = scanner.api_argus_market_brief().get_json()
    assert value['unifiedStatus']=='GENERATED' and value['generatedAt']==brief['generatedAt']
    assert brief=={'unifiedStatus':'GENERATED','generatedAt':'2026-10-07T00:00:00Z'}

def test_restart_returns_whole_restored_edition_without_provider(monkeypatch):
    state={'data':None};monkeypatch.setattr(scanner,'_MARKET_BRIEF',state)
    saved={'unifiedStatus':'GENERATED','calculationSnapshots':{'5':{'original':True}}}
    monkeypatch.setattr(scanner,'_market_brief_history_restore',lambda:state.update(lastSuccessful=saved))
    monkeypatch.setattr(scanner,'_market_brief_refresh',lambda **kw:pytest.fail('provider path'))
    with scanner.app.test_request_context('/api/argus/market-brief'):
        value=scanner.api_argus_market_brief().get_json()
    assert value['calculationSnapshots']==saved['calculationSnapshots']

def test_no_edition_is_unavailable_not_generated(monkeypatch):
    monkeypatch.setattr(scanner,'_MARKET_BRIEF',{'data':None})
    monkeypatch.setattr(scanner,'_market_brief_history_restore',lambda:None)
    with scanner.app.test_request_context('/api/argus/market-brief'):
        response,status=scanner.api_argus_market_brief()
    assert status==503 and response.get_json()['reason']=='edition_not_yet_available'
