# -*- coding: utf-8 -*-
"""ARGUS Session-Aware Scheduler — v12.2.1 Phase 1(純・stdlibのみ)。

固定壁時計cronだけに依存しない: 市場カレンダー/セッション状態からミッションを
冪等生成し、lease/claim・期限切れ回収・見逃し検知・重複防止を提供する。
実行体は既存cron(caos-scan等)が /admin/missions/tick を叩く — 新規常駐なし。
"""
from typing import Any, Dict, List, Optional

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
    if m.get("status") in ("complete", "skipped"):
        return False
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
                  grace_min: int = 45) -> List[Dict[str, Any]]:
    """予定時刻+猶予を過ぎて未完了=missed(沈黙消失させない)。"""
    out = []
    for m in missions or []:
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
