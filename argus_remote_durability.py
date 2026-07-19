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
                        "outcome_unresolved", "outcome_retry_scheduled",
                        "outcome_resolved", "outcome_expired", "incident_opened",
                        "incident_resolved", "soak_started",
                        "soak_interrupted",  # v12.2.10: 中断もcritical(隠さない)
                        "soak_invalidated",
                        "soak_completed", "learning_proposal_created",
                        "challenger_updated", "material_learning_approved",
                        "champion_promoted", "champion_rolled_back")
BACKEND_STATES = ("configured", "not_configured", "unavailable", "degraded",
                  "healthy")


def _h(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def _ep(iso):
    """ISO→epoch(TZ混在の文字列比較は禁止 — v12.2.9でbackdate判定を修正)。
    naive時刻はJSTとして解釈(ARGUS慣行) — 実行マシンのTZに依存させない。"""
    if not iso:
        return None
    try:
        from datetime import datetime, timedelta, timezone
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone(timedelta(hours=9)))
        return d.timestamp()
    except Exception:
        return None


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
        # v12.2.9: JST発行時刻とUTC nowの文字列比較はbackdate誤判定を生む
        # (JST 09時以降が常にineligible化する欠陥) — epoch比較に修正
        "noBackdate": (_ep(f.get("issuedAt")) is None or _ep(now_iso) is None
                       or _ep(f.get("issuedAt")) <= _ep(now_iso) + 60),
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


# ── v12.2.8 ADDENDUM: 意味論の明確化(測定/台帳origin/信頼性式/版同一性) ──────

def research_measurement_summary(*, latest: Optional[Dict[str, Any]],
                                 stability: Dict[str, Any],
                                 unresolved_important: int,
                                 primary_strength: Optional[int],
                                 fresh_pending: int,
                                 canary_misses: int) -> Dict[str, Any]:
    """最新run/安定測定/証拠ゲート/正式2x認定を別概念として明示する。
    生の比>1.0でも証拠blockerを上書きできない。"""
    ev_blockers = []
    if unresolved_important > 0:
        ev_blockers.append(f"未回収ソース{unresolved_important}件")
    if not primary_strength:
        ev_blockers.append("一次情報不足")
    if fresh_pending > 0:
        ev_blockers.append(f"新鮮候補未検証{fresh_pending}件")
    if canary_misses > 0:
        ev_blockers.append(f"canary見逃し{canary_misses}件")
    ev_status = "blocked" if ev_blockers else (
        "passed" if latest else "insufficient")
    stable_ok = bool(stability.get("currentRatioEligible")) and         stability.get("confidence") in ("medium", "high")
    two_x = {
        "calibrated": bool(stability.get("runCount", 0) >= 3),
        "ratioThresholdPassed": bool((stability.get("medianRatio") or 0) >= 2.0),
        "evidenceGatePassed": ev_status == "passed",
        "primarySourceGatePassed": bool(primary_strength),
        "eligible": False,
    }
    two_x["eligible"] = all(v for k, v in two_x.items() if k != "eligible")
    # v12.2.10: 「正式倍率認定」の曖昧文言を廃止 — 統計的算出可能性と
    # 優位性主張の許可は別概念。統計安定だけでは優位性を正式主張できない。
    superiority_allowed = (stable_ok and ev_status == "passed"
                           and bool(primary_strength)
                           and (stability.get("medianRatio") or 0) > 1.0)
    lines = []
    if latest:
        lines.append(f"最新run: {latest.get('ratio')}x({latest.get('symbol')})")
    if stability.get("medianRatio") is not None:
        lines.append(f"安定中央値: {stability['medianRatio']}x")
    lines.append(f"安定信頼度: {stability.get('confidence')}")
    lines.append("安定倍率算出: " + ("可" if stable_ok else "不可"))
    lines.append("Gemini優位性の正式認定: "
                 + ("可" if superiority_allowed else "不可"))
    lines.append("2x認定: " + ("可" if two_x["eligible"] else "不可"))
    if ev_blockers:
        lines.append("理由: " + " / ".join(ev_blockers))
    return {"latestRun": latest,
            # formallyEligible=deprecated(=統計算出可のみの旧名・値は維持)
            "stableMeasurement": {**stability, "formallyEligible": stable_ok,
                                  "statisticallyStable": stable_ok,
                                  "formallyEligibleDeprecatedJa":
                                      "旧名 — 統計的算出可能性のみを意味する"},
            "evidenceGate": {"unresolvedImportantSources": unresolved_important,
                             "primarySourceStrength": primary_strength,
                             "freshCandidatesPending": fresh_pending,
                             "canaryMisses": canary_misses,
                             "status": ev_status, "blockers": ev_blockers},
            "superiorityClaimAllowed": superiority_allowed,
            "twoXReadinessGate": two_x,
            "ownerReadableJa": " / ".join(lines),
            "semanticsJa": ("最新run=単発の生値・安定測定=3run以上の中央値・"
                            "証拠ゲート=一次/未回収/新鮮/canary・"
                            "統計算出可≠優位性正式認定≠2x認定 — 4概念は別物")}


