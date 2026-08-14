"""Registry Core inventory, determinism, and non-authority invariants."""

import ast
import json
import pathlib

import argus_recovery_registry as registry


EXPECTED_STATE_IDS = tuple(sorted("""
backend.agent_queue
backend.checkpoint_histories
backend.cost_policy
backend.forecasts
backend.formal_benchmarks
backend.foundation_jobs
backend.incidents
backend.integrity_hashes
backend.learned_memory
backend.local_wal
backend.mission_artifacts
backend.mission_durability
backend.mission_windows
backend.missions
backend.nonce_authority
backend.ops_journal
backend.ops_sequence_allocator
backend.outcomes
backend.receipt_queue
backend.remote_ack_cycle
backend.remote_recovery_required
backend.schema_identity
backend.soak_state
backend.stage1_control
backend.term_overlay
backend.url_cache
client.browser_caches
client.core_private_state
client.dismissed_gaps
client.pasted_research
client.replay_drawings
client.risk_lines
client.vault_ciphertext
external.ec2_build_identity
external.private_git_objects
external.public_ledger_originals
market.asset_reports
market.chart_intelligence
market.ledger_derived
market.ledger_source
market.replay_contexts
market.replay_receipts
market.today_derived
market.today_source
market.verified_views
secondary.accepted_queues
secondary.ai_gate_cost_security
secondary.ai_results
secondary.buy_candidates
secondary.decision_jobs
secondary.event_backbone
secondary.intelligence_facts
secondary.learning_materialization
secondary.legacy_predictions
secondary.legacy_scan_state
secondary.osint_investigation_store
secondary.owner_intelligence
secondary.sweep_cooldown
secondary.tdnet_timing
secondary.url_and_agent_work
security.recovery_keys
""".split()))

EXPECTED_MUTATION_IDS = tuple(sorted("""
ai.result_and_cost
benchmark.lifecycle
client.local_mutation
control.soak_stage1
core.batch_cursor
core.mission_transition
core.ops_journal_transition
decision.job_update
deployment.build_identity_update
durability.receipt_ack
external.private_git_write
external.public_ledger_write
foundation.lifecycle
intelligence.fact_update
learning.materialization
legacy.prediction_update
legacy.scan_update
market.analytics_refresh
market.asset_report_update
market.ledger_update
market.verified_view_publish
osint.accepted_work
osint.investigation_update
owner.intelligence_update
queue.accepted_work
security.nonce_reservation
startup.restore_transition
""".split()))

EXPECTED_POLICY_SHA256 = \
    "f08a22350686f4c0fcbbdea50b185915ca17331edc15ffc84ad854b51ed550c1"


def test_registry_is_valid_sorted_unique_and_exact_inventory_equivalent():
    assert registry.validate_registry() == ()
    assert tuple(row.stateId for row in registry.states()) == EXPECTED_STATE_IDS
    assert tuple(row.mutationId for row in registry.mutations()) == \
        EXPECTED_MUTATION_IDS
    assert len(EXPECTED_STATE_IDS) == 61
    assert len(EXPECTED_MUTATION_IDS) == 27

    summary = registry.registry_summary()
    assert summary["stateCount"] == 61
    assert summary["mutationClassCount"] == 27
    assert summary["classificationCounts"] == {
        "A_AUTHORITATIVE_NON_REACQUIRABLE": 30,
        "B_AUTHORITATIVE_SOURCE_FACTS": 13,
        "C_DETERMINISTIC_RECOMPUTABLE": 5,
        "D_REACQUIRABLE_WITH_CONTRACT": 1,
        "E_CACHE_EPHEMERAL": 2,
        "F_UNKNOWN_OWNER_SEMANTICS_REQUIRED": 10,
    }
    assert summary["mustPreserveCount"] == 59
    assert summary["privacyCounts"] == {
        "PUBLIC_METADATA": 11,
        "INTERNAL": 22,
        "OWNER_PRIVATE": 9,
        "SECURITY_SENSITIVE": 11,
        "SECRET": 1,
        "CLIENT_PRIVATE": 6,
        "CLIENT_OPAQUE": 1,
    }
    assert summary["currentWalCoverageCounts"] == {
        "COMPLETE": 0,
        "PARTIAL": 6,
        "INDEPENDENT_DURABLE_SOURCE": 4,
        "NOT_DURABLE_FOR_EXACT_REPLAY": 12,
        "UNKNOWN": 5,
    }


