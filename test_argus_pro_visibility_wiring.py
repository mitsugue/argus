"""ARGUS Pro — Visibility Guard decision wiring (Phase 3).

The guard must ACTUALLY constrain judgment, not merely warn:
  - confidenceCap lowers every label's confidence,
  - a situational blockedActions=["ENTER"] downgrades aggressive entry to WAIT,
  - structural-only limitation (no cap / no block) leaves labels untouched.
The wiring can only make judgment MORE conservative, never more aggressive.
"""
import scanner


# ── pure helper: _apply_visibility_guard ────────────────────────────────────
def test_cap_lowers_confidence():
    action, conf, *_ = scanner._apply_visibility_guard(
        "HOLD", 0.9, "r", "n", "LIVE", vg_cap=0.6, vg_blocked=set(), vg_reason="")
    assert conf == 0.6
    assert action == "HOLD"  # cap alone does not change the action


def test_cap_never_raises_confidence():
    _, conf, *_ = scanner._apply_visibility_guard(
        "HOLD", 0.3, "r", "n", "LIVE", vg_cap=0.6, vg_blocked=set(), vg_reason="")
    assert conf == 0.3  # below the cap → untouched


def test_no_cap_no_block_leaves_label_untouched():
    action, conf, reason, nxt, sig, dg = scanner._apply_visibility_guard(
        "BUY_DIP", 0.8, "r", "n", "LIVE", vg_cap=None, vg_blocked=set(), vg_reason="")
    assert (action, conf, dg) == ("BUY_DIP", 0.8, False)


def test_entry_block_downgrades_aggressive_to_wait():
    # ADD maps to the ENTER signal (newEntry allowed). With ENTER blocked it must
    # be downgraded to WAIT and flagged.
    action, conf, reason, nxt, sig, dg = scanner._apply_visibility_guard(
        "ADD", 0.8, "base reason", "", "LIVE", vg_cap=None,
        vg_blocked={"ENTER"}, vg_reason="ブリッジ停滞")
    assert action == "WAIT"
    assert dg is True
    assert sig["permissions"]["newEntry"] == "blocked"
    assert conf <= 0.5
    assert "一時停止" in reason and "ブリッジ停滞" in reason


def test_entry_block_leaves_defensive_actions_alone():
    # HOLD does not permit a new entry → nothing to downgrade.
    action, conf, reason, nxt, sig, dg = scanner._apply_visibility_guard(
        "HOLD", 0.4, "r", "n", "LIVE", vg_cap=None, vg_blocked={"ENTER"}, vg_reason="x")
    assert action == "HOLD" and dg is False


# ── end-to-end: get_action_labels honours a forced guard ─────────────────────
def _labels_with_guard(monkeypatch, guard):
    monkeypatch.setattr(scanner, "_visibility_guard", lambda: guard)
    return scanner.get_action_labels(["8058", "9984"], ["NVDA", "AAPL"])


def test_response_carries_visibility_block(monkeypatch):
    g = {"visibilityLevel": "reduced", "confidenceCap": 0.6, "blockedActions": [],
         "reasonCodes": ["CALIBRATION_BURN_IN"], "coverageLineJa": "…", "warnings": []}
    d = _labels_with_guard(monkeypatch, g)
    v = d["visibility"]
    assert v["confidenceCap"] == 0.6 and v["entryBlocked"] is False
    # every non-mock label is capped
    caps = [l["confidence"] for l in d["labels"] if l.get("status") != "mock"]
    assert all(c <= 0.6 + 1e-9 for c in caps)


def test_entry_blocked_invariant_no_label_allows_new_entry(monkeypatch):
    g = {"visibilityLevel": "reduced", "confidenceCap": None, "blockedActions": ["ENTER"],
         "reasonCodes": ["BRIDGE_STALE"], "coverageLineJa": "…",
         "warnings": [{"code": "BRIDGE_STALE", "messageJa": "配信停滞"}]}
    d = _labels_with_guard(monkeypatch, g)
    assert d["visibility"]["entryBlocked"] is True
    # SAFETY INVARIANT: with ENTER blocked, no label may permit a new entry
    for l in d["labels"]:
        assert (l.get("signal") or {}).get("permissions", {}).get("newEntry") != "allowed", l["symbol"]


def test_gate_killswitch_reverts_behaviour(monkeypatch):
    # ARGUS_VISIBILITY_GATE=0 must revert to warn-only: no cap, no block applied.
    g = {"visibilityLevel": "reduced", "confidenceCap": 0.3, "blockedActions": ["ENTER"],
         "reasonCodes": ["BRIDGE_STALE"], "coverageLineJa": "", "warnings": []}
    monkeypatch.setattr(scanner, "_visibility_guard", lambda: g)
    monkeypatch.setenv("ARGUS_VISIBILITY_GATE", "0")
    d = scanner.get_action_labels(["8058"], ["NVDA"])
    assert d["visibility"]["confidenceCap"] is None
    assert d["visibility"]["entryBlocked"] is False


def test_clean_guard_does_not_force_downgrade(monkeypatch):
    g = {"visibilityLevel": "full", "confidenceCap": None, "blockedActions": [],
         "reasonCodes": [], "coverageLineJa": "", "warnings": []}
    d = _labels_with_guard(monkeypatch, g)
    assert d["visibility"]["entryBlocked"] is False
    assert all(l.get("visibilityDowngraded") is False for l in d["labels"])
