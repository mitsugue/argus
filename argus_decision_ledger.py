# -*- coding: utf-8 -*-
"""ARGUS Decision Ledger — v12.2.0 ADDENDUM(純・stdlibのみ)。

LOOP B(判断学習ループ)の土台:
- 不変ForecastRecord(発行後編集不可・成果フィールド混入不可・look-ahead拒否・整合hash)
- OutcomeRecord(価格欠損=unresolved・絶対/相対/セクター相対を分離・捏造なし)
- 適正スコア族の分離(Brier/区間/方向/ランキング/棄権 — 単一恣意スコア禁止)
- CalibrationState(最小サンプル・縮約・1件で激変しない)
- ErrorAttribution(幸運な的中で悪い推論を正当化しない)
- LearningProposal(1観測で本番変更不可・重要変更はオーナー承認必須・ロールバック可)
- JobLedger(冪等キー・見逃し検知)
既存のCalibration Ledger v4は本番採点として継続 — 本モジュールはそのv2基盤。
"""
import hashlib
import json
from typing import Any, Dict, List, Optional

HORIZONS = ("intraday", "next_session", "1d", "3d", "5d", "20d",
            "event_window", "medium_term")
TARGET_TYPES = ("direction", "return_band", "volatility", "drawdown_risk",
                "event_reaction", "relative_performance", "scenario",
                "action_priority", "supply_demand_state", "flow_state",
                "catalyst_verdict")
_FORBIDDEN_FORECAST_FIELDS = ("outcome", "endPrice", "absoluteReturn",
                              "realizedVolatility", "outcomeAsOf")
RUBRIC_VERSION = "decision-rubric-v1"


