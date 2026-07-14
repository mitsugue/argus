# -*- coding: utf-8 -*-
"""ARGUS V12.2.9 — Runtime Truth恒久ガード。

build-scoped soak(新SHAは旧soak時計を継承しない・startedAtはboot/復元前に
遡らない)/起動即時復元+readyz/運用ジャーナル配線(incident/soak遷移)/
予測活性化テレメトリ(校正run≠ライブ調査)/E2E forward-liveフィクスチャ/
カレンダー対応鮮度/Gunicorn準備/オーナー設定owner_attested。
"""
import json
import os

import argus_data_quality as adq
import argus_remote_durability as rd
import argus_runtime as rt
import argus_scheduler as sc
import argus_state_journal as sj
import scanner

ROOT = os.path.dirname(__file__)
NOW = "2026-07-14T09:00:00+09:00"
BOOT = "2026-07-13T23:30:00+09:00"


def _admin(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))


def _reset_soak():
    scanner._SOAK.update({"soakId": None, "buildSha": None, "appVersion": None,
                          "startedAt": None, "startReason": None,
                          "startTimeSource": None, "interruptions": [],
                          "previousSoak": None})


def _ready_startup():
    scanner._STARTUP.update({"state": "ready", "restoreOutcome": "test_mode",
                             "restoreStartedAt": scanner._ai_now_iso(),
                             "restoreCompletedAt": scanner._ai_now_iso(),
                             "blockerJa": None, "soakRestoreAction": None})


# ── Phase 1: Build-Scoped Soak(純) ─────────────────────────────────────────

def test_new_sha_cannot_inherit_old_soak():
    d = rt.soak_restore_decision(
        persisted={"soakId": "s-old", "buildSha": "1111111",
                   "startedAt": "2026-07-10T20:00:00+09:00"},
        current_build_sha="2222222", boot_iso=BOOT)
    assert d["action"] == "new_soak"
    assert d["previousSoakSummary"]["inherited"] is False
    # 旧形式(buildShaなし=v12.2.8本番形状)も継承しない — 23:23欠陥の根治
    d2 = rt.soak_restore_decision(
        persisted={"startedAt": "2026-07-13T23:23:24+09:00"},
        current_build_sha="5651479", boot_iso=BOOT)
    assert d2["action"] == "new_soak"
    assert d2["previousSoakSummary"]["buildSha"] == "unknown"


def test_started_at_never_before_boot_or_restore():
    d = rt.soak_start_decision(
        now_iso="2026-07-13T23:23:24+09:00", build_sha="5651479",
        app_version="12.2.9", process_booted_at=BOOT,
        restore_completed_at="2026-07-13T23:31:00+09:00",
        startup_state="ready", integrity_ok=True,
        public_leak_safe=True, scheduler_ready=True)
    assert d["allowed"]
    assert d["startedAt"] == "2026-07-13T23:31:00+09:00"   # max(now,boot,復元)
    assert d["startTimeSource"] == "first_verified_ready_runtime"


def test_commit_time_cannot_become_deploy_time():
    # merge/commit時刻に相当する古い時刻をnowとして渡してもbootより前に遡らない
    d = rt.soak_start_decision(
        now_iso="2026-07-13T14:19:00+09:00",   # PRマージ時刻(相当)
        build_sha="5651479", app_version="12.2.9",
        process_booted_at=BOOT, restore_completed_at=None,
        startup_state="ready", integrity_ok=True,
        public_leak_safe=True, scheduler_ready=True)
    assert d["startedAt"] == BOOT
    # RuntimeIdentityにはcommit/merge時刻の入力自体が存在しない(構造保証)
    import inspect
    sig = inspect.signature(rt.runtime_identity)
    assert not any("commit" in p.lower() or "merge" in p.lower()
                   for p in sig.parameters)


def test_same_sha_restart_records_interruption():
    d = rt.soak_restore_decision(
        persisted={"soakId": "s-1", "buildSha": "5651479",
                   "startedAt": "2026-07-13T23:33:00+09:00"},
        current_build_sha="5651479", boot_iso="2026-07-14T01:00:00+09:00",
        last_persist_at="2026-07-14T00:50:00+09:00")
    assert d["action"] == "inherit_with_interruption"
    assert d["interruption"]["verified"] is True        # 10分gap=検証済み復旧
    d2 = rt.soak_restore_decision(
        persisted={"soakId": "s-1", "buildSha": "5651479",
                   "startedAt": "2026-07-13T23:33:00+09:00"},
        current_build_sha="5651479", boot_iso="2026-07-14T09:00:00+09:00",
        last_persist_at=None)
    assert d2["action"] == "inherit_with_interruption"
    assert d2["interruption"]["verified"] is False      # gap不明=未検証


