"""2026-10-20 (owner): the bridge lamp tells a restart wait from no receipt, and never hides a US-session stop."""
import time

import scanner


def lamp(monkeypatch, *, us_open, uptime, pushes=None):
    monkeypatch.setitem(scanner._BRIDGE_HB, "data", None)
    monkeypatch.setitem(scanner._BRIDGE_HB, "receivedAt", 0.0)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda: False)
    monkeypatch.setattr(scanner, "_us_market_open", lambda: us_open)
    monkeypatch.setattr(scanner, "_PUSHED_QUOTES", {"US": pushes or {}, "JP": {}})
    monkeypatch.setattr(scanner, "_INTEL_COLLECT_PROCESS_STARTED", time.monotonic() - uptime)
    lamps = {l["key"]: l for l in scanner._system_health(allow_provider_fetch=False)["lamps"]}
    return lamps["bridge"]


def test_right_after_a_start_the_lamp_says_it_is_waiting(monkeypatch):
    out = lamp(monkeypatch, us_open=False, uptime=40)
    assert out["status"] == "off" and "再起動後の受信待ち" in out["detailJa"]
    assert "旧ブリッジ" not in out["detailJa"]


def test_a_us_session_wait_is_still_a_warning(monkeypatch):
    out = lamp(monkeypatch, us_open=True, uptime=40)
    assert out["status"] == "warning" and "再起動後の受信待ち" in out["detailJa"]


def test_after_the_wait_nothing_received_is_said_plainly(monkeypatch):
    out = lamp(monkeypatch, us_open=False, uptime=900)
    assert out["status"] == "off"
    assert "生存の知らせ・価格とも未受信" in out["detailJa"] and "待機" not in out["detailJa"]
    out = lamp(monkeypatch, us_open=True, uptime=900)
    assert out["status"] == "warning" and "US市場時間中なのに受信なし" in out["detailJa"]


def test_the_legacy_wording_is_kept_only_for_pushes_without_a_heartbeat(monkeypatch):
    out = lamp(monkeypatch, us_open=True, uptime=900, pushes={"SPY": {"ts": time.time() - 30, "row": {}}})
    assert out["status"] == "ok" and "旧ブリッジ(heartbeat未対応)" in out["detailJa"]
