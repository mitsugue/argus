"""Recovery Phase A registry safety invariants."""

import dataclasses
import ast
import json
import pathlib

import argus_recovery_registry as registry


def test_registry_is_valid_sorted_unique_and_deterministic():
    assert registry.validate_registry() == []
    state_ids = [row.stateId for row in registry.states()]
    mutation_ids = [row.mutationClass for row in registry.mutations()]
    assert state_ids == sorted(state_ids)
    assert mutation_ids == sorted(mutation_ids)
    assert len(state_ids) == len(set(state_ids))
    assert len(mutation_ids) == len(set(mutation_ids))
    first = json.dumps(registry.registry_document(), sort_keys=True)
    second = json.dumps(registry.registry_document(), sort_keys=True)
    assert first == second


def test_a_b_and_f_are_conservatively_must_preserve():
    protected = {registry.Classification.A, registry.Classification.B,
                 registry.Classification.F}
    assert all(row.mustPreserveNow for row in registry.states()
               if row.classification in protected)
    unresolved = [row for row in registry.states()
                  if row.classification == registry.Classification.F]
    assert unresolved
    assert all(row.intendedFutureDurability == registry.FutureDurability.UNRESOLVED
               for row in unresolved)


def test_unproved_c_and_uncontracted_d_remain_preserved():
    for row in registry.states():
        if row.classification == registry.Classification.C and \
                not row.rebuildProofAccepted:
            assert row.mustPreserveNow is True
        if row.classification == registry.Classification.D and \
                not row.reacquisitionContractAccepted:
            assert row.mustPreserveNow is True


def test_private_and_secret_states_are_never_telemetry_exportable():
    private = {registry.PrivacyClass.OWNER_PRIVATE,
               registry.PrivacyClass.SECRET,
               registry.PrivacyClass.CLIENT_PRIVATE,
               registry.PrivacyClass.CLIENT_OPAQUE}
    for row in registry.states():
        if row.containsSecret or row.containsOwnerPrivateData or \
                row.privacyClass in private:
            assert row.allowedInTelemetry is False


def test_unknown_classification_and_unsafe_omission_fail_closed():
    base = registry.states()[0]
    unknown = dataclasses.replace(base, classification="G_UNKNOWN")
    assert any("unknown_classification" in error
               for error in registry.validate_registry([unknown], []))
    invalid_durability = dataclasses.replace(
        base, intendedFutureDurability="MAGICAL_DURABILITY")
    assert any("invalid_intendedFutureDurability" in error
               for error in registry.validate_registry(
                   [invalid_durability], []))

    c_row = next(row for row in registry.states()
                 if row.classification == registry.Classification.C)
    unsafe_c = dataclasses.replace(c_row, mustPreserveNow=False,
                                   rebuildProofAccepted=False)
    assert any("unproved_rebuild_cannot_omit" in error
               for error in registry.validate_registry([unsafe_c], []))

    d_row = next(row for row in registry.states()
                 if row.classification == registry.Classification.D)
    unsafe_d = dataclasses.replace(d_row, mustPreserveNow=False,
                                   reacquisitionContractAccepted=False)
    assert any("uncontracted_reacquisition_cannot_omit" in error
               for error in registry.validate_registry([unsafe_d], []))


def test_ephemeral_full_plus_wal_requires_explicit_reason():
    e_row = next(row for row in registry.states()
                 if row.classification == registry.Classification.E)
    unsafe = dataclasses.replace(
        e_row, intendedFutureDurability=registry.FutureDurability.FULL_PLUS_WAL,
        ephemeralFullWalReason=None)
    assert any("ephemeral_full_wal_reason_required" in error
               for error in registry.validate_registry([unsafe], []))
    safe = dataclasses.replace(unsafe, ephemeralFullWalReason="audit requirement")
    assert not any("ephemeral_full_wal_reason_required" in error
                   for error in registry.validate_registry([safe], []))


def test_mutation_targets_exist_and_unknown_discovery_is_loud_not_runtime_fatal():
    known = set(registry.state_by_id())
    assert all(set(row.targetStateIds) <= known for row in registry.mutations())
    assert registry.unregistered_state_ids(
        ["backend.missions", "future.authority.unknown"]) == (
            "future.authority.unknown",)


def test_large_stores_client_boundary_and_legacy_predictions_are_explicit():
    by_id = registry.state_by_id()
    checkpoint_keys = {key for row in registry.states()
                       for key in row.checkpointKeys}
    assert {"marketLedger", "verifiedViewSnapshots", "assetChartReports",
            "chartIntelligence", "marketReplay", "todayIntelligence"} <= \
        checkpoint_keys
    legacy = by_id["secondary.legacy_predictions"]
    assert legacy.classification == registry.Classification.F
    assert legacy.mustPreserveNow is True
    assert legacy.intendedFutureDurability == registry.FutureDurability.UNRESOLVED
    for state_id in ("client.risk_lines", "client.replay_drawings",
                     "client.pasted_research", "client.dismissed_gaps"):
        row = by_id[state_id]
        assert row.classification == registry.Classification.F
        assert row.currentRecoveryCoverage == registry.RecoveryCoverage.CLIENT_BOUNDARY
        assert row.containsOwnerPrivateData is True


def test_current_wal_coverage_summary_never_invents_complete_coverage():
    summary = registry.registry_summary()
    assert summary["validationStatus"] == "valid"
    assert summary["currentWalCoverageCounts"]["COMPLETE"] == 0
    assert summary["currentWalCoverageCounts"][
        "NOT_DURABLE_FOR_EXACT_REPLAY"] > 0
    assert summary["shadowOnly"] is True


def test_every_literal_checkpoint_section_is_registered():
    tree = ast.parse(pathlib.Path("scanner.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_osint_persist_locked")
    observed = set()

    def dict_keys(value):
        if isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    observed.add(key.value)

    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "blob":
                    dict_keys(node.value)
                elif isinstance(target, ast.Subscript) and \
                        isinstance(target.value, ast.Name) and \
                        target.value.id == "blob" and \
                        isinstance(target.slice, ast.Constant) and \
                        isinstance(target.slice.value, str):
                    observed.add(target.slice.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                isinstance(node.func.value, ast.Name) and \
                node.func.value.id == "blob" and node.func.attr == "update" and \
                node.args:
            dict_keys(node.args[0])
    registered = {key for row in registry.states() for key in row.checkpointKeys}
    assert observed
    assert observed - registered == set()
