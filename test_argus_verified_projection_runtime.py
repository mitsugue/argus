"""Worker wiring preserves raw verification, restore ownership and disk reads."""
import ast
import copy
import inspect
import tempfile

import pytest

import argus_market_artifact_store as artifacts
import argus_verified_snapshot as snapshots
import scanner
from test_argus_market_artifact_split import (
    _isolate_market_stores, _reset_market_stores, _seed_verified)  # noqa: F401
from test_argus_persistent_mission_storage import scanner_storage
from test_argus_verified_snapshot import boundary_store, candidate, payload


@pytest.mark.parametrize('flag', [False, None, 1, 'true', True])
def test_only_literal_private_hint_changes_allocation_not_raw_checks(monkeypatch, flag):
    source = boundary_store()
    source['_published_readonly'] = True  # Data cannot select the Python hint.
    expected = snapshots.state_hash(source)
    normalize = snapshots.normalize_store
    verify = snapshots.verify_snapshot
    calls = {'owned':0, 'verify':0}
    def owned(value):
        calls['owned'] += 1
        return normalize(value)
    def checked(value, **kwargs):
        calls['verify'] += 1
        return verify(value, **kwargs)
    monkeypatch.setattr(snapshots, 'normalize_store', owned)
    monkeypatch.setattr(snapshots, 'verify_snapshot', checked)
    assert snapshots.state_hash(source, _published_readonly=flag) == expected
    assert calls == {'owned':0 if flag is True else 1, 'verify':len(source['current'])}
    key = next(iter(source['current']))
    source['current'][key]['payloadHash'] = 'corrupt'
    assert snapshots.state_hash(source, _published_readonly=flag) == snapshots.state_hash(source)


def test_allocation_hint_sites_are_exact_and_raw_deny_list_is_preserved():
    class Visitor(ast.NodeVisitor):
        def __init__(self): self.functions=[];self.calls=[]
        def visit_FunctionDef(self, node):
            self.functions.append(node.name);self.generic_visit(node);self.functions.pop()
        def visit_Call(self, node):
            hints=[kw for kw in node.keywords if kw.arg=='_published_readonly']
            if hints:
                assert isinstance(node.func, ast.Attribute)
                assert isinstance(node.func.value, ast.Name)
                assert node.func.value.id=='argus_verified_snapshot' and node.func.attr=='state_hash'
                assert len(hints)==1 and isinstance(hints[0].value,ast.Constant) and hints[0].value.value is True
                assert isinstance(node.args[0],ast.Name) and node.args[0].id=='_VERIFIED_VIEW_SNAPSHOTS'
                self.calls.append(self.functions[-1])
            self.generic_visit(node)
    visitor=Visitor();visitor.visit(ast.parse(inspect.getsource(scanner)))
    assert visitor.calls==['_api_argus_admin_missions_tick_impl']*2
    # The independent existing deny-list test still requires every raw caller.
    from test_argus_memory_attribution import test_raw_hash_deny_list_callers_remain_unchanged
    test_raw_hash_deny_list_callers_remain_unchanged()


def test_checkpoint_avoids_full_owned_copy_but_preserves_artifact_and_public_reads(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp, scanner_storage(tmp) as paths:
        _reset_market_stores();identity=_seed_verified()
        original=copy.deepcopy(scanner._VERIFIED_VIEW_SNAPSHOTS)
        expected=snapshots.state_hash(original)
        seen=[];hash_function=snapshots._state_hash_for_persistence
        def checked(value, **kwargs):
            assert type(value) is dict and not snapshots._has_normalized_store_provenance(value)
            seen.append(value)
            return hash_function(value, **kwargs)
        def forbidden(*a,**kw): pytest.fail('checkpoint copied the whole verified store')
        with monkeypatch.context() as local:
            local.setattr(snapshots,'normalize_store',forbidden)
            local.setattr(snapshots,'_state_hash_for_persistence',checked)
            assert scanner._osint_persist()['verified'] is True
        assert len(seen)==1 and seen[0]==original
        assert scanner._MARKET_STORE_RESIDENCY['verifiedViewSnapshots']['attached'] is False
        doc=artifacts.load(paths['root'],'verifiedViewSnapshots')
        assert doc['stateHash']==expected and doc['payload']==original
        served=scanner._verified_market_snapshot('1321',5)
        assert served['snapshotId']==identity
        served['payload']['indicators']['bars'][0]['close']=999
        again=scanner._verified_market_snapshot('1321',5)
        assert again['payload']['indicators']['bars'][0]['close']!=999


@pytest.mark.parametrize('rejected', ['older','quality'])
def test_readonly_restore_lookup_keeps_serialized_ownership_and_pointer_rules(monkeypatch,rejected):
    _reset_market_stores()
    method=scanner._VERIFIED_VIEW_METHOD_VERSION
    local=candidate(method=method,dataset_hash='local',body=payload(dataset_hash='local'),
                    generated_at='2026-07-23T06:03:00Z')
    key=snapshots.snapshot_key('market-chart','1321','5D')
    scanner._VERIFIED_VIEW_SNAPSHOTS['current'][key]=local
    old=candidate(method=method,quality='partial' if rejected=='quality' else 'live',
                  generated_at='2026-07-23T06:04:00Z' if rejected=='quality' else '2026-07-23T06:01:00Z')
    extra=candidate(symbol='SPY',method=method)
    other=snapshots.snapshot_key('market-chart','SPY','5D')
    incoming={'current':{key:old,other:extra,'invalid':{'schemaVersion':'bad'}}}
    before=copy.deepcopy(incoming)
    expected=copy.deepcopy(scanner._VERIFIED_VIEW_SNAPSHOTS)
    for row in snapshots.normalize_store(incoming)['current'].values():
        expected,_=snapshots.publish_atomic(expected,row,now_iso=scanner._ai_now_iso())
    def forbidden(*a,**kw): pytest.fail('restore lookup copied the whole input store')
    with monkeypatch.context() as local_patch:
        local_patch.setattr(snapshots,'normalize_store',forbidden)
        assert scanner._merge_restored_market_artifact('verifiedViewSnapshots',incoming) is True
    assert scanner._VERIFIED_VIEW_SNAPSHOTS==expected
    assert scanner._VERIFIED_VIEW_SNAPSHOTS['current'][key]==local
    assert incoming==before
    incoming['current'][other]['payload']['indicators']['bars'][0]['close']=999
    assert scanner._VERIFIED_VIEW_SNAPSHOTS['current'][other]['payload']['indicators']['bars'][0]['close']!=999
    assert snapshots.state_hash(scanner._VERIFIED_VIEW_SNAPSHOTS)==snapshots.state_hash(expected)
