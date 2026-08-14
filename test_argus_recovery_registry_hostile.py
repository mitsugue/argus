"""Hostile type and compatibility matrix for Registry Core v1."""

import dataclasses
from enum import Enum
import math

import pytest

import argus_recovery_registry as registry


class HostileValue:
    def __bool__(self):
        raise AssertionError("validator called __bool__")

    def __hash__(self):
        raise AssertionError("validator called __hash__")

    def __iter__(self):
        raise AssertionError("validator called __iter__")

    def __str__(self):
        raise AssertionError("validator called __str__")

    def __repr__(self):
        raise AssertionError("validator called __repr__")


class HostileCollisionKey:
    def __init__(self, collision):
        self.collision = collision
        self.calls = []

    def __hash__(self):
        self.calls.append("hash")
        return hash(self.collision)

    def __eq__(self, other):
        self.calls.append("eq")
        raise AssertionError("authorization called hostile __eq__")

    def __str__(self):
        self.calls.append("str")
        raise AssertionError("authorization called hostile __str__")

    def __repr__(self):
        self.calls.append("repr")
        raise AssertionError("authorization called hostile __repr__")


class WrongEnum(str, Enum):
    VALUE = "PUBLIC_METADATA"


def _errors_for_state(row):
    return registry.validate_registry((row,), ())


def _errors_for_mutation(row):
    return registry.validate_registry(registry.states(), (row,))


@pytest.mark.parametrize("value", [
    None, True, False, 0, 1, -1, 1.5, math.nan, math.inf,
    "tuple", ["x"], {"x": 1}, {"x"}, (item for item in ("x",)),
    HostileValue(),
])
def test_total_validator_rejects_non_tuple_top_level_without_raising(value):
    first = registry.validate_registry(value, value)
    second = registry.validate_registry(value, value)
    assert first == second
    assert "state_registry:not_exact_tuple" in first
    assert "mutation_registry:not_exact_tuple" in first


def test_total_validator_bounds_exact_tuple_without_iteration_hazards():
    oversized = tuple(HostileValue() for _ in range(513))
    assert registry.validate_registry(oversized, ()) == (
        "state_registry:too_many_rows",)
    assert registry.validate_registry((), oversized) == (
        "mutation_registry:too_many_rows",)
    assert "state[0]:not_exact_StateDeclaration" in \
        registry.validate_registry((HostileValue(),), ())
    assert "mutation[0]:not_exact_MutationDeclaration" in \
        registry.validate_registry((), (HostileValue(),))


@pytest.mark.parametrize("field", [
    "mustPreserveNow", "containsSecret", "containsOwnerPrivateData",
    "allowedInTelemetry",
])
@pytest.mark.parametrize("value,is_exact", [
    (True, True), (False, True), (0, False), (1, False),
    ("true", False), ("false", False), (None, False),
    ([], False), ({}, False), (HostileValue(), False),
])
def test_state_boolean_fields_require_exact_bool(field, value, is_exact):
    row = dataclasses.replace(registry.states()[0], **{field: value})
    errors = _errors_for_state(row)
    code = f":{field}:not_exact_bool"
    assert any(code in error for error in errors) is (not is_exact)


@pytest.mark.parametrize("field", [
    "deterministicReducerExpected", "syncDurabilityCandidate",
])
@pytest.mark.parametrize("value,is_exact", [
    (True, True), (False, True), (0, False), (1, False),
    ("false", False), (None, False), ([], False), ({}, False),
    (HostileValue(), False),
])
def test_mutation_boolean_fields_require_exact_bool(field, value, is_exact):
    row = dataclasses.replace(registry.mutations()[0], **{field: value})
    errors = _errors_for_mutation(row)
    code = f":{field}:not_exact_bool"
    assert any(code in error for error in errors) is (not is_exact)


STATE_ENUM_FIELDS = (
    ("classification", registry.Classification),
    ("currentStorageKind", registry.StorageKind),
    ("currentRecoveryCoverage", registry.RecoveryCoverage),
    ("privacyClass", registry.PrivacyClass),
    ("intendedFutureDurability", registry.FutureDurability),
    ("sourceDerivedStatus", registry.StateNature),
    ("mutationRegistryExpectation", registry.ReducerExpectation),
)


