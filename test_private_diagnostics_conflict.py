"""A confirmed branch conflict never overwrites earlier private evidence."""
import io
import json
import urllib.error
import pytest
from scripts import private_diagnostics_store as store


class Reply:
    def __init__(self, status=201, body=b''):
        self.status=status;self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.body[:limit]


def error(status):
    return urllib.error.HTTPError('https://api.github.com/private',status,'PRIVATE_REASON',{},io.BytesIO(b'PRIVATE_BODY'))


@pytest.mark.parametrize('existing', [None,b'PRIVATE_RECORD',b'OTHER_ORIGINAL'])
@pytest.mark.parametrize('raised',[False,True])
def test_409_checks_current_destination_before_one_create_only_retry(tmp_path,existing,capsys,raised):
    path=tmp_path/'note.json';path.write_bytes(b'PRIVATE_RECORD');calls=[]
    def opener(request,timeout):
        calls.append(request)
        if len(calls)==1:
            request.add_header('Content-length','999')
            if raised:raise error(409)
            return Reply(409)
        if request.get_method()=='GET':
            assert request.full_url.endswith('/note.json?ref=main')
            assert request.headers['Accept']=='application/vnd.github.raw+json'
            assert request.data is None and request.get_header('Content-length') is None
            if existing is None:raise error(404)
            return Reply(200,existing)
        assert len(calls)==3 and existing is None
        assert 'sha' not in json.loads(request.data)
        return Reply()
    if existing==b'OTHER_ORIGINAL':
        with pytest.raises(store.PrivateStoreError) as exc:store.store('warm','123',[path],'TOKEN',opener=opener)
        assert exc.value.failure_code=='IMMUTABLE_CONFLICT'
    else:assert store.store('warm','123',[path],'TOKEN',opener=opener)==1
    assert [r.get_method() for r in calls]==(['PUT','GET','PUT'] if existing is None else ['PUT','GET'])
    assert not capsys.readouterr().out


def test_a_second_409_remains_failed_without_unbounded_retry(tmp_path):
    path=tmp_path/'note.json';path.write_bytes(b'PRIVATE_RECORD');methods=[]
    def opener(request,timeout):
        methods.append(request.get_method());raise error(404 if request.get_method()=='GET' else 409)
    with pytest.raises(store.PrivateStoreError) as exc:store.store('warm','123',[path],'TOKEN',opener=opener)
    assert exc.value.failure_code=='HTTP_409' and methods==['PUT','GET','PUT']


@pytest.mark.parametrize('status',[401,403,404,422,429,500])
def test_other_failures_are_not_retried(tmp_path,status):
    path=tmp_path/'note.json';path.write_bytes(b'PRIVATE_RECORD');calls=[]
    def opener(request,timeout):calls.append(request);raise error(status)
    with pytest.raises(store.PrivateStoreError):store.store('warm','123',[path],'TOKEN',opener=opener)
    assert len(calls)==1


def test_conflict_resolution_keeps_the_original_sixty_second_file_deadline(tmp_path,monkeypatch):
    path=tmp_path/'note.json';path.write_bytes(b'PRIVATE_RECORD');calls=[];clock=[10.0]
    monkeypatch.setattr(store.time,'monotonic',lambda:clock[0])
    def opener(request,timeout):
        calls.append((request.get_method(),timeout))
        if request.get_method()=='PUT':clock[0]=65.0;raise error(409)
        assert timeout<=5
        clock[0]=71.0;raise error(404)
    with pytest.raises(store.PrivateStoreError) as exc:store.store('warm','123',[path],'TOKEN',opener=opener)
    assert exc.value.failure_code=='DEADLINE' and len(calls)==2


def test_read_failure_after_conflict_never_starts_another_write(tmp_path):
    path=tmp_path/'note.json';path.write_bytes(b'PRIVATE_RECORD');methods=[]
    def opener(request,timeout):
        methods.append(request.get_method());raise error(403 if request.get_method()=='GET' else 409)
    with pytest.raises(store.PrivateStoreError) as exc:store.store('warm','123',[path],'TOKEN',opener=opener)
    assert exc.value.failure_code=='HTTP_403' and methods==['PUT','GET']


def test_authenticated_conflict_read_never_follows_a_redirect():
    assert store._NoRedirect().redirect_request(None,None,None,None,None,None) is None