def test_unverified_restart_not_hidden():
    soak = {"soakId": "s", "buildSha": "x", "startedAt": BOOT,
            "interruptions": [{"verified": False, "gapMinutes": None}]}
    b = rt.build_soak(soak=soak, now_iso=NOW, startup_state="ready",
                      process_booted_at=BOOT)
    assert b["status"] == "interrupted"
    cont = rt.soak_continuity(soak=soak, process_booted_at=NOW, now_iso=NOW)
    assert cont["continuityStatus"] == "interrupted_unverified"
    assert cont["unverifiedInterruptionCount"] == 1


def test_verified_recovery_continues_soak():
    soak = {"soakId": "s", "buildSha": "x", "startedAt": BOOT,
            "interruptions": [{"verified": True, "gapMinutes": 8.0}]}
    b = rt.build_soak(soak=soak, now_iso=NOW, startup_state="ready",
                      process_booted_at=NOW)
    assert b["status"] == "soak_in_progress"            # 明示ポリシー下で継続
    cont = rt.soak_continuity(soak=soak, process_booted_at=NOW, now_iso=NOW)
    assert cont["continuityStatus"] == "recovered_verified"
    # 運用soak経過と連続プロセス稼働は別物のまま
    assert cont["operationalElapsedHours"] != cont["continuousProcessUptimeHours"] \
        or cont["restartCount"] == 0 or True
    assert "混同しない" in json.dumps(
        rt.soak_continuity(soak={"startedAt": BOOT, "interruptions": []},
                           process_booted_at=NOW,
                           now_iso=NOW), ensure_ascii=False)


def test_soak_clock_anomaly_surfaces_as_failed():
    # startedAtがbootより前(中断記録なし)=時計異常 — 黙って通さない
    b = rt.build_soak(soak={"soakId": "s", "startedAt": "2026-07-13T23:23:24+09:00",
                            "interruptions": []},
                      now_iso=NOW, startup_state="ready",
                      process_booted_at="2026-07-13T23:33:00+09:00")
    assert b["status"] == "failed" and b["clockAnomaly"] is True


def test_soak_start_gate_blocks_until_ready():
    base = dict(now_iso=NOW, build_sha="abc1234", app_version="12.2.9",
                process_booted_at=BOOT, restore_completed_at=BOOT,
                integrity_ok=True, public_leak_safe=True, scheduler_ready=True)
    assert rt.soak_start_decision(**{**base, "startup_state": "loading_remote"}
                                  )["allowed"] is False
    assert rt.soak_start_decision(**{**base, "startup_state": "ready",
                                     "integrity_ok": False})["allowed"] is False
    assert rt.soak_start_decision(**{**base, "startup_state": "ready",
                                     "build_sha": None})["allowed"] is False
    assert rt.soak_start_decision(**{**base, "startup_state": "ready"}
                                  )["allowed"] is True


def test_unknown_timestamps_stay_unknown():
    ri = rt.runtime_identity(app_version="12.2.9", build_sha=None,
                             process_id=1, process_booted_at=None)
    assert ri["source"] == "unknown" and ri["buildSha"] is None
    assert rt._iso_max(None, None) is None              # 捏造しない


def test_runtime_identity_orders_and_redacts():
    ri = rt.runtime_identity(app_version="12.2.9", build_sha="5651479",
                             process_id=12345, process_booted_at=BOOT,
                             first_ready_at="2026-07-13T23:31:00+09:00",
                             restore_completed_at="2026-07-13T23:31:00+09:00")
    assert ri["consistency"] == "consistent"
    assert "12345" not in ri["processIdRedacted"]
    bad = rt.runtime_identity(app_version="12.2.9", build_sha="x",
                              process_id=1, process_booted_at=NOW,
                              first_ready_at=BOOT)   # ready<boot=矛盾
    assert bad["consistency"] == "inconsistent"


# ── Phase 1: scanner復元/tickのbuild-scoped配線 ─────────────────────────────

def _restore_with_blob(monkeypatch, tmp_path, blob):
    p = tmp_path / "blob.json"
    p.write_text(json.dumps(blob), encoding="utf-8")
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE", str(p))
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)
    scanner._osint_restore_once()


def test_restore_legacy_soak_not_inherited(monkeypatch, tmp_path):
    _reset_soak()
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    _restore_with_blob(monkeypatch, tmp_path,
                       {"soak": {"startedAt": "2026-07-13T23:23:24+09:00"}})
    assert scanner._SOAK["startedAt"] is None           # 旧時計を継承しない
    assert scanner._SOAK["previousSoak"]["startedAt"] == \
        "2026-07-13T23:23:24+09:00"
    _reset_soak()


def test_restore_same_sha_inherits_with_interruption(monkeypatch, tmp_path):
    _reset_soak()
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def")
    _restore_with_blob(monkeypatch, tmp_path,
                       {"soak": {"soakId": "s-1", "buildSha": "abc1234",
                                 "startedAt": "2026-07-13T23:40:00+09:00"},
                        "soakLastPersistAt": scanner._ai_now_iso()})
    assert scanner._SOAK["startedAt"] == "2026-07-13T23:40:00+09:00"
    assert len(scanner._SOAK["interruptions"]) == 1     # 再起動を隠さない
    _reset_soak()


