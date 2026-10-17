# -*- coding: utf-8 -*-
"""ARGUS Runtime Truth — v12.2.9(純・stdlibのみ)。

Build-scoped soak / 起動復元ライフサイクル / 運用ジャーナル可観測性 /
予測活性化テレメトリ / カレンダー対応鮮度 / 本番サーバ・オーナー設定の真実性。

原則: デプロイ時刻・soak時刻・検証状態を捏造しない(不明はunknownのまま)。
Gitのcommit/merge時刻はデプロイ時刻ではない。Render Deploy liveの正確な時刻が
取得できない場合は「そのSHAで最初に検証されたhealthy-ready実行時刻」を使い、
時刻ソースを正直にラベルする。
"""
import copy
import hashlib
import json
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
SOAK_STATES = ("not_started", "running", "scheduler_delayed",
               "verification_gap", "interrupted", "completed")
SOAK_EVIDENCE_TYPES = ("scheduled_mission", "backend_health",
                       "journal_commit", "journal_read_back", "boot_restore")
SOAK_HEARTBEAT_GAP_SECONDS = 90 * 60
SOAK_INTERRUPTION_GAP_SECONDS = 3 * 60 * 60


def _same_build_identity(left: Optional[str], right: Optional[str]) -> bool:
    """Accept exact or unambiguous seven-character/full SHA equivalents."""
    a, b = str(left or "").strip().lower(), str(right or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return min(len(a), len(b)) >= 7 and (a.startswith(b) or b.startswith(a))


def _historical_gap_evidence(soak: Dict[str, Any]) -> Dict[str, Any]:
    points: List[Tuple[float, str]] = []
    started = soak.get("startedAt")
    if _ep(started) is not None:
        points.append((_ep(started), str(started)))
    for row in (soak.get("heartbeats") or []):
        if not isinstance(row, dict):
            continue
        observed = row.get("observedAt")
        if _ep(observed) is not None:
            points.append((_ep(observed), str(observed)))
    points.sort(key=lambda item: item[0])
    gaps = [
        (right[0] - left[0], left[1], right[1])
        for left, right in zip(points, points[1:])
    ]
    if not gaps:
        return {"maximumEvidenceGapSeconds": 0,
                "maximumEvidenceGapStartAt": None,
                "maximumEvidenceGapEndAt": None}
    seconds, start_at, end_at = max(gaps, key=lambda item: item[0])
    return {"maximumEvidenceGapSeconds": int(seconds),
            "maximumEvidenceGapStartAt": start_at,
            "maximumEvidenceGapEndAt": end_at}


_RUNNING_SOAK_STATES = {"running", "soak_in_progress", "scheduler_delayed",
                        "verification_gap", "active_unproven"}


def _running_soak_interruption_evidence(
        *, persisted: Dict[str, Any], superseding_build_sha: Optional[str],
        successor_boot: Optional[str]) -> Dict[str, Any]:
    """Derive only terminal facts supported by persisted build/boot evidence.

    This helper deliberately does not infer ``planned_owner_restart``.  That
    classification requires the separately verified durable owner marker used
    by :func:`soak_restore_decision` for same-build restarts.
    """
    state = str(persisted.get("terminalState") or
                persisted.get("state") or "not_started")
    if state not in _RUNNING_SOAK_STATES:
        return {}
    previous_sha = (persisted.get("buildShaFull") or
                    persisted.get("buildSha"))
    previous_boot = (persisted.get("processBootedAt") or
                     persisted.get("processBootId"))
    different_build = bool(
        previous_sha and superseding_build_sha and
        not _same_build_identity(str(previous_sha),
                                 str(superseding_build_sha)))
    different_boot = bool(
        previous_boot and successor_boot and
        str(previous_boot) != str(successor_boot))
    if different_build:
        interruption_class = "backend_build_changed"
    elif different_boot:
        interruption_class = "boot_discontinuity"
    else:
        return {}
    return {
        "interruptionClass": interruption_class,
        "failureClass": interruption_class,
        "failureReason": (
            "backend_build_changed_during_running_soak"
            if different_build else
            "backend_boot_changed_during_running_soak"),
        "terminalizationProvenance":
            "derived_from_persisted_build_and_boot_evidence",
        "interruptionClassSource":
            "derived_from_persisted_build_and_boot_evidence",
        "previousBackendBuildSha": previous_sha,
        "previousBoot": previous_boot,
        "successorBoot": successor_boot,
    }


def historical_soak_summary(
        *, persisted: Any, superseding_build_sha: Optional[str],
        superseded_at: Optional[str] = None,
        lifecycle_relation: str = "superseded_by_backend_deployment",
        lifecycle_reason: str = "backend_build_changed") -> Dict[str, Any]:
    """Project immutable terminal truth separately from lifecycle metadata.

    The input is never mutated.  Missing historical failure evidence stays
    explicit and null; no deployment/restart may manufacture a terminal
    result that was not present or derivable from durable heartbeat evidence.
    """
    source = copy.deepcopy(persisted) if isinstance(persisted, dict) else {}
    build_sha = source.get("buildShaFull") or source.get("buildSha")
    rows = [row for row in (source.get("heartbeats") or [])
            if isinstance(row, dict)]
    last_at = source.get("lastHeartbeatAt")
    if not last_at and rows:
        last_at = rows[-1].get("observedAt")
    derived: Dict[str, Any] = {}
    if source.get("startedAt") and rows and build_sha and last_at:
        derived = build_soak_state(
            soak=source, now_iso=str(last_at),
            current_build_sha=str(source.get("buildSha") or build_sha),
            required_hours=int(source.get("requiredHours") or 72))

    stored_state = source.get("terminalState") or source.get("state")
    terminal_states = {"interrupted", "completed", "operationally_verified",
                       "failed"}
    stale_pin = any(row.get("healthStatus") == "build_mismatch"
                    for row in rows)
    interruption_evidence = _running_soak_interruption_evidence(
        persisted=source, superseding_build_sha=superseding_build_sha,
        successor_boot=superseded_at)
    if stored_state in terminal_states:
        terminal_state = str(stored_state)
    elif stale_pin:
        terminal_state = "interrupted"
    elif interruption_evidence:
        terminal_state = "interrupted"
    elif derived.get("state") in terminal_states:
        terminal_state = str(derived.get("state"))
    else:
        terminal_state = "historical_evidence_incomplete"

    failure_class = source.get("failureClass")
    failure_source = "persisted" if failure_class else None
    if not failure_class and terminal_state == "interrupted" and stale_pin:
        failure_class = "scheduler_configuration_mismatch"
        failure_source = "derived_from_persisted_build_mismatch_heartbeat"
    if not failure_class and terminal_state == "interrupted" and \
            interruption_evidence:
        failure_class = interruption_evidence.get("failureClass")
        failure_source = interruption_evidence.get(
            "terminalizationProvenance")
    if not failure_class and terminal_state == "interrupted" and \
            derived.get("state") == "interrupted" and \
            derived.get("failureClass"):
        failure_class = derived.get("failureClass")
        failure_source = "derived_from_persisted_heartbeat_evidence"

    interruptions = copy.deepcopy(source.get("interruptions") or [])
    detected = [row.get("detectedAt") for row in interruptions
                if isinstance(row, dict) and row.get("detectedAt")]
    interrupted_at = source.get("interruptedAt") or \
        source.get("interruptionAt") or _iso_max(*detected)
    if not interrupted_at and interruption_evidence:
        interrupted_at = superseded_at
    gap = _historical_gap_evidence(source)
    incomplete = terminal_state == "historical_evidence_incomplete" or (
        terminal_state == "interrupted" and not failure_class)
    missing = []
    if not source.get("soakId"):
        missing.append("soakId")
    if not source.get("startedAt"):
        missing.append("startedAt")
    if terminal_state == "historical_evidence_incomplete":
        missing.append("terminalState")
    if terminal_state == "interrupted" and not failure_class:
        missing.append("failureClass")

    relationship_sha = str(superseding_build_sha or "") or None
    failure_reason = (source.get("failureReason") or
                      interruption_evidence.get("failureReason") or
                      derived.get("reason") or
                      ("stale_ec2_expected_build_sha" if stale_pin else None))
    try:
        interruption_count = int(
            source.get("interruptionCount") or len(interruptions))
    except (TypeError, ValueError):
        interruption_count = len(interruptions)
    restart_count = sum(
        str(row.get("type") or "") in {
            "process_restart", "process_restart_same_build"}
        for row in interruptions if isinstance(row, dict))
    out = {
        "soakId": source.get("soakId"),
        "buildSha": source.get("buildSha") or "unknown",
        "buildShaFull": source.get("buildShaFull"),
        "backendBuildSha": build_sha or "unknown",
        "appVersion": source.get("appVersion"),
        "backendVersion": source.get("backendVersion") or
            source.get("appVersion"),
        "startedAt": source.get("startedAt"),
        "state": terminal_state,
        "status": terminal_state,
        "terminalState": terminal_state,
        "failureClass": failure_class,
        "interruptionClass": source.get("interruptionClass") or
            failure_class,
        "failureClassSource": failure_source or "unavailable",
        "failureReason": failure_reason,
        "interruptedAt": interrupted_at,
        "continuityInterruptions": interruptions,
        "interruptionCount": interruption_count,
        "restartCount": restart_count,
        "lastHeartbeatAt": last_at,
        "lastHeartbeatSource": source.get("lastHeartbeatSource"),
        "heartbeatCount": len(rows),
        **gap,
        "completed72h": bool(source.get("completed72h")),
        "formalResult": source.get("formalResult"),
        "inherited": False,
        "archiveImmutable": True,
        "historicalEvidenceState": (
            "historical_evidence_incomplete" if incomplete else
            "preserved_from_immutable_history"),
        "missingHistoricalFields": sorted(set(missing)),
        "lifecycleRelation": lifecycle_relation,
        "lifecycleReason": lifecycle_reason,
        # Legacy alias retained for consumers; lifecycleReason is canonical.
        "reason": failure_reason or lifecycle_reason,
        "supersededByBuildSha": relationship_sha,
        # Backward-compatible alias; it no longer replaces terminal state.
        "supersededBy": relationship_sha,
        "supersedingBuildShaExact": bool(
            relationship_sha and len(relationship_sha) == 40),
        "terminalizationProvenance": (
            source.get("terminalizationProvenance") or
            interruption_evidence.get("terminalizationProvenance") or
            ("persisted" if stored_state in terminal_states else None)),
        "interruptionClassSource": (
            source.get("interruptionClassSource") or
            interruption_evidence.get("interruptionClassSource") or
            failure_source or "unavailable"),
        "previousBackendBuildSha": (
            source.get("previousBackendBuildSha") or
            interruption_evidence.get("previousBackendBuildSha") or
            build_sha),
        "previousBoot": (source.get("previousBoot") or
                         interruption_evidence.get("previousBoot")),
        "successorBoot": (source.get("successorBoot") or
                          interruption_evidence.get("successorBoot")),
    }
    if superseded_at:
        out["supersededAt"] = superseded_at
    return out


def normalize_previous_soak_summary(
        *, previous: Any, history: Any,
        current_build_sha: Optional[str], boot_iso: str) -> Optional[Dict[str, Any]]:
    """Idempotently rebuild a public summary from immutable history."""
    prev = copy.deepcopy(previous) if isinstance(previous, dict) else {}
    history_rows = [copy.deepcopy(row) for row in (history or [])
                    if isinstance(row, dict)]
    soak_id = prev.get("soakId")
    started_at = prev.get("startedAt")
    match = next((row for row in reversed(history_rows)
                  if row.get("soakId") == soak_id and
                  (not started_at or row.get("startedAt") == started_at)), None)
    relationship_sha = (prev.get("supersededByBuildSha") or
                        prev.get("supersededBy") or current_build_sha)
    if match is not None:
        return historical_soak_summary(
            persisted=match,
            superseding_build_sha=relationship_sha,
            superseded_at=prev.get("supersededAt") or boot_iso,
            lifecycle_relation=prev.get("lifecycleRelation") or
                "superseded_by_backend_deployment",
            lifecycle_reason=prev.get("lifecycleReason") or
                prev.get("reason") or "backend_build_changed")
    if not prev:
        return None
    # The compact legacy summary is not authoritative terminal evidence.
    return {
        "soakId": soak_id,
        "buildSha": prev.get("buildSha") or "unknown",
        "startedAt": started_at,
        "state": "historical_evidence_incomplete",
        "status": "historical_evidence_incomplete",
        "terminalState": "historical_evidence_incomplete",
        "failureClass": None,
        "failureClassSource": "unavailable",
        "inherited": False,
        "archiveImmutable": False,
        "historicalEvidenceState": "historical_evidence_incomplete",
        "missingHistoricalFields": ["authoritativeHistoryRecord",
                                    "terminalState", "failureClass"],
        "lifecycleRelation": prev.get("lifecycleRelation") or
            "superseded_by_backend_deployment",
        "lifecycleReason": prev.get("lifecycleReason") or
            prev.get("reason") or "backend_build_changed",
        "supersededByBuildSha": relationship_sha,
        "supersededBy": relationship_sha,
        "supersedingBuildShaExact": bool(
            relationship_sha and len(str(relationship_sha)) == 40),
    }


def soak_start_decision(*, now_iso: str, scheduled_for: str,
                        trigger_source: str, mission_window_id: str,
                        build_sha: Optional[str],
                        app_version: str,
                        process_booted_at: Optional[str],
                        restore_completed_at: Optional[str],
                        startup_state: str, integrity_ok: bool,
                        public_leak_safe: bool,
                        scheduler_ready: bool) -> Dict[str, Any]:
    """Natural EC2 mission windowだけにSoak開始権限を与える。

    ``now_iso`` は検証時刻に過ぎず、Soak時計には使わない。startedAtは
    mission windowのscheduledAtと完全一致する。手動/GitHub実行、bootや
    restoreより前のwindow、未来windowはfail closedにする。
    """
    blockers = []
    scheduled_ep = _ep(scheduled_for)
    now_ep = _ep(now_iso)
    boot_ep = _ep(process_booted_at)
    restore_ep = _ep(restore_completed_at)
    if trigger_source != "ec2_systemd":
        blockers.append("natural_ec2_execution_required")
    if not mission_window_id or not str(mission_window_id).startswith("mw-"):
        blockers.append("mission_window_identity_invalid")
    if scheduled_ep is None:
        blockers.append("scheduled_at_invalid")
    elif now_ep is not None and scheduled_ep > now_ep + 1:
        blockers.append("scheduled_at_in_future")
    if scheduled_ep is not None and boot_ep is not None and \
            scheduled_ep < boot_ep - 1:
        blockers.append("mission_window_before_boot")
    if scheduled_ep is not None and restore_ep is not None and \
            scheduled_ep < restore_ep - 1:
        blockers.append("mission_window_before_restore")
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
    return {"allowed": True, "blockers": [], "startedAt": scheduled_for,
            "startedBy": "ec2_systemd",
            "firstMissionWindowId": mission_window_id,
            "startReason": "first_natural_ec2_mission_window",
            "startTimeSource": "mission_window_scheduled_at",
            "ownerReadableJa": ("自然EC2 mission windowで開始"
                                "(startedAt=scheduledAt、手動時刻の流用なし)")}


def formal_soak_closure(*, soak_state: Dict[str, Any],
                        mission_result: Optional[str],
                        remote_cycle: Dict[str, Any]) -> Dict[str, Any]:
    """72h時計・scheduler・mission・Remote Journalを独立評価する。"""
    duration_ok = float(soak_state.get("elapsedHours") or 0) >= 72
    scheduler_ok = soak_state.get("schedulerContinuityVerified") is True
    mission_ok = (
        mission_result in ("caught_up", "completed", "no_new_session") and
        soak_state.get("failureClass") not in
        ("application_failure", "build_mismatch",
         "durable_integrity_failure", "journal_failure"))
    remote_ok = (
        remote_cycle.get("remoteDurabilityState") == "verified" and
        remote_cycle.get("readBackVerified") is True and
        remote_cycle.get("walReadBackVerified") is True)
    completed = bool(duration_ok and scheduler_ok and mission_ok and remote_ok)
    return {
        "completed72h": completed,
        "duration": {"passed": duration_ok,
                     "elapsedHours": soak_state.get("elapsedHours")},
        "schedulerContinuity": {
            "passed": scheduler_ok,
            "failureClass": soak_state.get("failureClass")},
        "missionExecution": {"passed": mission_ok, "result": mission_result},
        "remoteDurability": {
            "passed": remote_ok,
            "state": remote_cycle.get("remoteDurabilityState"),
            "receiptCommitSha": remote_cycle.get("receiptCommitSha"),
            "receiptErrorClass": remote_cycle.get("receiptErrorClass")},
        "status": "completed" if completed else "observing",
    }


def soak_restore_decision(*, persisted: Any, current_build_sha: Optional[str],
                          boot_iso: str,
                          last_persist_at: Optional[str] = None,
                          max_verified_gap_min: float = 45.0,
                          current_boot_id: Optional[str] = None,
                          planned_restart_marker: Any = None
                          ) -> Dict[str, Any]:
    """復元snapshot内のsoakをどう扱うか。
    ①同一build SHA → 時計を継承+中断(interruption)として記録(隠さない)。
    ②別SHA/不明SHA → 継承しない(新buildは旧buildのsoak時計を相続できない)。"""
    if not isinstance(persisted, dict) or not persisted.get("startedAt"):
        return {"action": "ignore", "ownerReadableJa": "復元soakなし"}
    p_sha = persisted.get("buildShaFull") or persisted.get("buildSha")
    persisted_boot_id = persisted.get("processBootId")
    state = str(persisted.get("terminalState") or
                persisted.get("state") or "not_started")
    running = state in _RUNNING_SOAK_STATES
    boot_changed = bool(
        current_boot_id and persisted_boot_id and
        str(current_boot_id) != str(persisted_boot_id))
    same_build = bool(p_sha and current_build_sha and _same_build_identity(
        str(p_sha), str(current_build_sha)))
    if running and same_build and (boot_changed or not persisted_boot_id):
        marker = (planned_restart_marker
                  if isinstance(planned_restart_marker, dict) else {})
        planned = bool(
            marker.get("durable") is True and
            marker.get("interruptionClass") == "planned_owner_restart" and
            marker.get("soakId") == persisted.get("soakId") and
            (not persisted_boot_id or
             marker.get("sourceBootId") == persisted_boot_id))
        interruption_class = (
            "planned_owner_restart" if planned else
            "boot_discontinuity" if boot_changed else "backend_restart")
        terminal = copy.deepcopy(persisted)
        interruptions = list(terminal.get("interruptions") or [])
        evidence = {
            "type": "process_restart_same_build",
            "interruptionClass": interruption_class,
            "detectedAt": boot_iso,
            "lastPersistAt": last_persist_at,
            "sourceBootId": persisted_boot_id,
            "currentBootId": current_boot_id,
            "plannedMarkerVerified": planned,
        }
        if not any(
                row.get("detectedAt") == boot_iso and
                row.get("interruptionClass") == interruption_class
                for row in interruptions if isinstance(row, dict)):
            interruptions.append(evidence)
        terminal.update({
            "state": "interrupted", "status": "interrupted",
            "terminalState": "interrupted", "completed72h": False,
            "interruptedAt": terminal.get("interruptedAt") or boot_iso,
            "interruptionClass": interruption_class,
            "failureClass": interruption_class,
            "failureReason": "backend_boot_changed_during_running_soak",
            "interruptions": interruptions,
            "interruptionCount": len(interruptions),
        })
        previous = historical_soak_summary(
            persisted=terminal, superseding_build_sha=current_build_sha,
            superseded_at=boot_iso,
            lifecycle_relation="same_build_boot_discontinuity",
            lifecycle_reason="backend_process_boot_changed")
        return {
            "action": "terminalize_interrupted",
            "terminalSoak": terminal,
            "previousSoakSummary": previous,
            "interruptionClass": interruption_class,
            "ownerReadableJa": (
                "実行中Soakのboot断絶を検出 — 旧時計をinterruptedで固定"),
        }
    if same_build and not running and state in (
            "interrupted", "completed", "failed", "superseded"):
        previous = historical_soak_summary(
            persisted=persisted, superseding_build_sha=current_build_sha,
            superseded_at=boot_iso,
            lifecycle_relation="terminal_record_preserved",
            lifecycle_reason="terminal_soak_is_not_resumable")
        return {
            "action": "preserve_terminal",
            "previousSoakSummary": previous,
            "ownerReadableJa": "終了済みSoakを不変のまま保持",
        }
    if same_build:
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
    interruption_evidence = _running_soak_interruption_evidence(
        persisted=persisted, superseding_build_sha=current_build_sha,
        successor_boot=boot_iso)
    if running and interruption_evidence:
        terminal = copy.deepcopy(persisted)
        terminal.update({
            "state": "interrupted", "status": "interrupted",
            "terminalState": "interrupted", "completed72h": False,
            "interruptedAt": terminal.get("interruptedAt") or boot_iso,
            **interruption_evidence,
        })
        previous = historical_soak_summary(
            persisted=terminal, superseding_build_sha=current_build_sha,
            superseded_at=boot_iso,
            lifecycle_relation="superseded_by_backend_deployment",
            lifecycle_reason=interruption_evidence["failureClass"])
        return {
            "action": "terminalize_interrupted",
            "terminalSoak": terminal,
            "previousSoakSummary": previous,
            "interruptionClass": interruption_evidence["failureClass"],
            "ownerReadableJa": (
                "実行中Soakのbuild/boot断絶を検出 — "
                "旧時計をinterruptedで固定"),
        }
    previous = historical_soak_summary(
        persisted=persisted,
        superseding_build_sha=current_build_sha,
        superseded_at=boot_iso,
        lifecycle_reason="backend_build_changed")
    return {"action": "new_soak",
            "previousSoakSummary": previous,
            "ownerReadableJa": ("build SHAが異なる/不明 — 旧soak時計を継承しない"
                                "(build-scoped soak)")}


def soak_heartbeat(*, soak_id: str, build_sha: Optional[str],
                   runtime_version: str, expected_at: str, observed_at: str,
                   source: str, health_status: str, ready_status: str,
                   restore_outcome: Optional[str], durable_integrity: str,
                   journal_status: str, read_back_verified: bool,
                   scheduler_delay_seconds: int, evidence_type: str,
                   now_iso: Optional[str] = None,
                   retrospective: bool = False) -> Optional[Dict[str, Any]]:
    """公開安全なbuild heartbeat。未来証拠と未知evidenceを安全拒否する。"""
    observed_ep = _ep(observed_at)
    expected_ep = _ep(expected_at)
    now_ep = _ep(now_iso or observed_at)
    if evidence_type not in SOAK_EVIDENCE_TYPES or observed_ep is None \
            or expected_ep is None or now_ep is None:
        return None
    if observed_ep > now_ep + 1 or expected_ep > observed_ep:
        return None
    # This heartbeat is a truth record for one exact window.  An operational
    # effective delay may include missed windows from before this build/Soak,
    # so derive the heartbeat value from its own timeline coordinates.
    measured_delay_seconds = max(0, int(observed_ep - expected_ep))
    body = {
        "soakId": soak_id, "buildSha": build_sha,
        "runtimeVersion": runtime_version,
        "expectedAt": expected_at, "observedAt": observed_at,
        "source": source, "healthStatus": health_status,
        "readyStatus": ready_status, "restoreOutcome": restore_outcome,
        "durableIntegrity": durable_integrity,
        "journalStatus": journal_status,
        "readBackVerified": bool(read_back_verified),
        "schedulerDelaySeconds": measured_delay_seconds,
        "evidenceType": evidence_type,
        "retrospectiveEvidence": bool(retrospective),
    }
    body["stateHash"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return body


def append_soak_heartbeat(soak: Dict[str, Any],
                          heartbeat: Optional[Dict[str, Any]],
                          max_len: int = 400) -> bool:
    """同一build/window/evidenceの重複と非権威的な診断証拠を抑止。

    GitHub schedule は EC2 systemd の backup scheduler であり、その
    expected-build pin の誤りは control-plane 設定障害であって production
    process の中断証拠ではない。実backend SHAを持つEC2 heartbeatやruntime
    continuityを上書きしないよう、backup由来のbuild_mismatchはSoak列へ
    追加しない。呼び出し側はworkflow結果として別途赤表示できる。
    """
    if not heartbeat or heartbeat.get("soakId") != soak.get("soakId") \
            or heartbeat.get("buildSha") != soak.get("buildSha") \
            or heartbeat.get("source") == "manual":
        return False
    if heartbeat.get("source") == "github_schedule" and \
            heartbeat.get("healthStatus") == "build_mismatch":
        return False
    rows = soak.setdefault("heartbeats", [])
    key = (heartbeat.get("buildSha"), heartbeat.get("expectedAt"),
           heartbeat.get("evidenceType"), heartbeat.get("source"))
    if any((h.get("buildSha"), h.get("expectedAt"), h.get("evidenceType"),
            h.get("source")) == key for h in rows if isinstance(h, dict)):
        return False
    rows.append(heartbeat)
    del rows[:-max(1, int(max_len))]
    soak["lastHeartbeatAt"] = heartbeat.get("observedAt")
    soak["lastHeartbeatSource"] = heartbeat.get("source")
    return True


def build_soak_state(*, soak: Dict[str, Any], now_iso: str,
                     current_build_sha: Optional[str],
                     required_hours: int = 72) -> Dict[str, Any]:
    """独立証拠を束ね、単一scheduler source障害とapp障害を分離する。"""
    rows = sorted(
        [h for h in (soak.get("heartbeats") or []) if isinstance(h, dict)],
        key=lambda h: str(h.get("observedAt") or ""))
    last = rows[-1] if rows else None
    started = soak.get("startedAt")
    elapsed = _hours_between(started, now_iso) if started else 0.0
    evidence_times = [_ep(started)] + [_ep(h.get("observedAt")) for h in rows]
    evidence_times = sorted(e for e in evidence_times if e is not None)
    evidence_gaps = [b - a for a, b in zip(evidence_times, evidence_times[1:])]
    max_evidence_gap = max(evidence_gaps, default=0)
    now_ep = _ep(now_iso)
    source_latest = {}
    for heartbeat in rows:
        source = heartbeat.get("source")
        if source:
            source_latest[str(source)] = heartbeat
    warning_sources = []
    for source in ("ec2_systemd", "github_schedule"):
        source_row = source_latest.get(source)
        source_ep = _ep(source_row.get("observedAt")) if source_row else None
        if source_ep is None or now_ep is None or \
                now_ep - source_ep > SOAK_HEARTBEAT_GAP_SECONDS:
            warning_sources.append(source)
    fresh_rows = [
        heartbeat for heartbeat in rows
        if now_ep is not None and _ep(heartbeat.get("observedAt")) is not None
        and now_ep - _ep(heartbeat.get("observedAt"))
        <= SOAK_HEARTBEAT_GAP_SECONDS
    ]
    healthy_fresh = [
        heartbeat for heartbeat in fresh_rows
        if heartbeat.get("healthStatus") == "ok"
        and heartbeat.get("readyStatus") == "ready"
        and heartbeat.get("durableIntegrity") in ("ok", "unknown")
        and heartbeat.get("journalStatus") not in
        ("hash_mismatch", "unreadable", "sequence_conflict")
    ]
    latest_evidence_gap = (
        now_ep - _ep(last.get("observedAt"))
        if last and now_ep is not None and
        _ep(last.get("observedAt")) is not None else None)
    scheduler_continuity_verified = bool(
        started and last and
        max_evidence_gap <= SOAK_HEARTBEAT_GAP_SECONDS and
        latest_evidence_gap is not None and
        latest_evidence_gap <= SOAK_HEARTBEAT_GAP_SECONDS and
        any(int(h.get("schedulerDelaySeconds") or 0) <= 5 * 60
            for h in healthy_fresh))
    reference = healthy_fresh[-1] if healthy_fresh else last
    blocker = None
    failure_class = None
    failure_reason = None
    if not started or last is None:
        state = "not_started"
        blocker = "有効なheartbeat未記録"
        failure_class = "verification_gap"
    elif not current_build_sha or reference.get("buildSha") != current_build_sha:
        state = "interrupted"
        blocker = "build SHA不一致"
        failure_class = "build_mismatch"
    elif any(not i.get("verified") for i in (soak.get("interruptions") or [])
             if isinstance(i, dict)):
        state = "interrupted"
        blocker = "過去の未検証中断（成功へ書き換えない）"
        failure_class = "application_failure"
    elif reference.get("healthStatus") == "build_mismatch":
        state = "interrupted"
        blocker = "EC2 schedulerの期待build SHAがbackendと不一致"
        failure_class = "scheduler_configuration_mismatch"
        failure_reason = "stale_ec2_expected_build_sha"
    elif reference.get("healthStatus") != "ok" or \
            reference.get("readyStatus") != "ready":
        state = "interrupted"
        blocker = "backend health/ready異常"
        failure_class = "application_failure"
    elif reference.get("durableIntegrity") not in ("ok", "unknown"):
        state = "interrupted"
        blocker = "durable state整合性異常"
        failure_class = "durable_integrity_failure"
    elif reference.get("journalStatus") in ("hash_mismatch", "unreadable",
                                             "sequence_conflict"):
        state = "interrupted"
        blocker = "Remote Journal整合性異常"
        failure_class = "journal_failure"
    elif max_evidence_gap > SOAK_INTERRUPTION_GAP_SECONDS:
        state = "interrupted"
        blocker = "heartbeat列に長時間の未証明区間"
        failure_class = "scheduler_source_failure"
    elif max_evidence_gap > SOAK_HEARTBEAT_GAP_SECONDS:
        state = "verification_gap"
        blocker = "heartbeat列の継続性を確認中"
        failure_class = "verification_gap"
    else:
        gap = (now_ep - _ep(reference.get("observedAt"))
               if now_ep is not None and
               _ep(reference.get("observedAt")) is not None else None)
        if gap is not None and gap > SOAK_INTERRUPTION_GAP_SECONDS:
            state = "interrupted"
            blocker = "長時間にわたり代替継続性証拠なし"
            failure_class = "scheduler_source_failure"
        elif gap is not None and gap > SOAK_HEARTBEAT_GAP_SECONDS:
            state = "verification_gap"
            blocker = "次の継続性証拠を確認中"
            failure_class = "verification_gap"
        elif not reference.get("readBackVerified"):
            state = "verification_gap"
            blocker = "Remote Journal read-back未確認"
            failure_class = "verification_gap"
        elif not any(int(h.get("schedulerDelaySeconds") or 0) <= 5 * 60
                     for h in healthy_fresh):
            state = "scheduler_delayed"
            blocker = "定期実行遅延（backend停止は未確認）"
            failure_class = "scheduler_source_failure"
        elif elapsed is not None and elapsed >= required_hours and any(
                not h.get("retrospectiveEvidence") for h in rows):
            state = "completed"
        else:
            state = "running"
    owner = {
        "not_started": "新buildの有効heartbeat待ち",
        "running": "継続性証拠を確認しながらSoak実行中",
        "scheduler_delayed": ("定期実行が遅れています。アプリ本体の停止は"
                              "確認されていません。"),
        "verification_gap": "一部の継続性証拠が未確認です。",
        "interrupted": "継続稼働を証明できない重大な空白があります。",
        "completed": f"{required_hours}時間の継続性証拠を確認済み",
    }[state]
    return {"soakId": soak.get("soakId"),
            "buildSha": soak.get("buildSha"),
            "state": state, "heartbeatCount": len(rows),
            "lastHeartbeatAt": last.get("observedAt") if last else None,
            "lastHeartbeatSource": last.get("source") if last else None,
            "lastHeartbeat": last, "elapsedHours": elapsed or 0,
            "maximumEvidenceGapSeconds": int(max_evidence_gap),
            "schedulerContinuityVerified":
                scheduler_continuity_verified,
            "blockerJa": blocker, "ownerReadableJa": owner,
            "failureClass": failure_class,
            "reason": failure_reason,
            "warningSources": warning_sources,
            "warningSource": (warning_sources[0] if len(warning_sources) == 1
                              else None),
            "schedulerAuthority": {
                "primary": "ec2_systemd", "backup": "github_schedule",
                "manual": "diagnostic_only"},
            "sourceLastSeenAt": {
                source: heartbeat.get("observedAt")
                for source, heartbeat in source_latest.items()},
            "referenceHeartbeatSource": (reference.get("source")
                                         if reference else None)}


def build_soak(*, soak: Dict[str, Any], now_iso: str, startup_state: str,
               process_booted_at: Optional[str] = None,
               ops_missed: int = 0, ops_failed_safe: int = 0,
               unresolved_critical_incidents: int = 0,
               durability_integrity: str = "unknown",
               required_hours: int = 72,
               current_build_sha: Optional[str] = None) -> Dict[str, Any]:
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
    state_view = build_soak_state(
        soak=soak, now_iso=now_iso,
        current_build_sha=current_build_sha or soak.get("buildSha"),
        required_hours=required_hours)
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
            "previousSoak": copy.deepcopy(soak.get("previousSoak")),
            "ownerReadableJa": ja,
            # statusは既存API互換、stateはv12.3.1 heartbeat state machine。
            **state_view}


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
                    acked_keys=None,
                    compacted_type_counts: Optional[Dict[str, int]] = None,
                    now_iso: str = "") -> Dict[str, Any]:
    """OperationalJournalSummary。compact済みの歴代件数をゼロ表示しない
    (active WALと歴代合計を分離ラベル)。
    v12.2.10: remote committed/pendingは検証済みread-back ackの冪等キー
    (acked_keys)のみから導出 — 復元時刻/生成時刻のプロキシ比較は廃止。"""
    evs = [e for e in (events or []) if isinstance(e, dict)]
    counts: Dict[str, int] = {}
    for e in evs:
        k = e.get("eventType") or "unknown"
        counts[k] = counts.get(k, 0) + 1
    for k, v in (compacted_type_counts or {}).items():
        counts[k] = counts.get(k, 0) + int(v or 0)
    active = len(evs)
    compact_n = sum(int(v or 0) for v in (compacted_type_counts or {}).values())
    total = max(int(total_observed or 0), active + compact_n)
    compacted = max(compact_n, total - active)
    ak = set(acked_keys or ())
    remote_committed = sum(
        1 for e in evs if str(e.get("idempotencyKey")) in ak)
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
