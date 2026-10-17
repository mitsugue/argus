"""Tests for the backend Action Level signal resolver (argus_signal.py)."""
import argus_signal as S


def test_legacy_mapping():
    assert S.resolve_signal("HOLD")["code"] == "HOLD_ONLY"
    assert S.resolve_signal("WAIT_FOR_PULLBACK")["code"] == "PREPARE"
    assert S.resolve_signal("TRIM")["code"] == "DEFEND"
    assert S.resolve_signal("EXIT")["code"] == "EXIT"
    assert S.resolve_signal("ADD")["code"] == "ENTER"


def test_buy_dip_conditional():
    assert S.resolve_signal("BUY_DIP", data_quality="PARTIAL")["code"] == "PREPARE"
    assert S.resolve_signal("BUY_DIP", gates_pass=True, data_quality="LIVE")["code"] == "ENTER"


def test_stale_cannot_enter():
    assert S.resolve_signal("ADD", data_quality="STALE")["code"] != "ENTER"


def test_override_more_defensive():
    assert S.resolve_signal("HOLD", downside_override="REVIEW_REQUIRED")["code"] == "REVIEW"
    assert S.resolve_signal("HOLD", downside_override="EXIT_WATCH", exit_confirmed=True)["code"] == "EXIT"
    assert S.resolve_signal("ADD", downside_override="TRIM_WATCH")["code"] == "DEFEND"


def test_material_downside_partial_review():
    assert S.resolve_signal("ADD", material_downside=True, data_quality="PARTIAL")["code"] == "REVIEW"


def test_permissions_shape():
    sig = S.resolve_signal("HOLD")
    assert sig["permissions"]["newEntry"] == "blocked" and sig["permissions"]["add"] == "blocked"
    assert sig["schemaVersion"] == "action-level-v1" and sig["legacyAction"] == "HOLD"
    enter = S.resolve_signal("ADD")
    assert enter["permissions"]["newEntry"] == "allowed"


def test_no_order_surface():
    for bad in ("place_order", "execute", "buy", "sell", "broker"):
        assert not hasattr(S, bad)