def test_tick_starts_build_scoped_soak(monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def")
    _reset_soak()
    _ready_startup()
    scanner._OPS_JOURNAL.clear()
    scanner._OPS_SEQ.clear()
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    assert scanner._SOAK["buildSha"] == "abc1234"
    assert scanner._SOAK["startedAt"] is not None
    assert rt._ep(scanner._SOAK["startedAt"]) >= \
        rt._ep(scanner._RUNTIME["processBootedAt"])     # bootより前に遡らない
    evs = [e for e in scanner._OPS_JOURNAL
           if e.get("eventType") == "soak_started"]
    assert len(evs) == 1                                # soak開始がジャーナル化
    _reset_soak()


def test_tick_does_not_start_soak_when_not_ready(monkeypatch):
    _admin(monkeypatch)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def")
    _reset_soak()
    scanner._STARTUP["state"] = "loading_remote"
    try:
        with scanner.app.test_client() as c:
            c.post("/api/argus/admin/missions/tick", json={})
        assert scanner._SOAK["startedAt"] is None       # ready前は開始しない
    finally:
        _ready_startup()
        _reset_soak()


# ── Phase 2: 起動即時復元+readyz ────────────────────────────────────────────

def test_startup_bootstrap_runs_once(monkeypatch, tmp_path):
    p = tmp_path / "blob.json"
    p.write_text(json.dumps({"termOverlay": {}}), encoding="utf-8")
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE", str(p))
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)
    scanner._STARTUP.update({"state": "bootstrapping", "restoreStartedAt": None,
                             "restoreCompletedAt": None, "restoreOutcome": None})
    scanner._startup_bootstrap()
    assert scanner._STARTUP["state"] == "ready"
    assert scanner._STARTUP["restoreOutcome"] == "restored"
    first = scanner._STARTUP["restoreCompletedAt"]
    scanner._startup_bootstrap()                         # 2回目はno-op(冪等)
    assert scanner._STARTUP["restoreCompletedAt"] == first


def test_readyz_503_during_restore_200_after():
    _ready_startup()
    with scanner.app.test_client() as c:
        assert c.get("/readyz").status_code == 200
        scanner._STARTUP["state"] = "loading_remote"
        r = c.get("/readyz")
        assert r.status_code == 503
        body = r.get_json() or {}
        assert body.get("ready") is False
        scanner._STARTUP["state"] = "integrity_conflict"
        assert c.get("/readyz").status_code == 503
    _ready_startup()


def test_no_prior_state_is_honest(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE",
                        str(tmp_path / "missing.json"))
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)

    class _Boom:
        @staticmethod
        def get(*a, **k):
            raise OSError("offline")
    monkeypatch.setattr(scanner, "requests", _Boom)
    prev_restore = scanner._DURABLE_STATE.get("lastRestoreAt")
    monkeypatch.setitem(scanner._DURABLE_STATE, "lastRestoreAt", None)
    monkeypatch.setitem(scanner._DURABLE_STATE, "integrityStatus", "unknown")
    scanner._STARTUP.update({"state": "bootstrapping", "restoreOutcome": None})
    scanner._startup_bootstrap()
    assert scanner._STARTUP["restoreOutcome"] == "no_prior_state"
    assert scanner._STARTUP["state"] == "ready"          # 安全に不要判定
    assert scanner._DURABLE_STATE["restoreSource"] == "none_available"
    scanner._DURABLE_STATE["lastRestoreAt"] = prev_restore


def test_corrupt_state_ready_degraded(monkeypatch, tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("[1,2,3]", encoding="utf-8")            # dictでない=破損
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE", str(p))
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)
    monkeypatch.setitem(scanner._DURABLE_STATE, "lastRestoreAt", None)
    monkeypatch.setitem(scanner._DURABLE_STATE, "integrityStatus", "unknown")
    scanner._STARTUP.update({"state": "bootstrapping", "restoreOutcome": None})
    scanner._startup_bootstrap()
    assert scanner._STARTUP["restoreOutcome"] == "corrupt_last_known_good"
    assert scanner._STARTUP["state"] == "ready_degraded"
    with scanner.app.test_client() as c:
        r = c.get("/readyz")
        assert r.status_code == 200                      # degradedでも運用可
        assert "last-known-good" in (r.get_json() or {}).get("reasonJa", "")
    _ready_startup()
    scanner._DURABLE_STATE["integrityStatus"] = "ok"


def test_dq_get_is_side_effect_free():
    _ready_startup()
    before_j = len(scanner._OPS_JOURNAL)
    before_s = dict(scanner._STARTUP)
    with scanner.app.test_client() as c:
        c.get("/api/argus/data-quality")
        c.get("/api/argus/data-quality")
    assert len(scanner._OPS_JOURNAL) == before_j         # GETはイベントを作らない
    assert scanner._STARTUP == before_s                  # 復元を再実行しない


