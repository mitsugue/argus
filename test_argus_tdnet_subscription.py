"""A cancelled add-on reports as cancelled, and never buys itself officialness.

2026-09-29: the owner cancelled the J-Quants TDnet/Company Disclosure Add-on. The
free mirror keeps the disclosures flowing, so the risk in this change is not an
outage — it is that the system either (a) nags forever about a purchase the owner
ended, or (b) hides the downgrade and lets a lower-tier item pass as official.
Both are tested here.
"""
import argus_jquants_tdnet
import argus_tdnet_subscription as sub


def test_absent_variable_keeps_probing_the_paid_feed():
    """The default must never be 'off': that would silently waste a live add-on."""
    assert sub.mode({}) == sub.MODE_AUTO
    assert sub.is_declared_off({}) is False


def test_the_owner_can_declare_the_cancellation_in_several_spellings():
    for word in ("off", "OFF", " off ", "0", "false", "no", "cancelled",
                 "canceled", "unsubscribed", "not_subscribed"):
        assert sub.is_declared_off({sub.ENV_VAR: word}) is True, word


def test_an_unrecognised_value_probes_rather_than_assuming_cancelled():
    for word in ("maybe", "yes-ish", "1 ", "true", "on", "subscribed", "auto"):
        assert sub.is_declared_off({sub.ENV_VAR: word}) is False, word


def test_a_declared_cancellation_is_not_graded_as_a_fault():
    assert sub.is_failure_status(sub.STATUS_NOT_SUBSCRIBED) is False
    # Every real problem still grades as one.
    for bad in ("entitlement_missing", "endpoint_not_found", "rate_limited",
                "unavailable", "not_configured"):
        assert sub.is_failure_status(bad) is True, bad
    # A working feed is not a fault either.
    for good in ("official_tdnet_live", "live"):
        assert sub.is_failure_status(good) is False, good


def test_the_status_word_is_distinct_from_every_failure_word():
    """'cancelled' must be unsayable as 'broken' — that is the whole point."""
    assert sub.STATUS_NOT_SUBSCRIBED != "entitlement_missing"
    for http in (401, 403, 404, 429, 500, None):
        assert argus_jquants_tdnet.status_from_http(http) != sub.STATUS_NOT_SUBSCRIBED


def test_the_declared_snapshot_carries_no_disclosures_and_says_why_in_japanese():
    snapshot = argus_jquants_tdnet.build_snapshot(
        [], as_of="2026-09-29T12:00:00+09:00", **sub.snapshot_fields())
    assert snapshot["items"] == []
    assert snapshot["status"] == sub.STATUS_NOT_SUBSCRIBED
    assert snapshot["entitlement"] == sub.ENTITLEMENT_NOT_SUBSCRIBED
    assert snapshot["provider"] == "jquants-tdnet"
    # The owner reads this line months later: it must say intentional, name the
    # substitute, and admit the lost confirmation.
    note = snapshot["noteJa"]
    assert "解約" in note and "意図的" in note
    assert "yanoshin" in note
    assert "confirmed_cause" in note or "確定原因" in note


def test_the_note_never_tells_the_owner_to_go_and_buy_it_again():
    for text in (sub.NOTE_JA, sub.registry_row()["noteJa"]):
        for nag in ("購入", "ご利用中", "Subscription", "アドオンプラン", "確認してください"):
            assert nag not in text, (nag, text)


def test_the_registry_row_shows_the_decision_not_a_green_tick():
    row = sub.registry_row()
    assert row["status"] == sub.STATUS_NOT_SUBSCRIBED
    assert row["status"] not in ("confirmed_live", "live")
    assert "解約済み" in row["entitlement"]


def test_a_cancelled_addon_cannot_lift_corroboration_to_official():
    """The downgrade is the honest consequence and must survive the declaration."""
    import argus_event_card
    for has_official in (False,):
        level = argus_event_card.corroboration_level(
            independent_family_count=3, has_official=has_official,
            market_confirmed=True)
        assert "official" not in level, level


def test_nothing_in_this_module_reaches_the_network_or_the_server():
    import inspect
    source = inspect.getsource(sub)
    for forbidden in ("requests", "urllib", "socket", "import scanner", "JQUANTS_API_KEY"):
        assert forbidden not in source, forbidden