@pytest.mark.parametrize("field,enum_type", STATE_ENUM_FIELDS)
@pytest.mark.parametrize("bad_value", [
    "PUBLIC_METADATA", WrongEnum.VALUE, 1, None, [], {}, HostileValue(),
])
def test_state_enums_require_exact_expected_enum(field, enum_type, bad_value):
    row = dataclasses.replace(registry.states()[0], **{field: bad_value})
    errors = _errors_for_state(row)
    assert any(f":{field}:not_exact_enum" in error for error in errors)


MUTATION_ENUM_FIELDS = (
    ("criticality", registry.MutationCriticality),
    ("currentWalCoverage", registry.WalCoverage),
    ("futureTreatment", registry.FutureMutationTreatment),
    ("privacyClass", registry.PrivacyClass),
    ("payloadTelemetryPolicy", registry.PayloadTelemetryPolicy),
)


@pytest.mark.parametrize("field,enum_type", MUTATION_ENUM_FIELDS)
@pytest.mark.parametrize("bad_value", [
    "METADATA_ONLY", WrongEnum.VALUE, 1, None, [], {}, HostileValue(),
])
def test_mutation_enums_require_exact_expected_enum(field, enum_type, bad_value):
    row = dataclasses.replace(registry.mutations()[0], **{field: bad_value})
    errors = _errors_for_mutation(row)
    assert any(f":{field}:not_exact_enum" in error for error in errors)


@pytest.mark.parametrize("field,bad_value", [
    ("stateId", ""),
    ("stateId", "Upper.Case"),
    ("stateId", "security.秘密"),
    ("stateId", "x." + "a" * 129),
    ("humanName", ""),
    ("humanName", "x" * 161),
    ("mutationDomain", "Bad Domain"),
    ("mutationDomain", "秘密"),
    ("evidenceOwnerModule", "x" * 257),
    ("notes", "x" * 1025),
    ("notes", "bad\nline"),
    ("humanName", None),
    ("notes", HostileValue()),
])
def test_state_strings_are_bounded_and_field_specific(field, bad_value):
    row = dataclasses.replace(registry.states()[0], **{field: bad_value})
    assert any(f":{field}:" in error for error in _errors_for_state(row))


@pytest.mark.parametrize("field,bad_value", [
    ("mutationId", ""),
    ("mutationId", "Bad.Id"),
    ("mutationId", "x." + "a" * 129),
    ("sourceFamily", "bad family"),
    ("sourceFamily", "秘密"),
    ("currentPersistenceRoute", "x" * 257),
    ("notes", "x" * 1025),
    ("notes", HostileValue()),
])
def test_mutation_strings_are_bounded_and_field_specific(field, bad_value):
    row = dataclasses.replace(registry.mutations()[0], **{field: bad_value})
    assert any(f":{field}:" in error for error in _errors_for_mutation(row))


@pytest.mark.parametrize("field,bad_value", [
    ("rebuildRequirements", ["input"]),
    ("rebuildRequirements", (item for item in ("input",))),
    ("rebuildRequirements", ("same", "same")),
    ("rebuildRequirements", tuple(str(i) for i in range(65))),
    ("rebuildRequirements", (HostileValue(),)),
    ("checkpointKeys", ["missions"]),
    ("checkpointKeys", (item for item in ("missions",))),
    ("checkpointKeys", ("missions", "missions")),
    ("checkpointKeys", tuple(f"Key{i}" for i in range(65))),
    ("checkpointKeys", ("bad-key",)),
    ("checkpointKeys", (HostileValue(),)),
])
def test_state_containers_are_exact_bounded_tuples(field, bad_value):
    row = dataclasses.replace(registry.states()[0], **{field: bad_value})
    assert any(f":{field}" in error for error in _errors_for_state(row))


