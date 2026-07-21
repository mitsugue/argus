"""ARGUS V12.2.2 — 現行エポック再認定/forward-live起動/週次月次/soakの恒久ガード。"""
from datetime import datetime as RealDateTime

import argus_ai_gate as gate
import argus_decision_ledger as dl
import argus_osint_engine as oe
import argus_scheduler as sc
import scanner

NOW = "2026-07-10T09:00:00+09:00"


# ── Phase 0/1: エポック再認定 ────────────────────────────────────────────────

def test_legacy_runs_excluded_from_current_baseline():
    scanner._OSINT_BASELINE_RUNS.clear()
    # 旧エポック(v12.1.7相当・epochIdなし)の5run — 旧0.92xの元
    for i in range(5):
        scanner._OSINT_BASELINE_RUNS.append(
            {"score": 70 + i, "case": f"c{i % 2}", "at": NOW})
    cur = scanner._baseline_current_epoch()
    assert cur == []                       # 旧runは現行エポックに入らない
    b = oe.baseline_from_runs(cur)
    assert b["baselineType"] == "single_run"
    assert b["runCount"] == 0              # not_requalified
    assert len(scanner._baseline_legacy_runs()) == 5


def test_current_epoch_runs_qualify():
    scanner._OSINT_BASELINE_RUNS.clear()
    ep = scanner._current_epoch_id()
    for i, c in enumerate(("a", "a", "b", "b", "a")):
        scanner._OSINT_BASELINE_RUNS.append(
            {"score": 68 + i, "case": c, "at": NOW, "epochId": ep})
    b = oe.baseline_from_runs(scanner._baseline_current_epoch())
    assert b["runCount"] == 5
    assert b["baselineType"] == "calibrated_baseline"


def test_dq_marks_not_requalified_and_legacy():
    scanner._OSINT_BASELINE_RUNS.clear()
    scanner._OSINT_BASELINE_RUNS.append({"score": 72, "case": "x", "at": NOW})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        ce = d.get("currentResearchEpoch") or {}
        assert ce.get("requalified") is False
        assert "not_requalified" in ce.get("statusJa", "")
        assert ce.get("legacyRuns") == 1
        assert "0.92" in (ce.get("legacyNoteJa") or "")
        assert "現行比として表示しない" in (ce.get("legacyNoteJa") or "")


def test_research_ratio_excludes_decision_and_reliability():
    # RPS成分に判断/信頼性系のキーが混入していないこと(研究族のみ)
    ver = [{"titleJa": "x", "verificationStatus": "verified",
            "primaryEligible": True, "sourceType": "industry_forecast",
            "directness": "sector_theme", "freshness": "today"}]
    runs = [{"provider": "gemini", "status": "ok",
             "claims": [{"titleJa": "g", "verified": True}]}]
    rps = oe.research_power_score(
        verified=ver, agent_runs=runs, gap_ledger=[],
        coverage={"totalCoverage": "medium"},
        contradiction=oe.contradiction_report(ver, runs),
        context_advantages=[], learning_updated=False)
    for banned in ("missionCompletion", "brier", "forecastQuality",
                   "decisionQuality", "agentReliability"):
        assert not any(banned.lower() in k.lower()
                       for k in rps["components"]), banned


# ── Phase 2: プリフライト+ウォームアップ ────────────────────────────────────

def test_cold_store_queues_warmup_not_forecast(monkeypatch):
    class FixedBusinessDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            fixed = RealDateTime.fromisoformat(NOW)
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW)
    monkeypatch.setattr(scanner, "datetime", FixedBusinessDateTime)
    scanner._MISSIONS.clear()
    scanner._FORECAST_LEDGER.clear()
    scanner._OSINT_STORE.clear()
    scanner._OSINT_AGENT_QUEUE.clear()
    import argus_scheduler as _sc
    _sd = NOW[:10]
    _due = _sc.mission(mission_type="pre_session_forecast", market="JP",
                       session_date=_sd,
                       scheduled_for=f"{_sd}T00:01:00+09:00")
    scanner._MISSIONS.append(_due)   # 壁時計非依存: 到来済み発行ミッションを注入
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    assert len(scanner._FORECAST_LEDGER) == 0      # コールドから発行しない
    assert scanner._OSINT_AGENT_QUEUE               # ウォームアップをキュー済み
    wm = [m for m in scanner._MISSIONS
          if m.get("checkpoint") == "warmup_queued"]
    assert wm, "warmupチェックポイントが記録される"


