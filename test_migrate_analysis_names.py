"""Metadata migration preserves history and rejects ambiguous/corrupt input."""
import copy

import pytest

import argus_today_intelligence as today
from scripts.migrate_analysis_names import migrate, translate


def source():
    body = {"symbol": "1321", "market": "JP", "asOf": "2026-09-08",
            "methodVersion": "retired_method_v1", "ohlcv": {"close": 123.45},
            "calibration": {"probability": None, "validated": False},
            "shortSelling": {"value": 0}, "failedRally": {"state": "NONE"}}
    row = {**body, "id": "today-" + today._hash(body)}
    state = {**today.empty_state(), "snapshots": [row],
             "shortSellingHistory": [{"date": "2026-09-01", "value": 12.3}],
             "lastUpdatedAt": "2026-09-08T16:00:00Z"}
    return {"todayIntelligence": state, "todayIntelligenceStateHash": today.state_hash(state),
            "holdings": [{"symbol": "1321", "quantity": 5, "cost": 100.0}],
            "settings": {"enabled": False}, "predictions": [{"action": "WAIT"}]}


def test_history_preserved_and_identities_recomputed_without_mutating_source():
    before = source()
    original = copy.deepcopy(before)
    result, receipt = migrate(before, {"retired_method_v1": "jp-market-engine-v1"})
    assert before == original
    assert receipt["productionApplied"] is False
    assert len(receipt["identityChanges"]) == 1
    old = before["todayIntelligence"]["snapshots"][0]
    new = result["todayIntelligence"]["snapshots"][0]
    assert old["id"] != new["id"]
    assert {k: v for k, v in old.items() if k not in {"id", "methodVersion"}} == {
        k: v for k, v in new.items() if k not in {"id", "methodVersion"}}
    for key in ("holdings", "settings", "predictions"):
        assert result[key] == before[key]
    assert result["todayIntelligence"]["shortSellingHistory"] == before["todayIntelligence"]["shortSellingHistory"]
    assert result["todayIntelligenceStateHash"] == today.state_hash(result["todayIntelligence"])
    repeated, second = migrate(result, {"retired_method_v1": "jp-market-engine-v1"})
    assert repeated == result
    assert second["identityChanges"] == []


@pytest.mark.parametrize("field", ["id", "sectionHash"])
def test_corrupt_original_cannot_receive_a_new_valid_identity(field):
    before = source()
    if field == "id":
        before["todayIntelligence"]["snapshots"][0]["id"] = "today-corrupt"
    else:
        before["todayIntelligenceStateHash"] = "corrupt"
    with pytest.raises(ValueError, match="(source_identity|source_section_hash)_invalid"):
        migrate(before, {"retired_method_v1": "jp-market-engine-v1"})


def test_unhandled_signed_history_is_not_silently_rewritten():
    before = source()
    before["predictions"][0]["method"] = "retired_method_v1"
    with pytest.raises(ValueError, match="unhandled_section"):
        migrate(before, {"retired_method_v1": "jp-market-engine-v1"})


def test_key_collision_and_non_idempotent_mapping_fail():
    with pytest.raises(ValueError, match="collision"):
        translate({"retired_field": 1, "current_field": 2}, {"retired_field": "current_field"})
    with pytest.raises(ValueError, match="idempotent"):
        migrate(source(), {"a": "b", "b": "c"})


def test_only_exact_strings_change():
    assert translate({"retired_field": [False, 0, None, 0.5, "retired_fields"]},
                     {"retired_field": "current_field"}) == {
                         "current_field": [False, 0, None, 0.5, "retired_fields"]}


def _restore_policy(monkeypatch):
    import json
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps({
        "schemaVersion": "product-naming-policy-v1", "rules": [
            {"id": "N001", "pattern": "retired_method_v1"}]}))
    return json.dumps({"retired_method_v1": "jp-market-engine-v1"})


def test_restore_preserves_source_and_receipts_without_claiming_checkpoint(tmp_path, monkeypatch):
    import json
    import argus_persistent_storage as storage
    from scripts.analysis_migration_restore import prepare_restore, record_restore_applied
    mapping = _restore_policy(monkeypatch)
    original = storage.seal_checkpoint({**source(), "schemaVersion": "argus-durable-v3"})
    before = copy.deepcopy(original)
    current, prepared = prepare_restore(original, root=tmp_path, mapping_text=mapping)
    assert original == before and storage.verify_checkpoint(original)
    assert "localCheckpointIntegrity" not in current
    archive = tmp_path / "analysis-name-migration" / prepared["sourceArchive"]
    assert json.loads(archive.read_text()) == before
    assert archive.stat().st_mode & 0o777 == 0o600
    assert prepared["productionApplied"] is False
    applied = record_restore_applied(prepared, root=tmp_path)
    assert applied["status"] == "APPLIED_TO_MEMORY"
    assert applied["productionApplied"] is False and applied["checkpointVerified"] is False
    repeated, same = prepare_restore(original, root=tmp_path, mapping_text=mapping)
    assert repeated == current and same == prepared
    assert record_restore_applied(same, root=tmp_path) == applied
    unchanged, receipt = prepare_restore(current, root=tmp_path, mapping_text=mapping)
    assert unchanged == current and receipt is None