@pytest.mark.parametrize("bad_value", [
    ["backend.missions"],
    (item for item in ("backend.missions",)),
    ("backend.missions", "backend.missions"),
    tuple(f"future.state_{i}" for i in range(65)),
    ("Bad.Target",),
    (HostileValue(),),
    (),
])
def test_mutation_targets_are_exact_bounded_nonempty_tuple(bad_value):
    row = dataclasses.replace(
        registry.mutations()[0], targetStateIds=bad_value)
    assert any(":targetStateIds" in error
               for error in _errors_for_mutation(row))


@pytest.mark.parametrize("classification", [
    registry.Classification.A,
    registry.Classification.B,
])
def test_a_or_b_class_cannot_be_ephemeral(classification):
    row = next(item for item in registry.states()
               if item.classification is classification)
    bad = dataclasses.replace(
        row, intendedFutureDurability=registry.FutureDurability.EPHEMERAL)
    errors = _errors_for_state(bad)
    assert any("classification_future_incompatible" in error or
               "unresolved_state_must_remain_unresolved" in error
               for error in errors)


@pytest.mark.parametrize("future", [
    registry.FutureDurability.FULL_PLUS_WAL,
    registry.FutureDurability.IMMUTABLE_EXTERNAL_REF,
    registry.FutureDurability.REBUILD_AFTER_PROOF,
    registry.FutureDurability.REACQUIRE_AFTER_CONTRACT,
    registry.FutureDurability.EPHEMERAL,
])
def test_f_accepts_only_unresolved_future_durability(future):
    row = next(item for item in registry.states()
               if item.classification is registry.Classification.F)
    bad = dataclasses.replace(row, intendedFutureDurability=future)
    assert any("unresolved_state_must_remain_unresolved" in error
               for error in _errors_for_state(bad))


def test_c_and_d_must_preserve_in_v1_and_require_contract_inputs():
    c_row = next(row for row in registry.states()
                 if row.classification is registry.Classification.C)
    d_row = next(row for row in registry.states()
                 if row.classification is registry.Classification.D)
    assert any("v1_rebuild_state_must_preserve" in error
               for error in _errors_for_state(
                   dataclasses.replace(c_row, mustPreserveNow=False)))
    assert any("rebuild_contract_incomplete" in error
               for error in _errors_for_state(
                   dataclasses.replace(c_row, rebuildRequirements=())))
    assert any("v1_reacquirable_state_must_preserve" in error
               for error in _errors_for_state(
                   dataclasses.replace(d_row, mustPreserveNow=False)))
    assert any("reacquisition_contract_incomplete" in error
               for error in _errors_for_state(
                   dataclasses.replace(d_row, rebuildRequirements=())))


def test_retained_e_requires_full_wal_preservation_and_reason():
    row = next(item for item in registry.states()
               if item.classification is registry.Classification.E)
    missing_reason = dataclasses.replace(
        row, mustPreserveNow=True,
        intendedFutureDurability=registry.FutureDurability.FULL_PLUS_WAL,
        ephemeralRetentionReason=None)
    assert any("retained_cache_reason_required" in error
               for error in _errors_for_state(missing_reason))
    valid = dataclasses.replace(
        missing_reason, ephemeralRetentionReason="Audit receipt retention")
    assert registry.validate_registry((valid,), ()) == ()


@pytest.mark.parametrize("privacy", [
    registry.PrivacyClass.INTERNAL,
    registry.PrivacyClass.OWNER_PRIVATE,
    registry.PrivacyClass.SECURITY_SENSITIVE,
    registry.PrivacyClass.SECRET,
    registry.PrivacyClass.CLIENT_PRIVATE,
    registry.PrivacyClass.CLIENT_OPAQUE,
])
def test_nonpublic_privacy_can_never_authorize_telemetry(privacy):
    row = next(item for item in registry.states()
               if item.privacyClass is privacy)
    bad = dataclasses.replace(row, allowedInTelemetry=True)
    assert registry.state_allows_public_telemetry(bad) is False
    assert any("incompatible_public_telemetry" in error
               for error in _errors_for_state(bad))


def test_public_metadata_cannot_hide_private_or_secret_content():
    row = next(item for item in registry.states()
               if registry.state_allows_public_telemetry(item))
    for change in (
            {"containsSecret": True},
            {"containsOwnerPrivateData": True}):
        bad = dataclasses.replace(row, **change)
        assert registry.state_allows_public_telemetry(bad) is False
        assert any("public_metadata_contains_private_content" in error
                   for error in _errors_for_state(bad))


