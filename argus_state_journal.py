# -*- coding: utf-8 -*-
"""ARGUS Write-Through Operational Journal — v12.2.7(純・stdlibのみ)。

正直な耐久保証: ①クリティカル遷移で即時にローカルWAL(/tmp)へappend(プロセス
再起動=損失ほぼ0) ②30分毎cronがledgerブランチへflush(リモート最大損失窓≦30分)。
厳密write-throughではなくbuffered write-through — この保証を偽らない。
"""
import hashlib
import json
from typing import Any, Dict, List, Optional

JOURNAL_SCHEMA_VERSION = "journal-v1"
EVENT_TYPES = ("mission_scheduled", "mission_claimed", "mission_checkpointed",
               "mission_completed", "mission_retry_wait", "mission_failed_safe",
               "mission_missed", "mission_recovered", "forecast_issued",
               "forecast_superseded", "outcome_resolved", "incident_opened",
               "incident_resolved", "soak_started", "soak_heartbeat",
               "soak_invalidated", "soak_completed", "postmortem_created",
               "weekly_report_created", "monthly_report_created",
               "learning_proposal_created", "challenger_created",
               "challenger_updated", "research_measurement_recorded",
               "calibration_updated",
               # v12.2.9: 遷移→イベント行列の完全化(soak中断/承認/昇格系)
               "soak_interrupted", "material_learning_approved",
               "champion_promoted", "champion_rolled_back")
ORIGINS = ("forward_live", "historical_replay", "scheduler",
           "admin_validation", "recovery")
_PRIVATE_FIELDS = ("quantity", "avgCost", "acquisitionPrice", "pnl",
                   "fundValue", "passphrase", "hmac", "token", "apiKey")


def _hash(o: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def event(*, event_type: str, aggregate_type: str, aggregate_id: str,
          sequence: int, occurred_at: str, payload: Dict[str, Any],
          origin: str = "scheduler", model_epoch: str = "",
          rubric_version: str = "",
          prev_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """遷移イベント生成。私的フィールドを含むpayloadは拒否(None)。"""
    if event_type not in EVENT_TYPES or origin not in ORIGINS:
        return None
    flat = json.dumps(payload, ensure_ascii=False)
    if any(f'"{k}"' in flat for k in _PRIVATE_FIELDS):
        return None                     # public-safe journalに私的データ不可
    idem = f"{event_type}:{aggregate_type}:{aggregate_id}:{sequence}"
    body = {"eventType": event_type, "aggregateType": aggregate_type,
            "aggregateId": aggregate_id, "sequence": int(sequence),
            "occurredAt": occurred_at,
            "schemaVersion": JOURNAL_SCHEMA_VERSION,
            "publicSafePayload": payload, "idempotencyKey": idem,
            "origin": origin, "modelEpoch": model_epoch,
            "rubricVersion": rubric_version,
            "previousEventHash": prev_hash,
            "privacyClassification": "public_safe"}
    body["eventId"] = f"ev-{_hash(body)}"
    body["integrityHash"] = _hash(body)
    return body


def append(journal: List[Dict[str, Any]], ev: Optional[Dict[str, Any]],
           max_len: int = 400) -> bool:
    """冪等append。重複キーは無視・単調sequence違反は拒否(False)。"""
    if not ev:
        return False
    if any(e.get("idempotencyKey") == ev["idempotencyKey"] for e in journal):
        return False                    # 冪等: 重複無視
    last_seq = max((e.get("sequence", -1) for e in journal
                    if e.get("aggregateType") == ev["aggregateType"] and
                    e.get("aggregateId") == ev["aggregateId"]), default=-1)
    if ev["sequence"] <= last_seq:
        return False                    # 単調性違反は安全拒否
    journal.append(ev)
    while len(journal) > max_len:
        journal.pop(0)
    return True


def verify(ev: Dict[str, Any]) -> bool:
    body = {k: v for k, v in ev.items() if k != "integrityHash"}
    return ev.get("integrityHash") == _hash(body)


def load_valid(events: List[Any]) -> Dict[str, Any]:
    """復元: 壊れたイベントは捨てて数える(last-known-good再構成)。"""
    ok, corrupt = [], 0
    for e in (events or []):
        if isinstance(e, dict) and verify(e):
            ok.append(e)
        else:
            corrupt += 1
    return {"events": ok, "corruptCount": corrupt}


# ── Phase 6: Forecast Issuance Decision ─────────────────────────────────────

ISSUANCE_DECISIONS = ("eligible", "wait_next_session",
                      "recovered_intraday_eligible", "stale_opportunity",
                      "insufficient_data", "mock_blocked", "duplicate",
                      "private_context_required")


def forecast_issuance_decision(*, store_ready: bool, mock_data: bool,
                               already_issued_today: bool,
                               now_hhmm: str, market: str,
                               session_close_hhmm: str = "15:30") -> Dict[str, Any]:
    """発行判定 — 曖昧な「未発行」を出さない。回収発行は意味のある残り時間のみ。
    backdateなし(informationCutoffAt=実時刻)・セッション後は翌セッション待ち。"""
    if mock_data:
        d = "mock_blocked"; ja = "mock/デモデータ — 発行不可"
    elif already_issued_today:
        d = "duplicate"; ja = "本日分は発行済み(冪等)"
    elif not store_ready:
        d = "insufficient_data"; ja = "調査ストア未ウォーム — ウォームアップ後に再判定"
    elif market == "JP" and now_hhmm >= session_close_hhmm:
        d = "wait_next_session"
        ja = "当日セッション終了後 — 翌セッションの寄り前に発行"
    elif market == "JP" and now_hhmm >= "13:00":
        d = "stale_opportunity"
        ja = "残り取引時間が短く当日予測の意味が薄い — 翌セッション待ち"
    elif market == "JP" and now_hhmm > "09:00":
        d = "recovered_intraday_eligible"
        ja = "回収発行可(ザラ場・情報カットオフは実時刻・backdateなし)"
    else:
        d = "eligible"; ja = "発行可(寄り前)"
    return {"decision": d, "ownerReadableJa": ja,
            "recoveryPermitted": d == "recovered_intraday_eligible",
            "nextOpportunityJa": ("翌営業日 08:30 JST"
                                  if d in ("wait_next_session",
                                           "stale_opportunity") else None)}