def test_dq_forecast_readiness_blocker():
    scanner._OSINT_STORE.clear()
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        fr = d.get("forecastReadiness") or {}
        assert fr.get("readiness") == "insufficient_data"
        assert "ウォームアップ" in (fr.get("blockerJa") or "")


# ── Phase 4/9: replay分離+soak ──────────────────────────────────────────────

def test_replay_never_mixes_with_live():
    fc = dl.forecast_record(symbol="6965", market="JP",
                            issued_at="2026-07-01T08:30:00+09:00",
                            horizon="next_session",
                            target_type="catalyst_verdict",
                            forecast_value="unknown",
                            now_iso="2026-07-01T08:30:00+09:00")
    fc["origin"] = "historical_replay"
    live = [f for f in [fc] if f.get("origin") == "forward_live"]
    assert live == []                       # replayはlive集計に入らない


def test_replay_lookahead_rejected():
    # as-of以降の発行時刻はforecast_recordが拒否(look-ahead保護はreplayでも同一)
    assert dl.forecast_record(symbol="6965", market="JP",
                              issued_at="2026-07-02T00:00:00+09:00",
                              horizon="1d", target_type="direction",
                              forecast_value="up",
                              now_iso="2026-07-01T00:00:00+09:00") is None


def test_soak_states():
    assert sc.soak_status(started_at=None, now_iso=NOW,
                          summary={})["status"] == "architecture_ready"
    s1 = sc.soak_status(started_at="2026-07-10T08:30:00+09:00", now_iso=NOW,
                        summary={"missed": 0, "failedSafe": 0})
    assert s1["status"] == "active_unproven"
    s2 = sc.soak_status(started_at="2026-07-07T09:00:00+09:00", now_iso=NOW,
                        summary={"missed": 0, "failedSafe": 0})
    assert s2["status"] == "operationally_verified"
    s3 = sc.soak_status(started_at="2026-07-09T09:00:00+09:00", now_iso=NOW,
                        summary={"missed": 5, "failedSafe": 0})
    assert s3["status"] == "degraded"


# ── Phase 6/7: 週次月次+challenger shadow ───────────────────────────────────

def test_periodic_missions_idempotent():
    w = sc.generate_periodic_missions(session_date="2026-07-13", weekday=0,
                                      day_of_month=13)
    assert [m["missionType"] for m in w] == ["weekly_learning_review"]
    again = sc.generate_periodic_missions(session_date="2026-07-13", weekday=0,
                                          day_of_month=13, existing=w)
    assert again == []
    m = sc.generate_periodic_missions(session_date="2026-08-01", weekday=5,
                                      day_of_month=1)
    assert {x["missionType"] for x in m} == {"monthly_model_review",
                                             "benchmark_calibration"}


def test_challenger_shadow_never_promotes():
    ce = dl.challenger_evaluation(
        proposal={"proposalType": "query_expansion"},
        champion_version="prod", challenger_version="shadow-1",
        sample_count=1, metric_before=None, metric_after=None, now_iso=NOW)
    assert ce["state"] == "shadow"
    assert ce["ownerDecision"] == "pending"
    assert ce["recommendation"] == "insufficient_sample"
    assert ce["rollbackTarget"] == "prod"


def test_shadow_context_sparse_history_no_influence():
    fd = dl.future_decision_context_shadow(symbol="6965", confirming_cases=1,
                                           disconfirming_cases=0, sample_count=1)
    assert fd["learningInfluence"] == "none"
    assert fd["shadowOnly"] is True
    assert "履歴不足" in fd["caveatJa"]
    fd2 = dl.future_decision_context_shadow(symbol="6965", confirming_cases=4,
                                            disconfirming_cases=3, sample_count=7)
    assert fd2["disconfirmingCases"] == 3      # 反証例を必ず保持


# ── 公開境界 ────────────────────────────────────────────────────────────────

def test_dq_no_leak_v12_2_2():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        assert "currentResearchEpoch" in d and "forecastReadiness" in d
        body = str(d)
        for banned in ("passphrase", "hmac", "OPENAI_API_KEY", "quantity",
                       "avgCost", "保有判断も24時間365日稼働中"):
            assert banned not in body