def test_unknown_privacy_is_invalid_and_never_public():
    row = dataclasses.replace(
        registry.states()[0], privacyClass="PUBLIC_METADATA",
        allowedInTelemetry=True)
    assert registry.state_allows_public_telemetry(row) is False
    assert any(":privacyClass:not_exact_enum" in error
               for error in _errors_for_state(row))


def test_unknown_and_mixed_targets_fail_closed():
    template = next(
        row for row in registry.mutations()
        if registry.mutation_allows_public_telemetry(row))
    unknown = dataclasses.replace(
        template, mutationId="future.unknown_target",
        targetStateIds=("future.missing_state",))
    assert registry.mutation_allows_public_telemetry(unknown) is False
    assert any("unknown_target:future.missing_state" in error
               for error in _errors_for_mutation(unknown))

    private_target = next(
        row.stateId for row in registry.states()
        if row.privacyClass is registry.PrivacyClass.SECURITY_SENSITIVE)
    mixed = dataclasses.replace(
        template, mutationId="future.mixed_target",
        targetStateIds=(template.targetStateIds[0], private_target))
    assert registry.mutation_allows_public_telemetry(mixed) is False
    assert any("public_mutation_targets_nonpublic_state" in error
               for error in _errors_for_mutation(mixed))


def test_duplicate_state_and_mutation_ids_are_invalid():
    state = registry.states()[0]
    mutation = registry.mutations()[0]
    assert "state_registry:duplicate_state_id" in \
        registry.validate_registry((state, state), ())
    assert "mutation_registry:duplicate_mutation_id" in \
        registry.validate_registry(registry.states(), (mutation, mutation))


def test_future_security_state_defaults_private_and_cannot_taint_public_mutation():
    future = registry._s(
        "security.future_private_state", "Future private security state",
        registry.Classification.A, registry.StorageKind.LOCAL_SIDECAR,
        registry.RecoveryCoverage.LOCAL_ONLY, "security",
        registry.PrivacyClass.SECURITY_SENSITIVE,
        registry.FutureDurability.FULL_PLUS_WAL,
        registry.StateNature.CONTROL, registry.ReducerExpectation.REQUIRED,
        "future_security_module.py", "Future-entry hostile regression row.")
    assert future.allowedInTelemetry is False
    assert registry.state_allows_public_telemetry(future) is False
    assert registry.validate_registry((future,), ()) == ()

    explicit = dataclasses.replace(future, allowedInTelemetry=True)
    assert any("incompatible_public_telemetry" in error
               for error in registry.validate_registry((explicit,), ()))

    safe_mutation = next(
        row for row in registry.mutations()
        if registry.mutation_allows_public_telemetry(row))
    mixed = dataclasses.replace(
        safe_mutation, mutationId="security.future_mixed_mutation",
        targetStateIds=(safe_mutation.targetStateIds[0], future.stateId))
    state_rows = tuple(sorted(
        registry.states() + (future,), key=lambda row: row.stateId))
    state_index = {row.stateId: row for row in state_rows}
    assert registry.mutation_allows_public_telemetry(mixed, state_index) is False
    assert any("public_mutation_targets_nonpublic_state" in error
               for error in registry.validate_registry(state_rows, (mixed,)))


def test_direct_declaration_and_unknown_helper_default_fail_closed():
    template = registry.states()[0]
    values = {
        field.name: getattr(template, field.name)
        for field in dataclasses.fields(registry.StateDeclaration)
        if field.name not in {"allowedInTelemetry", "ephemeralRetentionReason"}
    }
    direct = registry.StateDeclaration(**values)
    assert direct.allowedInTelemetry is False

    unknown = registry._s(
        "security.future_unknown", "Future unknown classification",
        "G_UNKNOWN", registry.StorageKind.LOCAL_SIDECAR,
        registry.RecoveryCoverage.UNKNOWN, "security",
        registry.PrivacyClass.SECURITY_SENSITIVE,
        registry.FutureDurability.UNRESOLVED,
        registry.StateNature.CONTROL, registry.ReducerExpectation.UNRESOLVED,
        "future.py", "Unknown classification remains preserve-now and invalid.")
    assert unknown.mustPreserveNow is True
    assert unknown.allowedInTelemetry is False
    assert any(":classification:not_exact_enum" in error
               for error in registry.validate_registry((unknown,), ()))


