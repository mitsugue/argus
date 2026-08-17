"""Static convergence gates for the Round 2 one-authority architecture."""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import argus_single_decision as single_decision


ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "scanner.py"
RESEARCH_PLANE = (
    ROOT / "argus_research_compute.py",
    ROOT / "scripts" / "run_round2_research.py",
    ROOT / "scripts" / "round2_resource_probe.py",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name)
    return ast.get_source_segment(source, node) or ""


def _assigned_literal(tree: ast.Module, name: str):
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name
               for target in targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing module constant: {name}")


def _imported_modules(tree: ast.Module) -> set[str]:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_scanner_cannot_import_the_offline_research_compute_plane():
    modules = _imported_modules(_tree(SCANNER))
    assert "argus_research_compute" not in modules
    assert "scripts.run_round2_research" not in modules
    assert "scripts.round2_resource_probe" not in modules


def test_research_plane_has_no_network_environment_or_implicit_clock():
    forbidden_import_roots = {
        "aiohttp", "anthropic", "dotenv", "ftplib", "http", "httpx",
        "openai", "os", "requests", "smtplib", "socket", "subprocess",
        "time", "urllib", "websocket",
    }
    forbidden_clock_calls = {
        "now", "today", "utcnow", "time", "monotonic", "perf_counter",
    }
    for path in RESEARCH_PLANE:
        tree = _tree(path)
        imported_roots = {
            name.split(".", 1)[0] for name in _imported_modules(tree)}
        assert imported_roots.isdisjoint(forbidden_import_roots), path
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert forbidden_clock_calls.isdisjoint(calls), path


def test_legacy_scanner_authority_is_sealed_evidence_only():
    tree = _tree(SCANNER)
    assert _assigned_literal(
        tree, "LEGACY_DECISION_AUTHORITY_ROLE") == "EVIDENCE_ONLY"
    assert _assigned_literal(
        tree, "LEGACY_DECISION_AUTHORITY_ACTIVE") is False

    for name in ("get_action_labels", "get_action_alerts", "get_daily_digest"):
        source = _function_source(SCANNER, name)
        assert "LEGACY_DECISION_AUTHORITY_ROLE" in source
        assert '"finalDecisionAuthorityActive": False' in source

    digest = _function_source(SCANNER, "get_daily_digest")
    assert '"call": None' in digest
    assert '"legacyCall": legacy_call' in digest

    scout = _function_source(SCANNER, "_entry_scout_evidence_only")
    assert 'out["authorityRole"] = LEGACY_DECISION_AUTHORITY_ROLE' in scout
    assert 'out["finalDecisionAuthorityActive"] = False' in scout


def test_legacy_top3_and_dynamic_exit_cannot_emit_final_actions():
    phase4 = _function_source(SCANNER, "phase4_final_top3")
    assert 's["authorityRole"] = LEGACY_DECISION_AUTHORITY_ROLE' in phase4
    assert 's["finalDecisionAuthorityActive"] = False' in phase4
    assert "log_prediction(" not in phase4
    assert "push_notify(" not in phase4

    phase5 = _function_source(SCANNER, "phase5_post_open")
    retired_prefix = phase5.split("\n    return", 1)[0]
    assert '"status": "evidence_only"' in retired_prefix
    assert '"authorityRole": LEGACY_DECISION_AUTHORITY_ROLE' in retired_prefix
    assert '"finalDecisionAuthorityActive": False' in retired_prefix
    assert "push_notify(" not in retired_prefix


def test_scheduled_ai_candidate_route_is_non_persistent_evidence_only():
    tree = _tree(SCANNER)
    prompt = _assigned_literal(tree, "_BUY_CANDIDATE_SYSTEM")
    generator = _function_source(SCANNER, "_buy_candidates_generate")
    route = _function_source(SCANNER, "api_argus_buy_candidates_generate")
    resident = _function_source(SCANNER, "_residency_ai_tick")
    scanner_source = SCANNER.read_text(encoding="utf-8")

    assert "follow-up research evidence" in prompt
    assert "GOOD ENTRY" not in prompt
    assert "BUY-NOW" not in prompt
    assert '"authorityRole": LEGACY_DECISION_AUTHORITY_ROLE' in generator
    assert '"finalDecisionAuthorityActive": False' in generator
    assert '"persisted": False' in generator
    assert "evidenceStrength" in generator
    assert "push_notify(" not in generator
    assert "log_prediction(" not in generator
    assert "_buy_candidates_persist(" not in generator
    assert "_BUY_CANDIDATES_FILE" not in scanner_source
    assert "_buy_candidates_restore" not in scanner_source
    assert 'skipped["authorityRole"] = LEGACY_DECISION_AUTHORITY_ROLE' in route
    assert "EVIDENCE_ONLY" in resident


def test_scanner_has_no_primary_stance_import_or_counter_vote():
    tree = _tree(SCANNER)
    assert "argus_primary_stance" not in _imported_modules(tree)
    counter_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "Counter"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "Counter")
    ]
    assert counter_calls == []


def test_one_primary_vocabulary_and_seven_sign_is_not_old_action_level():
    assert single_decision.PRIMARY_ACTIONS == (
        "BUY", "HOLD", "WAIT", "REDUCE", "EXIT")
    assert single_decision.SEVEN_SIGN_SCHEMA_VERSION == "seven-sign-v1"
    assert single_decision.SEVEN_SIGN_SCHEMA_VERSION != "action-level-v1"

    old_action_level = (
        ROOT / "web" / "src" / "domain" / "actionLevel.ts").read_text(
            encoding="utf-8")
    assert "SIGNAL_SCHEMA_VERSION = 'action-level-v1'" in old_action_level
    assert re.search(
        r"HOLD_ONLY:\s*\{[^\n]*level:\s*5\b", old_action_level)

    seven_candidate = inspect.getsource(single_decision._seven_candidate)
    assert 'if action == "HOLD":\n        return 4' in seven_candidate
    assert "candidateLevel" in inspect.getsource(
        single_decision._seven_sign_projection)
    assert "productionLevel" in inspect.getsource(
        single_decision._seven_sign_projection)
