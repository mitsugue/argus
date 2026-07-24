# -*- coding: utf-8 -*-
"""ARGUS Session-Aware Scheduler — v12.3.2(純・stdlibのみ)。

固定壁時計cronだけに依存しない: 市場カレンダー/セッション状態からミッションを
冪等生成し、lease/claim・期限切れ回収・見逃し検知・重複防止を提供する。
実行体の正本はEC2 systemd timer。GitHub Actionsはbackup、manualは診断専用。
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


UTC = timezone.utc
MISSION_WINDOW_INTERVAL_SECONDS = 30 * 60
MISSION_WINDOW_OFFSET_MINUTE = 7
# 2026-07-17--19 の Actions 実履歴では */30 が 30--90分超遅延し、
# 複数windowが欠落した。通常のstep起動余裕を5分、1 cadence以内を遅延、
# 3 cadence以内を重大遅延、それ以上をmissedとして分離する。
MISSION_DELAYED_AFTER_SECONDS = 5 * 60
MISSION_SEVERE_AFTER_SECONDS = 30 * 60
MISSION_MISSED_AFTER_SECONDS = 90 * 60
MISSION_WINDOW_RETRY_LEASE_SECONDS = 10 * 60
MISSION_CATCHUP_LIMIT = 2
SCHEDULER_SOURCE_PRIORITY = {
    "ec2_systemd": 1,
    "github_schedule": 2,
    "manual": 3,
}
_LEGACY_SOURCE_MAP = {"schedule": "github_schedule"}


def normalize_trigger_source(source: Any) -> Optional[str]:
    """旧schedule表記を安全に受けつつ、authorityを3種へ正規化する。"""
    normalized = _LEGACY_SOURCE_MAP.get(str(source), str(source))
    return normalized if normalized in SCHEDULER_SOURCE_PRIORITY else None


def scheduler_source_priority(source: Any) -> Optional[int]:
    normalized = normalize_trigger_source(source)
    return SCHEDULER_SOURCE_PRIORITY.get(normalized) if normalized else None


def _aware(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _z(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def scheduler_delay_class(delay_seconds: int) -> str:
    delay = max(0, int(delay_seconds))
    if delay <= MISSION_DELAYED_AFTER_SECONDS:
        return "on_time"
    if delay <= MISSION_SEVERE_AFTER_SECONDS:
        return "delayed"
    if delay <= MISSION_MISSED_AFTER_SECONDS:
        return "severely_delayed"
    return "missed"


def mission_window(*, observed_at: str, trigger_source: str = "github_schedule",
                   scheduled_for: Optional[str] = None,
                   offset_minute: int = MISSION_WINDOW_OFFSET_MINUTE
                   ) -> Optional[Dict[str, Any]]:
    """UTC 30分windowを決定論生成。古い時刻を現在windowへ付け替えない。"""
    observed = _aware(observed_at)
    trigger_source = normalize_trigger_source(trigger_source)
    if observed is None or trigger_source is None:
        return None
    if scheduled_for:
        scheduled = _aware(scheduled_for)
    else:
        offset = int(offset_minute) * 60
        slot = int((observed.timestamp() - offset) //
                   MISSION_WINDOW_INTERVAL_SECONDS)
        scheduled = datetime.fromtimestamp(
            slot * MISSION_WINDOW_INTERVAL_SECONDS + offset, tz=UTC)
    if scheduled is None or scheduled > observed:
        return None
    delay = int((observed - scheduled).total_seconds())
    scheduled_iso = _z(scheduled)
    return {
        "missionWindowId": f"mw-{scheduled_iso}",
        "scheduledFor": scheduled_iso,
        "triggeredAt": _z(observed),
        "triggerSource": trigger_source,
        "sourcePriority": scheduler_source_priority(trigger_source),
        "receivedAt": _z(observed),
        "delaySeconds": delay,
        "delayClassification": scheduler_delay_class(delay),
    }


def apply_window_history(window: Dict[str, Any],
                         records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """前回自然windowから欠落窓と実効遅延を導出（cron式から捏造しない）。"""
    rec = dict(window)
    if rec.get("triggerSource") == "manual":
        rec.update({"rawDelaySeconds": rec.get("delaySeconds", 0),
                    "missedWindowCount": 0, "windowGapSeconds": None})
        return rec
    prior = [r for r in records if r.get("triggerSource") != "manual" and
             r.get("scheduledFor") and
             str(r.get("scheduledFor")) < str(rec.get("scheduledFor"))]
    last = max(prior, key=lambda r: str(r.get("scheduledFor"))) if prior else None
    raw_delay = int(rec.get("delaySeconds") or 0)
    if not last:
        rec.update({"rawDelaySeconds": raw_delay, "missedWindowCount": 0,
                    "windowGapSeconds": None,
                    "previousMissionWindowId": None})
        return rec
    prev_at = _aware(last.get("scheduledFor"))
    current_at = _aware(rec.get("scheduledFor"))
    observed = _aware(rec.get("triggeredAt"))
    if prev_at is None or current_at is None or observed is None:
        return rec
    gap = max(0, int((current_at - prev_at).total_seconds()))
    missed = max(0, gap // MISSION_WINDOW_INTERVAL_SECONDS - 1)
    next_expected = prev_at + timedelta(seconds=MISSION_WINDOW_INTERVAL_SECONDS)
    effective_delay = max(raw_delay, int((observed - next_expected).total_seconds()))
    rec.update({
        "rawDelaySeconds": raw_delay,
        "delaySeconds": max(0, effective_delay),
        "delayClassification": scheduler_delay_class(effective_delay),
        "missedWindowCount": missed,
        "windowGapSeconds": gap,
        "previousMissionWindowId": last.get("missionWindowId"),
    })
    return rec


def begin_mission_window(records: List[Dict[str, Any]], *,
                         window: Dict[str, Any], build_sha: Optional[str],
                         started_at: str,
                         runtime_version: Optional[str] = None
                         ) -> Tuple[Dict[str, Any], bool]:
    """同一windowの完了後重複を抑止。失敗/lease切れだけ再試行可能。"""
    wid = window.get("missionWindowId")
    existing = next((r for r in records if r.get("missionWindowId") == wid),
                    None)
    now = _aware(started_at)
    if existing is not None:
        terminal = existing.get("status") in ("completed", "expected_skip")
        started = _aware(existing.get("startedAt"))
        leased = (existing.get("status") == "started" and now is not None and
                  started is not None and
                  (now - started).total_seconds() <
                  MISSION_WINDOW_RETRY_LEASE_SECONDS)
        if terminal or leased:
            existing["duplicateSuppressed"] = int(
                existing.get("duplicateSuppressed") or 0) + 1
            existing["lastDuplicateAt"] = started_at
            existing["lastDuplicateSource"] = window.get("triggerSource")
            existing["duplicateSources"] = sorted(set(
                list(existing.get("duplicateSources") or []) +
                [str(window.get("triggerSource") or "unknown")]))
            return existing, False
        existing.update({
            **window, "startedAt": started_at, "completedAt": None,
            "status": "started", "buildSha": build_sha,
            "runtimeVersion": runtime_version,
            "leaseOwner": window.get("triggerSource"),
            "leaseExpiresAt": (_z(now + timedelta(
                seconds=MISSION_WINDOW_RETRY_LEASE_SECONDS)) if now else None),
            "finalStatus": None,
            "retryCount": int(existing.get("retryCount") or 0) + 1,
            "errorClass": None,
        })
        return existing, True
    rec = {
        **window, "startedAt": started_at, "completedAt": None,
        "status": "started", "buildSha": build_sha,
        "runtimeVersion": runtime_version,
        "leaseOwner": window.get("triggerSource"),
        "leaseExpiresAt": (_z(now + timedelta(
            seconds=MISSION_WINDOW_RETRY_LEASE_SECONDS)) if now else None),
        "finalStatus": None,
        "retryCount": 0, "duplicateSuppressed": 0, "errorClass": None,
    }
    records.append(rec)
    return rec, True


def finish_mission_window(record: Dict[str, Any], *, completed_at: str,
                          status: str = "completed",
                          error_class: Optional[str] = None) -> Dict[str, Any]:
    if status not in ("completed", "expected_skip", "partial",
                      "degraded", "failed"):
        status = "failed"
        error_class = error_class or "invalid_terminal_status"
    record["completedAt"] = completed_at
    record["status"] = status
    record["finalStatus"] = status
    record["errorClass"] = str(error_class)[:80] if error_class else None
    return record


def batch_limit_reached(*, processed: int, max_events: int,
                        elapsed_seconds: float,
                        max_seconds: float) -> bool:
    """Pure guard used before claiming the next durable transition."""
    return (int(processed) >= max(1, int(max_events)) or
            float(elapsed_seconds) >= max(0.0, float(max_seconds)))


def bounded_catchup_windows(*, last_scheduled_for: Optional[str],
                            current_scheduled_for: str,
                            limit: int = MISSION_CATCHUP_LIMIT) -> List[str]:
    """診断用の限定catch-up候補。呼び出し側が過去windowを現在扱いしない。"""
    last = _aware(last_scheduled_for) if last_scheduled_for else None
    current = _aware(current_scheduled_for)
    if last is None or current is None or current <= last:
        return []
    out = []
    cursor = last + timedelta(seconds=MISSION_WINDOW_INTERVAL_SECONDS)
    while cursor < current and len(out) < max(0, int(limit)):
        out.append(f"mw-{_z(cursor)}")
        cursor += timedelta(seconds=MISSION_WINDOW_INTERVAL_SECONDS)
    return out


def scheduled_mission_summary(records: List[Dict[str, Any]], *,
                              now_iso: str) -> Dict[str, Any]:
    rows = sorted((r for r in records if isinstance(r, dict) and
                   r.get("triggerSource") != "manual"),
                  key=lambda r: str(r.get("scheduledFor") or ""))
    last = rows[-1] if rows else None
    current = mission_window(observed_at=now_iso,
                             trigger_source="ec2_systemd")
    next_at = None
    if current and _aware(current["scheduledFor"]):
        next_at = _z(_aware(current["scheduledFor"]) +
                     timedelta(seconds=MISSION_WINDOW_INTERVAL_SECONDS))
    return {
        "lastScheduledTick": last.get("completedAt") if last else None,
        "nextExpectedTick": next_at,
        "lastDelaySeconds": last.get("delaySeconds") if last else None,
        "lastDelayClassification": (last.get("delayClassification")
                                    if last else "unknown"),
        "lastMissedWindowCount": int(last.get("missedWindowCount") or 0)
        if last else 0,
        "currentMissionWindow": (current.get("missionWindowId")
                                 if current else None),
        "lastMissionWindowId": last.get("missionWindowId") if last else None,
        "duplicateSuppressed": sum(int(r.get("duplicateSuppressed") or 0)
                                   for r in rows),
        "windowCount": len(rows),
        "scheduleOffsetMinute": MISSION_WINDOW_OFFSET_MINUTE,
        "catchUpLimit": MISSION_CATCHUP_LIMIT,
        "primaryScheduler": "ec2_systemd",
        "backupScheduler": "github_schedule",
        "manualRole": "diagnostic_only",
        "lastTriggerSource": last.get("triggerSource") if last else None,
        "sourcePriority": dict(SCHEDULER_SOURCE_PRIORITY),
    }

MISSION_TYPES = ("pre_session_research", "pre_session_forecast",
                 "session_open_check", "intraday_anomaly_monitor",
                 "material_move_war_room", "event_precheck",
                 "event_reaction_check", "post_session_snapshot",
                 "forecast_outcome_resolution", "daily_postmortem",
                 "daily_learning", "overnight_osint", "weekly_learning_review",
                 "monthly_model_review", "benchmark_calibration",
                 "missed_mission_recovery")

MISSION_STATUSES = ("scheduled", "claimed", "running", "checkpointed",
                    "complete", "retry_wait", "failed_safe", "missed",
                    "recovered", "skipped")

# セッション定義(JST基準の時刻・市場ごと)。祝日/半日は呼び出し側がis_holiday等で渡す。
_DAILY_PLAN = (
    # (missionType, market, jst_hhmm)
    ("pre_session_forecast", "JP", "08:30"),
    ("session_open_check", "JP", "09:05"),
    ("post_session_snapshot", "JP", "15:40"),
    ("pre_session_forecast", "US", "22:00"),
    ("post_session_snapshot", "US", "05:10"),   # 翌暦日側
    ("forecast_outcome_resolution", "ALL", "16:00"),
    ("daily_postmortem", "ALL", "16:10"),
    ("daily_learning", "ALL", "16:20"),
    ("overnight_osint", "ALL", "02:00"),
)


def mission(*, mission_type: str, market: str, session_date: str,
            scheduled_for: str, execution_plane: str = "research_server",
            symbol: Optional[str] = None, model_epoch: str = "",
            rubric_version: str = "") -> Optional[Dict[str, Any]]:
    if mission_type not in MISSION_TYPES:
        return None
    idem = f"{mission_type}:{market}:{session_date}" + (f":{symbol}" if symbol else "")
    return {"missionId": f"m-{idem}", "missionType": mission_type,
            "market": market, "symbol": symbol,
            "scheduledFor": scheduled_for, "sessionDate": session_date,
            "idempotencyKey": idem, "executionPlane": execution_plane,
            "status": "scheduled", "retryCount": 0, "maxRetries": 3,
            "claimedAt": None, "startedAt": None, "completedAt": None,
            "lastHeartbeatAt": None, "checkpoint": None, "nextRetryAt": None,
            "failureReasonRedacted": None, "costState": None,
            "dataQualityState": None, "privacyMode": "public_safe",
            "modelEpoch": model_epoch, "rubricVersion": rubric_version}


def generate_daily_missions(*, session_date: str, now_iso: str,
                            jp_holiday: bool = False, us_holiday: bool = False,
                            existing: Optional[List[Dict[str, Any]]] = None,
                            model_epoch: str = "",
                            rubric_version: str = "") -> List[Dict[str, Any]]:
    """当日ミッションの冪等生成。既存キーはスキップ(重複ゼロ)。祝日はskipped発行。"""
    have = {m.get("idempotencyKey") for m in (existing or [])}
    out = []
    for mtype, market, hhmm in _DAILY_PLAN:
        holiday = (market == "JP" and jp_holiday) or (market == "US" and us_holiday)
        m = mission(mission_type=mtype, market=market, session_date=session_date,
                    scheduled_for=f"{session_date}T{hhmm}:00+09:00",
                    model_epoch=model_epoch, rubric_version=rubric_version)
        if m is None or m["idempotencyKey"] in have:
            continue
        if holiday:
            m["status"] = "skipped"
            m["failureReasonRedacted"] = "market_holiday"
        out.append(m)
        have.add(m["idempotencyKey"])
    return out


def generate_periodic_missions(*, session_date: str, weekday: int,
                               day_of_month: int,
                               existing: Optional[List[Dict[str, Any]]] = None,
                               model_epoch: str = "",
                               rubric_version: str = "") -> List[Dict[str, Any]]:
    """週次(月曜)/月次(1日)ミッションの冪等生成。"""
    have = {m.get("idempotencyKey") for m in (existing or [])}
    out = []
    plans = []
    if weekday == 0:
        plans.append(("weekly_learning_review", "ALL", "07:30"))
    if day_of_month == 1:
        plans.append(("monthly_model_review", "ALL", "07:45"))
        plans.append(("benchmark_calibration", "ALL", "07:50"))
    for mtype, market, hhmm in plans:
        m = mission(mission_type=mtype, market=market, session_date=session_date,
                    scheduled_for=f"{session_date}T{hhmm}:00+09:00",
                    model_epoch=model_epoch, rubric_version=rubric_version)
        if m and m["idempotencyKey"] not in have:
            out.append(m)
            have.add(m["idempotencyKey"])
    return out


SOAK_REQUIRED_HOURS = 72
SOAK_STATUSES = ("architecture_ready", "active_unproven", "soak_in_progress",
                 "operationally_verified", "degraded")


def soak_status(*, started_at: Optional[str], now_iso: str,
                summary: Dict[str, Any]) -> Dict[str, Any]:
    """24-72h soak判定。短期稼働から実証を主張しない。"""
    if not started_at:
        return {"status": "architecture_ready", "elapsedHours": 0,
                "requiredHours": SOAK_REQUIRED_HOURS,
                "ownerReadableJa": "soak未開始"}
    hrs = _min_between(started_at, now_iso) / 60.0
    missed = int(summary.get("missed") or 0)
    failed = int(summary.get("failedSafe") or 0)
    if missed > 2 or failed > 3:
        st = "degraded"
    elif hrs >= SOAK_REQUIRED_HOURS:
        st = "operationally_verified"
    elif hrs >= 1:
        st = "soak_in_progress"
    else:
        st = "active_unproven"
    return {"status": st, "elapsedHours": round(hrs, 1),
            "requiredHours": SOAK_REQUIRED_HOURS,
            "startedAt": started_at,
            "ownerReadableJa": {
                "architecture_ready": "soak未開始",
                "active_unproven": "稼働開始直後 — 実証未了",
                "soak_in_progress": f"soak進行中({round(hrs,1)}h/"
                                    f"{SOAK_REQUIRED_HOURS}h) — 完了まで実証を主張しない",
                "operationally_verified": "72時間soak完了 — 運用実証済み",
                "degraded": "見逃し/失敗が閾値超過 — degraded",
            }[st]}


def claim(m: Dict[str, Any], now_iso: str, lease_min: int = 20) -> bool:
    """lease取得。claimed/runningで心拍が新しければ取れない(分散安全)。"""
    if m.get("status") in ("complete", "skipped", "recovered", "failed_safe"):
        return False                    # 終端状態は再claim不可(重複実行防止)
    hb = m.get("lastHeartbeatAt")
    if m.get("status") in ("claimed", "running") and hb and \
            _min_between(hb, now_iso) < lease_min:
        return False
    m["status"] = "claimed"
    m["claimedAt"] = now_iso
    m["lastHeartbeatAt"] = now_iso
    return True


def _min_between(a: str, b: str) -> float:
    """ISO分差(同日近傍の簡易・タイムゾーンは呼び出し側で正規化済み前提)。"""
    try:
        from datetime import datetime
        fa = datetime.fromisoformat(a.replace("Z", "+00:00"))
        fb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return abs((fb - fa).total_seconds()) / 60.0
    except Exception:
        return 1e9


def complete(m: Dict[str, Any], now_iso: str) -> None:
    m["status"] = "complete"
    m["completedAt"] = now_iso


def fail(m: Dict[str, Any], now_iso: str, reason: str) -> None:
    m["retryCount"] = int(m.get("retryCount") or 0) + 1
    m["failureReasonRedacted"] = str(reason)[:60]
    if m["retryCount"] >= int(m.get("maxRetries") or 3):
        m["status"] = "failed_safe"
    else:
        m["status"] = "retry_wait"
        # 指数バックオフ(分)は呼び出し側がnextRetryAtに反映
        m["nextRetryAt"] = None


def detect_missed(missions: List[Dict[str, Any]], now_iso: str,
                  grace_min: int = 45,
                  max_records: Optional[int] = None) -> List[Dict[str, Any]]:
    """予定時刻+猶予を過ぎて未完了=missed(沈黙消失させない)。"""
    out = []
    for m in missions or []:
        if max_records is not None and len(out) >= max(0, int(max_records)):
            break
        if m.get("status") in ("complete", "skipped", "failed_safe", "missed"):
            continue
        sf = m.get("scheduledFor")
        if sf and _min_between(sf, now_iso) > grace_min and sf < now_iso:
            m["status"] = "missed"
            out.append(m)
    return out


def recover(m: Dict[str, Any], now_iso: str) -> None:
    if m.get("status") == "missed":
        m["status"] = "recovered"
        m["completedAt"] = now_iso


def ops_summary(missions: List[Dict[str, Any]]) -> Dict[str, Any]:
    by = {}
    for m in missions or []:
        by[m.get("status")] = by.get(m.get("status"), 0) + 1
    total = len(missions or [])
    done = by.get("complete", 0) + by.get("recovered", 0) + by.get("skipped", 0)
    return {"total": total, "byStatus": by,
            "completionRatePct": int(100 * done / total) if total else None,
            "missed": by.get("missed", 0),
            "failedSafe": by.get("failed_safe", 0)}
