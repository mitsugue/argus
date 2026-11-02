"""Real artifact/checkpoint paths preserve retired files and restore ownership."""
import ast
import copy
import inspect
from pathlib import Path
import tempfile

import pytest

import scanner
import argus_market_artifact_items as items
import argus_market_artifact_store as artifacts
import argus_persistent_storage as storage
import argus_verified_snapshot as snapshots
from test_argus_market_artifact_split import (
    _isolate_market_stores, _reset_market_stores, _seed_verified)  # noqa: F401
from test_argus_market_store_residency import _seed_asset
from test_argus_persistent_mission_storage import scanner_storage
from test_argus_verified_snapshot import candidate
from test_argus_parsed_restore_snapshots import old_restore, store_of


def asset_files(root):
    paths = [Path(artifacts.path_for(root, 'assetChartReports'))]
    paths.extend(Path(items.directory_for(root, 'assetChartReports')).glob('*.json'))
    return {str(path): path.read_bytes() for path in paths}


def seed_archives():
    _reset_market_stores()
    _seed_verified()
    _seed_asset()
    assert scanner._osint_persist()['verified'] is True


@pytest.mark.parametrize('reason', ['mission_tick', 'release_seed'])
def test_retired_bulk_attachment_and_real_checkpoint_never_reload_or_rewrite_archive(monkeypatch, reason):
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        seed_archives()
        before = asset_files(root)
        expected_hash = artifacts.load(root, 'assetChartReports')['stateHash']
        load = artifacts.load
        def checked(directory, name, *args, **kwargs):
            assert name != 'assetChartReports', 'retired archive was bulk-loaded'
            return load(directory, name, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(scanner, '_ASSET_CHART_GENERATION', False)
            patch.setattr(artifacts, 'load', checked)
            patch.setattr(scanner.argus_asset_chart_cache, 'normalize_store',
                          lambda *a, **k: pytest.fail('retired store was normalized'))
            attached = scanner._attach_market_stores(reason)
            assert set(attached) == {'verifiedViewSnapshots'}
            assert scanner._precompute_asset_chart_tick()['status'] == 'retired'
            assert scanner._osint_persist()['verified'] is True
        checkpoint = storage.load_checkpoint(paths['checkpoint'], require_seal=True)
        assert checkpoint['assetChartReportsStateHash'] == expected_hash
        assert not scanner._market_store_attached('assetChartReports')
        assert asset_files(root) == before
        served = scanner._asset_chart_current('JP', '7203', 'weekly')
        assert served['payload']['reportId'] == 'r-weekly'
        served['payload']['indicators']['bars'][0]['close'] = 999
        assert scanner._asset_chart_current('JP', '7203', 'weekly')['payload']['indicators']['bars'][0]['close'] == 2980.0
        assert asset_files(root) == before


@pytest.mark.parametrize('explicit', [False, True])
def test_enabled_generation_and_explicit_restore_keep_full_attachment(monkeypatch, explicit):
    with tempfile.TemporaryDirectory() as root, scanner_storage(root):
        seed_archives()
        before = asset_files(root)
        expected = artifacts.load(root, 'assetChartReports')['payload']
        monkeypatch.setattr(scanner, '_ASSET_CHART_GENERATION', not explicit)
        kwargs = {'names':('assetChartReports',)} if explicit else {}
        attached = scanner._attach_market_stores('mission_tick', **kwargs)
        assert 'assetChartReports' in attached
        assert scanner._market_store_attached('assetChartReports')
        assert scanner._ASSET_CHART_REPORTS == expected
        assert asset_files(root) == before


@pytest.mark.parametrize('flag', [False, None, 1, 'true', True])
def test_only_private_literal_flag_consumes_parse_without_changing_restore_truth(monkeypatch, flag):
    _reset_market_stores()
    incoming = store_of(candidate(), candidate(symbol='SPY'))
    incoming['_owned_parsed_payload'] = True
    before = copy.deepcopy(incoming)
    expected = old_restore(snapshots.empty_store(), before)
    consume = snapshots._consume_parsed_restore_snapshots
    calls = []
    def checked(value):
        calls.append(value)
        yield from consume(value)
    monkeypatch.setattr(snapshots, '_consume_parsed_restore_snapshots', checked)
    assert scanner._merge_restored_market_artifact(
        'verifiedViewSnapshots', incoming, _owned_parsed_payload=flag)
    assert scanner._VERIFIED_VIEW_SNAPSHOTS == expected
    assert len(calls) == (1 if flag is True else 0)
    if flag is True:
        assert incoming['current'] == {}
    else:
        assert incoming == before


@pytest.mark.parametrize('boot_restore', [False, True])
def test_actual_private_loader_consumes_parse_and_keeps_original_file(monkeypatch, boot_restore):
    with tempfile.TemporaryDirectory() as root, scanner_storage(root):
        seed_archives()
        path = Path(artifacts.path_for(root, 'verifiedViewSnapshots'))
        before_bytes = path.read_bytes()
        original = artifacts.load(root, 'verifiedViewSnapshots')['payload']
        expected = old_restore(snapshots.empty_store(), original)
        consume = snapshots._consume_parsed_restore_snapshots
        seen = []
        def checked(parsed):
            assert parsed == original
            seen.append(parsed)
            yield from consume(parsed)
        monkeypatch.setattr(snapshots, '_consume_parsed_restore_snapshots', checked)
        if boot_restore:
            _reset_market_stores()
            (Path(items.directory_for(root, 'verifiedViewSnapshots'))/items.INDEX_NAME).unlink()
            assert 'verifiedViewSnapshots' in scanner._market_artifacts_restore()
        else:
            scanner._attach_market_store('verifiedViewSnapshots', 'generation')
        assert len(seen) == 1 and seen[0]['current'] == {}
        assert scanner._VERIFIED_VIEW_SNAPSHOTS == expected
        assert path.read_bytes() == before_bytes
        for row in scanner._VERIFIED_VIEW_SNAPSHOTS['current'].values():
            assert snapshots.verify_snapshot(row)[0]


def test_consumption_authority_is_only_two_private_json_loader_sites():
    class Visitor(ast.NodeVisitor):
        def __init__(self): self.functions=[];self.sites=[];self.iterators=[]
        def visit_FunctionDef(self, node):
            self.functions.append(node.name);self.generic_visit(node);self.functions.pop()
        def visit_Call(self, node):
            for keyword in node.keywords:
                if keyword.arg == '_owned_parsed_payload':
                    assert isinstance(node.func, ast.Name) and node.func.id == '_merge_restored_market_artifact'
                    assert isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                    self.sites.append(self.functions[-1])
            if isinstance(node.func, ast.Attribute) and node.func.attr == '_consume_parsed_restore_snapshots':
                assert isinstance(node.func.value, ast.Name) and node.func.value.id == 'argus_verified_snapshot'
                self.iterators.append(self.functions[-1])
            self.generic_visit(node)
    visitor=Visitor();visitor.visit(ast.parse(inspect.getsource(scanner)))
    assert visitor.sites == ['_attach_market_store','_market_artifacts_restore']
    assert visitor.iterators == ['_merge_restored_market_artifact']
    from test_argus_memory_attribution import test_raw_hash_deny_list_callers_remain_unchanged
    test_raw_hash_deny_list_callers_remain_unchanged()
