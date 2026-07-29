"""ARGUS V11.5.7 — bridge entitlement isolation + heartbeat + segmented status
(Jul-3 OpenD incident: JP quote permission lost while US stayed healthy)."""
import importlib.util
import json
import time

import scanner


def _load_bridge(monkeypatch, disable_jp=False):
    monkeypatch.delenv("JP_ENTITLEMENT_BACKOFF_SEC", raising=False)
    if disable_jp:
        monkeypatch.setenv("ARGUS_DISABLE_JP_QUOTES", "1")
    else:
        monkeypatch.delenv("ARGUS_DISABLE_JP_QUOTES", raising=False)
    spec = importlib.util.spec_from_file_location("moomoo_push_test", "bridge/moomoo_push.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _FakeDF:
    """Tiny stand-in for the moomoo snapshot dataframe."""
    def __init__(self, rows):
        self._rows = rows
    def iterrows(self):
        for i, r in enumerate(self._rows):
            yield i, r


class _FakeQC:
    """get_market_snapshot fake: per-market scripted results."""
    def __init__(self, by_market):
        self.by_market = by_market
        self.calls = []
    def get_market_snapshot(self, codes):
        mkt = "JP" if str(codes[0]).upper().startswith("JP.") else "US"
        self.calls.append((mkt, list(codes)))
        return self.by_market[mkt]


def _us_ok_df():
    return (0, _FakeDF([{"code": "US.NVDA", "last_price": 190.0,
                         "prev_close_price": 185.0, "volume": 1000}]))


def test_snapshot_rows_transport_market_timestamp(monkeypatch):
    m = _load_bridge(monkeypatch)
    rows = m.rows_from_snapshot(_FakeDF([{
        "code": "US.NVDA", "last_price": 190.0,
        "prev_close_price": 185.0, "volume": 1000,
        "update_time": "2026-07-27 16:00:00",
    }]))
    assert rows[0]["exchangeTs"] == "2026-07-27T20:00:00Z"
    assert rows[0]["quoteRight"] == "unknown"
    assert rows[0]["entitlement"] == "unknown"


def test_snapshot_rows_transport_safe_quote_right(monkeypatch):
    m = _load_bridge(monkeypatch)
    rows = m.rows_from_snapshot(_FakeDF([{
        "code": "JP.1321", "last_price": 65000.0,
        "prev_close_price": 64900.0, "volume": 100,
        "update_time": "2026-07-28 11:30:00",
        "quote_right": "REALTIME",
    }]))
    assert rows[0]["market"] == "JP"
    assert rows[0]["quoteRight"] == "realtime"
    assert rows[0]["entitlement"] == "realtime"


# ── entitlement isolation ────────────────────────────────────────────────────

def test_jp_permission_failure_does_not_block_us(monkeypatch):
    m = _load_bridge(monkeypatch)
    assert m.JP_ENTITLEMENT_BACKOFF_SEC == 7 * 24 * 3600
    qc = _FakeQC({"US": _us_ok_df(), "JP": (-1, "No permission to get quotes")})
    state = dict(m.STATE)
    stocks, jp_tried = m.fetch_market_quotes(
        qc, {"US": ["US.NVDA"], "JP": ["JP.8058"]}, state=state, disable_jp=False,
        now=1000.0, ret_ok=0)
    assert jp_tried is True
    assert [s["symbol"] for s in stocks] == ["NVDA"]        # US pushed normally
    assert state["jpLastErrorClass"] == "permission"
    assert state["jpBlockUntil"] == 1000.0 + 7 * 24 * 3600  # weekly probe armed
    # next cycle inside the backoff window: JP is NOT even attempted
    qc2 = _FakeQC({"US": _us_ok_df(), "JP": (-1, "No permission to get quotes")})
    stocks2, jp_tried2 = m.fetch_market_quotes(
        qc2, {"US": ["US.NVDA"], "JP": ["JP.8058"]}, state=state, disable_jp=False,
        now=1030.0, ret_ok=0)
    assert jp_tried2 is False
    assert [c[0] for c in qc2.calls] == ["US"]              # only the US call happened
    assert [s["symbol"] for s in stocks2] == ["NVDA"]


def test_jp_permission_log_backoff_no_spam(monkeypatch, capsys):
    m = _load_bridge(monkeypatch)
    state = dict(m.STATE)
    # Start beyond the weekly dedup interval so this isolated fresh state emits
    # one initial diagnostic; the second forced entitlement probe remains inside
    # that same logging window.
    for t in (700000.0, 702000.0):
        state["jpBlockUntil"] = 0.0
        qc = _FakeQC({"US": _us_ok_df(), "JP": (-1, "No permission to get quotes")})
        m.fetch_market_quotes(qc, {"US": [], "JP": ["JP.8058"]}, state=state,
                              disable_jp=False, now=t, ret_ok=0)
    out = capsys.readouterr().out
    assert out.count("no permission") == 1                  # dedup within the window


def test_disable_jp_env_excludes_jp(monkeypatch):
    m = _load_bridge(monkeypatch, disable_jp=True)
    assert m.DISABLE_JP is True
    assert m.jp_push_active() is False
    assert m.jp_realtime_status() == "disabled"
    assert m.bridge_mode() == "us_only"
    qc = _FakeQC({"US": _us_ok_df(), "JP": (-1, "should never be called")})
    stocks, jp_tried = m.fetch_market_quotes(
        qc, m.split_codes_by_market(["JP.8058", "US.NVDA"]), now=1000.0, ret_ok=0)
    assert jp_tried is False
    assert [c[0] for c in qc.calls] == ["US"]
    assert [s["symbol"] for s in stocks] == ["NVDA"]


def test_full_mode_both_markets_unchanged(monkeypatch):
    """Regression: when both markets are entitled, behavior is the pre-incident one."""
    m = _load_bridge(monkeypatch)
    jp_df = (0, _FakeDF([{"code": "JP.8058", "last_price": 3000.0,
                          "prev_close_price": 2950.0, "volume": 500}]))
    qc = _FakeQC({"US": _us_ok_df(), "JP": jp_df})
    state = dict(m.STATE)
    stocks, jp_tried = m.fetch_market_quotes(
        qc, {"US": ["US.NVDA"], "JP": ["JP.8058"]}, state=state, disable_jp=False,
        now=1000.0, ret_ok=0)
    assert jp_tried is True
    assert sorted(s["symbol"] for s in stocks) == ["8058", "NVDA"]
    assert m.bridge_mode(state, disable_jp=False) == "full"


def test_runtime_entitlement_loss_reads_fallback_mode(monkeypatch):
    m = _load_bridge(monkeypatch)
    state = dict(m.STATE)
    state["jpBlockUntil"] = time.time() + 1800
    state["jpLastErrorClass"] = "permission"
    assert m.bridge_mode(state, disable_jp=False) == "fallback"
    assert m.jp_realtime_status(state, disable_jp=False) == "entitlement_unavailable"


def test_heartbeat_payload_no_secrets(monkeypatch):
    monkeypatch.setenv("ARGUS_ADMIN_TOKEN", "SUPERSECRETTOKEN")
    monkeypatch.setenv("ARGUS_BRIDGE_HMAC_SECRET", "SUPERSECRETHMAC")
    m = _load_bridge(monkeypatch, disable_jp=True)
    hb = m.build_heartbeat()
    blob = json.dumps(hb)
    assert "SUPERSECRET" not in blob
    assert hb["jpRealtimeStatus"] == "disabled"
    assert hb["jpFallbackActive"] is True
    assert hb["bridgeMode"] == "us_only"
    for k in ("lastQuotePushAt", "lastUSQuotePushAt", "lastJPQuotePushAt",
              "acceptedCountLastPush", "openDStatus", "diskUsagePct",
              "jpSnapshotErrors", "usSnapshotErrors", "usLastErrorClass"):
        assert k in hb


def test_market_error_telemetry_is_separate(monkeypatch):
    m = _load_bridge(monkeypatch)
    state = dict(m.STATE)
    qc = _FakeQC({
        "US": (-1, "RemoteClose"),
        "JP": (0, _FakeDF([{
            "code": "JP.1321", "last_price": 65000.0,
            "prev_close_price": 64900.0, "volume": 100,
        }])),
    })
    stocks, jp_tried = m.fetch_market_quotes(
        qc,
        {"US": ["US.SPY"], "JP": ["JP.1321"]},
        state=state,
        now=1000.0,
        ret_ok=0,
    )
    assert jp_tried is True
    assert [row["market"] for row in stocks] == ["JP"]
    assert state["usSnapshotErrors"] == 1
    assert state["usLastErrorClass"] == "api_unhealthy"
    assert state["jpSnapshotErrors"] == 0
    assert state["jpLastErrorClass"] is None


def test_opend_error_classification(monkeypatch):
    m = _load_bridge(monkeypatch)
    assert m.classify_opend_error("SMS verification required") == "sms_required"
    assert m.classify_opend_error("RemoteClose / Context status bad") == "api_unhealthy"


# ── backend: heartbeat receiver + segmented lamps ────────────────────────────

def _post_hb(c, over):
    hb = {"at": scanner._ai_now_iso(), "bridgeVersion": "11.5.7", "bridgeMode": "full",
          "openDStatus": "connected", "lastQuotePushAt": scanner._ai_now_iso(),
          "lastUSQuotePushAt": scanner._ai_now_iso(), "lastJPQuotePushAt": None,
          "acceptedCountLastPush": 12, "usRealtimeStatus": "ok",
          "jpRealtimeStatus": "ok", "jpFallbackActive": False,
          "jpLastErrorClass": None, "usLastErrorClass": None,
          "jpSnapshotErrors": 0, "usSnapshotErrors": 0,
          "diskUsagePct": 13.0, "intervalSec": 15}
    hb.update(over)
    return c.post("/api/argus/bridge/heartbeat", json={"heartbeat": hb},
                  headers={"X-ARGUS-ADMIN-TOKEN": "tok"})


def test_heartbeat_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/bridge/heartbeat").status_code in (401, 503)


def test_heartbeat_sanitizes_and_status_segments(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        r = _post_hb(c, {"jpRealtimeStatus": "entitlement_unavailable",
                         "jpFallbackActive": True, "bridgeMode": "fallback",
                         "jpSnapshotErrors": 4, "usSnapshotErrors": 1,
                         "evil": "x", "password": "y"})
        assert r.status_code == 200
        assert "evil" not in scanner._BRIDGE_HB["data"]
        assert "password" not in scanner._BRIDGE_HB["data"]
        assert scanner._BRIDGE_HB["data"]["jpSnapshotErrors"] == 4
        assert scanner._BRIDGE_HB["data"]["usSnapshotErrors"] == 1
        d = c.get("/api/argus/bridge/status").get_json()
    assert d["jpRealtimeStatus"] == "entitlement_unavailable"
    assert d["jpFallbackActive"] is True
    assert d["bridgeProcess"] == "ok"
    assert "日本株リアルタイムは利用できません" in d["noteJa"]


def test_lamp_jp_entitlement_unavailable_is_warning(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        _post_hb(c, {"jpRealtimeStatus": "entitlement_unavailable", "jpFallbackActive": True,
                     "bridgeMode": "fallback"})
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert lamps["jp_realtime"]["status"] == "warning"
    assert "権限なし" in lamps["jp_realtime"]["detailJa"]
    assert "代替データ" in lamps["jp_realtime"]["detailJa"]


def test_lamp_jp_disabled_is_gray_with_fallback_copy(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        _post_hb(c, {"jpRealtimeStatus": "disabled", "jpFallbackActive": True,
                     "bridgeMode": "us_only"})
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert lamps["jp_realtime"]["status"] == "off"
    assert "代替データ" in lamps["jp_realtime"]["detailJa"]
    # segmented: bridge itself stays ok — but JP is visibly not live
    assert lamps["bridge"]["status"] == "ok"


def test_lamp_sms_required_is_stopped(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        _post_hb(c, {"openDStatus": "sms_required"})
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert lamps["bridge"]["status"] == "stopped"
    assert "SMS認証" in lamps["bridge"]["detailJa"]


def test_lamp_disk_critical(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        _post_hb(c, {"diskUsagePct": 98.0})
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert lamps["bridge_disk"]["status"] == "stopped"
    with scanner.app.test_client() as c:
        _post_hb(c, {"diskUsagePct": 92.0})
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert lamps["bridge_disk"]["status"] == "warning"


def test_legacy_bridge_without_heartbeat(monkeypatch):
    """Old bridge (pre-11.5.7): keep the push-derived lamp + honest note."""
    monkeypatch.setitem(scanner._BRIDGE_HB, "data", None)
    monkeypatch.setitem(scanner._BRIDGE_HB, "receivedAt", 0.0)
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert "bridge" in lamps
    assert "旧ブリッジ" in lamps["bridge"]["detailJa"] or "push" in lamps["bridge"]["detailJa"]
    assert "us_realtime" not in lamps          # segmented lamps need a heartbeat


def test_admin_diagnostic_gated_and_recommends(monkeypatch):
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/admin/bridge/diagnostic").status_code in (401, 503)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        _post_hb(c, {"jpRealtimeStatus": "entitlement_unavailable", "jpFallbackActive": True,
                     "bridgeMode": "fallback", "jpLastErrorClass": "permission"})
        d = c.get("/api/argus/admin/bridge/diagnostic",
                  headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
    assert d["schemaVersion"] == "bridge-diagnostic-v1"
    assert d["lastJpErrorClass"] == "permission"
    assert any("JP権限" in r or "権限" in r for r in d["recommendedActionsJa"])


def test_bridge_status_no_forbidden_keys(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        _post_hb(c, {})
        blob = json.dumps(c.get("/api/argus/bridge/status").get_json(),
                          ensure_ascii=False).lower()
    for bad in ('"prompt":', '"apikey":', '"api_key":', '"token":', '"secret":',
                '"holdings":', '"pnl":'):
        assert bad not in blob, bad
