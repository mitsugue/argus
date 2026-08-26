"""v13.5.36 — MARKET SITUATION BRIEF non-authority guards (owner directive
2026-08-26, permanent regression guard).

Invariant: the brief is OUTPUT / EXPLANATION ONLY.
Allowed direction:   canonical evidence / SDA  →  brief
Forbidden direction: brief  →  SDA input / riskKernel / decision-evidence
                     authority / final action / confidence.

Layered guards: AST import boundary (every non-scanner module), AST
reference-scope inside scanner (display+worker functions only), signature
guard (authority projections cannot even receive a brief), and a runtime
invariance proof (flipping the brief bullish↔bearish leaves the canonical
SDA-safe projection byte-identical).
"""
import ast
import inspect
import json
import pathlib

import argus_market_brief as mb
import argus_sho
import scanner

ROOT = pathlib.Path(__file__).resolve().parent

# scanner functions allowed to touch brief symbols: the brief's own block,
# its public route, and the background worker that refreshes it.
_ALLOWED_SCANNER_SCOPES = {
    "_brief_market_view_summary", "_brief_news_events",
    "_compose_market_brief", "_market_brief_ai_polish",
    "_market_brief_refresh", "api_argus_market_brief",
    "_news_intake_loop",
}
_BRIEF_SYMBOL_PREFIXES = ("_market_brief", "_brief_")
_BRIEF_SYMBOLS = {"argus_market_brief", "_MARKET_BRIEF"}


def _imports_of(path: pathlib.Path) -> set:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_static_import_boundary_no_module_imports_the_brief():
    """AST import graph: only scanner (orchestrator/display) may import the
    composer. Every authority/producer module fails CI if it ever does."""
    for path in sorted(ROOT.glob("*.py")):
        if path.name in ("scanner.py", "argus_market_brief.py") \
                or path.name.startswith("test_"):
            continue
        assert "argus_market_brief" not in _imports_of(path), (
            f"{path.name} must never import the market brief "
            "(brief→authority direction is forbidden)")


def test_scanner_brief_references_stay_in_display_scope():
    """Inside scanner, brief symbols may only appear in the brief's own
    functions, its route and the intake worker — never inside evidence
    builders, riskKernel producers or decision reducers."""
    tree = ast.parse((ROOT / "scanner.py").read_text())
    offenders = []
    stack = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Name(self, node):
            name = node.id
            if name in _BRIEF_SYMBOLS or any(
                    name.startswith(p) for p in _BRIEF_SYMBOL_PREFIXES):
                scope = stack[-1] if stack else "<module>"
                # module level = the import + the state literal, allowed.
                if scope != "<module>" and scope not in _ALLOWED_SCANNER_SCOPES:
                    offenders.append((scope, name))
            self.generic_visit(node)

    Visitor().visit(tree)
    assert offenders == [], offenders


def test_authority_signatures_cannot_receive_a_brief():
    """Contract guard: no public argus_sho callable accepts anything
    brief-shaped — the forbidden direction is unrepresentable."""
    for name, fn in inspect.getmembers(argus_sho, inspect.isfunction):
        for param in inspect.signature(fn).parameters:
            assert "brief" not in param.lower(), (name, param)


def _bullish_brief():
    return {"schemaVersion": mb.BRIEF_SCHEMA, "now": "強気材料が優勢",
            "why": "追い風", "next": "続伸確認", "aiText": {
                "nowJa": "強気", "whyJa": "追い風", "nextJa": "続伸"},
            "facts": [], "sdaAuthority": False}


def _bearish_brief():
    return {"schemaVersion": mb.BRIEF_SCHEMA, "now": "弱気材料が優勢",
            "why": "逆風", "next": "下落警戒", "aiText": {
                "nowJa": "弱気", "whyJa": "逆風", "nextJa": "警戒"},
            "facts": [], "sdaAuthority": False}


def test_runtime_flipping_the_brief_leaves_sda_projection_identical():
    """Hold canonical evidence constant; swing the published brief from
    bullish to bearish. The canonical SDA-safe projection must stay
    byte-identical — the brief has no runtime path into authority."""
    cutoff = "2026-08-26T00:00:00Z"

    def projection_bytes():
        return json.dumps(argus_sho.project_today_sda_safe(
            cutoff=cutoff, evidence={}, reversal={}),
            sort_keys=True, ensure_ascii=False)

    saved = dict(scanner._MARKET_BRIEF)
    try:
        scanner._MARKET_BRIEF["data"] = _bullish_brief()
        bullish_view = projection_bytes()
        scanner._MARKET_BRIEF["data"] = _bearish_brief()
        bearish_view = projection_bytes()
        assert bullish_view == bearish_view
    finally:
        scanner._MARKET_BRIEF.clear()
        scanner._MARKET_BRIEF.update(saved)


def test_forward_direction_evidence_into_brief_is_allowed():
    """The opposite (allowed) direction: canonical market-view evidence and
    verified stores flow INTO the composer."""
    brief = mb.compose_brief(
        now_iso="2026-08-26T00:00:00Z",
        market_view_summary={"label": "反転:混在・証拠評価5/7"})
    assert any(f["source"] == "market_view" for f in brief["facts"])
    assert brief["sdaAuthority"] is False


def test_repo_grep_tripwire_frontend_authority_files():
    """Simple additional tripwire: the TS decision layer must not mention
    the brief (the dedicated node test enforces the import boundary; this
    keeps a second, dumber sensor)."""
    for rel in ("web/src/domain", "web/src/hooks/useAssetIntel.ts",
                "web/src/hooks/useDecisionEvidence.ts"):
        target = ROOT / rel
        paths = list(target.rglob("*.ts")) if target.is_dir() else [target]
        for path in paths:
            text = path.read_text()
            for banned in ("useMarketBrief", "market-brief", "MarketBrief"):
                assert banned not in text, (str(path), banned)