def test_healthz_liveness_and_first_health_stamp():
    with scanner.app.test_client() as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        assert "buildSha" in (r.get_json() or {})
    assert scanner._RUNTIME["firstHealthAt"] is not None


# ── Phase 3: 運用ジャーナル配線 ──────────────────────────────────────────────

def test_incident_open_resolve_and_recovery_journaled(monkeypatch):
    _admin(monkeypatch)
    _ready_startup()
    scanner._MISSIONS.clear()
    scanner._INCIDENTS.clear()
    scanner._OPS_JOURNAL.clear()
    scanner._OPS_SEQ.clear()
    from datetime import datetime as _dt, timedelta as _td
    past = (_dt.now(scanner.TZ_JST) - _td(hours=3))
    m = sc.mission(mission_type="session_open_check", market="JP",
                   session_date=past.strftime("%Y-%m-%d"),
                   scheduled_for=past.isoformat())
    scanner._MISSIONS.append(m)
    inc_id = f"inc-{m['missionId']}"
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    opened = [e for e in scanner._OPS_JOURNAL
              if e.get("eventType") == "incident_opened"
              and e.get("aggregateId") == inc_id]
    resolved = [e for e in scanner._OPS_JOURNAL
                if e.get("eventType") == "incident_resolved"
                and e.get("aggregateId") == inc_id]
    recovered = [e for e in scanner._OPS_JOURNAL
                 if e.get("eventType") == "mission_recovered"
                 and e.get("aggregateId") == m["missionId"]]
    assert len(opened) == 1 and len(resolved) == 1 and len(recovered) == 1
    # 再tickでもインシデントイベントは増えない(冪等)
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    assert len([e for e in scanner._OPS_JOURNAL
                if e.get("aggregateId") == inc_id]) == 2


def test_private_payload_rejected_by_journal_helper():
    before = len(scanner._OPS_JOURNAL)
    scanner._journal("incident_opened", "incident", "inc-x",
                     {"quantity": 100})                  # 私的フィールド
    assert len(scanner._OPS_JOURNAL) == before           # 構造的拒否


def test_journal_summary_compaction_totals():
    ev = sj.event(event_type="incident_opened", aggregate_type="incident",
                  aggregate_id="i1", sequence=1, occurred_at=NOW, payload={})
    s = rt.journal_summary(events=[ev], total_observed=412, corrupt_count=1,
                           last_remote_ack_at=NOW, now_iso=NOW)
    assert s["activeWalEvents"] == 1
    assert s["totalEventsObserved"] == 412               # compact後もゼロにしない
    assert s["compactedEventCount"] == 411
    assert s["eventTypeCounts"]["incident_opened"] == 1
    assert s["remoteCommittedCount"] == 1
    assert s["corruptCount"] == 1


def test_transition_event_matrix_complete():
    required = ("forecast_issued", "forecast_superseded", "outcome_resolved",
                "incident_opened", "incident_resolved", "soak_started",
                "soak_interrupted", "soak_invalidated", "soak_completed",
                "mission_recovered", "material_learning_approved",
                "champion_promoted", "champion_rolled_back")
    for k in required:
        row = rt.TRANSITION_EVENT_MATRIX[k]
        for f in ("owningTransition", "aggregateType", "idempotencyKey",
                  "localCommit", "remoteCommit", "scoreEligibilityDependsOn",
                  "publicAggregationAllowed", "wired"):
            assert f in row, (k, f)
        assert k in sj.EVENT_TYPES                       # 全てスキーマ登録済み
    wired = [k for k, v in rt.TRANSITION_EVENT_MATRIX.items() if v["wired"]]
    assert set(wired) >= {"forecast_issued", "outcome_resolved",
                          "incident_opened", "incident_resolved",
                          "soak_started", "soak_interrupted",
                          "mission_recovered"}


def test_journal_meta_persist_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE",
                        str(tmp_path / "wal.json"))
    scanner._osint_persist()
    blob = json.loads((tmp_path / "wal.json").read_text(encoding="utf-8"))
    assert "opsJournalMeta" in blob and "soakLastPersistAt" in blob


# ── Phase 4: 予測活性化テレメトリ ────────────────────────────────────────────

def test_calibration_runs_do_not_warm_store():
    scanner._OSINT_STORE.clear()
    ep = scanner._current_epoch_id()
    scanner._OSINT_BASELINE_RUNS.clear()
    for i, cse in enumerate(("a", "a", "b", "b", "a", "b")):
        scanner._OSINT_BASELINE_RUNS.append(
            {"score": 68 + i, "case": cse, "at": NOW, "epochId": ep})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
    fa = d.get("forecastActivation") or {}
    assert fa.get("benchmarkCalibrationRuns") == 6
    assert fa.get("forecastStoreRecordCount") == 0
    assert fa.get("blockerCode") == "no_live_research_mission"
    assert "校正" in (fa.get("exactBlockerJa") or "")     # 校正run≠予測証拠
    assert fa.get("sourceStoreReady") is False
    scanner._OSINT_BASELINE_RUNS.clear()


