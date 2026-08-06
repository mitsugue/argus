"""Deterministic formal-Soak suppression and one-time arm proof."""
from __future__ import annotations

import pytest

import argus_checkpoint_v2_stage1 as stage1


SHA = "a" * 40


def natural(state, index):
    return stage1.record_generation(
        state,
        {"verified": True, "generationId": f"gen-{index}",
         "databaseBytes": 100 + index,
         "sourceSerializedBytes": 50 + index,
         "resourceTelemetry": {
             "success": True,
             "processRssAfterBytes": 500_000_000 + index,
             "processPeakRssBytes": 800_000_000,
             "cgroupMemoryPeakBytes": 900_000_000,
             "diskFreeAfterBytes": 2 * 1024 ** 3,
             "pendingGenerationCount": 0,
             "legacyTempBaselineCount": 1,
             "legacyTempAfterCount": 1,
             "newLegacyTempCount": 0,
         }},
        trigger_source="ec2_systemd", mission_window_id=f"mw-{index}")


def accepted_state():
    state = stage1.empty_state(SHA)
    for index in range(3):
        state = natural(state, index)
    return stage1.record_acceptance(
        state, resource_accepted=True, disk_accepted=True,
        isolated_restore_verified=True, restore_authority_approved=True)


def test_new_sha_and_three_natural_generations_do_not_start_soak():
    state = stage1.empty_state(SHA)
    assert state["formalSoakState"] == "not_started"
    assert not stage1.may_start_formal_soak(
        state, trigger_source="ec2_systemd", qualified_natural_tick=True)
    for index in range(3):
        state = natural(state, index)
        assert not stage1.may_start_formal_soak(
            state, trigger_source="ec2_systemd", qualified_natural_tick=True)
    assert len(state["naturalGenerations"]) == 3
    assert state["validationWindowCount"] == 3
    assert state["generationCount"] == 3
    assert state["legacyRestoreAuthority"] is True
    assert state["v2RestoreAuthority"] is False


def test_manual_and_diagnostic_generations_do_not_count_or_start():
    state = stage1.empty_state(SHA)
    for source in ("manual", "diagnostic", "workflow_dispatch"):
        state = stage1.record_generation(
            state, {"verified": True, "generationId": f"gen-{source}"},
            trigger_source=source, mission_window_id=f"mw-{source}")
        assert not stage1.may_start_formal_soak(
            state, trigger_source=source, qualified_natural_tick=True)
    assert state["naturalGenerations"] == []


def test_owner_arm_creates_no_soak_and_next_natural_consumes_once():
    state = stage1.arm(
        accepted_state(), build_sha=SHA,
        armed_at="2026-08-04T00:00:00Z")
    assert state["formalSoakArmed"] is True
    assert state["formalSoakState"] == "armed"
    assert not stage1.may_start_formal_soak(
        state, trigger_source="manual", qualified_natural_tick=True)
    assert stage1.may_start_formal_soak(
        state, trigger_source="ec2_systemd", qualified_natural_tick=True)
    consumed = stage1.consume_arm(
        state, consumed_at="2026-08-04T00:07:00Z",
        mission_window_id="mw-start", arm_id=state["armId"])
    assert consumed["formalSoakArmed"] is False
    assert consumed["formalSoakState"] == "started"
    assert not stage1.may_start_formal_soak(
        consumed, trigger_source="ec2_systemd", qualified_natural_tick=True)


def test_arm_requires_three_natural_and_all_acceptance_gates():
    state = stage1.empty_state(SHA)
    with pytest.raises(stage1.Stage1ControlError,
                       match="three_distinct_natural_windows_required"):
        stage1.arm(state, build_sha=SHA, armed_at="now")
    for index in range(3):
        state = natural(state, index)
    with pytest.raises(stage1.Stage1ControlError,
                       match="stage1_acceptance_incomplete"):
        stage1.arm(state, build_sha=SHA, armed_at="now")


def test_failure_disarms_and_blocks_promotion_without_retry_state():
    state = stage1.arm(
        accepted_state(), build_sha=SHA,
        armed_at="2026-08-04T00:00:00Z")
    failed = stage1.record_failure(
        state, "checkpoint_v2_disk_reserve_insufficient",
        {"freeBytes": 1})
    assert failed["formalSoakArmed"] is False
    assert failed["formalSoakState"] == "not_started"
    assert failed["authorityPromotionBlocked"] is True
    assert failed["lastValidationFailure"]["classification"] == \
        "checkpoint_v2_disk_reserve_insufficient"
    assert "retry" not in failed


def test_duplicate_generation_ids_do_not_satisfy_three_generation_gate():
    state = stage1.empty_state(SHA)
    for _ in range(5):
        state = natural(state, 1)
    assert len(state["naturalGenerations"]) == 1
    with pytest.raises(stage1.Stage1ControlError,
                       match="three_distinct_natural_windows_required"):
        stage1.record_acceptance(
            state, resource_accepted=True, disk_accepted=True,
            isolated_restore_verified=True,
            restore_authority_approved=True)


def test_two_generations_in_one_window_count_as_one_validation_window():
    state = stage1.empty_state(SHA)
    for generation_id in ("gen-a", "gen-b"):
        state = stage1.record_generation(
            state, {"verified": True, "generationId": generation_id},
            trigger_source="ec2_systemd", mission_window_id="mw-one")
    assert state["generationCount"] == 2
    assert state["validationWindowCount"] == 1
    with pytest.raises(stage1.Stage1ControlError,
                       match="three_distinct_natural_windows_required"):
        stage1.record_acceptance(
            state, resource_accepted=True, disk_accepted=True,
            isolated_restore_verified=True,
            restore_authority_approved=True)


def test_counts_survive_bounded_generation_history_and_normalization():
    state = stage1.empty_state(SHA)
    for index in range(20):
        state = natural(state, index)
    assert len(state["naturalGenerations"]) == 12
    assert state["generationCount"] == 20
    assert state["validationWindowCount"] == 20
    restored = stage1.normalize(state, SHA)
    assert restored["generationCount"] == 20
    assert restored["validationWindowCount"] == 20
