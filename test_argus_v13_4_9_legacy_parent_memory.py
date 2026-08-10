"""v13.4.9 legacy-parent allocator lifecycle closure."""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest import mock

import argus_checkpoint_v2 as v2


def test_legacy_reclaim_uses_existing_scoped_allocator_boundary():
    with mock.patch.object(
            v2, "_release_unused_allocator_memory",
            return_value={"attempted": True, "supported": True,
                          "sourceBytes": 128 * 1024 ** 2,
                          "rssReleasedBytes": 64 * 1024 ** 2}) as release:
        result = v2.release_consumed_legacy_snapshot_memory(128 * 1024 ** 2)
    release.assert_called_once_with(128 * 1024 ** 2)
    assert result["attempted"] is True
    assert result["rssReleasedBytes"] == 64 * 1024 ** 2


def test_legacy_reclaim_does_not_force_gc_or_change_small_snapshot_policy():
    source = pathlib.Path(v2.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    wrapper = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and
        node.name == "release_consumed_legacy_snapshot_memory")
    attributes = [
        node.attr for node in ast.walk(wrapper)
        if isinstance(node, ast.Attribute)]
    assert "collect" not in attributes
    with mock.patch.object(v2.ctypes, "CDLL") as loader:
        result = v2.release_consumed_legacy_snapshot_memory(1024)
    assert result["attempted"] is False
    loader.assert_not_called()


def test_scanner_reclaims_after_both_legacy_owners_and_before_v2_child():
    source = pathlib.Path("scanner.py").read_text(encoding="utf-8")
    start = source.index("def _osint_persist_locked():")
    end = source.index("\ndef _checkpoint_v2_dual_write", start)
    body = source[start:end]
    delete_blob = body.index("del blob")
    delete_sealed = body.index("del sealed_blob")
    reclaim = body.index("release_consumed_legacy_snapshot_memory")
    child = body.index("_checkpoint_v2_dual_write(checkpoint)")
    assert delete_blob < delete_sealed < reclaim < child
    assert "legacyAllocatorReclaim" in body


def test_reclaim_report_remains_scalar_and_privacy_safe():
    trim = mock.MagicMock(return_value=1)
    allocator = SimpleNamespace(malloc_trim=trim)
    with mock.patch.object(v2, "_process_rss_bytes",
                           side_effect=[900_000_000, 300_000_000]), \
            mock.patch.object(v2.ctypes, "CDLL", return_value=allocator), \
            mock.patch.object(v2.os, "uname",
                              return_value=SimpleNamespace(sysname="Linux")):
        report = v2.release_consumed_legacy_snapshot_memory(128 * 1024 ** 2)
    trim.assert_called_once_with(0)
    assert report["rssReleasedBytes"] == 600_000_000
    assert all(value is None or isinstance(value, (bool, int))
               for value in report.values())


def test_production_lifecycle_probe_uses_real_route_and_persistence_path():
    source = pathlib.Path(
        "scripts/stage1_production_lifecycle_probe.py").read_text(
            encoding="utf-8")
    assert '"/api/argus/admin/missions/tick"' in source
    assert "_osint_persist" not in source
    assert "launch_isolated_generation" not in source
    assert "actualFlaskMissionTickRoute" in source
    assert "actualStateNormalizationAndHashes" in source
    assert "providerNetworkCalls" in source


def test_production_lifecycle_gate_preserves_resource_limits_and_variants():
    source = pathlib.Path(
        "scripts/stage1_production_lifecycle_probe.py").read_text(
            encoding="utf-8")
    ast.parse(source)
    assert "MINIMUM_CYCLES = 32" in source
    assert "RSS_GROWTH_LIMIT = 128 * 1024 ** 2" in source
    assert "CGROUP_PEAK_LIMIT = 3 * 1024 ** 3" in source
    workflow = pathlib.Path(
        ".github/workflows/checkpoint-v2-gate.yml").read_text(
            encoding="utf-8")
    assert "variant: [pre_fix, candidate]" in workflow
    assert "--memory 4g --memory-swap 4g" in workflow
    assert "stage1_production_lifecycle_probe.py" in workflow
