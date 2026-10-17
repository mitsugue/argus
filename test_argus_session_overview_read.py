"""Ordinary login admits saved explanation reads only, never legacy mutations."""
from types import SimpleNamespace
from flask import Flask, g
import pytest
import argus_owner_dialogue_api as api

@pytest.mark.parametrize('verified', [False, True])
@pytest.mark.parametrize('action', ['overview','history','usage','ask','vault','notifications'])
def test_session_read_capability_is_narrow(tmp_path, verified, action):
    app=Flask(__name__); app.extensions['argus_owner_auth']=SimpleNamespace(enabled=True)
    @app.before_request
    def verified_session():
        g.owner_session_verified=verified
    calls=[]
    api.register(app,authorize=lambda token:(False,{'error':'unauthorized'},401),
        storage_path=lambda:str(tmp_path/'overview.sqlite3'),market_brief=lambda:{},
        generate=lambda *a,**k:calls.append('AI'),now=lambda:'2026-10-07T01:00:00Z',
        registered_subjects=lambda:[{'market':'JP','symbol':'7203'}])
    response=app.test_client().post('/api/argus/owner-dialogue',json={
        'action':action,'symbol':'7203','market':'JP','horizon':5})
    assert response.status_code==(200 if verified and action=='overview' else 401)
    if verified and action=='overview':
        assert response.get_json()['overviewRead']['mode']=='SAVED_ONLY'
    assert calls==[]

@pytest.mark.parametrize('members', [[],None,[{'market':'US','symbol':'7203'}],[{'market':'JP','symbol':'7203','enabled':False}]])
def test_session_cannot_read_unregistered_subject(tmp_path,members):
    app=Flask(__name__);app.extensions['argus_owner_auth']=SimpleNamespace(enabled=True)
    @app.before_request
    def verified_session(): g.owner_session_verified=True
    api.register(app,authorize=lambda token:(False,{'error':'unauthorized'},401),
        storage_path=lambda:str(tmp_path/'overview.sqlite3'),market_brief=lambda:{},
        generate=lambda *a,**k:pytest.fail('read generated'),now=lambda:'2026-10-07T01:00:00Z',
        registered_subjects=lambda:members)
    response=app.test_client().post('/api/argus/owner-dialogue',json={
        'action':'overview','symbol':'7203','market':'JP','horizon':5})
    assert response.status_code==403
    assert response.get_json()['error']=='subject_not_registered'
