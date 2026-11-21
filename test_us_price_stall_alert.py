"""2026-11-21: a bridge heartbeat without US prices is told once a day."""
import argus_web_push as push
import scanner

NOW = 1_795_300_000.0  # a fixed instant


def _state(monkeypatch, *, hb_age=30, opened_ago=3600, price_ages=(), market_open=True):
    monkeypatch.setattr(scanner, "_BRIDGE_HB", {"data": {"bridgeMode": "us_only"}, "receivedAt": NOW - hb_age})
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES",
                        {"US": {f"S{i}": {"ts": NOW - age} for i, age in enumerate(price_ages)}})
    monkeypatch.setattr(scanner, "_us_market_open", lambda: market_open)
    monkeypatch.setattr(scanner, "_us_regular_open_epoch", lambda now: NOW - opened_ago)


def test_heartbeat_without_prices_is_a_note(monkeypatch):
    _state(monkeypatch)
    note = scanner._us_price_stall_note(NOW)
    assert note == {"at": NOW, "lastPriceAgeSeconds": None}
    _state(monkeypatch, price_ages=(4000, 2500))
    assert scanner._us_price_stall_note(NOW)["lastPriceAgeSeconds"] == 2500


def test_no_note_when_prices_flow_or_bridge_or_market_is_quiet(monkeypatch):
    _state(monkeypatch, price_ages=(60,))
    assert scanner._us_price_stall_note(NOW) is None            # prices arrive
    _state(monkeypatch, hb_age=600)
    assert scanner._us_price_stall_note(NOW) is None            # bridge itself is down (its own lamp)
    _state(monkeypatch, market_open=False)
    assert scanner._us_price_stall_note(NOW) is None            # outside the regular session
    _state(monkeypatch, opened_ago=600)
    assert scanner._us_price_stall_note(NOW) is None            # first 30 minutes after the open
    monkeypatch.setattr(scanner, "_BRIDGE_HB", {})
    assert scanner._us_price_stall_note(NOW) is None            # no heartbeat ever


def test_one_notice_a_day_for_every_device():
    first = push.us_price_stall_proposals({"at": NOW}, NOW)
    later = push.us_price_stall_proposals({"at": NOW + 600}, NOW + 600)
    assert len(first) == 1 and first[0]["kind"] == "security"
    assert first[0]["key"] == later[0]["key"] and first[0]["key"].startswith("bridge-us-prices:")
    assert first[0]["title"] == "ARGUS 警報｜米国株の値段が届いていません"
    assert "30分以上" in first[0]["body"] and first[0]["hash"] == "#settings"
    assert first[0]["expires"] - first[0]["due"] == push.SECURITY_INTERVAL_SECONDS
    assert push.us_price_stall_proposals(None, NOW) == []
    assert push.us_price_stall_proposals({"at": NOW - 7200}, NOW) == []   # stale note
    assert push.us_price_stall_proposals({"at": True}, NOW) == []


def test_regular_open_epoch_reads_the_exchange_calendar():
    # 2026-11-20 (Fri) 15:00 UTC: the regular session opened at 14:30 UTC.
    import datetime as dt
    now = dt.datetime(2026, 11, 20, 15, 0, tzinfo=dt.timezone.utc).timestamp()
    opened = scanner._us_regular_open_epoch(now)
    assert opened == dt.datetime(2026, 11, 20, 14, 30, tzinfo=dt.timezone.utc).timestamp()
