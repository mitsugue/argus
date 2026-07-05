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


def test_deterministic():
    a = json.dumps(_console(), ensure_ascii=False)
    b = json.dumps(_console(), ensure_ascii=False)
    assert a == b