def test_public_telemetry_inventory_is_explicit_and_rfc_strict():
    safe_states = tuple(
        row.stateId for row in registry.states()
        if registry.state_allows_public_telemetry(row))
    assert safe_states == tuple(sorted((
        "backend.checkpoint_histories",
        "backend.integrity_hashes",
        "backend.learned_memory",
        "backend.schema_identity",
        "external.public_ledger_originals",
        "market.asset_reports",
        "market.chart_intelligence",
        "market.replay_contexts",
        "market.replay_receipts",
        "market.today_derived",
        "market.verified_views",
    )))
    assert all(row.privacyClass is registry.PrivacyClass.PUBLIC_METADATA
               for row in registry.states()
               if registry.state_allows_public_telemetry(row))
    assert not any(
        row.allowedInTelemetry
        for row in registry.states()
        if row.privacyClass is registry.PrivacyClass.INTERNAL)

    safe_mutations = tuple(
        row.mutationId for row in registry.mutations()
        if registry.mutation_allows_public_telemetry(row))
    assert safe_mutations == (
        "external.public_ledger_write",
        "market.asset_report_update",
        "market.verified_view_publish",
    )


def test_policy_document_and_sha_are_byte_deterministic():
    first_document = registry.registry_document()
    second_document = registry.registry_document()
    assert first_document == second_document
    assert registry.registry_policy_canonical_bytes() == \
        registry.registry_policy_canonical_bytes()
    assert registry.registry_policy_sha256() == EXPECTED_POLICY_SHA256
    assert registry.REGISTRY_POLICY_SHA256 == EXPECTED_POLICY_SHA256
    assert len(registry.registry_policy_canonical_bytes()) == 57972

    encoded = json.dumps(
        first_document, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert encoded == registry.registry_policy_canonical_bytes()
    assert "generatedAt" not in first_document
    assert first_document["authoritative"] is False
    assert first_document["stateRegistry"]["authoritative"] is False
    assert first_document["mutationRegistry"]["authoritative"] is False


def _checkpoint_literal_keys() -> tuple[str, ...]:
    tree = ast.parse(pathlib.Path("scanner.py").read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_osint_persist_locked")
    observed = set()

    def collect_dict_keys(value):
        if isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    observed.add(key.value)

    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "blob":
                    collect_dict_keys(node.value)
                elif isinstance(target, ast.Subscript) and \
                        isinstance(target.value, ast.Name) and \
                        target.value.id == "blob" and \
                        isinstance(target.slice, ast.Constant) and \
                        isinstance(target.slice.value, str):
                    observed.add(target.slice.value)
        elif isinstance(node, ast.Call) and \
                isinstance(node.func, ast.Attribute) and \
                isinstance(node.func.value, ast.Name) and \
                node.func.value.id == "blob" and \
                node.func.attr == "update" and node.args:
            collect_dict_keys(node.args[0])
    return tuple(sorted(observed))


def test_every_literal_checkpoint_top_level_key_is_registered():
    observed = _checkpoint_literal_keys()
    assert len(observed) == 47
    assert registry.unregistered_checkpoint_keys(observed) == ()
    # localCheckpointIntegrity is added by the sealing writer rather than the
    # literal blob assembly, so the registry is intentionally a strict superset.
    assert set(observed) < set(registry.registered_checkpoint_keys())
    assert set(registry.registered_checkpoint_keys()) - set(observed) == {
        "localCheckpointIntegrity"}


def test_inventory_tripwire_reports_unknowns_without_runtime_reflection():
    assert registry.unregistered_state_ids((
        "backend.missions", "future.authority.unknown")) == (
            "future.authority.unknown",)
    assert registry.unregistered_checkpoint_keys((
        "missions", "futureCheckpointKey")) == ("futureCheckpointKey",)
    assert registry.unregistered_state_ids(["backend.missions"]) == (
        "<invalid_observed_state_ids_container>",)
    assert registry.unregistered_checkpoint_keys(["missions"]) == (
        "<invalid_checkpoint_inventory_container>",)


def test_registry_module_has_no_runtime_authority_or_io_imports():
    tree = ast.parse(
        pathlib.Path("argus_recovery_registry.py").read_text(encoding="utf-8"))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= {"dataclasses", "enum", "hashlib", "json", "re", "typing"}
    source = pathlib.Path("argus_recovery_registry.py").read_text(
        encoding="utf-8")
    for forbidden in (
            "import scanner", "open(", "os.environ", "requests.", "flask"):
        assert forbidden not in source