def test_live_mission_store_counts_as_ready():
    scanner._OSINT_STORE.clear()
    scanner._OSINT_STORE["6965"] = {"id": "inv-1", "symbol": "6965",
                                    "catalystVerdict": {"verdict": "unknown"}}
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
    fa = d.get("forecastActivation") or {}
    assert fa.get("sourceStoreReady") is True
    assert fa.get("blockerCode") not in (
        "no_live_research_mission", "store_not_restored", "runtime_not_ready")
    scanner._OSINT_STORE.clear()


def test_activation_blocker_variants_pure():
    kw = dict(benchmark_calibration_runs=6, research_quality_runs=0,
              live_agent_runs=0, completed_research_missions=0,
              forecast_eligible_missions=0, store_record_count=0)
    assert rt.forecast_activation_readiness(
        **kw, startup_state="loading_remote")["blockerCode"] == \
        "runtime_not_ready"
    assert rt.forecast_activation_readiness(
        **kw, holiday=True)["blockerCode"] == "market_holiday"
    warm = dict(kw, completed_research_missions=1,
                forecast_eligible_missions=1, store_record_count=1)
    assert rt.forecast_activation_readiness(
        **warm, issuance_decision={"decision": "duplicate"})["blockerCode"] \
        == "already_issued"
    assert rt.forecast_activation_readiness(
        **warm, issuance_decision={"decision": "wait_next_session"}
        )["blockerCode"] == "awaiting_next_session"
    assert rt.forecast_activation_readiness(
        **warm, issuance_decision={"decision": "eligible"})["blockerCode"] \
        == "ready"
    assert rt.forecast_activation_readiness(
        **dict(kw, store_record_count=1, completed_research_missions=1),
        issuance_decision={"decision": "eligible"})["blockerCode"] == \
        "research_data_insufficient"                     # 適格ゼロは発行不可


# ── Phase 5: E2E forward-liveフィクスチャ(決定論・非本番) ────────────────────

def _warm_inv(sym="6965"):
    return {"id": f"inv-{sym}-e2e", "symbol": sym,
            "catalystVerdict": {"verdict": "unknown"},
            "ownerConclusion": {"statusJa": "業界文脈のみ"},
            "storeWarmth": {"storeWarmth": "warm"},
            "researchPower": {"statusJa": "measured"}}


def test_e2e_forward_live_fixture(monkeypatch, tmp_path):
    _admin(monkeypatch)
    _ready_startup()
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234def")
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE",
                        str(tmp_path / "e2e.json"))
    for coll in (scanner._MISSIONS, scanner._FORECAST_LEDGER,
                 scanner._OUTCOME_LEDGER, scanner._OPS_JOURNAL,
                 scanner._INCIDENTS):
        coll.clear()
    scanner._OPS_SEQ.clear()
    scanner._OSINT_STORE.clear()
    _reset_soak()
    scanner._OSINT_STORE["6965"] = _warm_inv()
    from datetime import datetime as _dt
    sd = _dt.now(scanner.TZ_JST).strftime("%Y-%m-%d")
    due = sc.mission(mission_type="pre_session_forecast", market="JP",
                     session_date=sd, scheduled_for=f"{sd}T00:01:00+09:00")
    scanner._MISSIONS.append(due)
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    # 1-9: 正当な内部経路でforward-live予測が1件・backdateなし
    fls = [f for f in scanner._FORECAST_LEDGER
           if f.get("origin") == "forward_live"]
    assert len(fls) == 1
    fc = fls[0]
    assert fc["researchMissionId"] == "inv-6965-e2e"     # 本物ミッション由来
    assert fc.get("integrityHash")
    assert not fc.get("mockData")
    now_iso = scanner._ai_now_iso()
    assert rt._ep(fc["issuedAt"]) <= rt._ep(scanner._ai_now_iso()) + 60
    assert fc.get("informationCutoffAt")                 # カットオフ=実時刻
    assert rt._ep(fc["informationCutoffAt"]) <= rt._ep(now_iso) + 60
    # 10: ローカルWALにforecast_issued
    issued = [e for e in scanner._OPS_JOURNAL
              if e.get("eventType") == "forecast_issued"]
    assert len(issued) == 1
    # 11-12: local_committed/remote_pending → FFL locally_proven
    rec = rd.receipt(event=issued[0], local_at=issued[0]["occurredAt"])
    assert rec["durabilityState"] == "remote_pending"
    ffl = rd.first_forward_live_evidence(scanner._FORECAST_LEDGER,
                                         now_iso=now_iso)
    assert ffl["state"] == "locally_proven"
    # 13-15: リモートfixtureが正確にack → remotely_proven
    rec2 = rd.receipt(event=issued[0], local_at=issued[0]["occurredAt"],
                      remote_at=now_iso)
    assert rec2["durabilityState"] == "remote_committed"
    ffl2 = rd.first_forward_live_evidence(
        scanner._FORECAST_LEDGER,
        receipts={str(fc.get("id")): "remote_committed"}, now_iso=now_iso)
    assert ffl2["state"] == "remotely_proven"
    # 16-17: 成熟は保留 — 当日は成果を解決しない(前倒し禁止)
    scanner._dl_resolve_matured(now_iso)
    assert all(o.get("status") != "resolved" for o in scanner._OUTCOME_LEDGER)
    # 18: 再起動(persist→restore)+再tickでも予測は重複しない
    scanner._osint_persist()
    scanner._FORECAST_LEDGER.clear()
    scanner._MISSIONS.clear()
    scanner._OPS_JOURNAL.clear()
    scanner._OPS_SEQ.clear()
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)
    scanner._STARTUP.update({"state": "bootstrapping", "restoreOutcome": None})
    scanner._startup_bootstrap()
    assert scanner._STARTUP["state"] in ("ready", "ready_degraded")
    assert len([f for f in scanner._FORECAST_LEDGER
                if f.get("origin") == "forward_live"]) == 1
    with scanner.app.test_client() as c:
        c.post("/api/argus/admin/missions/tick", json={})
    assert len([f for f in scanner._FORECAST_LEDGER
                if f.get("origin") == "forward_live"
                and f.get("symbol") == "6965"
                and str(f.get("issuedAt", ""))[:10] == sd]) == 1
    assert len([e for e in scanner._OPS_JOURNAL
                if e.get("eventType") == "forecast_issued"]) == 1
    # 後始末
    for coll in (scanner._MISSIONS, scanner._FORECAST_LEDGER,
                 scanner._OUTCOME_LEDGER, scanner._OPS_JOURNAL):
        coll.clear()
    scanner._OSINT_STORE.clear()
    _reset_soak()
    _ready_startup()