def _hash(obj: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def forecast_record(*, symbol: str, market: str, issued_at: str,
                    horizon: str, target_type: str, forecast_value: str,
                    probability_band: str = "", primary_stance: str = "",
                    conditions_ja: Optional[List[str]] = None,
                    invalidation_ja: Optional[List[str]] = None,
                    evidence_ids: Optional[List[str]] = None,
                    research_mission_id: str = "",
                    model_epoch: str = "", prompt_version: str = "",
                    data_quality_status: str = "unknown",
                    confidence: str = "", mock_data: bool = False,
                    supersedes: Optional[str] = None,
                    now_iso: str = "", **extra) -> Optional[Dict[str, Any]]:
    """不変予測レコードを発行。成果フィールドの混入・look-aheadは拒否(None)。"""
    if horizon not in HORIZONS or target_type not in TARGET_TYPES:
        return None
    if any(k in extra for k in _FORBIDDEN_FORECAST_FIELDS):
        return None                    # 成果情報は予測レコードに書けない
    if now_iso and issued_at and issued_at > now_iso:
        return None                    # 未来時刻の発行=look-ahead拒否
    body = {
        "symbol": str(symbol).upper(), "market": market,
        "issuedAt": issued_at, "forecastHorizon": horizon,
        "targetType": target_type, "forecastValue": str(forecast_value)[:120],
        "probabilityBand": probability_band[:40],
        "primaryStance": primary_stance[:40],
        "conditionsJa": list(conditions_ja or [])[:6],
        "invalidationJa": list(invalidation_ja or [])[:6],
        "evidenceIds": list(evidence_ids or [])[:12],
        "researchMissionId": research_mission_id,
        "modelEpoch": model_epoch, "promptVersion": prompt_version,
        "rubricVersion": RUBRIC_VERSION,
        "dataQualityStatus": data_quality_status,
        "confidence": confidence[:20], "mockData": bool(mock_data),
        "supersedesForecastId": supersedes,
        "immutableCreatedAt": now_iso or issued_at,
    }
    body["id"] = f"fc-{_hash(body)}"
    body["integrityHash"] = _hash(body)
    return body


def verify_forecast_integrity(rec: Dict[str, Any]) -> bool:
    if not isinstance(rec, dict) or "integrityHash" in rec.get("id", ""):
        pass
    # originは輸送メタ(forward_live/historical_replay)であり予測内容ではない
    body = {k: v for k, v in rec.items()
            if k not in ("integrityHash", "origin")}
    return rec.get("integrityHash") == _hash(body)


def outcome_record(*, forecast: Dict[str, Any], outcome_as_of: str,
                   start_price: Optional[float], end_price: Optional[float],
                   benchmark_return: Optional[float] = None,
                   sector_return: Optional[float] = None,
                   max_adverse_pct: Optional[float] = None,
                   max_favorable_pct: Optional[float] = None,
                   invalidation_triggered: bool = False,
                   conditions_triggered: Optional[List[str]] = None,
                   now_iso: str = "") -> Dict[str, Any]:
    """成果解決。必要価格が欠けていればunresolved(0リターン扱い禁止・捏造なし)。"""
    if start_price is None or end_price is None or not start_price:
        return {"forecastId": forecast.get("id"), "status": "unresolved",
                "missingOutcomeDataJa": ["価格データ欠損 — 0%扱いにしない"],
                "immutableCreatedAt": now_iso or outcome_as_of}
    ret = (end_price - start_price) / start_price * 100.0
    rec = {"forecastId": forecast.get("id"), "status": "resolved",
           "symbol": forecast.get("symbol"),
           "horizon": forecast.get("forecastHorizon"),
           "outcomeAsOf": outcome_as_of,
           "absoluteReturnPct": round(ret, 3),
           "benchmarkRelativeReturnPct": (round(ret - benchmark_return, 3)
                                          if benchmark_return is not None else None),
           "sectorRelativeReturnPct": (round(ret - sector_return, 3)
                                       if sector_return is not None else None),
           "maximumAdverseExcursionPct": max_adverse_pct,
           "maximumFavorableExcursionPct": max_favorable_pct,
           "invalidationTriggered": bool(invalidation_triggered),
           "scenarioConditionsTriggered": list(conditions_triggered or [])[:6],
           "immutableCreatedAt": now_iso or outcome_as_of}
    rec["integrityHash"] = _hash(rec)
    return rec


# ── スコア族(分離・混同禁止) ─────────────────────────────────────────────────

def brier_score(prob: float, occurred: bool) -> float:
    return round((float(prob) - (1.0 if occurred else 0.0)) ** 2, 4)


def interval_coverage(low: float, high: float, actual: float) -> bool:
    return float(low) <= float(actual) <= float(high)


def balanced_accuracy(tp: int, tn: int, fp: int, fn: int) -> Optional[float]:
    if (tp + fn) == 0 or (tn + fp) == 0:
        return None
    return round(0.5 * (tp / (tp + fn) + tn / (tn + fp)), 4)


def precision_at_k(ranked_hits: List[bool], k: int) -> Optional[float]:
    xs = list(ranked_hits or [])[:k]
    return round(sum(1 for x in xs if x) / len(xs), 4) if xs else None


def selective_accuracy(decided_correct: int, decided_total: int,
                       abstained: int) -> Dict[str, Any]:
    cov = decided_total / max(1, decided_total + abstained)
    acc = decided_correct / decided_total if decided_total else None
    return {"coverage": round(cov, 4),
            "selectiveAccuracy": round(acc, 4) if acc is not None else None,
            "abstained": abstained}


# ── 校正(最小サンプル+縮約 — 1件で激変しない) ──────────────────────────────

MIN_SAMPLES = {"provisional": 5, "usable": 20}


def calibration_state(*, band: str, sample_count: int, observed_freq: float,
                      stated_prob: float, prior: float = 0.5,
                      shrink_n: int = 20) -> Dict[str, Any]:
    n = int(sample_count)
    shrunk = ((observed_freq * n) + (prior * shrink_n)) / (n + shrink_n)
    level = ("insufficient" if n < MIN_SAMPLES["provisional"] else
             "low" if n < MIN_SAMPLES["usable"] else
             "medium" if n < 60 else "high")
    return {"confidenceBand": band, "sampleCount": n,
            "observedFrequency": round(observed_freq, 4),
            "shrunkFrequency": round(shrunk, 4),
            "calibrationError": round(abs(shrunk - stated_prob), 4),
            "confidenceLevel": level,
            "noteJa": "履歴不足" if level == "insufficient" else None}


# ── 誤り帰属(確率的結果と過程を分離) ─────────────────────────────────────────

ERROR_TYPES = ("missed_news", "stale_news", "wrong_source",
               "unsupported_causal_inference", "direct_vs_theme_confusion",
               "value_chain_map_missing", "official_disclosure_missed",
               "data_quality_failure", "provider_failure", "model_hallucination",
               "confidence_overstated", "confidence_understated",
               "regime_misclassification", "flow_misread",
               "supply_demand_misread", "event_timing_error", "ranking_error",
               "random_or_unexplained")


def error_attribution(*, forecast_id: str, outcome_id: str,
                      error_types: List[str], counterfactual_ja: str = "",
                      preventable: str = "unknown",
                      supporting_evidence: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    ets = [e for e in (error_types or []) if e in ERROR_TYPES]
    if not ets:
        return None
    return {"forecastId": forecast_id, "outcomeId": outcome_id,
            "errorTypes": ets[:5],
            "supportingEvidence": list(supporting_evidence or [])[:6],
            "counterfactualJa": counterfactual_ja[:200],
            "preventable": preventable if preventable in ("true", "false",
                                                          "unknown") else "unknown",
            "lucky_outcome_note": ("幸運な結果は悪い推論を正当化しない/"
                                   "不運な結果は健全な過程を自動で誤りにしない")}


# ── 学習提案(1観測で本番変更不可・重要変更は承認必須) ─────────────────────────

PROPOSAL_TYPES = ("query_expansion", "source_weight", "source_addition",
                  "value_chain_edge", "confidence_calibration",
                  "priority_threshold", "scenario_weight", "stale_filter",
                  "provider_route", "prompt_change", "rubric_change")
_AUTO_SAFE_TYPES = ("query_expansion",)
_MATERIAL_MIN_SAMPLES = 20


def learning_proposal(*, proposal_type: str, proposed_change: str,
                      sample_count: int, source_records: Optional[List[str]] = None,
                      risk_level: str = "low") -> Optional[Dict[str, Any]]:
    if proposal_type not in PROPOSAL_TYPES:
        return None
    n = int(sample_count)
    auto_ok = proposal_type in _AUTO_SAFE_TYPES and n >= 1
    material = proposal_type not in _AUTO_SAFE_TYPES
    if material and n < 2:
        status = "rejected"            # 1観測で本番変更は構造不可
    elif auto_ok:
        status = "validated"           # 低リスク探索語のみ自動(サニタイズ前提)
    else:
        status = "proposed"            # holdout+オーナー承認まで昇格しない
    return {"proposalType": proposal_type,
            "proposedChange": str(proposed_change)[:160],
            "sampleCount": n,
            "sourceRecords": list(source_records or [])[:8],
            "riskLevel": risk_level,
            "holdoutRequired": material,
            "ownerApprovalRequired": material,
            "status": status,
            "canAutoPromote": auto_ok,
            "noteJa": ("重要変更 — 最小サンプル/time-splitホールドアウト/"
                       "champion-challenger/オーナー承認が必須" if material else
                       "低リスク探索語 — サニタイズ済みで自動学習可")}


def can_promote(proposal: Dict[str, Any], *, owner_approved: bool,
                holdout_passed: bool) -> bool:
    if proposal.get("canAutoPromote"):
        return True
    return (bool(owner_approved) and bool(holdout_passed)
            and int(proposal.get("sampleCount") or 0) >= _MATERIAL_MIN_SAMPLES)


# ── 24x365 ジョブ台帳(冪等・見逃し検知) ──────────────────────────────────────

def job_record(*, job_id: str, mission_type: str, scheduled_at: str,
               idempotency_key: str, status: str = "queued") -> Dict[str, Any]:
    return {"jobId": job_id, "missionType": mission_type,
            "scheduledAt": scheduled_at, "idempotencyKey": idempotency_key,
            "status": status, "retryCount": 0, "startedAt": None,
            "completedAt": None, "failureReasonRedacted": None}


def detect_missed_jobs(jobs: List[Dict[str, Any]], now_iso: str,
                       stale_after_min: int = 90) -> List[str]:
    """完了もfailedもしていない古いジョブ=見逃し(沈黙消失させない)。"""
    missed = []
    for j in jobs or []:
        if j.get("status") in ("complete", "failed_safe"):
            continue
        at = str(j.get("scheduledAt") or "")
        if at and at < now_iso and (now_iso[:16] > at[:16]):
            missed.append(j.get("jobId"))
    return missed[:10]


def is_duplicate_job(jobs: List[Dict[str, Any]], idempotency_key: str) -> bool:
    return any(j.get("idempotencyKey") == idempotency_key for j in jobs or [])


# ── v12.2.2 Phase 7/8: challenger影走行+履歴影響shadow ─────────────────────

def challenger_evaluation(*, proposal: Dict[str, Any], champion_version: str,
                          challenger_version: str, sample_count: int,
                          metric_before: Optional[float],
                          metric_after: Optional[float],
                          now_iso: str = "") -> Dict[str, Any]:
    """shadow challenger評価レコード。昇格はしない(オーナー承認まで)。"""
    return {"championVersion": champion_version,
            "challengerVersion": challenger_version,
            "proposalType": proposal.get("proposalType"),
            "sampleCount": int(sample_count),
            "metricsBefore": metric_before, "metricsAfter": metric_after,
            "recommendation": ("insufficient_sample" if sample_count <
                               _MATERIAL_MIN_SAMPLES else "review"),
            "ownerDecision": "pending", "state": "shadow",
            "rollbackTarget": champion_version, "at": now_iso,
            "noteJa": "shadow走行のみ — 本番判断は不変・昇格はオーナー承認後"}


def future_decision_context_shadow(*, symbol: str,
                                   confirming_cases: int,
                                   disconfirming_cases: int,
                                   sample_count: int,
                                   applied_learning_ids: Optional[list] = None) -> Dict[str, Any]:
    """履歴影響のshadow文脈。疎な履歴は影響なし・反証例を必ず数える。"""
    n = int(sample_count)
    influence = ("none" if n < MIN_SAMPLES["provisional"] else
                 "weak" if n < MIN_SAMPLES["usable"] else "moderate")
    return {"symbol": str(symbol).upper(),
            "confirmingCases": int(confirming_cases),
            "disconfirmingCases": int(disconfirming_cases),
            "sampleCount": n,
            "learningInfluence": influence,
            "appliedLearningIds": list(applied_learning_ids or [])[:6],
            "shadowOnly": True,
            "caveatJa": ("履歴不足 — 影響なし" if influence == "none" else
                         "shadow表示のみ — 本番の構えは変更しない。"
                         "反証例も同時に提示(確証バイアス防止)")}