def test_helper_does_not_coerce_explicit_hostile_values():
    row = registry._s(
        "security.future_hostile", "Future hostile row",
        registry.Classification.A, registry.StorageKind.LOCAL_SIDECAR,
        registry.RecoveryCoverage.LOCAL_ONLY, "security",
        registry.PrivacyClass.SECURITY_SENSITIVE,
        registry.FutureDurability.FULL_PLUS_WAL,
        registry.StateNature.CONTROL, registry.ReducerExpectation.REQUIRED,
        "test.py", "Explicit values must remain uncoerced.",
        preserve=None, telemetry="false", keys=["missions"],
        inputs=(item for item in ("input",)))
    assert row.mustPreserveNow is None
    assert row.allowedInTelemetry == "false"
    assert type(row.checkpointKeys) is list
    assert not isinstance(row.rebuildRequirements, tuple)
    errors = registry.validate_registry((row,), ())
    assert any(":mustPreserveNow:not_exact_bool" in error for error in errors)
    assert any(":allowedInTelemetry:not_exact_bool" in error for error in errors)
    assert any(":checkpointKeys:not_exact_tuple" in error for error in errors)
    assert any(":rebuildRequirements:not_exact_tuple" in error
               for error in errors)


def test_uninitialized_exact_declarations_return_specific_canonical_errors():
    state = object.__new__(registry.StateDeclaration)
    mutation = object.__new__(registry.MutationDeclaration)

    state_first = registry.validate_registry((state,), ())
    state_second = registry.validate_registry((state,), ())
    assert state_first == state_second
    assert "state[0]:stateId:missing_field" in state_first
    assert "state[0]:allowedInTelemetry:missing_field" in state_first
    assert "registry:validation_containment" not in state_first
    assert registry.state_allows_public_telemetry(state) is False

    mutation_first = registry.validate_registry((), (mutation,))
    mutation_second = registry.validate_registry((), (mutation,))
    assert mutation_first == mutation_second
    assert "mutation[0]:mutationId:missing_field" in mutation_first
    assert "mutation[0]:targetStateIds:missing_field" in mutation_first
    assert "registry:validation_containment" not in mutation_first
    assert registry.mutation_allows_public_telemetry(mutation) is False


def test_exact_declaration_with_deleted_field_is_specific_and_denied():
    state = dataclasses.replace(registry.states()[0])
    object.__delattr__(state, "classification")
    assert registry.validate_registry((state,), ()) == (
        "state[0]:classification:missing_field",)
    assert registry.state_allows_public_telemetry(state) is False

    mutation = dataclasses.replace(registry.mutations()[0])
    object.__delattr__(mutation, "criticality")
    errors = registry.validate_registry(registry.states(), (mutation,))
    assert any(error.endswith(":criticality:missing_field")
               for error in errors)
    assert registry.mutation_allows_public_telemetry(mutation) is False


def test_subclass_wrong_dataclass_and_malformed_tuple_are_total():
    class StateSubclass(registry.StateDeclaration):
        pass

    state_subclass = object.__new__(StateSubclass)
    wrong_dataclass = object.__new__(registry.MutationDeclaration)
    assert registry.validate_registry((state_subclass,), ()) == (
        "state[0]:not_exact_StateDeclaration",)
    assert registry.validate_registry((wrong_dataclass,), ()) == (
        "state[0]:not_exact_StateDeclaration",)
    assert registry.validate_registry((), (state_subclass,)) == (
        "mutation[0]:not_exact_MutationDeclaration",)
    assert registry.validate_registry((None, 1, [], {}), ()) == (
        "state[0]:not_exact_StateDeclaration",
        "state[1]:not_exact_StateDeclaration",
        "state[2]:not_exact_StateDeclaration",
        "state[3]:not_exact_StateDeclaration",
    )