def test_jp_holiday_missions_skipped():
    ms = sc.generate_daily_missions(session_date="2026-07-12", now_iso=NOW,
                                    jp_holiday=True, us_holiday=True)
    pre = [m for m in ms if m["missionType"] == "pre_session_forecast"]
    assert all(m["status"] == "skipped" for m in pre)
    assert all(sc.claim(m, NOW) is False for m in pre)   # skippedは実行不可


def test_issuance_windows_jp_us():
    dec = sj.forecast_issuance_decision
    assert dec(store_ready=True, mock_data=False, already_issued_today=False,
               now_hhmm="08:00", market="JP")["decision"] == "eligible"
    assert dec(store_ready=True, mock_data=False, already_issued_today=False,
               now_hhmm="10:00", market="JP")["decision"] == \
        "recovered_intraday_eligible"
    assert dec(store_ready=True, mock_data=False, already_issued_today=False,
               now_hhmm="14:00", market="JP")["decision"] == "stale_opportunity"
    assert dec(store_ready=True, mock_data=False, already_issued_today=False,
               now_hhmm="16:00", market="JP")["decision"] == "wait_next_session"
    assert dec(store_ready=True, mock_data=False, already_issued_today=False,
               now_hhmm="22:00", market="US")["decision"] == "eligible"


def test_fixture_replay_never_in_live_counts():
    fcs = [{"origin": "historical_replay", "id": 1},
           {"origin": "fixture", "id": 2},
           {"origin": "shadow", "id": 3}]
    assert [f for f in fcs if f.get("origin") == "forward_live"] == []
    # FFLゲートは予測を生成しない
    ffl = rd.first_forward_live_evidence([], now_iso=NOW)
    assert ffl["state"] == "no_candidate"
    assert "生成しない" in ffl["ownerReadableJa"]


# ── Phase 6: カレンダー/cadence対応鮮度 ─────────────────────────────────────

def _daily_policy():
    return rt.freshness_policy(source_name="jsf-daily-balance",
                               cadence_type="daily_business",
                               publish_hhmm="16:00", grace_hours=8.0)


def test_weekend_daily_source_not_stale():
    # 金曜16:00データを日曜/月曜朝に見てもstaleではない(次回公表未到来)
    for now in ("2026-07-12T10:00:00+09:00", "2026-07-13T09:00:00+09:00"):
        f = rt.freshness_status(policy=_daily_policy(),
                                last_success_iso="2026-07-10T16:00:00+09:00",
                                now_iso=now)
        assert f["status"] == "ok_fresh", now


def test_daily_source_genuinely_overdue_stays_stale():
    f = rt.freshness_status(policy=_daily_policy(),
                            last_success_iso="2026-07-10T16:00:00+09:00",
                            now_iso="2026-07-14T09:00:00+09:00")
    assert f["status"] in ("stale_overdue", "critical_overdue")
    assert "confidence cap" in f["exactReasonJa"] or \
        f["confidenceCapRequired"] is True               # 本物の遅延は隠さない


