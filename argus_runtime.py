# -*- coding: utf-8 -*-
"""ARGUS Runtime Truth — v12.2.9(純・stdlibのみ)。

Build-scoped soak / 起動復元ライフサイクル / 運用ジャーナル可観測性 /
予測活性化テレメトリ / カレンダー対応鮮度 / 本番サーバ・オーナー設定の真実性。

原則: デプロイ時刻・soak時刻・検証状態を捏造しない(不明はunknownのまま)。
Gitのcommit/merge時刻はデプロイ時刻ではない。Render Deploy liveの正確な時刻が
取得できない場合は「そのSHAで最初に検証されたhealthy-ready実行時刻」を使い、
時刻ソースを正直にラベルする。
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

JST = timezone(timedelta(hours=9))


def _ep(iso: Optional[str]) -> Optional[float]:
    """naive時刻はJSTとして解釈(ARGUS慣行) — 実行マシンTZ非依存の決定論。"""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=JST)
        return d.timestamp()
    except Exception:
        return None


def _iso_max(*isos: Optional[str]) -> Optional[str]:
    """epoch比較で最大のISOを返す(文字列比較はTZ混在で誤るため使わない)。"""
    best, best_ep = None, None
    for s in isos:
        e = _ep(s)
        if e is not None and (best_ep is None or e > best_ep):
            best, best_ep = s, e
    return best


def _hours_between(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ea, eb = _ep(a), _ep(b)
    if ea is None or eb is None:
        return None
    return round((eb - ea) / 3600.0, 2)


# ── Phase 1: Runtime Identity ────────────────────────────────────────────────

RUNTIME_TIME_SOURCES = ("first_verified_ready", "process_boot", "unknown")


def runtime_identity(*, app_version: str, build_sha: Optional[str],
                     process_id: Any, process_booted_at: Optional[str],
                     first_health_at: Optional[str] = None,
                     first_ready_at: Optional[str] = None,
                     restore_started_at: Optional[str] = None,
                     restore_completed_at: Optional[str] = None,
                     build_first_observed_at: Optional[str] = None
                     ) -> Dict[str, Any]:
    """実行時アイデンティティ。commit/merge時刻は入力に存在しない(構造的に
    デプロイ時刻へ化けない)。時系列矛盾はinconsistentとして正直に出す。"""
    source = ("first_verified_ready" if first_ready_at else
              "process_boot" if process_booted_at else "unknown")
    issues: List[str] = []
    chain = [("processBootedAt", process_booted_at),
             ("restoreStartedAt", restore_started_at),
             ("restoreCompletedAt", restore_completed_at),
             ("firstReadyAt", first_ready_at)]
    prev_name, prev_ep = None, None
    for name, val in chain:
        e = _ep(val)
        if e is None:
            continue
        if prev_ep is not None and e < prev_ep - 1:
            issues.append(f"{name}<{prev_name}")
        prev_name, prev_ep = name, e
    if _ep(first_health_at) is not None and _ep(process_booted_at) is not None \
            and _ep(first_health_at) < _ep(process_booted_at) - 1:
        issues.append("firstHealthAt<processBootedAt")
    pid_red = hashlib.sha256(str(process_id).encode()).hexdigest()[:8]
    consistency = "consistent" if not issues else "inconsistent"
    return {"appVersion": app_version or "unknown",
            "buildSha": build_sha or None,
            "processIdRedacted": f"p-{pid_red}",
            "processBootedAt": process_booted_at,
            "firstHealthAt": first_health_at,
            "firstReadyAt": first_ready_at,
            "restoreStartedAt": restore_started_at,
            "restoreCompletedAt": restore_completed_at,
            "buildFirstObservedAt": build_first_observed_at,
            "source": source, "consistency": consistency,
            "consistencyIssues": issues,
            "ownerReadableJa": (
                f"build {build_sha or '不明'} / boot {str(process_booted_at)[:19]}"
                + ("(時系列整合)" if consistency == "consistent"
                   else f"(時系列矛盾: {','.join(issues)})"))}


# ── Phase 1: Build-Scoped Soak ───────────────────────────────────────────────

BUILD_SOAK_STATUSES = ("not_started", "bootstrapping", "restoring",
                       "soak_in_progress", "interrupted", "degraded",
                       "operationally_verified", "failed")


def soak_start_decision(*, now_iso: str, build_sha: Optional[str],
                        app_version: str,
                        process_booted_at: Optional[str],
                        restore_completed_at: Optional[str],
                        startup_state: str, integrity_ok: bool,
                        public_leak_safe: bool,
                        scheduler_ready: bool) -> Dict[str, Any]:
    """soak開始ゲート。前提(build識別/復元完了/整合ok/leak-safe/scheduler ready)
    未達なら開始しない。startedAtは now/boot/復元完了 の最大 — bootや復元より
    前の開始時刻は構造的に不可能。commit/merge時刻は入力に存在しない。"""
    blockers = []
    if not build_sha:
        blockers.append("build_identity_unknown")
    if startup_state not in ("ready", "ready_degraded"):
        blockers.append("startup_not_ready")
    if not integrity_ok:
        blockers.append("durability_integrity_not_ok")
    if not public_leak_safe:
        blockers.append("public_leak_gate")
    if not scheduler_ready:
        blockers.append("scheduler_not_ready")
    if blockers:
        return {"allowed": False, "blockers": blockers, "startedAt": None,
                "ownerReadableJa": "soak開始条件未達: " + ",".join(blockers)}
    started = _iso_max(now_iso, process_booted_at, restore_completed_at)
    return {"allowed": True, "blockers": [], "startedAt": started,
            "startReason": "runtime_ready_first_tick",
            "startTimeSource": "first_verified_ready_runtime",
            "ownerReadableJa": ("build稼働・復元完了を確認した最初のtickで開始"
                                "(デプロイ時刻の捏造なし・boot/復元前に遡らない)")}


def soak_restore_decision(*, persisted: Any, current_build_sha: Optional[str],
                          boot_iso: str,
                          last_persist_at: Optional[str] = None,
                          max_verified_gap_min: float = 45.0) -> Dict[str, Any]:
    """復元snapshot内のsoakをどう扱うか。
    ①同一build SHA → 時計を継承+中断(interruption)として記録(隠さない)。
    ②別SHA/不明SHA → 継承しない(新buildは旧buildのsoak時計を相続できない)。"""
    if not isinstance(persisted, dict) or not persisted.get("startedAt"):
        return {"action": "ignore", "ownerReadableJa": "復元soakなし"}
    p_sha = persisted.get("buildSha")
    if p_sha and current_build_sha and p_sha == current_build_sha:
        gap_min = None
        ea, eb = _ep(last_persist_at), _ep(boot_iso)
        if ea is not None and eb is not None:
            gap_min = round(abs(eb - ea) / 60.0, 1)
        verified = gap_min is not None and gap_min <= max_verified_gap_min
        return {"action": "inherit_with_interruption",
                "interruption": {"type": "process_restart_same_build",
                                 "detectedAt": boot_iso,
                                 "lastPersistAt": last_persist_at,
                                 "gapMinutes": gap_min,
                                 "verified": verified},
                "ownerReadableJa": ("同一SHA再起動 — soak継続+中断を記録"
                                    + ("(検証済み復旧)" if verified
                                       else "(未検証中断 — 隠さない)"))}
    return {"action": "new_soak",
            "previousSoakSummary": {"soakId": persisted.get("soakId"),
                                    "buildSha": p_sha or "unknown",
                                    "startedAt": persisted.get("startedAt"),
                                    "inherited": False},
            "ownerReadableJa": ("build SHAが異なる/不明 — 旧soak時計を継承しない"
                                "(build-scoped soak)")}


def build_soak(*, soak: Dict[str, Any], now_iso: str, startup_state: str,
               process_booted_at: Optional[str] = None,
               ops_missed: int = 0, ops_failed_safe: int = 0,
               unresolved_critical_incidents: int = 0,
               durability_integrity: str = "unknown",
               required_hours: int = 72) -> Dict[str, Any]:
    """BuildSoakビュー(集計・純)。時計異常(startedAt<boot)はfailedとして
    正直に表面化する(黙って通さない)。"""
    started = soak.get("startedAt")
    interruptions = list(soak.get("interruptions") or [])
    unverified = [i for i in interruptions if not i.get("verified")]
    elapsed = _hours_between(started, now_iso) if started else 0.0
    clock_anomaly = (started is not None and process_booted_at is not None
                     and _ep(started) is not None
                     and _ep(process_booted_at) is not None
                     and _ep(started) < _ep(process_booted_at) - 1
                     and not interruptions)
    if not started:
        if startup_state in ("loading_local", "loading_remote", "reconciling"):
            status = "restoring"
        elif startup_state == "bootstrapping":
            status = "bootstrapping"
        elif startup_state in ("integrity_conflict", "failed_safe"):
            status = "failed"
        else:
            status = "not_started"
    elif clock_anomaly:
        status = "failed"
    elif int(ops_missed) > 2 or int(ops_failed_safe) > 3 \
            or int(unresolved_critical_incidents) > 0 \
            or durability_integrity in ("write_failed", "corrupt_ignored"):
        status = "degraded"
    elif unverified:
        status = "interrupted"
    elif elapsed is not None and elapsed >= required_hours:
        status = "operationally_verified"
    else:
        status = "soak_in_progress"
    gaps = [i.get("gapMinutes") for i in interruptions
            if i.get("gapMinutes") is not None]
    ja = {"not_started": "soak未開始(開始条件待ち)",
          "bootstrapping": "起動処理中 — soak未開始",
          "restoring": "状態復元中 — soak未開始",
          "soak_in_progress": (f"build-scoped soak進行中"
                               f"({elapsed or 0}h/{required_hours}h)"),
          "interrupted": "未検証の中断あり — 無中断稼働とは主張しない",
          "degraded": "見逃し/失敗/整合性が閾値超過 — degraded",
          "operationally_verified": f"{required_hours}h soak完了(このbuild)",
          "failed": ("soak時計異常(startedAt<processBootedAt) — "
                     "このsoakを信頼しない" if clock_anomaly
                     else "起動失敗状態 — soak不可")}[status]
    return {"soakId": soak.get("soakId"),
            "buildSha": soak.get("buildSha"),
            "appVersion": soak.get("appVersion"),
            "processBootedAt": process_booted_at,
            "restoreCompletedAt": soak.get("restoreCompletedAt"),
            "startedAt": started,
            "requiredHours": required_hours,
            "elapsedHours": elapsed if started else 0,
            "status": status,
            "startReason": soak.get("startReason"),
            "startTimeSource": soak.get("startTimeSource"),
            "continuityInterruptions": interruptions,
            "maximumObservedInterruptionSec": (int(max(gaps) * 60)
                                               if gaps else None),
            "missed": int(ops_missed), "failedSafe": int(ops_failed_safe),
            "unresolvedCriticalIncidents": int(unresolved_critical_incidents),
            "durabilityIntegrity": durability_integrity,
            "clockAnomaly": bool(clock_anomaly),
            "previousSoak": soak.get("previousSoak"),
            "ownerReadableJa": ja}


def soak_continuity(*, soak: Dict[str, Any], process_booted_at: Optional[str],
                    now_iso: str) -> Dict[str, Any]:
    """運用soak経過と連続プロセス稼働時間を分離(混同しない)。"""
    started = soak.get("startedAt")
    interruptions = list(soak.get("interruptions") or [])
    verified = sum(1 for i in interruptions if i.get("verified"))
    unverified = len(interruptions) - verified
    gaps = [i.get("gapMinutes") for i in interruptions
            if i.get("gapMinutes") is not None]
    op_h = _hours_between(started, now_iso) if started else 0.0
    up_h = _hours_between(process_booted_at, now_iso)
    status = ("no_soak" if not started else
              "continuous" if not interruptions else
              "recovered_verified" if unverified == 0 else
              "interrupted_unverified")
    return {"operationalElapsedHours": op_h if started else 0,
            "continuousProcessUptimeHours": up_h,
            "restartCount": len(interruptions),
            "verifiedRecoveryCount": verified,
            "unverifiedInterruptionCount": unverified,
            "maximumInterruptionSec": int(max(gaps) * 60) if gaps else None,
            "continuityStatus": status,
            "ownerReadableJa": {
                "no_soak": "soak未開始",
                "continuous": (f"無中断: 運用{op_h or 0}h/プロセス連続{up_h or 0}h"
                               "(別concept — 混同しない)"),
                "recovered_verified": (f"再起動{len(interruptions)}回(全て検証済み"
                                       f"復旧) — 運用soak {op_h or 0}h継続"),
                "interrupted_unverified": (f"未検証中断{unverified}回 — "
                                           "無中断稼働とは主張しない"),
            }[status]}


# ── Phase 2: Startup Lifecycle / readyz ─────────────────────────────────────

STARTUP_STATES = ("bootstrapping", "loading_local", "loading_remote",
                  "reconciling", "ready", "ready_degraded",
                  "integrity_conflict", "failed_safe")
RESTORE_OUTCOMES = ("restored", "no_prior_state", "corrupt_last_known_good",
                    "test_mode")


def readyz_view(*, startup_state: str, app_version: str = "",
                build_sha: Optional[str] = None,
                restore_outcome: Optional[str] = None,
                blocker_ja: Optional[str] = None,
                now_iso: str = "") -> Tuple[Dict[str, Any], int]:
    """運用readiness(livenessの/healthzと分離)。readyのみ200・それ以外503。
    秘密/私的ペイロードなし・理由はredacted日本語。"""
    ready = startup_state in ("ready", "ready_degraded")
    reason = blocker_ja or (
        "運用準備完了" if startup_state == "ready" else
        "運用準備完了(degraded — last-known-goodで稼働)"
        if startup_state == "ready_degraded" else
        "起動復元中/整合性未確定 — 準備未完")
    return ({"ready": ready, "state": startup_state,
             "appVersion": app_version or "unknown",
             "buildSha": build_sha or None,
             "restoreOutcome": restore_outcome,
             "reasonJa": reason, "asOf": now_iso,
             "privacyLevel": "public_safe"},
            200 if ready else 503)


# ── Phase 3: Transition→Event Matrix + Journal Summary ──────────────────────

def _mx(owning, agg, idem, wired, score_dep, note=""):
    return {"owningTransition": owning, "aggregateType": agg,
            "idempotencyKey": idem, "localCommit": "immediate_wal",
            "remoteCommit": "ledger_cron_flush_30min",
            "scoreEligibilityDependsOn": score_dep,
            "publicAggregationAllowed": True, "wired": wired, "noteJa": note}


TRANSITION_EVENT_MATRIX: Dict[str, Dict[str, Any]] = {
    "forecast_issued": _mx("missions_tick.issue_forecast", "forecast",
                           "symbol:sessionDate:targetType + 単調sequence",
                           True, True),
    "forecast_superseded": _mx("(予約)supersede経路", "forecast",
                               "forecastId", False, True,
                               "現行運用に上書き発行なし — 経路実装時に配線"),
    "outcome_resolved": _mx("_dl_resolve_matured", "outcome",
                            "forecastId + 単調sequence", True, True),
    "incident_opened": _mx("missions_tick.detect_missed", "incident",
                           "incidentId(=inc-missionId) + 単調sequence",
                           True, False),
    "incident_resolved": _mx("missions_tick.recover(open→resolved遷移時のみ)",
                             "incident", "incidentId + 単調sequence",
                             True, False),
    "soak_started": _mx("missions_tick.soak_start_gate", "soak",
                        "soakId + 単調sequence", True, False),
    "soak_interrupted": _mx("_startup_bootstrap(同一SHA再起動検出)", "soak",
                            "soakId + 単調sequence", True, False),
    "soak_invalidated": _mx("(予約)時計異常/整合性破壊検出", "soak",
                            "soakId", False, False,
                            "build_soakビューがclockAnomaly=failedで表面化"),
    "soak_completed": _mx("(予約)72h到達の遷移記録", "soak", "soakId",
                          False, False,
                          "現状はbuild_soakビューが状態として表示"),
    "mission_recovered": _mx("missions_tick(missed→recovered遷移)", "mission",
                             "missionId + 単調sequence", True, False),
    "material_learning_approved": _mx("(予約)オーナー承認フロー", "learning",
                                      "proposalId", False, True,
                                      "重要変更はオーナー承認必須(v12.2.0)"),
    "champion_promoted": _mx("(予約)challenger昇格", "challenger",
                             "challengerId", False, True,
                             "shadowは昇格しない(現行は昇格経路なし)"),
    "champion_rolled_back": _mx("(予約)ロールバック", "challenger",
                                "challengerId", False, True),
}


def journal_summary(*, events: List[Dict[str, Any]],
                    total_observed: int = 0, corrupt_count: int = 0,
                    last_remote_ack_at: Optional[str] = None,
                    now_iso: str = "") -> Dict[str, Any]:
    """OperationalJournalSummary。compact済みの歴代件数をゼロ表示しない
    (active WALと歴代合計を分離ラベル)。"""
    evs = [e for e in (events or []) if isinstance(e, dict)]
    counts: Dict[str, int] = {}
    for e in evs:
        k = e.get("eventType") or "unknown"
        counts[k] = counts.get(k, 0) + 1
    active = len(evs)
    total = max(int(total_observed or 0), active)
    compacted = max(0, total - active)
    ack_ep = _ep(last_remote_ack_at)
    remote_committed = sum(
        1 for e in evs
        if ack_ep is not None and (_ep(e.get("occurredAt")) or 9e18) <= ack_ep)
    remote_pending = active - remote_committed
    last_local = evs[-1].get("occurredAt") if evs else None
    recon = ("not_run" if not last_remote_ack_at else
             "consistent" if remote_pending == 0 else "pending_flush")
    return {"activeWalEvents": active,
            "totalEventsObserved": total,
            "compactedEventCount": compacted,
            "eventTypeCounts": counts,
            "localCommittedCount": active,
            "remotePendingCount": remote_pending,
            "remoteCommittedCount": remote_committed,
            "corruptCount": int(corrupt_count or 0),
            "lastLocalEventAt": last_local,
            "lastRemoteAckAt": last_remote_ack_at,
            "reconciliationStatus": recon,
            "ownerReadableJa": (
                f"WAL {active}件(歴代{total}件・compact {compacted}件) / "
                f"remote待ち{remote_pending}件 — "
                "compact済みをゼロ件と表示しない")}


# ── Phase 4: Forecast Activation Readiness ──────────────────────────────────

ACTIVATION_BLOCKERS = ("runtime_not_ready", "store_not_restored",
                       "no_live_research_mission", "research_data_insufficient",
                       "source_quality_blocked", "outside_issuance_window",
                       "market_holiday", "already_issued", "duplicate",
                       "awaiting_next_session", "ready")


def forecast_activation_readiness(*, benchmark_calibration_runs: int,
                                  research_quality_runs: int,
                                  live_agent_runs: int,
                                  completed_research_missions: int,
                                  forecast_eligible_missions: int,
                                  store_record_count: int,
                                  store_last_write_at: Optional[str] = None,
                                  store_restored_at: Optional[str] = None,
                                  startup_state: str = "ready",
                                  issuance_decision: Optional[Dict[str, Any]] = None,
                                  market: str = "JP", holiday: bool = False,
                                  now_iso: str = "",
                                  next_eligible_session: str = "",
                                  next_eligible_mission_at: str = ""
                                  ) -> Dict[str, Any]:
    """予測活性化の正確なテレメトリ。校正/ベンチrunは予測ストアを温めない
    (研究族と予測族の分離) — 正当なforward-live Research Missionのみが
    forecast-eligibleなストア状態を作れる。"""
    dec = (issuance_decision or {}).get("decision") or "unknown"
    source_store_ready = (int(store_record_count) > 0
                          and int(forecast_eligible_missions) > 0)
    if startup_state not in ("ready", "ready_degraded"):
        code = "runtime_not_ready"
        exact = "起動復元が未完 — readyz=503の間は発行しない"
    elif startup_state == "ready_degraded" and store_record_count == 0 \
            and store_restored_at is None and completed_research_missions == 0:
        code = "store_not_restored"
        exact = "調査ストア未復元(degraded起動) — 復元/再調査後に再判定"
    elif holiday:
        code = "market_holiday"
        exact = f"{market}市場休場 — 発行対象セッションなし"
    elif int(store_record_count) == 0:
        code = "no_live_research_mission"
        exact = ("校正/ベンチマークrun(Gemini基準較正含む)は調査ストアを"
                 "温めない — 本物のResearch Mission(deep-dive)完了が必要。"
                 f"校正run={benchmark_calibration_runs}件は予測証拠ではない")
    elif int(forecast_eligible_missions) == 0:
        code = "research_data_insufficient"
        exact = "調査レコードはあるが予測適格(非mock・検証済み)がゼロ"
    elif dec == "duplicate":
        code = "already_issued"
        exact = "本日分は発行済み(冪等)"
    elif dec == "mock_blocked":
        code = "source_quality_blocked"
        exact = "mock/デモデータ — 発行不可"
    elif dec in ("wait_next_session", "stale_opportunity"):
        code = "awaiting_next_session"
        exact = "発行ウィンドウ外 — 翌セッション寄り前に発行"
    elif dec == "insufficient_data":
        code = "research_data_insufficient"
        exact = "調査ストア未ウォーム — ウォームアップ後に再判定"
    else:
        code = "ready"
        exact = "発行可能(正当なResearch Mission由来のストアあり)"
    return {"benchmarkCalibrationRuns": int(benchmark_calibration_runs),
            "researchQualityRuns": int(research_quality_runs),
            "liveAgentRuns": int(live_agent_runs),
            "completedResearchMissions": int(completed_research_missions),
            "forecastEligibleResearchMissions": int(forecast_eligible_missions),
            "forecastStoreRecordCount": int(store_record_count),
            "forecastStoreLastWriteAt": store_last_write_at,
            "forecastStoreRestoredAt": store_restored_at,
            "sourceStoreReady": source_store_ready,
            "currentMarket": market,
            "currentSession": (issuance_decision or {}).get("decision"),
            "nextEligibleSession": next_eligible_session or None,
            "nextEligibleMissionAt": next_eligible_mission_at or None,
            "issuanceWindowStatus": dec,
            "recoveryPermitted": bool(
                (issuance_decision or {}).get("recoveryPermitted")),
            "blockerCode": code, "exactBlockerJa": exact,
            "ownerReadableJa": (
                f"校正{benchmark_calibration_runs}run/ライブ調査"
                f"{completed_research_missions}件/予測適格"
                f"{forecast_eligible_missions}件 — {exact}")}


# ── Phase 6: Calendar/Cadence-Aware Freshness ────────────────────────────────

FRESHNESS_STATUSES = ("ok_fresh", "ok_not_due", "stale_overdue",
                      "critical_overdue", "unknown")
CADENCE_TYPES = ("daily_business", "weekly", "cron", "unknown")


def freshness_policy(*, source_name: str, cadence_type: str,
                     market_timezone: str = "Asia/Tokyo(JST)",
                     publish_hhmm: str = "16:00",
                     release_weekday: Optional[int] = None,
                     data_lag_days: int = 7,
                     cadence_minutes: Optional[int] = None,
                     grace_hours: float = 6.0,
                     grace_minutes: Optional[int] = None,
                     critical_multiple: float = 3.0) -> Dict[str, Any]:
    ct = cadence_type if cadence_type in CADENCE_TYPES else "unknown"
    return {"sourceName": source_name, "cadenceType": ct,
            "expectedCadence": {"daily_business": "営業日毎",
                                "weekly": "週次(公表曜日基準)",
                                "cron": f"{cadence_minutes or '?'}分毎cron",
                                "unknown": "不明(捏造しない)"}[ct],
            "expectedPublicationCalendar": (
                "営業日カレンダー(土日除外・祝日リスト供給時は祝日も)"
                if ct in ("daily_business", "weekly") else
                "収集cadence基準" if ct == "cron" else "unknown"),
            "marketTimezone": market_timezone,
            "publishHhmm": publish_hhmm,
            "releaseWeekday": release_weekday,
            "dataLagDays": int(data_lag_days),
            "cadenceMinutes": cadence_minutes,
            "graceHours": float(grace_hours),
            "graceMinutes": grace_minutes,
            "criticalMultiple": float(critical_multiple),
            "marketHolidayAware": True, "weekendAware": True}


def _jst_dt(iso: Optional[str]) -> Optional[datetime]:
    e = _ep(iso)
    if e is None:
        return None
    return datetime.fromtimestamp(e, JST)


def _is_business_day(d: datetime, holidays) -> bool:
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in set(holidays or ())


def _recent_publications(now: datetime, hhmm: str, holidays,
                         weekday: Optional[int] = None,
                         count: int = 3) -> List[datetime]:
    """now以前の直近公表時刻(新しい順)。weekday指定=週次・なし=営業日毎。"""
    hh, mm = int(hhmm[:2]), int(hhmm[3:5])
    out: List[datetime] = []
    d = now
    for _ in range(0, 40):
        cand = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
        ok_day = (_is_business_day(cand, holidays) if weekday is None
                  else cand.weekday() == weekday
                  and _is_business_day(cand, holidays))
        if ok_day and cand <= now:
            out.append(cand)
            if len(out) >= count:
                break
        d = d - timedelta(days=1)
    return out


def freshness_status(*, policy: Dict[str, Any], last_success_iso: Optional[str],
                     now_iso: str, holidays=()) -> Dict[str, Any]:
    """カレンダー/cadence対応の鮮度判定。市場が閉まっていて次回公表が未到来
    なだけの日次データをstaleにしない。本物の遅延は隠さない(格下げしない)。"""
    ct = policy.get("cadenceType")
    now = _jst_dt(now_iso)
    last = _jst_dt(last_success_iso)
    base = {"sourceName": policy.get("sourceName"), "policy": policy,
            "lastSuccessAt": last_success_iso,
            "lastExpectedPublicationAt": None,
            "nextExpectedPublicationAt": None}
    if now is None or ct == "unknown":
        return {**base, "status": "unknown",
                "confidenceCapRequired": True,
                "exactReasonJa": "期待cadence不明 — 鮮度を捏造しない"}
    if last is None:
        return {**base, "status": "unknown",
                "confidenceCapRequired": True,
                "exactReasonJa": "最終成功時刻が未取得 — unknown(捏造しない)"}
    if ct == "cron":
        cad = int(policy.get("cadenceMinutes") or 30)
        grace = int(policy.get("graceMinutes") or max(5, cad // 2))
        age_min = (now - last).total_seconds() / 60.0
        crit = cad * float(policy.get("criticalMultiple") or 3.0)
        if age_min <= cad:
            st, ja = "ok_fresh", f"収集cadence({cad}分)内({round(age_min)}分前)"
        elif age_min <= cad + grace:
            st = "ok_not_due"
            ja = f"次回collect cron猶予内({round(age_min)}分前/猶予{grace}分)"
        elif age_min <= crit:
            st = "stale_overdue"
            ja = f"収集が期待cadence+猶予を超過({round(age_min)}分前)"
        else:
            st = "critical_overdue"
            ja = f"収集停止の疑い({round(age_min)}分前 — cadenceの{policy.get('criticalMultiple')}倍超)"
        return {**base, "status": st, "exactReasonJa": ja,
                "confidenceCapRequired": st in ("stale_overdue",
                                                "critical_overdue")}
    weekday = (policy.get("releaseWeekday") if ct == "weekly" else None)
    pubs = _recent_publications(now, policy.get("publishHhmm") or "16:00",
                                holidays, weekday=weekday, count=3)
    if not pubs:
        return {**base, "status": "unknown", "confidenceCapRequired": True,
                "exactReasonJa": "公表カレンダーを構成できない — unknown"}
    last_expected = pubs[0]
    prev_expected = pubs[1] if len(pubs) > 1 else None
    step = timedelta(days=7 if ct == "weekly" else 1)
    nxt = last_expected + step
    while not (_is_business_day(nxt, holidays)
               if weekday is None else nxt.weekday() == weekday
               and _is_business_day(nxt, holidays)):
        nxt += timedelta(days=1)
    grace = timedelta(hours=float(policy.get("graceHours") or 6.0))
    # 週次はデータ日付が公表日より過去(前週分)になるため許容ラグを引いて比較
    lag = timedelta(days=int(policy.get("dataLagDays") or 0)) \
        if ct == "weekly" else timedelta(0)
    covers_latest = last >= (last_expected - lag - timedelta(minutes=5))
    base.update({"lastExpectedPublicationAt": last_expected.isoformat(),
                 "nextExpectedPublicationAt": nxt.isoformat()})
    if covers_latest:
        return {**base, "status": "ok_fresh", "confidenceCapRequired": False,
                "exactReasonJa": ("直近の期待公表分まで取得済み — "
                                  f"次回公表 {nxt.strftime('%m-%d %H:%M')} JSTまで"
                                  "staleではない(週末/休場を考慮)")}
    if now <= last_expected + grace:
        return {**base, "status": "ok_not_due", "confidenceCapRequired": False,
                "exactReasonJa": (f"最新公表分({last_expected.strftime('%m-%d %H:%M')})"
                                  f"の取得猶予内(+{policy.get('graceHours')}h) — "
                                  "staleではない")}
    covers_prev = (prev_expected is not None
                   and last >= (prev_expected - lag - timedelta(minutes=5)))
    st = "stale_overdue" if covers_prev else "critical_overdue"
    return {**base, "status": st, "confidenceCapRequired": True,
            "exactReasonJa": (f"期待公表({last_expected.strftime('%m-%d %H:%M')} JST)"
                              f"+猶予{policy.get('graceHours')}hを超過しても未取得 — "
                              + ("1回分の遅延" if st == "stale_overdue"
                                 else "2回分以上の遅延(要確認)")
                              + "。判断はconfidence capを維持")}


# ── Phase 7: Server Runtime ─────────────────────────────────────────────────

def server_runtime_info(*, server_type: str = "unknown",
                        workers: Optional[int] = None,
                        threads: Optional[int] = None,
                        startup_mode: str = "lazy_first_request",
                        graceful_shutdown: bool = True,
                        start_command_current: str = "python scanner.py",
                        start_command_prepared: str =
                        "gunicorn -c gunicorn.conf.py wsgi:app"
                        ) -> Dict[str, Any]:
    """本番サーバ準備状態。マルチworkerは状態フルスケジューラ/WALが未実証の
    ため安全と主張しない(1 workerを強制文書化)。"""
    multi_worker_safe = False
    if server_type == "gunicorn_wsgi" and (workers or 0) == 1:
        status = "production_wsgi_single_worker"
        ja = "Gunicorn(1 worker) — スケジューラ/WAL重複なしの安全構成"
    elif server_type == "gunicorn_wsgi":
        status = "unsafe_multi_worker"
        ja = ("複数worker構成 — スケジューラ/状態分裂が未実証のため"
              "本番安全と主張しない")
    elif server_type == "flask_dev":
        status = "dev_server"
        ja = ("Flask開発サーバで稼働中 — 本番はGunicorn 1 worker構成へ"
              "移行準備済み(Start Command変更はオーナー操作)")
    else:
        status = "unknown"
        ja = "サーバ種別未確定(テスト/import文脈)"
    return {"serverType": server_type, "workers": workers, "threads": threads,
            "startupMode": startup_mode,
            "gracefulShutdownSupported": bool(graceful_shutdown),
            "multiWorkerSafe": multi_worker_safe,
            "productionReadinessStatus": status,
            "startCommandCurrent": start_command_current,
            "startCommandPrepared": start_command_prepared,
            "ownerReadableJa": ja}


# ── Phase 8: Owner Control Truth ────────────────────────────────────────────

VERIFICATION_SOURCES = ("runtime_verified", "provider_api_verified",
                        "owner_attested", "unverified")


def owner_control_status(*, control: str, runtime_verified: bool = False,
                         provider_verified: bool = False,
                         attested_at: Optional[str] = None,
                         ttl_days: int = 90, now_iso: str = "",
                         evidence_ref: Optional[str] = None) -> Dict[str, Any]:
    """外部管理設定の真実性。手動確認はowner_attested(期限付き)であって
    runtime_verifiedではない。検証不能はunverifiedのまま(捏造しない)。"""
    expires = None
    if runtime_verified:
        src, status = "runtime_verified", "verified"
        ja = "サーバ実行時に検証済み"
    elif provider_verified:
        src, status = "provider_api_verified", "verified"
        ja = "プロバイダAPIで検証済み"
    elif attested_at:
        src = "owner_attested"
        ae = _ep(attested_at)
        if ae is not None:
            expires = datetime.fromtimestamp(
                ae, JST) + timedelta(days=int(ttl_days))
            ne = _ep(now_iso)
            valid = ne is None or ne <= expires.timestamp()
            status = "attested_valid" if valid else "attestation_expired"
            expires = expires.isoformat()
        else:
            status = "attestation_invalid"
        ja = ("オーナー手動確認(owner_attested・期限付き) — "
              "runtime検証済みとは主張しない"
              if status == "attested_valid" else
              "オーナー確認の期限切れ/不正 — 再確認が必要")
    else:
        src, status = "unverified", "unverified"
        ja = "未検証(サーバから外部管理設定を検証できない — 捏造しない)"
    return {"control": control, "verificationSource": src, "status": status,
            "attestedAt": attested_at, "expiresAt": expires,
            "evidenceReferenceRedacted": evidence_ref,
            "ownerReadableJa": ja}
