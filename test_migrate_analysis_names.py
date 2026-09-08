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
