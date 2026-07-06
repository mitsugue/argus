"""V11.22.0 Data Quality Console tests — spec §10."""
import json

import argus_data_quality as dq

NOW = "2026-07-05T18:00:00+00:00"


def _src(**kw):
    base = {"sourceName": "jsf-daily-balance", "sourceType": "supply_demand",
            "cadence": "daily", "lastSuccessAt": "2026-07-05T12:00:00+00:00",
            "expectedDisabled": False, "failureClass": None,
            "fallbackActive": False, "impactJa": "需給ランクの鮮度に影響"}
    base.update(kw)
    return base


def _console(**kw):
    base = {
        "sources": [
            _src(sourceName="us-realtime-bridge", sourceType="market_data",
                 cadence="realtime", lastSuccessAt="2026-07-05T17:59:30+00:00"),
            _src(),
            _src(sourceName="jquants-margin-weekly", cadence="weekly",
                 lastSuccessAt="2026-07-01T00:00:00+00:00"),
            _src(sourceName="moomoo JPリアルタイム", sourceType="market_data",
                 cadence="realtime", lastSuccessAt=None, expectedDisabled=True),
            _src(sourceName="逆日歩(品貸料)", sourceType="supply_demand",
                 cadence="daily", lastSuccessAt=None, expectedDisabled=True),
        ],
        "engines": [{"engineName": "supply_demand", "status": "ok",
                     "lastRunAt": NOW, "outputCount": 11}],
        "bridge": {"bridgeProcess": "ok", "openDStatus": "connected",
                   "bridgeMode": "us_only", "usRealtimeStatus": "ok",
                   "jpRealtimeStatus": "disabled", "jpFallbackActive": True,
                   "heartbeatAgeSec": 45, "acceptedCount": 12},
        "publicLeakSafe": True, "backupUnsafeWithData": False, "eventNear": False,
    }
    base.update(kw)
    return dq.build_console(base, NOW, app_version="11.22.0")


# ── validation ───────────────────────────────────────────────────────────────

def test_schema_and_enums():
    c = _console()
    assert c["overallStatus"] in dq.OVERALL
    for s in c["sourceHealth"]:
        assert s["status"] in dq.SOURCE_STATUSES
        assert s["freshnessBucket"] in dq.BUCKETS
    for e in c["engineHealth"]:
        assert e["status"] in dq.ENGINE_STATUSES
    assert c["bridgeHealth"]["jpRealtimeStatus"] == "disabled"
    assert "意図的に無効" in (c["bridgeHealth"]["jpRealtimeNoteJa"] or "")


def test_freshness_buckets():
    assert dq.freshness_bucket(60, "realtime") == "fresh"
    assert dq.freshness_bucket(2000, "realtime") == "stale"
    assert dq.freshness_bucket(20 * 3600, "daily") == "fresh"
    assert dq.freshness_bucket(3 * 86400, "daily") == "stale"
    assert dq.freshness_bucket(9 * 86400, "weekly") == "recent"
    assert dq.freshness_bucket(None, "daily") == "unknown"   # 捏造しない


# ── scoring ──────────────────────────────────────────────────────────────────

def test_all_ok():
    c = _console()
    assert c["overallStatus"] == "ok"
    assert "新しいデータ" in c["ownerReadableSummaryJa"]


def test_expected_disabled_never_critical():
    c = _console()
    dis = [s for s in c["sourceHealth"] if s["isExpectedDisabled"]]
    assert len(dis) == 2
    for s in dis:
        assert s["status"] == "disabled_expected"
        assert "意図的に無効" in s["ownerReadableStatusJa"]
    assert c["overallStatus"] == "ok"                     # 数えられていない
    assert len(c["expectedDisabled"]) == 3                # 恒久3件の説明リスト


def test_degraded_on_one_stale():
    c = _console(sources=[
        _src(sourceName="us-realtime-bridge", sourceType="market_data",
             cadence="realtime", lastSuccessAt="2026-07-05T17:59:30+00:00"),
        _src(lastSuccessAt="2026-07-02T00:00:00+00:00"),   # JSF 3.75日前 = stale
    ])
    assert c["overallStatus"] == "degraded"
    assert any("jsf" in i for i in c["topIssuesJa"])


def test_stale_with_fallback_is_degraded_source():
    c = _console(sources=[_src(lastSuccessAt="2026-07-02T00:00:00+00:00",
                               fallbackActive=True)])
    s = c["sourceHealth"][0]
    assert s["status"] == "degraded"
    assert "フォールバック稼働中" in s["ownerReadableStatusJa"]