def test_restore_requires_complete_policy_and_mapping_without_deleting_source(tmp_path, monkeypatch):
    from scripts.analysis_migration_restore import prepare_restore
    import argus_product_naming as naming
    mapping = _restore_policy(monkeypatch)
    before = source()
    original = copy.deepcopy(before)
    with pytest.raises(naming.NamingPolicyError, match="content_rejected"):
        prepare_restore(before, root=tmp_path, required=True)
    with pytest.raises(naming.NamingPolicyError, match="content_rejected"):
        prepare_restore(before, root=tmp_path, mapping_text='{"unrelated": "replacement"}')
    monkeypatch.delenv("PRODUCT_NAMING_POLICY")
    with pytest.raises(naming.NamingPolicyError, match="policy_unavailable"):
        prepare_restore(before, root=tmp_path, mapping_text=mapping)
    assert before == original and not list(tmp_path.iterdir())


def test_restore_archive_failures_never_apply_or_overwrite(tmp_path, monkeypatch):
    from scripts import analysis_migration_restore as migration
    import argus_persistent_storage as storage
    mapping = _restore_policy(monkeypatch)
    before = source()
    original = copy.deepcopy(before)
    with monkeypatch.context() as scoped:
        scoped.setattr(storage, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("disk_full")))
        with pytest.raises(OSError, match="disk_full"):
            migration.prepare_restore(before, root=tmp_path, mapping_text=mapping)
    assert before == original
    _, receipt = migration.prepare_restore(before, root=tmp_path, mapping_text=mapping)
    archive = tmp_path / "analysis-name-migration" / receipt["sourceArchive"]
    archive.write_text("corrupt")
    with pytest.raises(ValueError, match="archive_conflict"):
        migration.prepare_restore(before, root=tmp_path, mapping_text=mapping)
    with pytest.raises(ValueError, match="archive_invalid"):
        migration.record_restore_applied(receipt, root=tmp_path, production=True)
    assert archive.read_text() == "corrupt" and before == original


def test_restore_rejects_tampered_receipt_and_archive_symlink(tmp_path, monkeypatch):
    from scripts import analysis_migration_restore as migration
    mapping = _restore_policy(monkeypatch)
    _, receipt = migration.prepare_restore(source(), root=tmp_path, mapping_text=mapping)
    tampered = {**receipt, "sourceArchive": "../unrelated.json"}
    with pytest.raises(ValueError, match="receipt_invalid"):
        migration.record_restore_applied(tampered, root=tmp_path)
    archive = tmp_path / "analysis-name-migration" / receipt["sourceArchive"]
    retained = tmp_path / "retained.json"
    archive.rename(retained)
    archive.symlink_to(retained)
    with pytest.raises(ValueError, match="symlink_rejected"):
        migration.prepare_restore(source(), root=tmp_path, mapping_text=mapping)
    with pytest.raises(ValueError, match="archive_invalid"):
        migration.record_restore_applied(receipt, root=tmp_path)
    assert retained.is_file()