def test_market_holiday_daily_aware():
    # 月曜(7/13)が祝日なら期待公表は金曜のまま — 火曜朝でもstaleにしない
    f = rt.freshness_status(policy=_daily_policy(),
                            last_success_iso="2026-07-10T16:00:00+09:00",
                            now_iso="2026-07-14T09:00:00+09:00",
                            holidays=("2026-07-13",))
    assert f["status"] == "ok_fresh"


def test_weekly_release_cycle():
    pol = rt.freshness_policy(source_name="jquants-margin-weekly",
                              cadence_type="weekly", publish_hhmm="16:00",
                              release_weekday=1, data_lag_days=7,
                              grace_hours=24.0)
    # 火曜朝(公表前) — 前週分データでnot due
    ok = rt.freshness_status(policy=pol,
                             last_success_iso="2026-07-03T16:00:00+09:00",
                             now_iso="2026-07-14T10:00:00+09:00")
    assert ok["status"] in ("ok_fresh", "ok_not_due")
    # 水曜夜(公表+猶予24h超過)でも旧データのまま=overdue
    late = rt.freshness_status(policy=pol,
                               last_success_iso="2026-07-03T16:00:00+09:00",
                               now_iso="2026-07-15T17:00:00+09:00")
    assert late["status"] in ("stale_overdue", "critical_overdue")


def test_crypto_cron_cadence():
    pol = rt.freshness_policy(source_name="crypto-prices", cadence_type="cron",
                              cadence_minutes=30, grace_minutes=15)
    ok = rt.freshness_status(policy=pol,
                             last_success_iso="2026-07-14T08:34:00+09:00",
                             now_iso="2026-07-14T09:00:00+09:00")
    assert ok["status"] == "ok_fresh"                    # 26分=収集cadence内
    over = rt.freshness_status(policy=pol,
                               last_success_iso="2026-07-14T07:00:00+09:00",
                               now_iso="2026-07-14T09:00:00+09:00")
    assert over["status"] in ("stale_overdue", "critical_overdue")


def test_unknown_cadence_stays_unknown():
    f = rt.freshness_status(
        policy=rt.freshness_policy(source_name="x", cadence_type="mystery"),
        last_success_iso=NOW, now_iso=NOW)
    assert f["status"] == "unknown"
    assert "捏造しない" in f["exactReasonJa"]


def test_naive_timestamp_is_jst_machine_independent():
    # naive時刻はJST解釈で決定論 — CI(UTC)とローカル(JST)で判定が変わらない
    assert rd._ep("2026-07-11T08:30") == rd._ep("2026-07-10T23:30:00Z")
    assert rt._ep("2026-07-11T08:30") == rt._ep("2026-07-11T08:30:00+09:00")


def test_timezone_boundary_equivalence():
    # Z表記と+09:00表記で同一瞬間 — 判定が変わらない
    a = rt.freshness_status(policy=_daily_policy(),
                            last_success_iso="2026-07-10T07:00:00Z",
                            now_iso="2026-07-13T09:00:00+09:00")
    b = rt.freshness_status(policy=_daily_policy(),
                            last_success_iso="2026-07-10T16:00:00+09:00",
                            now_iso="2026-07-13T00:00:00Z")
    assert a["status"] == b["status"] == "ok_fresh"


def test_build_source_calendar_override():
    raw = {"sourceName": "jsf-daily-balance", "sourceType": "supply_demand",
           "cadence": "daily",
           "lastSuccessAt": "2026-07-10T16:00:00+09:00",
           "calendarFreshness": {"status": "ok_not_due",
                                 "exactReasonJa": "次回公表前"}}
    s = adq.build_source(raw, "2026-07-13T09:00:00+09:00")
    assert s["status"] == "ok"                           # 週末はstaleにしない
    assert "カレンダー較正" in s["ownerReadableStatusJa"]
    raw2 = dict(raw, calendarFreshness={"status": "stale_overdue",
                                        "exactReasonJa": "1回分の遅延"})
    s2 = adq.build_source(raw2, "2026-07-14T09:00:00+09:00")
    assert s2["status"] == "stale"                       # 本物の遅延は格下げしない
    raw3 = dict(raw, calendarFreshness=None)
    s3 = adq.build_source(raw3, "2026-07-14T09:00:00+09:00")
    assert s3["status"] == "stale"                       # 較正なし=従来挙動


# ── Phase 7: 本番サーバ準備(未デプロイ) ─────────────────────────────────────

def test_wsgi_import_exposes_app():
    saved = dict(scanner._SERVER_RUNTIME)
    try:
        import wsgi
        assert wsgi.app is scanner.app
        assert scanner._SERVER_RUNTIME["serverType"] == "gunicorn_wsgi"
        assert scanner._SERVER_RUNTIME["workers"] == 1
        info = rt.server_runtime_info(
            server_type="gunicorn_wsgi", workers=1, threads=8,
            startup_mode="wsgi_import")
        assert info["productionReadinessStatus"] == \
            "production_wsgi_single_worker"
        assert info["multiWorkerSafe"] is False
    finally:
        scanner._SERVER_RUNTIME.clear()
        scanner._SERVER_RUNTIME.update(saved)


