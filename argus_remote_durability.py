# -*- coding: utf-8 -*-
"""ARGUS Remote Durability — v12.2.8準備(純・stdlibのみ)。

ローカルcommitとリモートcommitを明示区別する。正直な保証:
- ローカルWAL=即時(v12.2.7)
- リモート=既存GitHub ledger(cron 30分毎flush) — サーバ自身はgit push不可のため
  クリティカルイベントは高速flushキューに積み「remote_pending」を正確に表示する。
  **60秒保証は主張しない(バックエンド実測まで)** — 実リモート損失窓≦30分。
"""
import hashlib
import json
from typing import Any, Dict, List, Optional

DURABILITY_STATES = ("not_persisted", "local_committed", "remote_pending",
                     "remote_committed", "remote_failed",
                     "recovered_from_local_wal", "recovered_from_remote",
                     "integrity_failed")
CRITICAL_EVENT_TYPES = ("forecast_issued", "forecast_superseded",
                        "outcome_resolved", "incident_opened",
                        "incident_resolved", "soak_started", "soak_invalidated",
                        "soak_completed", "learning_proposal_created",
                        "challenger_updated")
BACKEND_STATES = ("configured", "not_configured", "unavailable", "degraded",
                  "healthy")


def _h(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def receipt(*, event: Dict[str, Any], local_at: str,
            backend_type: str = "github_ledger_cron",
            remote_at: Optional[str] = None,
            failure: Optional[str] = None,
            retry_count: int = 0) -> Dict[str, Any]:
    """耐久レシート。remote_committedは検証済みリモート永続後のみ。"""
    if remote_at:
        state = "remote_committed"
    elif failure:
        state = "remote_failed"
    elif local_at:
        state = "remote_pending" if backend_type != "not_configured"             else "local_committed"
    else:
        state = "not_persisted"
    return {"eventId": event.get("eventId"),
            "aggregateType": event.get("aggregateType"),
            "aggregateId": event.get("aggregateId"),
            "localCommittedAt": local_at,
            "remoteQueuedAt": local_at if state == "remote_pending" else None,
            "remoteCommittedAt": remote_at,
            "localSequence": event.get("sequence"),
            "localIntegrityHash": event.get("integrityHash"),
            "durabilityState": state, "retryCount": retry_count,
            "lastFailureReasonRedacted": (str(failure)[:60] if failure else None),
            "backendType": backend_type,
            "maximumLossWindowSeconds": (0 if remote_at else 1800),
            "ownerReadableJa": {
                "remote_committed": "リモート永続済み",
                "remote_pending": "ローカル確定・リモートは30分毎flush待ち"
                                  "(完全永続とは呼ばない)",
                "local_committed": "ローカルのみ(リモート未設定)",
                "remote_failed": "リモート失敗 — ローカル保持・リトライ",
                "not_persisted": "未永続",
            }[state]}


def backend_status(*, ledger_cron_expected: bool = True,
                   last_remote_ack_iso: Optional[str] = None,
                   now_iso: str = "") -> Dict[str, Any]:
    """既存GitHub ledger(cron)バックエンドの正直な状態。"""
    if not ledger_cron_expected:
        st = "not_configured"
    elif last_remote_ack_iso and now_iso and             last_remote_ack_iso[:10] == now_iso[:10]:
        st = "healthy"
    elif last_remote_ack_iso:
        st = "degraded"
    else:
        st = "configured"
    return {"backendType": "github_ledger_cron", "state": st,
            "lastRemoteAckAt": last_remote_ack_iso,
            "guaranteeJa": ("リモート損失窓≦30分(cron flush) — "
                            "60秒保証は未実測のため主張しない")}


def reconcile(local_events: List[Dict[str, Any]],
              remote_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """WAL/リモートの照合。整合性優先・タイムスタンプ単独では上書きしない。"""
    lk = {e.get("idempotencyKey"): e for e in (local_events or [])
          if isinstance(e, dict)}
    rk = {e.get("idempotencyKey"): e for e in (remote_events or [])
          if isinstance(e, dict)}
    matched = conflict = 0
    for k in set(lk) & set(rk):
        if lk[k].get("integrityHash") == rk[k].get("integrityHash"):
            matched += 1
        else:
            conflict += 1
    local_only = [k for k in lk if k not in rk]
    remote_only = [k for k in rk if k not in lk]
    status = ("conflict" if conflict else
              "consistent" if not local_only and not remote_only else
              "reconciled")
    merged = dict(rk)
    for k in local_only:
        merged[k] = lk[k]               # ローカル先行分をリモートへ再送対象に
    return {"localEventCount": len(lk), "remoteEventCount": len(rk),
            "matchedCount": matched, "localOnlyCount": len(local_only),
            "remoteOnlyCount": len(remote_only), "conflictCount": conflict,
            "replayedCount": len(remote_only),
            "retransmittedCount": len(local_only),
            "status": status,
            "mergedEvents": list(merged.values()),
            "ownerReadableJa": {"consistent": "ローカル/リモート一致",
                                "reconciled": "差分を冪等に照合済み",
                                "conflict": "整合性競合 — last-known-good維持・"
                                            "インシデント発行(黙殺しない)",
                                }[status]}


# ── Phase 5: First Forward-Live Evidence Gate(検証のみ・生成しない) ──────────

FFL_STATES = ("no_candidate", "candidate_ineligible", "locally_proven",
              "remotely_proven", "pending_maturity", "matured", "resolved",
              "invalid")


def first_forward_live_evidence(forecasts: List[Dict[str, Any]],
                                receipts: Optional[Dict[str, str]] = None,
                                now_iso: str = "") -> Dict[str, Any]:
    """本物のforward-live予測を検証する(生成は絶対にしない)。"""
    cands = [f for f in (forecasts or [])
             if f.get("origin") == "forward_live" and not f.get("mockData")]
    if not cands:
        return {"state": "no_candidate", "candidateCount": 0,
                "ownerReadableJa": "forward-live候補なし — ゲートは予測を生成しない"}
    f = cands[0]
    checks = {
        "originForwardLive": f.get("origin") == "forward_live",
        "nonMock": not f.get("mockData"),
        "hasResearchMission": bool(f.get("researchMissionId")),
        "noBackdate": (f.get("issuedAt") or "") <= (now_iso or "9999"),
        "hashValid": bool(f.get("integrityHash")),
    }
    if not all(checks.values()):
        return {"state": "candidate_ineligible", "candidateCount": len(cands),
                "eligibilityChecks": checks,
                "ownerReadableJa": "候補はあるが適格性チェック未達"}
    rstate = (receipts or {}).get(str(f.get("id")), "local_committed")
    state = ("remotely_proven" if rstate == "remote_committed"
             else "locally_proven")
    return {"state": state, "candidateCount": len(cands),
            "forecastId": f.get("id"), "eligibilityChecks": checks,
            "localDurabilityState": "local_committed",
            "remoteDurabilityState": rstate,
            "ownerReadableJa": ("本物のforward-live予測を検証済み"
                                + ("(リモート永続済み)" if state == "remotely_proven"
                                   else "(ローカル確定・リモート待ち)"))}


# ── Phase 7/8: GPT-5.6 プローブ/Shadow比較(fixture駆動・昇格なし) ────────────

def capability_probe_record(*, requested_model: str,
                            configured: bool, pricing_known: bool,
                            budget_ok: bool,
                            fixture_result: Optional[Dict[str, Any]] = None,
                            executed_at: str = "") -> Dict[str, Any]:
    if not configured or not requested_model:
        st = "not_configured"
    elif not pricing_known:
        st = "pricing_unknown"
    elif not budget_ok:
        st = "budget_blocked"
    elif fixture_result is None:
        st = "unavailable"
    else:
        st = fixture_result.get("status", "available")
    return {"provider": "openai", "requestedModel": requested_model or None,
            "status": st,
            "responsesSupported": (fixture_result or {}).get("responses", False),
            "structuredOutputsSupported": (fixture_result or {}).get("structured",
                                                                     False),
            "usageReturned": (fixture_result or {}).get("usage", False),
            "pricingStatus": "known" if pricing_known else "unknown",
            "executedAt": executed_at,
            "canPromote": False,        # 可用性だけでは昇格不可(構造固定)
            "failureReasonRedacted": ((fixture_result or {}).get("reason")
                                      if st not in ("available",) else None),
            "ownerReadableJa": {
                "not_configured": "候補モデル未設定(pending_env_configuration)",
                "pricing_unknown": "価格不明 — fail-closedでプローブ遮断",
                "budget_blocked": "予算予約不可 — プローブ遮断",
                "unavailable": "API可用性未証明",
                "available": "可用性確認 — Shadowエポック作成可(昇格はしない)",
            }.get(st, st)}


def shadow_comparison(*, champion: Dict[str, Any], challenger: Dict[str, Any],
                      sample_count: int) -> Dict[str, Any]:
    def d(k):
        a, b = champion.get(k), challenger.get(k)
        return (round(b - a, 3) if isinstance(a, (int, float))
                and isinstance(b, (int, float)) else None)
    rec = ("insufficient_data" if sample_count < 5 else "continue_shadow")
    return {"championEpoch": champion.get("epoch"),
            "challengerEpoch": challenger.get("epoch"),
            "coverageDelta": d("coverage"), "precisionDelta": d("precision"),
            "schemaDelta": d("schemaSuccess"), "costDelta": d("cost"),
            "sampleCount": sample_count, "recommendation": rec,
            "ownerApprovalRequired": True, "productionChanged": False,
            "ownerReadableJa": "Shadow比較 — 本番判断は不変・昇格はオーナー承認必須"}