def research_claim_readiness(*, stable_median_ratio: Optional[float],
                             latest_run_ratio: Optional[float],
                             statistical_confidence: str,
                             run_count: int,
                             evidence_gate_passed: bool,
                             holdout_passed: Optional[bool],
                             primary_source_gate_passed: bool,
                             canary_gate_passed: bool,
                             blockers_ja: Optional[List[str]] = None
                             ) -> Dict[str, Any]:
    """v12.2.10 Phase 8: 統計的算出可能性と優位性/2x主張を構造分離。
    統計安定のみでは優位性を主張できない。最新の生runは主張ゲートを
    上書きできない。holdout未実施はFalse扱い(未実施で主張しない)。"""
    measurable = (run_count >= 3 and stable_median_ratio is not None
                  and statistical_confidence in ("medium", "high"))
    superiority = bool(measurable and evidence_gate_passed
                       and bool(holdout_passed)
                       and primary_source_gate_passed and canary_gate_passed
                       and (stable_median_ratio or 0) > 1.0)
    two_x = bool(superiority and (stable_median_ratio or 0) >= 2.0)
    lines = []
    if measurable:
        lines.append(f"安定倍率を算出可能: {stable_median_ratio}x"
                     f"(信頼度{statistical_confidence})")
    else:
        lines.append("安定倍率を算出不能(run不足/分散/信頼度)")
    lines.append("Gemini優位性の正式認定: " + ("可" if superiority else "不可"))
    lines.append("2x認定: " + ("可" if two_x else "不可"))
    if blockers_ja:
        lines.append("理由: " + "・".join(blockers_ja[:6]))
    return {"statisticalRatioMeasurable": measurable,
            "statisticalConfidence": statistical_confidence,
            "stableMedianRatio": stable_median_ratio,
            "latestRunRatio": latest_run_ratio,
            "evidenceGatePassed": bool(evidence_gate_passed),
            "holdoutPassed": (bool(holdout_passed)
                              if holdout_passed is not None else False),
            "holdoutStatus": ("passed" if holdout_passed else
                              "failed" if holdout_passed is not None
                              else "not_run"),
            "primarySourceGatePassed": bool(primary_source_gate_passed),
            "canaryGatePassed": bool(canary_gate_passed),
            "superiorityClaimAllowed": superiority,
            "twoXClaimAllowed": two_x,
            "exactBlockersJa": list(blockers_ja or []),
            "ownerReadableJa": " / ".join(lines)}