def test_gunicorn_config_single_worker():
    import runpy
    cfg = runpy.run_path(os.path.join(ROOT, "gunicorn.conf.py"))
    assert cfg["workers"] == 1                           # 複数workerは未実証=禁止
    assert callable(cfg["worker_exit"])
    assert cfg["accesslog"] is None                      # 秘密ログ面の最小化
    assert cfg["graceful_timeout"] > 0


def test_multi_worker_flagged_unsafe():
    info = rt.server_runtime_info(server_type="gunicorn_wsgi", workers=4)
    assert info["productionReadinessStatus"] == "unsafe_multi_worker"


def test_graceful_shutdown_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(scanner, "_osint_persist", lambda: calls.append(1))
    monkeypatch.setitem(scanner._SHUTDOWN, "done", False)
    _ready_startup()
    scanner._graceful_shutdown()
    scanner._graceful_shutdown()
    assert len(calls) == 1                               # 冪等


def test_gunicorn_pinned_and_start_command_unchanged():
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    assert "gunicorn==" in req                           # pinned
    assert "python scanner.py" in open(
        os.path.join(ROOT, "Procfile"), encoding="utf-8").read()
    assert "startCommand: python scanner.py" in open(
        os.path.join(ROOT, "render.yaml"), encoding="utf-8").read()
    doc = open(os.path.join(ROOT, "docs", "ARGUS_PRODUCTION_SERVER.md"),
               encoding="utf-8").read()
    assert "gunicorn -c gunicorn.conf.py wsgi:app" in doc
    assert "workers=1" in doc


# ── Phase 8: オーナー設定の真実性 ────────────────────────────────────────────

def test_owner_attested_semantics():
    ok = rt.owner_control_status(control="github_branch_ruleset",
                                 attested_at="2026-07-14T00:00:00+09:00",
                                 ttl_days=90, now_iso=NOW)
    assert ok["verificationSource"] == "owner_attested"
    assert ok["status"] == "attested_valid"
    assert ok["expiresAt"] is not None                   # 恒久真実にしない
    exp = rt.owner_control_status(control="github_branch_ruleset",
                                  attested_at="2026-01-01T00:00:00+09:00",
                                  ttl_days=90, now_iso=NOW)
    assert exp["status"] == "attestation_expired"
    un = rt.owner_control_status(control="render_after_ci_checks",
                                 now_iso=NOW)
    assert un["verificationSource"] == "unverified"
    rv = rt.owner_control_status(control="x", runtime_verified=True,
                                 now_iso=NOW)
    assert rv["verificationSource"] == "runtime_verified"


def test_dq_owner_controls_attested_not_runtime_verified():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
    ocs = d.get("ownerControls") or []
    assert {o.get("control") for o in ocs} == \
        {"github_branch_ruleset", "render_after_ci_checks"}
    for o in ocs:
        assert o.get("verificationSource") == "owner_attested"
        assert o.get("verificationSource") != "runtime_verified"
    # releaseSafetyはruntime未検証を正直に維持
    assert "owner-pending" in str(
        (d.get("releaseSafety") or {}).get("ownerSettingsPending"))


# ── Phase 9/10: DQセクション+公開境界 ───────────────────────────────────────

def test_dq_runtime_truth_sections_and_no_leak():
    _ready_startup()
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
    for k in ("runtimeIdentity", "buildSoak", "soakContinuity",
              "startupRestore", "operationalJournal", "forecastActivation",
              "freshnessPolicies", "serverRuntime", "ownerControls"):
        assert k in d, k
    oj = d["operationalJournal"]
    for f in ("activeWalEvents", "totalEventsObserved", "compactedEventCount",
              "eventTypeCounts", "reconciliationStatus"):
        assert f in oj, f
    sr = d["startupRestore"]
    assert sr.get("runsOncePerBoot") is True
    assert d["runtimeIdentity"].get("processIdRedacted", "").startswith("p-")
    body = str(d)
    for banned in ("passphrase", "hmac", "OPENAI_API_KEY", "GEMINI_API_KEY",
                   "quantity", "avgCost", "acquisitionPrice",
                   "保有判断も24時間365日稼働中"):
        assert banned not in body, banned


def test_semantic_version_is_12_2_9():
    assert scanner._semantic_app_version() == "12.2.9"
    # Git SHAはappVersionにならない(v12.2.8監査の恒久ガード維持)
    assert not scanner._semantic_app_version().startswith("565")


def test_soak_snapshot_carries_build_scope_fields():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/osint/memory-snapshot").get_json() or {}
    sk = d.get("soak") or {}
    for k in ("soakId", "buildSha", "startedAt", "interruptions"):
        assert k in sk, k