def test_warning_on_major_source_stale():
    c = _console(sources=[
        _src(sourceName="us-prices", sourceType="market_data",
             cadence="realtime", lastSuccessAt="2026-07-05T12:00:00+00:00"),  # 6h = very_stale
    ])
    assert c["overallStatus"] == "warning"


def test_warning_on_backup_unsafe():
    c = _console(backupUnsafeWithData=True)
    assert c["overallStatus"] == "warning"


def test_critical_on_bridge_down():
    c = _console(bridge={"bridgeProcess": "down", "usRealtimeStatus": "failed",
                         "jpRealtimeStatus": "disabled"})
    assert c["overallStatus"] == "critical"
    assert "重大" in c["ownerReadableSummaryJa"]


def test_critical_on_leak_guard():
    c = _console(publicLeakSafe=False)
    assert c["overallStatus"] == "critical"
    assert any("漏洩ガード" in i for i in c["topIssuesJa"])


def test_stale_margin_and_jsf_warnings():
    c = _console(sources=[
        _src(sourceName="jquants-margin-weekly", cadence="weekly",
             lastSuccessAt="2026-06-20T00:00:00+00:00"),   # 15日超 = very_stale
        _src(lastSuccessAt="2026-07-01T00:00:00+00:00"),   # JSF 4.75日 = very_stale
        _src(sourceName="fund-nav", sourceType="market_data", cadence="daily",
             lastSuccessAt="2026-06-25T00:00:00+00:00"),   # 10日 = very_stale (major)
    ])
    assert c["overallStatus"] == "warning"
    assert len([i for i in c["topIssuesJa"] if "古い" in i]) >= 2


def test_unknown_when_no_timestamps():
    c = _console(sources=[_src(lastSuccessAt=None)])
    s = c["sourceHealth"][0]
    assert s["status"] == "unknown" and s["freshnessBucket"] == "unknown"
    assert "捏造しません" in s["ownerReadableStatusJa"]


def test_failure_reason_redacted():
    c = _console(sources=[_src(failureClass="ConnectTimeout")])
    s = c["sourceHealth"][0]
    assert s["status"] == "failed"
    assert s["failureReasonRedacted"] == "ConnectTimeout"
    assert "redacted" in s["ownerReadableStatusJa"]


# ── privacy ──────────────────────────────────────────────────────────────────

def test_no_secrets_or_private_fields():
    blob = json.dumps(_console(), ensure_ascii=False)
    for banned in ("vaultPass", "passphrase=", "HMAC", "X-ARGUS-ADMIN-TOKEN",
                   "login_pwd", "Bearer ", "quantity", "averageCost",
                   "monthlyContribution", "fundName", "ownerAction"):
        assert banned not in blob, banned


def test_public_status_redacted():
    c = _console()
    d = dq.public_status(c, now_iso=NOW)
    assert d["storageMode"] == "public_redacted"
    assert d["overallStatus"] == "ok"
    assert d["heartbeatBucket"] == "fresh"
    assert d["expectedDisabledCount"] == 3
    assert "ok" in d["sourceCountByStatus"]
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("lastSuccessAt", "failureReason", "quantity", "vaultPass"):
        assert banned not in blob, banned


# ── V12.0.2 JP readiness / reboot safety ────────────────────────────────────

def test_jp_no_permission_not_ready_not_critical():
    r = dq.build_jp_readiness({"jpRealtimeStatus": "disabled",
                               "jpLastErrorClass": "no_permission",
                               "bridgeMode": "us_only", "jpFallbackActive": True})
    assert r["jpPermissionStatus"] == "no_permission"
    assert r["activationReady"] is False
    assert r["showActivationSteps"] is False
    assert "復帰不可" in r["ownerReadableStatusJa"]
    assert "クォート権限がない" in r["reasonJa"]
    assert "まだUS-onlyを外さないでください" in r["guardJa"]
    # 全体スコアはJP無効でcriticalにならない(既存expected-disabled動作)
    c = _console()
    assert c["overallStatus"] == "ok"
    assert c["jpReadiness"]["jpPermissionStatus"] in ("unknown", "no_permission")


def test_jp_ready_but_usonly_shows_guarded_steps():
    r = dq.build_jp_readiness({"jpRealtimeStatus": "ok", "bridgeMode": "us_only",
                               "bridgeProcess": "ok", "openDStatus": "connected",
                               "jpFallbackActive": True})
    # jp==ok かつ us_onlyフラグ → 準備OK・手順表示
    assert r["jpPermissionStatus"] == "ready"
    assert r["activationReady"] is True
    assert "復帰準備OK" in r["ownerReadableStatusJa"]