def test_runtime_migrates_verified_source_once_and_preserves_checkpoint(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    import scanner
    import argus_persistent_storage as storage
    from test_argus_persistent_mission_storage import scanner_storage, remote_snapshot
    mapping = _restore_policy(monkeypatch)
    monkeypatch.setenv("PRODUCT_ANALYSIS_MIGRATION_MAP", mapping)
    monkeypatch.setattr(scanner, "_TODAY_INTELLIGENCE", today.empty_state())
    monkeypatch.setattr(scanner, "_cost_policy_restore_durable", lambda: None)
    snapshot = {**remote_snapshot(), **source()}
    with scanner_storage(str(tmp_path)) as configured:
        storage.write_checkpoint(configured["checkpoint"], snapshot, temp_directory=str(tmp_path))
        original_bytes = Path(configured["checkpoint"]).read_bytes()
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._TODAY_INTELLIGENCE["snapshots"][0]["methodVersion"] == "jp-market-engine-v1"
        first = copy.deepcopy(scanner._TODAY_INTELLIGENCE)
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._TODAY_INTELLIGENCE == first
        receipt = scanner._DURABLE_STATE["analysisNameMigration"]
        assert receipt["status"] == "APPLIED_TO_MEMORY"
        assert receipt["productionApplied"] is True and receipt["checkpointVerified"] is False
        assert Path(configured["checkpoint"]).read_bytes() == original_bytes
        assert storage.verify_checkpoint(json.loads(original_bytes))


def test_runtime_missing_mapping_blocks_overwrite_and_can_retry(tmp_path, monkeypatch):
    from pathlib import Path
    import scanner
    import argus_persistent_storage as storage
    from test_argus_persistent_mission_storage import scanner_storage, remote_snapshot
    mapping = _restore_policy(monkeypatch)
    monkeypatch.delenv("PRODUCT_ANALYSIS_MIGRATION_MAP", raising=False)
    monkeypatch.setattr(scanner, "_TODAY_INTELLIGENCE", today.empty_state())
    monkeypatch.setattr(scanner, "_cost_policy_restore_durable", lambda: None)
    with scanner_storage(str(tmp_path)) as configured:
        storage.write_checkpoint(configured["checkpoint"], {**remote_snapshot(), **source()}, temp_directory=str(tmp_path))
        original = Path(configured["checkpoint"]).read_bytes()
        before = copy.deepcopy(scanner._TODAY_INTELLIGENCE)
        assert scanner._osint_restore_once() is None
        assert scanner._OSINT_PERSIST_STATE["restored"] is False
        assert scanner._TODAY_INTELLIGENCE == before
        assert scanner._DURABLE_STATE["analysisNameMigration"]["status"] == "BLOCKED"
        assert scanner._osint_persist_locked() == {
            "verified": False, "errorClass": "analysis_restore_incomplete"}
        assert Path(configured["checkpoint"]).read_bytes() == original
        monkeypatch.setenv("PRODUCT_ANALYSIS_MIGRATION_MAP", mapping)
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["analysisNameMigration"]["status"] == "APPLIED_TO_MEMORY"


def test_runtime_receipt_failure_rolls_back_all_store_changes(tmp_path, monkeypatch):
    from pathlib import Path
    import scanner
    import argus_persistent_storage as storage
    from test_argus_persistent_mission_storage import scanner_storage, remote_snapshot
    mapping = _restore_policy(monkeypatch)
    monkeypatch.setenv("PRODUCT_ANALYSIS_MIGRATION_MAP", mapping)
    monkeypatch.setattr(scanner, "_TODAY_INTELLIGENCE", today.empty_state())
    monkeypatch.setattr(scanner, "_cost_policy_restore_durable", lambda: None)
    monkeypatch.setattr(scanner.analysis_migration_restore, "record_restore_applied",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk_full")))
    with scanner_storage(str(tmp_path)) as configured:
        storage.write_checkpoint(configured["checkpoint"], {**remote_snapshot(), **source()}, temp_directory=str(tmp_path))
        original = Path(configured["checkpoint"]).read_bytes()
        before = copy.deepcopy(scanner._TODAY_INTELLIGENCE)
        assert scanner._osint_restore_once() is None
        assert scanner._TODAY_INTELLIGENCE == before
        assert scanner._OSINT_PERSIST_STATE["restored"] is False
        assert scanner._osint_persist_locked()["verified"] is False
        assert Path(configured["checkpoint"]).read_bytes() == original
        assert len(list((tmp_path / "analysis-name-migration").glob("source-*.json"))) == 1
        assert not list((tmp_path / "analysis-name-migration").glob("applied-*.json"))


def test_runtime_wal_cannot_reintroduce_metadata_after_snapshot_migration(tmp_path, monkeypatch):
    from pathlib import Path
    import scanner
    import argus_persistent_storage as storage
    import argus_tick_durability as wal
    from test_argus_persistent_mission_storage import scanner_storage, remote_snapshot
    mapping = _restore_policy(monkeypatch)
    monkeypatch.setenv("PRODUCT_ANALYSIS_MIGRATION_MAP", mapping)
    monkeypatch.setattr(scanner, "_TODAY_INTELLIGENCE", today.empty_state())
    monkeypatch.setattr(scanner, "_cost_policy_restore_durable", lambda: None)
    with scanner_storage(str(tmp_path)) as configured:
        storage.write_checkpoint(configured["checkpoint"], {**remote_snapshot(), **source()}, temp_directory=str(tmp_path))
        wal.append_wal(configured["wal"], sequence=1, kind="mission_transition", job_id="synthetic",
            payload={"aggregatePatch": {"type": "forecast", "record": {
                "id": "synthetic-forecast", "method": "retired_method_v1", "action": "WAIT"}}})
        original_wal = Path(configured["wal"]).read_bytes()
        original_checkpoint = Path(configured["checkpoint"]).read_bytes()
        before = copy.deepcopy(scanner._FORECAST_LEDGER)
        assert scanner._osint_restore_once() is None
        assert scanner._FORECAST_LEDGER == before
        assert scanner._OSINT_PERSIST_STATE["restored"] is False
        assert scanner._DURABLE_STATE["analysisNameMigration"]["status"] == "BLOCKED"
        assert scanner._osint_persist_locked()["verified"] is False
        assert Path(configured["wal"]).read_bytes() == original_wal
        assert Path(configured["checkpoint"]).read_bytes() == original_checkpoint


def test_translation_copies_only_changed_paths_and_never_mutates_source():
    unchanged = {"ohlcv": [{"close": 123.45, "volume": 1234}] * 1000}
    original = {"data": unchanged, "metadata": {"method": "retired_method_v1"}}
    before = copy.deepcopy(original)
    converted = translate(original, {"retired_method_v1": "jp-market-engine-v1"})
    assert original == before
    assert converted is not original
    assert converted["metadata"] is not original["metadata"]
    assert converted["data"] is unchanged
    converted["metadata"]["id"] = "current-id"
    assert original == before
