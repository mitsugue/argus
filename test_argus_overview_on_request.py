"""2026-11-10 owner: subject explanations are written only when the button is pressed."""
import copy
import time
from types import SimpleNamespace
from flask import Flask, g
import argus_owner_dialogue_api as api
import argus_owner_dialogue_store as store
import argus_market_brief as brief_module
import argus_overview_refresh as refresh
from test_argus_owner_dialogue import market_brief, answer, AT


def service(tmp_path, *, max_starts=3, session=False):
    path = tmp_path / 'owner.sqlite3'
    members = [{'market':'JP', 'symbol':'5803', 'enabled':True}]
    current = [market_brief()]
    calls = []
    app = Flask(__name__)
    if session:
        app.extensions['argus_owner_auth'] = SimpleNamespace(enabled=True)

        @app.before_request
        def verified():
            g.owner_session_verified = True
    controls = api.register(app, authorize=lambda token:(token=='owner', {'error':'unauthorized'}, 401),
        storage_path=lambda:str(path), market_brief=lambda:current[0],
        generate=lambda user, **kw:(calls.append(user), answer())[1], now=lambda:AT,
        generation_policy=lambda:{'model':'test','ruleVersion':'v1'},
        subject_materials=lambda **kw:[], registered_subjects=lambda:copy.deepcopy(members),
        refresh_policy=refresh.RefreshPolicy(max_starts=max_starts), manual_overviews=True)
    return path, current, calls, app.test_client(), controls


def press(client, symbol='5803', token='owner'):
    body = {'action':'overviewGenerate','symbol':symbol,'market':'JP','horizon':5}
    if token:
        body['ownerToken'] = token
    return client.post('/api/argus/owner-dialogue', json=body)


def wait(path, controls):
    for _ in range(200):
        items = store.history(path, controls['bootId'])['items']
        if items and items[0]['status'] != 'RUNNING':
            return items[0]
        time.sleep(.01)
    raise AssertionError('worker did not complete')


def new_edition(current):
    edition = copy.deepcopy(current[0])
    edition['facts'] = edition['facts'] + [{'text':'新しい市場の材料。', 'source':'trusted_mail',
        'priority':'P1', 'verification':'UNCONFIRMED'}]
    edition['unifiedContext'] = brief_module.unified_context(edition)
    current[0] = edition


def test_clock_never_generates_even_for_a_new_registration(tmp_path):
    path, current, calls, client, controls = service(tmp_path)
    for _ in range(3):
        assert controls['refreshSubjectOverviews']() == {'status':'MANUAL_ONLY', 'started':0}
        new_edition(current)
    assert calls == []
    read = client.post('/api/argus/owner-dialogue', json={'action':'overview', 'ownerToken':'owner',
        'symbol':'5803', 'market':'JP', 'horizon':5})
    assert read.get_json()['status'] == 'WAITING' and calls == []


def test_button_writes_one_explanation_and_reuses_unchanged_inputs(tmp_path):
    path, current, calls, client, controls = service(tmp_path)
    first = press(client)
    assert first.status_code == 202 and first.get_json()['overviewGenerate']['started'] is True
    assert wait(path, controls)['status'] == 'SUCCEEDED' and len(calls) == 1
    read = client.post('/api/argus/owner-dialogue', json={'action':'overview', 'ownerToken':'owner',
        'symbol':'5803', 'market':'JP', 'horizon':5}).get_json()
    assert read['status'] == 'SUCCEEDED' and read['overviewRead']['mode'] == 'SAVED_ONLY'
    again = press(client)
    assert again.status_code == 200 and again.get_json()['overviewGenerate']['started'] is False
    assert len(calls) == 1
    # Changed market inputs: the next press writes again.
    new_edition(current)
    assert press(client).status_code == 202
    assert wait(path, controls)['status'] == 'SUCCEEDED' and len(calls) == 2


def test_press_is_bounded_per_subject_and_day(tmp_path):
    path, current, calls, client, controls = service(tmp_path, max_starts=1)
    assert press(client).status_code == 202
    wait(path, controls)
    new_edition(current)
    limited = press(client)
    assert limited.status_code == 200
    assert limited.get_json()['overviewGenerate'] == {'started':False, 'reason':'DAILY_START_LIMIT',
        'checkedAt':AT}
    assert len(calls) == 1


def test_unregistered_or_unauthorized_press_never_generates(tmp_path):
    path, current, calls, client, controls = service(tmp_path)
    assert press(client, symbol='7203').status_code == 403
    assert press(client, token='wrong').status_code == 401
    assert press(client, token=None).status_code == 401
    assert calls == []


def test_signed_in_session_may_press(tmp_path):
    path, current, calls, client, controls = service(tmp_path, session=True)
    assert press(client, token=None).status_code == 202
    assert wait(path, controls)['status'] == 'SUCCEEDED' and len(calls) == 1
