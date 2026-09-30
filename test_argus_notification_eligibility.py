"""Owner-universe Push firewall regression matrix."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import argus_notification_eligibility as E
import scanner


def _membership(**states):
    return {symbol.upper(): {"ownerState": state} for symbol, state in states.items()}


def _decision(symbol, membership, *, status="fresh"):
    return E.evaluate_push_eligibility(
        scope=E.INDIVIDUAL_SECURITY,
        symbol=symbol,
        owner_membership=membership,
        membership_status=status,
    )


def test_holding_symbol_is_push_eligible():
    got = _decision("7203", _membership(**{"7203": "held"}))
    assert got == {"pushEligible": True, "reason": "symbol_in_owner_universe",
                   "ownerRelationship": "holding"}


def test_explicitly_marked_symbol_is_push_eligible():
    got = _decision("NVDA", _membership(NVDA="watch"))
    assert got["pushEligible"] is True
    assert got["ownerRelationship"] == "marked"


def test_holding_and_marked_is_one_eligible_decision(monkeypatch):
    membership = {"NVDA": {"ownerState": "held", "explicitlyMarked": True}}
    got = _decision("nvda", membership)
    assert got["pushEligible"] is True
    assert got["ownerRelationship"] == "holding_and_marked"
    monkeypatch.setattr(scanner, "_owner_symbols_cached", lambda: membership)
    monkeypatch.setitem(scanner._OWNER_SYMS_CACHE, "status", "fresh")
    assert scanner._push_eligibility(
        "individual_security", "NVDA")["pushEligible"] is True


def test_unmarked_unrelated_plus_20_mover_is_blocked():
    got = _decision("ARM", _membership(SBG="held"))
    assert got["pushEligible"] is False
    assert got["reason"] == "symbol_not_in_owner_universe"


def test_unmarked_unrelated_minus_20_mover_is_blocked():
    got = _decision("ARM", _membership(SBG="held"))
    assert got["pushEligible"] is False
    assert got["reason"] == "symbol_not_in_owner_universe"


def test_unmarked_theme_or_model_candidate_is_blocked():
    got = _decision("AI", _membership(NVDA="watch"))
    assert got["pushEligible"] is False


def test_peer_is_context_only_and_holding_remains_subject():
    membership = _membership(SBG="held")
    assert _decision("ARM", membership)["pushEligible"] is False
    assert _decision("SBG", membership)["ownerRelationship"] == "holding"


def test_peer_context_push_keeps_owner_holding_as_subject(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.setattr(scanner.requests, "post", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(scanner, "_owner_symbols_cached", lambda: _membership(SBG="held"))
    monkeypatch.setitem(scanner._OWNER_SYMS_CACHE, "status", "fresh")
    env = {"symbol": "SBG", "nameJa": "SOFTBANK GROUP",
           "eventType": "PEER_CONTEXT", "market": "JP",
           "session": "JP_REGULAR", "severity": 4,
           "recommendedPosture": "HOLD",
           "reasonJa": "Positive context from ARM strength."}
    assert scanner._event_ntfy(env) is True
    assert len(sent) == 1
    args, kwargs = sent[0]
    assert "SBG" in kwargs["headers"]["Title"]
    assert "ARM" not in kwargs["headers"]["Title"]
    assert "ARM" in kwargs["data"].decode("utf-8")


def test_symbol_removed_from_watchlist_is_blocked():
    assert _decision("ARM", {})["pushEligible"] is False


def test_former_holding_no_longer_held_or_marked_is_blocked():
    assert _decision("ARM", {})["pushEligible"] is False


def test_owner_universe_lookup_failure_fails_closed():
    assert _decision("ARM", None, status="unavailable")["pushEligible"] is False


def test_stale_membership_fails_closed():
    stale = _membership(ARM="watch")
    assert _decision("ARM", stale, status="stale")["pushEligible"] is False


def test_macro_cpi_fomc_notification_is_unaffected():
    got = E.evaluate_push_eligibility(scope="macro")
    assert got["pushEligible"] is True
    assert got["reason"] == "non_security_notification"


def test_other_non_security_notifications_are_unaffected():
    for scope in ("macro", "system", "portfolio", "digest"):
        got = E.evaluate_push_eligibility(scope=scope)
        assert got["pushEligible"] is True
        assert got["reason"] == "non_security_notification"


def test_market_mover_remains_recordable_but_direct_push_is_blocked(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.setattr(scanner, "_owner_symbols_cached", lambda: {})
    monkeypatch.setitem(scanner._OWNER_SYMS_CACHE, "status", "fresh")
    monkeypatch.setattr(scanner.requests, "post", lambda *a, **k: sent.append((a, k)))
    env = {"symbol": "ARM", "eventType": "MARKET_MOVER", "market": "US",
           "session": "US_REGULAR", "severity": 5,
           "recommendedPosture": "AVOID_CHASING", "reasonJa": "+20%"}
    assert scanner._event_ntfy(env) is False
    assert sent == []
    assert env["eventType"] == "MARKET_MOVER"  # analysis object remains intact


def test_marked_market_mover_reaches_event_transport_once(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.setattr(scanner.requests, "post", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(scanner, "_owner_symbols_cached", lambda: _membership(NVDA="watch"))
    monkeypatch.setitem(scanner._OWNER_SYMS_CACHE, "status", "fresh")
    env = {"symbol": "NVDA", "eventType": "MARKET_MOVER", "market": "US",
           "session": "US_REGULAR", "severity": 5,
           "recommendedPosture": "AVOID_CHASING", "reasonJa": "+20%"}
    assert scanner._event_ntfy(env) is True
    assert len(sent) == 1


def test_owner_cache_reads_snapshot_members_and_expires_failed_fallback(monkeypatch):
    clock = {"now": 1000.0}
    snapshot = {"generatedAt": "2026-08-09T00:00:00Z",
                "members": [{"symbol": "ARM", "ownerState": "watch"}]}
    monkeypatch.setattr(scanner.time, "time", lambda: clock["now"])
    monkeypatch.setattr(scanner, "_layer2b_read_latest", lambda: snapshot)
    scanner._OWNER_SYMS_CACHE.update({"syms": None, "ts": 0.0, "status": "unknown"})
    assert scanner._owner_symbols_cached()["ARM"]["ownerState"] == "watch"
    clock["now"] += scanner._OWNER_SYMS_TTL + 1
    monkeypatch.setattr(scanner, "_layer2b_read_latest", lambda: None)
    assert scanner._owner_symbols_cached() == {}
    assert scanner._OWNER_SYMS_CACHE["syms"] is None
    assert scanner._OWNER_SYMS_CACHE["status"] == "unavailable"
    # Fail closed for the bounded retry window instead of hammering the private
    # store on every mover event.
    monkeypatch.setattr(scanner, "_layer2b_read_latest",
                        lambda: (_ for _ in ()).throw(AssertionError("unexpected retry")))
    assert scanner._owner_symbols_cached() == {}


def test_events_active_does_not_expose_owner_universe_diagnostics(monkeypatch):
    monkeypatch.setattr(scanner, "_PUSH_GATE_STATS", {
        "allowed": 2, "blocked": 3,
        "byReason": {"symbol_not_in_owner_universe": 3},
    })
    monkeypatch.setattr(scanner, "_OWNER_SYMS_CACHE", {
        "syms": _membership(SECRET="held"), "ts": 1.0, "status": "fresh",
    })
    response = scanner.app.test_client().get("/api/argus/events-active")
    assert response.status_code == 200
    public = response.get_json()
    assert "pushEligibility" not in public
    assert "membershipCount" not in public
    assert "SECRET" not in json.dumps(public)


def test_all_backend_ntfy_producers_converge_on_the_firewall():
    """Static guard: new producers cannot silently bypass the central gate."""
    source = Path(scanner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    push_calls = []
    event_calls = []
    ntfy_post_functions = []

    class Audit(ast.NodeVisitor):
        def __init__(self):
            self.function = None

        def visit_FunctionDef(self, node):
            previous = self.function
            self.function = node.name
            self.generic_visit(node)
            self.function = previous

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "push_notify":
                push_calls.append(node)
            if isinstance(node.func, ast.Name) and node.func.id == "_event_ntfy":
                event_calls.append(node)
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "post"
                    and any(isinstance(arg, ast.JoinedStr)
                            and "ntfy.sh" in ast.unparse(arg)
                            for arg in node.args)):
                ntfy_post_functions.append(self.function)
            self.generic_visit(node)

    Audit().visit(tree)
    # The legacy phase transport (push_notify) was removed with the old
    # scanner phases; every remaining ntfy producer is the event transport.
    assert not push_calls
    assert event_calls
    assert all(any(kw.arg in {"notification_scope", "eligibility"}
                   for kw in call.keywords) for call in event_calls)
    assert set(ntfy_post_functions) == {"_event_ntfy"}


def test_direct_workflow_ntfy_inventory_is_non_security_only():
    workflows = Path(".github/workflows")
    direct = {
        path.name: path.read_text(encoding="utf-8")
        for path in workflows.glob("*.yml")
        if "ntfy.sh" in path.read_text(encoding="utf-8")
    }
    assert set(direct) == {
        "market-alerts.yml",
        "prediction-ledger.yml",
        "smoke-test.yml",
    }
    assert "Notify on failure" in direct["prediction-ledger.yml"]
    assert "Notify on failure" in direct["smoke-test.yml"]
    assert "posture flip" in direct["market-alerts.yml"]
    assert "high-impact event" in direct["market-alerts.yml"]
    assert "push-digest" in direct["market-alerts.yml"]
    assert "ARGUS Digest" in direct["market-alerts.yml"]


def test_notification_workflow_consolidation_preserves_schedule_semantics():
    workflows = Path(".github/workflows")
    files = sorted(workflows.glob("*.yml"))
    # What this guards is the schedule and notification surface, not the
    # number of files: a counted total broke on every unrelated workflow
    # (2026-09-28, twice).  Every workflow that fires on a schedule or can
    # notify must be one of these, and each is named with its reason.
    scheduled_or_notifying = {
        name for name, text in
        ((path.name, path.read_text(encoding="utf-8")) for path in files)
        if "- cron:" in text or "ntfy.sh" in text}
    assert scheduled_or_notifying == {
        "breadth-freshness.yml",      # JP breadth freshness sweep
        "caos-scan.yml",              # mission tick backup (:07/:37)
        "checkpoint-v2-gate.yml",     # nightly 4 GiB proof (2026-09-28)
        "event-ledger.yml",           # event ledger close
        "jpx-credit-weekly.yml",      # weekly JPX credit
        "learning-memory.yml",        # learning memory roll-up
        "macro-event-analysis.yml",   # macro result/generation slots
        "market-alerts.yml",          # the owner-facing alert cadence below
        "pages-deploy-watchdog.yml",  # cancels a Pages release stuck unassigned (2026-09-30)
        "prediction-ledger.yml",      # daily ledger close
        "smoke-test.yml",             # six-hourly production smoke
        "vault-sync.yml",             # owner vault sync
    }, sorted(scheduled_or_notifying)
    # Only these three may reach the owner's phone.
    notifying = {name for name, text in
                 ((path.name, path.read_text(encoding="utf-8")) for path in files)
                 if "ntfy.sh" in text}
    assert notifying == {"market-alerts.yml", "prediction-ledger.yml",
                         "smoke-test.yml"}, sorted(notifying)
    render = (workflows / "render-deploy-diagnostics.yml").read_text(encoding="utf-8")
    assert "- cron:" not in render and "ntfy.sh" not in render
    assert "workflow_dispatch" in render and "render_deploy_diagnostics.py" in render
    naming = (workflows / "product-naming.yml").read_text(encoding="utf-8")
    assert "- cron:" not in naming and "ntfy.sh" not in naming
    assert "product_naming_guard.py" in naming
    assert (workflows / "news-intake-ops.yml").exists()
    diagnostics = (workflows / "runtime-diagnostics.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in diagnostics and "- cron:" not in diagnostics
    assert "ntfy.sh" not in diagnostics and "secrets.ARGUS_ADMIN_TOKEN" in diagnostics
    assert not (workflows / "morning-digest.yml").exists()
    assert (workflows / "osint-check.yml").exists()
    assert (workflows / "restore-safe-pages.yml").exists()

    market = (workflows / "market-alerts.yml").read_text(encoding="utf-8")
    assert market.count("- cron:") == 5
    for cron in (
            "0 22,23 * * 0-4", "0 0-15 * * 1-5",
            "0 16-21 * * 1-5", "0 18 * * 0-4", "0 7 * * 1-5"):
        assert f"- cron: '{cron}'" in market
        assert f"github.event.schedule == '{cron}'" in market
    assert "default: alerts" in market
    assert "inputs.mode == 'alerts'" in market
    assert "inputs.mode == 'digest'" in market
    assert "  detect-and-push:" in market
    assert "  push-digest:" in market
    assert "permissions: {}" in market
    assert "GH_SCHEDULE: ${{ github.event.schedule }}" in market
    assert "GRACE = 90 * 60" in market
    assert "argus-alert-state-${{ github.run_id }}" in market

    detect_job, digest_job = market.split("\n  push-digest:\n", 1)
    assert "Restore previous state" in detect_job
    assert "Fetch digest and diff" in detect_job
    assert "Push alert (only on change" in detect_job
    assert "Save state" in detect_job
    assert "restore-keys: argus-alert-state-" in detect_job
    assert "Fetch digest (retry through Render cold start)" not in detect_job
    assert "Fetch digest (retry through Render cold start)" in digest_job
    assert "Push to ntfy (skipped when NTFY_TOPIC" in digest_job
    assert "Restore previous state" not in digest_job
    assert "Fetch digest and diff" not in digest_job
    assert "Save state" not in digest_job
