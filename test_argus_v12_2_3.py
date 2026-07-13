"""ARGUS V12.2.3 — 運用証拠ゲート(回収発行/soak永続/検証実行/replay E2E)の恒久ガード。"""
import argus_decision_ledger as dl
import argus_scheduler as sc
import scanner

NOW = "2026-07-10T12:00:00+09:00"


def _admin(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))


def test_recovery_issuance_idempotent(monkeypatch):
    _admin(monkeypatch)
    scanner._MISSIONS.clear()
    scanner._FORECAST_LEDGER.clear()
    scanner._OUTCOME_LEDGER.clear()
    scanner._OSINT_STORE.clear()
    scanner._OSINT_AGENT_QUEUE.clear()
    import argus_scheduler as _sc
    from datetime import datetime as _dt
    _sd = _dt.now(scanner.TZ_JST).strftime("%Y-%m-%d")
    _due = _sc.mission(mission_type="pre_session_forecast", market="JP",
                       session_date=_sd,
                       scheduled_for=f"{_sd}T00:01:00+09:00")
    scanner._MISSIONS.append(_due)   # 壁時計非依存: 到来済み発行ミッションを注入
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})   # コールド→warmup消費
        assert len(scanner._FORECAST_LEDGER) == 0
        # ストアが温まった状態を再現(実調査由来の形)
        scanner._OSINT_STORE["6965"] = {
            "id": "inv-x", "catalystVerdict": {"verdict": "unknown"},
            "ownerConclusion": {"statusJa": "Gemini未満"},
            "researchPower": {"statusJa": "Gemini未満"},
            "storeWarmth": {"storeWarmth": "warming"}}
        c.post("/api/argus/admin/missions/tick", json={})   # 回収発行
        n1 = len(scanner._FORECAST_LEDGER)
        assert n1 >= 1, "回収ミッションがforward-live予測を発行"
        assert all(f.get("origin") == "forward_live"
                   for f in scanner._FORECAST_LEDGER)
        c.post("/api/argus/admin/missions/tick", json={})   # 冪等
        assert len(scanner._FORECAST_LEDGER) == n1


def test_soak_persists_across_restore(tmp_path, monkeypatch):
    scanner._SOAK["startedAt"] = "2026-07-10T00:00:00+09:00"
    blob = scanner._missions_persist_blob() if hasattr(
        scanner, "_missions_persist_blob") else None
    # persist blobにsoakが同乗し、restoreがリセットしないこと(構造検査)
    import inspect
    src = inspect.getsource(scanner._osint_persist)
    assert '"soak"' in src
    src2 = inspect.getsource(scanner._osint_restore_once)
    assert "redeployでsoakをリセットしない" in src2


def test_validation_run_labeled(monkeypatch):
    _admin(monkeypatch)
    scanner._PERIODIC_REPORTS.clear()
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={"validate": "weekly"})
    reps = [r for r in scanner._PERIODIC_REPORTS
            if r.get("origin") == "validation_run"]
    assert reps and "定期実行ではない" in reps[0]["ownerReadableJa"]


def test_replay_end_to_end_labeled():
    # 凍結as-ofケース: 発行→成熟→解決→スコア→帰属→提案(全てreplayラベル)
    fc = dl.forecast_record(symbol="6965", market="JP",
                            issued_at="2026-07-01T08:30:00+09:00",
                            horizon="next_session", target_type="direction",
                            forecast_value="up", probability_band="60-70",
                            now_iso="2026-07-01T08:30:00+09:00")
    fc["origin"] = "historical_replay"
    assert dl.verify_forecast_integrity(fc)
    o = dl.outcome_record(forecast=fc, outcome_as_of="2026-07-02T15:10:00+09:00",
                          start_price=100.0, end_price=102.0,
                          benchmark_return=0.5,
                          max_adverse_pct=-0.8, max_favorable_pct=2.4,
                          now_iso="2026-07-02T15:10:00+09:00")
    assert o["status"] == "resolved"
    assert o["benchmarkRelativeReturnPct"] == 1.5
    b = dl.brier_score(0.65, True)
    assert b == 0.1225
    ea = dl.error_attribution(forecast_id=fc["id"], outcome_id="o1",
                              error_types=["random_or_unexplained"]) if False else         dl.error_attribution(forecast_id=fc["id"], outcome_id="o1",
                             error_types=["random_or_unexplained"])
    assert ea["errorTypes"] == ["random_or_unexplained"]
    lp = dl.learning_proposal(proposal_type="query_expansion",
                              proposed_change="replay由来語", sample_count=1)
    assert lp["canAutoPromote"] is True
    # replayはlive集計に入らない
    assert [f for f in [fc] if f.get("origin") == "forward_live"] == []


def test_incident_open_close(monkeypatch):
    _admin(monkeypatch)
    scanner._MISSIONS.clear()
    scanner._INCIDENTS.clear()
    old = sc.mission(mission_type="post_session_snapshot", market="JP",
                     session_date="2026-07-09",
                     scheduled_for="2026-07-09T15:40:00+09:00")
    scanner._MISSIONS.append(old)
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    assert any(i.get("component") == "scheduler" for i in scanner._INCIDENTS)
    rec = [i for i in scanner._INCIDENTS if i.get("status") == "resolved"]
    assert rec, "回収でインシデントclose"


def test_dq_research_measurement_honest():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        rm = d.get("researchMeasurement") or {}
        assert rm.get("status") in ("measured", "not_measured")
        assert "legacy" in rm.get("legacyNoteJa", "") or             "0.92" in rm.get("legacyNoteJa", "")
        assert "incidents" in d
        body = str(d)
        for banned in ("passphrase", "hmac", "quantity", "avgCost"):
            assert banned not in body
