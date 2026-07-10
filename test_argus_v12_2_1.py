"""ARGUS V12.2.1 — 二面アーキテクチャ/セッション対応スケジューラ/本番予測発行の恒久ガード。"""
import os

import argus_decision_ledger as dl
import argus_dual_plane as dp
import argus_scheduler as sc
import scanner

NOW = "2026-07-10T09:00:00+09:00"


# ── Phase 0: Dual-Plane ─────────────────────────────────────────────────────

def test_no_false_24x365_private_claim():
    st = dp.dual_plane_status()
    assert st["privateDecisionPlane"]["status"] == "client_only"
    assert st["privateDecisionPlane"]["active24x365"] is False
    assert dp.FORBIDDEN_CLAIM_JA not in str(st)
    assert "端末でARGUSを開いた時に更新されます" in st["honestClaimJa"]


def test_research_plane_cannot_access_private():
    assert dp.plane_may_access_private("research_server") is False
    assert dp.plane_may_access_private("public_redacted") is False
    assert dp.plane_may_access_private("private_client") is True


def test_private_worker_requires_verification():
    st = dp.dual_plane_status(private_worker_configured=True,
                              private_worker_verified=False)
    assert st["privateDecisionPlane"]["status"] == "private_worker_degraded"
    assert st["privateDecisionPlane"]["active24x365"] is False


# ── Phase 1: Scheduler ──────────────────────────────────────────────────────

def test_daily_missions_idempotent():
    ms = sc.generate_daily_missions(session_date="2026-07-10", now_iso=NOW)
    assert len(ms) == 9
    again = sc.generate_daily_missions(session_date="2026-07-10", now_iso=NOW,
                                       existing=ms)
    assert again == []


def test_holiday_skipped_not_silent():
    ms = sc.generate_daily_missions(session_date="2026-07-11", now_iso=NOW,
                                    jp_holiday=True)
    jp = [m for m in ms if m["market"] == "JP"]
    assert jp and all(m["status"] == "skipped" for m in jp)
    assert all(m["failureReasonRedacted"] == "market_holiday" for m in jp)


def test_lease_prevents_double_claim():
    m = sc.mission(mission_type="daily_learning", market="ALL",
                   session_date="2026-07-10", scheduled_for=NOW)
    assert sc.claim(m, NOW) is True
    assert sc.claim(m, "2026-07-10T09:05:00+09:00") is False   # lease内
    assert sc.claim(m, "2026-07-10T09:31:00+09:00") is True    # lease失効→回収


def test_missed_detected_and_recovered():
    m = sc.mission(mission_type="post_session_snapshot", market="JP",
                   session_date="2026-07-09",
                   scheduled_for="2026-07-09T15:40:00+09:00")
    missed = sc.detect_missed([m], NOW)
    assert missed and m["status"] == "missed"
    sc.recover(m, NOW)
    assert m["status"] == "recovered"
    assert sc.ops_summary([m])["missed"] == 0


def test_retry_backoff_to_failed_safe():
    m = sc.mission(mission_type="daily_learning", market="ALL",
                   session_date="2026-07-10", scheduled_for=NOW)
    for _ in range(3):
        sc.fail(m, NOW, "ProviderError")
    assert m["status"] == "failed_safe"
    assert m["retryCount"] == 3


# ── Phase 2/3: 本番予測発行+成果解決 ────────────────────────────────────────

def test_tick_admin_only():
    with scanner.app.test_client() as c:
        r = c.post("/api/argus/admin/missions/tick", json={})
        assert r.status_code in (401, 403, 503)


def test_tick_idempotent_no_duplicate_forecasts(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    scanner._MISSIONS.clear()
    scanner._FORECAST_LEDGER.clear()
    scanner._OUTCOME_LEDGER.clear()
    scanner._POSTMORTEMS.clear()
    with scanner.app.test_client() as c:
        r1 = c.post("/api/argus/admin/missions/tick", json={})
        assert r1.status_code == 200
        n1 = len(scanner._FORECAST_LEDGER)
        r2 = c.post("/api/argus/admin/missions/tick", json={})
        assert r2.get_json()["created"] == 0          # ミッション冪等
        assert len(scanner._FORECAST_LEDGER) == n1    # 予測重複なし
    ids = [f["id"] for f in scanner._FORECAST_LEDGER]
    assert len(ids) == len(set(ids))


def test_resolution_missing_price_unresolved(monkeypatch):
    scanner._FORECAST_LEDGER.clear()
    scanner._OUTCOME_LEDGER.clear()
    fc = dl.forecast_record(symbol="9999", market="JP",
                            issued_at="2026-07-09T08:30:00+09:00",
                            horizon="next_session",
                            target_type="catalyst_verdict",
                            forecast_value="unknown",
                            now_iso="2026-07-09T08:30:00+09:00")
    fc["origin"] = "forward_live"
    scanner._FORECAST_LEDGER.append(fc)
    n = scanner._dl_resolve_matured(NOW)
    assert n == 0
    assert scanner._OUTCOME_LEDGER[-1]["status"] == "unresolved"


def test_no_premature_resolution():
    scanner._FORECAST_LEDGER.clear()
    scanner._OUTCOME_LEDGER.clear()
    fc = dl.forecast_record(symbol="9999", market="JP",
                            issued_at=NOW, horizon="next_session",
                            target_type="catalyst_verdict",
                            forecast_value="unknown", now_iso=NOW)
    scanner._FORECAST_LEDGER.append(fc)
    scanner._dl_resolve_matured(NOW)                  # 同日=成熟前
    assert not scanner._OUTCOME_LEDGER


def test_postmortem_no_learning_claim_without_samples(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    scanner._MISSIONS.clear()
    scanner._POSTMORTEMS.clear()
    scanner._OUTCOME_LEDGER.clear()
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    if scanner._POSTMORTEMS:
        pm = scanner._POSTMORTEMS[-1]
        if pm["forecastsResolved"] == 0:
            assert "学習主張はしません" in pm["ownerReadableSummaryJa"]


# ── Phase 9: origin分離+公開境界 ────────────────────────────────────────────

def test_forward_live_origin_stamped(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    if scanner._FORECAST_LEDGER:
        assert all(f.get("origin") in ("forward_live", None)
                   for f in scanner._FORECAST_LEDGER)


def test_dq_exposes_agent_ops_dual_plane_no_leak():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        assert "agentOps" in d and "dualPlane" in d
        assert d["dualPlane"]["privateDecisionPlane"]["active24x365"] is False
        body = str(d)
        assert dp.FORBIDDEN_CLAIM_JA not in body
        for banned in ("forecastValue", "quantity", "avgCost", "passphrase",
                       "hmac", "OPENAI_API_KEY"):
            assert banned not in body, banned