def test_jp_live_when_full_mode():
    r = dq.build_jp_readiness({"jpRealtimeStatus": "ok", "bridgeMode": "full",
                               "bridgeProcess": "ok", "openDStatus": "connected"})
    assert r["ownerReadableStatusJa"] == "JPリアルタイム稼働中。"


def test_jp_unknown_permission_untested():
    r = dq.build_jp_readiness({"jpRealtimeStatus": "disabled",
                               "bridgeMode": "us_only", "jpFallbackActive": True})
    assert r["jpPermissionStatus"] == "unknown"
    assert r["activationReady"] == "unknown"
    assert "権限テスト未実施" in r["ownerReadableStatusJa"]
    assert "代替データで判定" in r["safeModeJa"]
    assert r["showActivationSteps"] is False       # 手順は隠す


def test_jp_wording_never_implies_live_when_disabled():
    r = dq.build_jp_readiness({"jpRealtimeStatus": "disabled",
                               "jpLastErrorClass": "entitlement",
                               "bridgeMode": "us_only"})
    blob = json.dumps(r, ensure_ascii=False)
    assert "稼働中" not in blob


def test_reboot_safety_unknown_autostart_warns():
    r = dq.build_reboot_safety({}, {})
    assert r["opendAutostartConfigured"] == "unknown"
    assert r["rebootSafe"] == "unknown"
    assert "推奨しません" in r["ownerReadableRiskJa"]
    blob = json.dumps(r, ensure_ascii=False)
    for banned in ("login_pwd", "vaultPass", "ps aux", "pgrep"):
        assert banned not in blob


def test_reboot_safe_only_when_both_confirmed():
    r = dq.build_reboot_safety({}, {"opendAutostart": True, "bridgeAutostart": True})
    assert r["rebootSafe"] is True
    assert "再起動可" in r["ownerReadableRiskJa"]
    r2 = dq.build_reboot_safety({}, {"opendAutostart": False, "bridgeAutostart": True})
    assert r2["rebootSafe"] is False          # bridge enabledだけでは不十分


def test_restart_required_surfaced_but_not_reboot_trigger():
    r = dq.build_reboot_safety({}, {"systemRestartRequired": True})
    assert r["systemRestartRequired"] is True
    assert r["rebootSafe"] == "unknown"       # 要求ありでも自動復旧未確認なら非推奨
    assert "推奨しません" in r["ownerReadableRiskJa"]


def test_heartbeat_whitelist_accepts_reboot_facts():
    import scanner
    for k in ("opendAutostart", "bridgeAutostart", "systemRestartRequired"):
        assert k in scanner._HB_ALLOWED_KEYS


def test_bridge_heartbeat_selfreport_has_no_secrets():
    import importlib.util, os as _os
    spec = importlib.util.spec_from_file_location(
        "mp", _os.path.join(_os.path.dirname(__file__), "bridge", "moomoo_push.py"))
    src = open(spec.origin, encoding="utf-8").read()
    # 自己申告はis-enabled/存在フラグのみ — 生ps/pgrepや資格情報を使わない
    seg = src[src.find("def _systemd_enabled"):src.find("def build_heartbeat")]
    for bad in ("login_pwd", "ps aux", "pgrep", "TOKEN", "HMAC"):
        assert bad not in seg, bad


def test_opend_service_example_has_no_secrets():
    src = open("bridge/opend.service.example", encoding="utf-8").read()
    for line in src.splitlines():
        assert not line.strip().startswith("Environment="), "unit must not embed credentials"
    for bad in ("login_pwd=", "password=", "PWD="):
        assert bad not in src, bad


def test_runbook_never_recommends_raw_process_commands():
    src = open("bridge/README.md", encoding="utf-8").read()
    for i, line in enumerate(src.splitlines(), 1):
        if "pgrep" in line or "ps aux" in line or ("`ps`" in line):
            assert any(w in line for w in ("使わない", "禁止", "見られ", "閲覧", "貼らない")), (i, line)


def test_readiness_script_secret_free():
    src = open("bridge/scripts/check_reboot_readiness.sh", encoding="utf-8").read()
    for bad in ("login_pwd", "TOKEN", "HMAC", "passphrase"):
        assert bad not in src, bad
    assert "ss -ltn" in src            # ポート確認はps系ではなくss


def test_deterministic():
    a = json.dumps(_console(), ensure_ascii=False)
    b = json.dumps(_console(), ensure_ascii=False)
    assert a == b