def decision_ledger_origin_summary(forecasts: List[Dict[str, Any]],
                                   outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """forecastCount=2がlive 2件を意味しないことを構造的に明示する。"""
    def _by(rows):
        c = {"forward_live": 0, "historical_replay": 0, "shadow": 0,
             "fixture": 0, "unknown_legacy": 0}
        for r in (rows or []):
            o = r.get("origin")
            # originなしの旧レコードは捏造せずunknown_legacy(採点対象外)
            key = o if o in c else "unknown_legacy"
            c[key] += 1
        c["total"] = len(rows or [])
        return c
    fc = _by(forecasts)
    oc = _by(outcomes)
    live_pending = sum(1 for f in (forecasts or [])
                       if f.get("origin") == "forward_live" and
                       not any(o.get("forecastId") == f.get("id")
                               for o in (outcomes or [])))
    live_resolved = sum(1 for o in (outcomes or [])
                        if o.get("origin") == "forward_live" and
                        o.get("status") == "resolved")
    return {"forecastCounts": fc, "outcomeCounts": oc,
            "forwardLive": {"pending": live_pending,
                            "resolved": live_resolved,
                            "scoreEligible": live_resolved},
            "scoreEligibleForecastCount": fc["forward_live"],
            "scoreEligibleOutcomeCount": live_resolved,
            "ownerReadableJa": (f"Forward-live予測: {fc['forward_live']}件 / "
                                f"replay: {fc['historical_replay']}件 / "
                                f"本番採点可能サンプル: {live_resolved}件")}


def agent_reliability_summary(missions: List[Dict[str, Any]],
                              now_iso: str = "") -> Dict[str, Any]:
    """完遂率の分母を式つきで明示。将来分/祝日skipは失敗ではない・分母0=insufficient。"""
    total = len(missions or [])
    by = {}
    future = 0
    for m in (missions or []):
        by[m.get("status")] = by.get(m.get("status"), 0) + 1
        if m.get("status") == "scheduled" and now_iso and                 str(m.get("scheduledFor", "")) > now_iso:
            future += 1
    completed = by.get("complete", 0)
    recovered = by.get("recovered", 0)
    skipped = by.get("skipped", 0)
    missed = by.get("missed", 0)
    failed = by.get("failed_safe", 0)
    denom = total - future - skipped
    if denom <= 0:
        rate = {"percent": None, "formulaJa": "分母0 — insufficient(100%とは言わない)"}
    else:
        rate = {"numerator": completed + recovered, "denominator": denom,
                "percent": int(100 * (completed + recovered) / denom),
                "formulaJa": ("(complete+recovered)÷(総数−未来予定−祝日skip) — "
                              "将来分と祝日は失敗に数えない・recoveredは別掲")}
    return {"totalMissions": total, "completedNormally": completed,
            "recovered": recovered, "skippedExpected": skipped,
            "scheduledFuture": future, "missedUnrecovered": missed,
            "failedSafe": failed, "completionRate": rate,
            "ownerReadableJa": (f"正常完了{completed}+回収{recovered} / "
                                f"対象{max(denom,0)}(将来{future}・skip{skipped}除外)")}


def build_identity(*, app_version: str, backend_sha: str,
                   frontend_version: str) -> Dict[str, Any]:
    """版同一性 — 空値は捏造せずincomplete。"""
    incomplete = not app_version or not backend_sha
    mismatch = (bool(app_version) and bool(frontend_version)
                and app_version != frontend_version)
    return {"appVersion": app_version or "unknown",
            "backendBuildSha": backend_sha or "unknown",
            "frontendVersion": frontend_version or "unknown",
            "consistency": ("mismatch" if mismatch else
                            "incomplete" if incomplete else "consistent"),
            "ownerReadableJa": ("版不一致 — 要確認" if mismatch else
                                "版情報が不完全(捏造しない)" if incomplete
                                else "版整合")}


def recovery_candidate_compatible(original: Dict[str, Any],
                                  candidate: Dict[str, Any]) -> bool:
    """回収候補の互換性: タイトル類似だけでは回収と主張しない —
    エンティティ+日付近接が必須。"""
    ot = str(original.get("titleJa") or original.get("sourceTitle") or "")
    ct = str(candidate.get("titleJa") or "")
    import re as _re
    _GENERIC = {"発売", "発表", "開催", "公開", "提供", "開始", "ニュース",
                "リリース", "本日", "予定"}
    def ents(t):
        return {w for w in _re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}|[ァ-ヶー]{3,}|[一-龠]{2,}", t) if w not in _GENERIC}
    if not (ents(ot) & ents(ct)):
        return False
    od = str(original.get("publishedAt") or "")[:10]
    cd = str(candidate.get("publishedAt") or "")[:10]
    if od and cd and od != cd:
        return False                    # 日付不一致は別ニュース扱い
    return True


def agent_reliability_rates(*, complete: int, recovered: int,
                            scheduled_future: int, skipped_expected: int,
                            total: int, missed_unrecovered: int,
                            failed_safe: int) -> Dict[str, Any]:
    """4レート分離(式つき)。分母0=insufficient≠100%。"""
    due = total - scheduled_future - skipped_expected
    def pct(n, d):
        return int(round(100 * n / d)) if d > 0 else None
    recoverable = recovered + missed_unrecovered
    return {"dueMissions": due,
            "normalCompletionRate": {"percent": pct(complete, due),
                                     "formulaJa": "complete÷due"},
            "effectiveCompletionRate": {"percent": pct(complete + recovered, due),
                                        "formulaJa":
                                        "(complete+recovered)÷(総数−未来−skip)"},
            "recoveryRate": {"percent": pct(recovered, recoverable),
                             "formulaJa": "recovered÷(recovered+未回収missed)"},
            "failureRate": {"percent": pct(missed_unrecovered + failed_safe, due),
                            "formulaJa": "(未回収missed+failed_safe)÷due"},
            "insufficientJa": ("分母0 — insufficient" if due <= 0 else None)}


def canary_miss_diagnostic(row: Dict[str, Any]) -> Dict[str, Any]:
    """canary見逃しの失敗段階診断(数字だけにしない)。"""
    found_g = bool(row.get("foundByGemini")) or bool(row.get("foundByGPT"))
    found_a = bool(row.get("foundByArgus"))
    if found_a:
        stage = None
    elif found_g:
        stage = "source_coverage"       # 外部AIは見つけた=収集範囲/取得の問題
    else:
        stage = "unknown"
    return {"caseId": row.get("topic"),
            "expectedEntities": row.get("expectedKeywords") or [],
            "failureStage": stage,
            "exactReasonJa": ("外部AIは検出・ARGUS未検出 — ソース網/取得の欠落"
                              if stage == "source_coverage" else
                              "双方未検出 — ケース自体の再検証が必要"
                              if stage == "unknown" else "検出済み"),
            "proposedFixJa": ("該当カテゴリのフィード/クエリ拡張を学習提案へ"
                              if stage == "source_coverage" else None),
            "blocksConfidence": stage is not None}