def test_hostile_extra_instance_key_is_not_interpreted_by_validator():
    state = object.__new__(registry.StateDeclaration)
    key = HostileCollisionKey("stateId")
    object.__getattribute__(state, "__dict__")[key] = HostileValue()
    key.calls.clear()

    errors = registry.validate_registry((state,), ())
    assert "state[0]:unexpected_instance_field" in errors
    assert "state[0]:stateId:missing_field" in errors
    assert key.calls == []


def test_validation_invalid_raw_state_enum_is_never_authorized():
    template = next(row for row in registry.states()
                    if registry.state_allows_public_telemetry(row))
    raw = dataclasses.replace(
        template, classification=template.classification.value)
    assert any(":classification:not_exact_enum" in error
               for error in registry.validate_registry((raw,), ()))
    assert registry.state_allows_public_telemetry(raw) is False


def test_validation_invalid_raw_mutation_enum_is_never_authorized():
    template = next(row for row in registry.mutations()
                    if registry.mutation_allows_public_telemetry(row))
    raw = dataclasses.replace(
        template, criticality=template.criticality.value)
    assert any(":criticality:not_exact_enum" in error
               for error in registry.validate_registry(
                   registry.states(), (raw,)))
    assert registry.mutation_allows_public_telemetry(raw) is False


def test_duplicate_safe_target_is_validation_invalid_and_policy_denied():
    template = next(row for row in registry.mutations()
                    if registry.mutation_allows_public_telemetry(row))
    duplicate = dataclasses.replace(
        template,
        targetStateIds=(template.targetStateIds[0],
                        template.targetStateIds[0]))
    assert any(":targetStateIds:duplicate_item" in error
               for error in registry.validate_registry(
                   registry.states(), (duplicate,)))
    assert registry.mutation_allows_public_telemetry(duplicate) is False


def test_hostile_collision_index_key_is_rejected_without_special_methods():
    mutation = next(row for row in registry.mutations()
                    if registry.mutation_allows_public_telemetry(row))
    key = HostileCollisionKey(mutation.targetStateIds[0])
    hostile_index = {key: registry.states()[0]}
    key.calls.clear()

    assert registry.mutation_allows_public_telemetry(
        mutation, hostile_index) is False
    assert key.calls == []


@pytest.mark.parametrize("index_factory", [
    lambda target, state: {1: state},
    lambda target, state: {target: object.__new__(
        registry.StateDeclaration)},
    lambda target, state: {target: None},
    lambda target, state: {"future.key_mismatch": state},
    lambda target, state: {},
    lambda target, state: [(target, state)],
])
def test_malformed_raw_state_indexes_fail_closed(index_factory):
    mutation = next(row for row in registry.mutations()
                    if registry.mutation_allows_public_telemetry(row))
    target = mutation.targetStateIds[0]
    state = registry.state_by_id()[target]
    assert registry.mutation_allows_public_telemetry(
        mutation, index_factory(target, state)) is False


def test_custom_mapping_and_dict_subclass_indexes_fail_closed():
    mutation = next(row for row in registry.mutations()
                    if registry.mutation_allows_public_telemetry(row))
    target = mutation.targetStateIds[0]
    state = registry.state_by_id()[target]

    class CustomMapping:
        def items(self):
            raise AssertionError("custom mapping must not be inspected")

    class DictSubclass(dict):
        pass

    assert registry.mutation_allows_public_telemetry(
        mutation, CustomMapping()) is False
    assert registry.mutation_allows_public_telemetry(
        mutation, DictSubclass({target: state})) is False


def test_semantically_duplicate_or_mismatched_state_index_is_denied():
    mutation = next(row for row in registry.mutations()
                    if registry.mutation_allows_public_telemetry(row))
    target = mutation.targetStateIds[0]
    state = registry.state_by_id()[target]
    # Two keys cannot represent the same valid declaration: the second key
    # must mismatch its declaration stateId and therefore denies the index.
    duplicate_semantics = {
        target: state,
        "future.duplicate_semantics": state,
    }
    assert registry.mutation_allows_public_telemetry(
        mutation, duplicate_semantics) is False
