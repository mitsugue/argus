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
import math
import re
from datetime import datetime, timedelta, timezone
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
JST = timezone(timedelta(hours=9))


def _hash(obj: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def _ep(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=JST)
        return d.timestamp()
    except Exception:
        return None


def _iso_after(iso: str, seconds: int) -> Optional[str]:
    ep = _ep(iso)
    if ep is None:
        return None
    return datetime.fromtimestamp(ep + max(0, int(seconds)), JST).isoformat()


def outcome_id(forecast_id: Any) -> str:
    """Forecastごとに一意な安定Outcome ID。再試行で変化しない。"""
    return f"oc-{_hash({'forecastId': str(forecast_id or 'unknown')})}"


def seal_outcome(rec: Dict[str, Any]) -> Dict[str, Any]:
    """可変な解決状態を更新した後のintegrity hashを再計算する。"""
    rec["integrityHash"] = _hash({k: v for k, v in rec.items()
                                  if k != "integrityHash"})
    return rec


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
        # v12.2.9: 情報カットオフ=発行実時刻(look-ahead拒否済み=backdate不可)
        "informationCutoffAt": issued_at,
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
    """成果解決。必要価格が欠けていればunresolved(0リターン扱い禁止・捏造なし)。
    v12.2.10: originを予測から構造的に継承 — 既知originの新規outcomeが
    unknown_legacyへ落ちない(旧レコードのみunknown_legacyのまま)。"""
    _origin = forecast.get("origin")
    _origin = _origin if _origin in ("forward_live", "historical_replay",
                                     "shadow", "fixture") else "unknown_legacy"
    _inherit = {"origin": _origin,
                "forecastIntegrityHash": forecast.get("integrityHash"),
                "informationCutoffAt": forecast.get("informationCutoffAt")
                or forecast.get("issuedAt"),
                "resolutionSource": "price_history_cached",
                "resolvedRecordedAt": now_iso or outcome_as_of}
    _oid = outcome_id(forecast.get("id"))
    if start_price is None or end_price is None or not start_price:
        rec = {"id": _oid, "forecastId": forecast.get("id"),
                "status": "unresolved",
                "resolutionState": "unresolved_missing_price",
                "retryCount": 0, "lastRetryAt": None, "nextRetryAt": None,
                "missingOutcomeReason": "missing_price",
                "missingOutcomeDataJa": ["価格データ欠損 — 0%扱いにしない"],
                "transitionHistory": [{"from": "matured",
                                       "to": "unresolved_missing_price",
                                       "at": now_iso or outcome_as_of,
                                       "reason": "missing_price"}],
                "immutableCreatedAt": now_iso or outcome_as_of, **_inherit}
        return seal_outcome(rec)
    ret = (end_price - start_price) / start_price * 100.0
    rec = {"id": _oid, "forecastId": forecast.get("id"), "status": "resolved",
           "resolutionState": "resolved", "retryCount": 0,
           "lastRetryAt": None, "nextRetryAt": None,
           "symbol": forecast.get("symbol"),
           "horizon": forecast.get("forecastHorizon"),
           "outcomeAsOf": outcome_as_of, **_inherit,
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
    return seal_outcome(rec)


def schedule_outcome_retry(outcome: Dict[str, Any], *, now_iso: str,
                           retry_interval_seconds: int) -> Dict[str, Any]:
    """初回unresolvedに次回時刻を付与。同一Outcome ID/作成時刻を維持する。"""
    rec = dict(outcome)
    rec.setdefault("id", outcome_id(rec.get("forecastId")))
    rec.setdefault("retryCount", 0)
    rec.setdefault("lastRetryAt", None)
    rec["nextRetryAt"] = _iso_after(now_iso, retry_interval_seconds)
    rec.setdefault("missingOutcomeReason", "missing_price")
    rec.setdefault("resolutionState", "unresolved_missing_price")
    rec.setdefault("transitionHistory", [])
    return seal_outcome(rec)


def outcome_retry_due(outcome: Dict[str, Any], *, now_iso: str) -> bool:
    """resolved/expiredは対象外。legacyで時刻なしのunresolvedは再試行可能。"""
    if outcome.get("status") == "resolved" or \
            outcome.get("resolutionState") == "unresolved_expired":
        return False
    nxt = _ep(outcome.get("nextRetryAt"))
    now = _ep(now_iso)
    return now is not None and (nxt is None or now >= nxt)


def retry_outcome_record(*, existing: Dict[str, Any], forecast: Dict[str, Any],
                         outcome_as_of: str, start_price: Optional[float],
                         end_price: Optional[float], now_iso: str,
                         retry_interval_seconds: int,
                         expire_after_seconds: int = 0) -> Dict[str, Any]:
    """同じOutcomeを再解決。ID/作成時刻/履歴を維持し、0価格は採点しない。"""
    if not outcome_retry_due(existing, now_iso=now_iso):
        return dict(existing)
    created_at = existing.get("immutableCreatedAt") or now_iso
    created_ep, now_ep = _ep(created_at), _ep(now_iso)
    retry_count = int(existing.get("retryCount") or 0) + 1
    history = list(existing.get("transitionHistory") or [])
    stable_id = existing.get("id") or outcome_id(existing.get("forecastId")
                                                   or forecast.get("id"))
    if expire_after_seconds > 0 and created_ep is not None and now_ep is not None \
            and now_ep - created_ep >= expire_after_seconds:
        rec = dict(existing)
        history.append({"from": rec.get("resolutionState") or "unresolved",
                        "to": "unresolved_expired", "at": now_iso,
                        "reason": "retry_window_expired"})
        rec.update({"id": stable_id, "status": "unresolved",
                    "resolutionState": "unresolved_expired",
                    "retryCount": retry_count, "lastRetryAt": now_iso,
                    "nextRetryAt": None,
                    "missingOutcomeReason": "retry_window_expired",
                    "transitionHistory": history})
        return seal_outcome(rec)
    candidate = outcome_record(
        forecast=forecast, outcome_as_of=outcome_as_of,
        start_price=start_price, end_price=end_price, now_iso=now_iso)
    if candidate.get("status") == "resolved":
        rec = dict(existing)
        rec.update(candidate)
        history.append({"from": existing.get("resolutionState") or "unresolved",
                        "to": "resolved", "at": now_iso,
                        "reason": "price_available"})
        rec.update({"id": stable_id, "immutableCreatedAt": created_at,
                    "retryCount": retry_count, "lastRetryAt": now_iso,
                    "nextRetryAt": None, "transitionHistory": history})
        rec.pop("missingOutcomeDataJa", None)
        rec.pop("missingOutcomeReason", None)
        return seal_outcome(rec)
    rec = dict(existing)
    history.append({"from": existing.get("resolutionState")
                            or "unresolved_missing_price",
                    "to": "retry_pending", "at": now_iso,
                    "reason": "missing_price"})
    rec.update({"id": stable_id, "status": "unresolved",
                "resolutionState": "retry_pending",
                "retryCount": retry_count, "lastRetryAt": now_iso,
                "nextRetryAt": _iso_after(now_iso, retry_interval_seconds),
                "missingOutcomeReason": "missing_price",
                "missingOutcomeDataJa": ["価格データ欠損 — 0%扱いにしない"],
                "transitionHistory": history})
    return seal_outcome(rec)


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


# ── v12.2.10 Phase 7: Decision Scoring Readiness(採点語彙の構造分離) ─────────

def decision_scoring_readiness(forecasts: List[Dict[str, Any]],
                               outcomes: List[Dict[str, Any]],
                               now_iso: str = "") -> Dict[str, Any]:
    """「将来採点に適格な予測」と「完了採点サンプル」を同名にしない。
    forward_live以外(replay/shadow/fixture/unknown_legacy)は本番採点から除外。"""
    live = [f for f in (forecasts or [])
            if f.get("origin") == "forward_live" and not f.get("mockData")]
    excluded_fc = len(forecasts or []) - len(live)
    o_by_fid = {}
    for o in (outcomes or []):
        o_by_fid.setdefault(o.get("forecastId"), o)
    pending_maturity = matured_awaiting = completed = 0
    for f in live:
        o = o_by_fid.get(f.get("id"))
        if o is None:
            pending_maturity += 1
        elif o.get("status") == "resolved" and o.get("origin") == "forward_live":
            completed += 1                # 成熟+正当解決+origin継承の三条件
        else:
            matured_awaiting += 1         # 成熟したが未解決(価格欠損等)
    excluded_oc = sum(1 for o in (outcomes or [])
                      if o.get("origin") != "forward_live")
    return {"forwardLiveForecastsIssued": len(live),
            "forecastEligibleForFutureScoring": len(live),
            "pendingMaturity": pending_maturity,
            "maturedAwaitingResolution": matured_awaiting,
            "resolvedEligibleOutcomes": completed,
            "completedScoreableSamples": completed,
            "excludedForecasts": excluded_fc,
            "excludedOutcomes": excluded_oc,
            "deprecatedFieldNoteJa": ("旧scoreEligibleForecastCount=将来採点適格・"
                                      "旧forwardLive.scoreEligible=完了サンプル — "
                                      "同名異義のため本モデルへ移行"),
            "ownerReadableJa": (
                f"Forward-live予測{len(live)}件。"
                f"うち将来採点に適格{len(live)}件。"
                f"完了採点サンプル{completed}件"
                + ("" if completed else
                   " — 成熟または成果解決を待っています")
                + (f"(成熟待ち{pending_maturity}件/解決待ち"
                   f"{matured_awaiting}件)"))}


# ── Prediction Ledger sealed v2 (additive; legacy checkpoint shape unchanged) ─
#
# These records deliberately remain storage-neutral.  Runtime/Git adapters may
# append them to durable storage, but this core neither creates another ledger
# authority nor assumes the scanner's bounded legacy forecast/outcome lists are
# canonical history.

PREDICTION_LEDGER_V2_SCHEMA = "argus-prediction-ledger-v2"
PIT_TRUTH_REF_SCHEMA = "argus-pit-truth-ref-v1"
SESSION_MATURITY_SCHEMA = "argus-session-maturity-v1"
EVALUATION_METRIC_SCHEMA = "argus-evaluation-metric-v1"
FORECAST_DISTRIBUTION_SCHEMA = "argus-categorical-forecast-distribution-v1"

PREDICTION_MODES = ("historical_replay", "forward_live", "shadow")
PREDICTION_LEDGER_MODES = PREDICTION_MODES
LEGACY_PREDICTION_MODE = "unknown_legacy"
OUTCOME_RESOLUTION_STATUSES = ("OBSERVED", "UNSCORABLE", "AMBIGUOUS")
METRIC_FAMILIES = ("mfe", "mae", "target", "invalidation", "end",
                   "opportunity", "benchmark", "score", "missing")
METRIC_POLARITIES = ("higher_better", "lower_better", "neutral",
                     "contextual")

_V2_MAX_EVIDENCE_REFS = 24
_V2_MAX_METRICS = 64
_V2_MAX_AGGREGATE_EVENTS = 10000
_V2_MAX_EMBEDDED_BYTES = 8192
_V2_MAX_DISTRIBUTION_CLASSES = 16
_V2_DISTRIBUTION_SUM_TOLERANCE = 1e-9
_V2_METRIC_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,95}$")
_V2_CLASS_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_V2_FORBIDDEN_PREDICTION_FIELDS = set(_FORBIDDEN_FORECAST_FIELDS) | {
    "outcomeEventId", "outcomeResolution", "evaluation", "evaluationMetrics",
    "realizedReturn", "maximumFavorableExcursion", "maximumAdverseExcursion",
}
_WAIT_AVOIDED_MAE = "opportunity.avoided_mae_pct"
_WAIT_MISSED_MFE = "opportunity.missed_mfe_pct"


def _v2_hash(value: Any) -> Optional[str]:
    """Full canonical SHA-256.  Non-JSON/non-finite values are never sealable."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(raw).hexdigest()


def _v2_json_copy(value: Any, max_bytes: int = _V2_MAX_EMBEDDED_BYTES) -> Any:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > max_bytes:
            return None
        return json.loads(raw.decode("utf-8"))
    except (TypeError, ValueError):
        return None


def _v2_string(value: Any, limit: int, *, required: bool = False) -> Optional[str]:
    if not isinstance(value, str):
        return None
    out = value.strip()
    if required and not out:
        return None
    if len(out) > limit:
        return None
    return out


def _v2_string_list(value: Any, limit: int,
                    item_limit: int = 160) -> Optional[List[str]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        return None
    out = []
    for item in value:
        text = _v2_string(item, item_limit, required=True)
        if text is None:
            return None
        out.append(text)
    return out


def _v2_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _v2_seal(body: Dict[str, Any], prefix: str) -> Optional[Dict[str, Any]]:
    identity_hash = _v2_hash(body)
    if identity_hash is None:
        return None
    rec = dict(body)
    rec["id"] = f"{prefix}-{identity_hash[:24]}"
    integrity_hash = _v2_hash(rec)
    if integrity_hash is None:
        return None
    rec["integrityHash"] = integrity_hash
    return rec


def _v2_verify_seal(rec: Any, *, prefix: str,
                    record_type: str) -> bool:
    if not isinstance(rec, dict):
        return False
    if rec.get("schemaVersion") != PREDICTION_LEDGER_V2_SCHEMA or \
            rec.get("recordType") != record_type:
        return False
    integrity_hash = rec.get("integrityHash")
    record_id = rec.get("id")
    if not isinstance(integrity_hash, str) or not isinstance(record_id, str):
        return False
    sealed = {k: v for k, v in rec.items() if k != "integrityHash"}
    if _v2_hash(sealed) != integrity_hash:
        return False
    body = {k: v for k, v in sealed.items() if k != "id"}
    identity_hash = _v2_hash(body)
    return bool(identity_hash and record_id == f"{prefix}-{identity_hash[:24]}")


def point_in_time_truth_ref(*, snapshot_id: str, source_id: str,
                            as_of: str, known_at: str, content_hash: str,
                            observation_kind: str,
                            observed_fields: List[str],
                            target_session_id: str = "",
                            provider: str = "", revision: str = "") \
        -> Optional[Dict[str, Any]]:
    """Provider-neutral immutable reference to what was knowable at a cutoff.

    ``provider`` is descriptive provenance only.  Identity and matching use the
    neutral source/snapshot/content/session fields, never a provider schema.
    """
    sid = _v2_string(snapshot_id, 160, required=True)
    source = _v2_string(source_id, 120, required=True)
    digest = _v2_string(content_hash, 160, required=True)
    kind = _v2_string(observation_kind, 80, required=True)
    session_id = _v2_string(target_session_id, 160)
    provider_text = _v2_string(provider, 120)
    revision_text = _v2_string(revision, 120)
    fields = _v2_string_list(observed_fields, 32, 80)
    as_ep, known_ep = _ep(as_of), _ep(known_at)
    if None in (sid, source, digest, kind, session_id, provider_text,
                revision_text, fields) or not fields:
        return None
    if as_ep is None or known_ep is None or as_ep > known_ep:
        return None
    return {
        "schemaVersion": PIT_TRUTH_REF_SCHEMA,
        "snapshotId": sid,
        "sourceId": source,
        "provider": provider_text,
        "asOf": as_of,
        "knownAt": known_at,
        "revision": revision_text,
        "contentHash": digest,
        "observationKind": kind,
        "observedFields": fields,
        "targetSessionId": session_id,
    }


truth_reference = point_in_time_truth_ref


def _normalize_truth_ref(value: Any, *, cutoff_at: Optional[str] = None,
                         require_target_session: bool = False) \
        -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schemaVersion") != PIT_TRUTH_REF_SCHEMA:
        return None
    normalized = point_in_time_truth_ref(
        snapshot_id=value.get("snapshotId"), source_id=value.get("sourceId"),
        as_of=value.get("asOf"), known_at=value.get("knownAt"),
        content_hash=value.get("contentHash"),
        observation_kind=value.get("observationKind"),
        observed_fields=value.get("observedFields"),
        target_session_id=value.get("targetSessionId") or "",
        provider=value.get("provider") or "",
        revision=value.get("revision") or "")
    if normalized is None or normalized != value:
        return None
    if require_target_session and not normalized.get("targetSessionId"):
        return None
    if cutoff_at is not None:
        cutoff_ep = _ep(cutoff_at)
        if cutoff_ep is None or _ep(normalized["knownAt"]) > cutoff_ep:
            return None
    return normalized


def session_maturity_contract(*, calendar_id: str, target_session_id: str,
                              target_at: str, maturity_at: str,
                              horizon: str, session_kind: str = "regular") \
        -> Optional[Dict[str, Any]]:
    """Independent trading-calendar/session contract; contains no provider IDs."""
    calendar = _v2_string(calendar_id, 120, required=True)
    session_id = _v2_string(target_session_id, 160, required=True)
    kind = _v2_string(session_kind, 60, required=True)
    target_ep, maturity_ep = _ep(target_at), _ep(maturity_at)
    if calendar is None or session_id is None or kind is None or \
            horizon not in HORIZONS or target_ep is None or maturity_ep is None \
            or maturity_ep < target_ep:
        return None
    return {
        "schemaVersion": SESSION_MATURITY_SCHEMA,
        "calendarId": calendar,
        "targetSessionId": session_id,
        "sessionKind": kind,
        "horizon": horizon,
        "targetAt": target_at,
        "maturityAt": maturity_at,
    }


maturity_contract = session_maturity_contract


def _normalize_maturity(value: Any, *, horizon: str,
                        cutoff_at: str) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schemaVersion") != SESSION_MATURITY_SCHEMA:
        return None
    normalized = session_maturity_contract(
        calendar_id=value.get("calendarId"),
        target_session_id=value.get("targetSessionId"),
        target_at=value.get("targetAt"), maturity_at=value.get("maturityAt"),
        horizon=value.get("horizon"), session_kind=value.get("sessionKind"))
    if normalized is None or normalized != value or normalized["horizon"] != horizon:
        return None
    cutoff_ep = _ep(cutoff_at)
    if cutoff_ep is None or _ep(normalized["targetAt"]) <= cutoff_ep:
        return None
    return normalized


def _normalize_policy(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    if set(value) - {"policyId", "policyVersion", "parametersHash"}:
        return None
    policy_id = _v2_string(value.get("policyId"), 120, required=True)
    version = _v2_string(value.get("policyVersion"), 80, required=True)
    parameters_hash = _v2_string(value.get("parametersHash") or "", 160)
    if None in (policy_id, version, parameters_hash):
        return None
    return {"policyId": policy_id, "policyVersion": version,
            "parametersHash": parameters_hash}


def _normalize_engine(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    engine_id = _v2_string(value.get("engineId"), 120, required=True)
    version = _v2_string(value.get("engineVersion"), 120, required=True)
    build_sha = _v2_string(value.get("buildSha"), 160, required=True)
    if None in (engine_id, version, build_sha):
        return None
    normalized = {"engineId": engine_id, "engineVersion": version,
                  "buildSha": build_sha}
    return normalized if normalized == value else None


def _normalize_embedded_dict(value: Any, *, allow_none: bool = True) -> Any:
    if value is None and allow_none:
        return None
    copied = _v2_json_copy(value)
    return copied if isinstance(copied, dict) else None


_V2_COMPARATORS = ("", ">", ">=", "<", "<=", "==", "touch")


def target_ladder_entry(*, target_id: str, value: float, unit: str,
                        comparator: str = "touch",
                        target_at: str = "") -> Optional[Dict[str, Any]]:
    target = _v2_string(target_id, 120, required=True)
    unit_text = _v2_string(unit, 40, required=True)
    if target is None or unit_text is None or not _v2_number(value) or \
            comparator not in _V2_COMPARATORS or \
            (target_at and _ep(target_at) is None):
        return None
    row = {"targetId": target, "value": float(value), "unit": unit_text}
    if comparator:
        row["comparator"] = comparator
    if target_at:
        row["targetAt"] = target_at
    return row


def invalidation_rule(*, rule_id: str, value: float, unit: str,
                      comparator: str = "touch",
                      target_at: str = "") -> Optional[Dict[str, Any]]:
    rule = _v2_string(rule_id, 120, required=True)
    unit_text = _v2_string(unit, 40, required=True)
    if rule is None or unit_text is None or not _v2_number(value) or \
            comparator not in _V2_COMPARATORS or \
            (target_at and _ep(target_at) is None):
        return None
    row = {"ruleId": rule, "value": float(value), "unit": unit_text}
    if comparator:
        row["comparator"] = comparator
    if target_at:
        row["targetAt"] = target_at
    return row


def _normalize_target_ladder(value: Any,
                             maturity: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(value, (list, tuple)) or len(value) > 12:
        return None
    out = []
    seen = set()
    allowed = {"targetId", "value", "unit", "comparator", "targetAt"}
    for raw in value:
        if not isinstance(raw, dict) or set(raw) - allowed:
            return None
        target = _v2_string(raw.get("targetId"), 120, required=True)
        unit = _v2_string(raw.get("unit"), 40, required=True)
        comparator = raw.get("comparator") or ""
        target_at = raw.get("targetAt") or ""
        if target is None or target in seen or unit is None or \
                not _v2_number(raw.get("value")) or \
                comparator not in _V2_COMPARATORS or \
                (target_at and _ep(target_at) != _ep(maturity.get("targetAt"))):
            return None
        seen.add(target)
        out.append(_v2_json_copy(raw, 1024))
    return out


def _normalize_invalidation(value: Any,
                            maturity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    allowed = {"ruleId", "value", "unit", "comparator", "targetAt"}
    if not isinstance(value, dict) or set(value) - allowed:
        return None
    rule = _v2_string(value.get("ruleId"), 120, required=True)
    unit = _v2_string(value.get("unit"), 40, required=True)
    comparator = value.get("comparator") or ""
    target_at = value.get("targetAt") or ""
    if rule is None or unit is None or not _v2_number(value.get("value")) or \
            comparator not in _V2_COMPARATORS or \
            (target_at and _ep(target_at) != _ep(maturity.get("targetAt"))):
        return None
    return _v2_json_copy(value, 1024)


def forecast_distribution(*, class_labels: List[str],
                          probabilities: List[float],
                          class_order_version: str) \
        -> Optional[Dict[str, Any]]:
    """Bounded categorical forecast whose class order is explicit and sealed.

    Probabilities use the unit interval.  Evaluation policies may select a
    scoring rule, but may not reinterpret the sealed label order.
    """
    if not isinstance(class_labels, (list, tuple)) or \
            not isinstance(probabilities, (list, tuple)) or \
            not 2 <= len(class_labels) <= _V2_MAX_DISTRIBUTION_CLASSES or \
            len(class_labels) != len(probabilities):
        return None
    version = _v2_string(class_order_version, 80, required=True)
    if version is None:
        return None
    labels: List[str] = []
    seen = set()
    for raw_label in class_labels:
        label = _v2_string(raw_label, 80, required=True)
        if label is None or not _V2_CLASS_LABEL_RE.fullmatch(label) or \
                label in seen:
            return None
        labels.append(label)
        seen.add(label)
    values: List[float] = []
    for probability in probabilities:
        if not _v2_number(probability) or \
                not 0.0 <= float(probability) <= 1.0:
            return None
        values.append(float(probability))
    if not math.isclose(math.fsum(values), 1.0, rel_tol=0.0,
                        abs_tol=_V2_DISTRIBUTION_SUM_TOLERANCE):
        return None
    return {
        "schemaVersion": FORECAST_DISTRIBUTION_SCHEMA,
        "classOrderVersion": version,
        "classLabels": labels,
        "probabilities": values,
    }


def _normalize_forecast_distribution(value: Any) \
        -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {
            "schemaVersion", "classOrderVersion", "classLabels",
            "probabilities"} or \
            value.get("schemaVersion") != FORECAST_DISTRIBUTION_SCHEMA:
        return None
    normalized = forecast_distribution(
        class_labels=value.get("classLabels"),
        probabilities=value.get("probabilities"),
        class_order_version=value.get("classOrderVersion"))
    return normalized if normalized == value else None


def prediction_record_v2(*, mode: str, symbol: str, market: str,
                         issued_at: str, horizon: str, target_type: str,
                         forecast_value: str, truth_ref: Dict[str, Any],
                         maturity: Dict[str, Any], engine_id: str,
                         engine_version: str, build_sha: str,
                         evaluation_policy: Dict[str, Any],
                         now_iso: str, confidence: Optional[float] = None,
                         candidate_action: str = "",
                         target_ladder: Optional[List[Dict[str, Any]]] = None,
                         invalidation: Optional[Dict[str, Any]] = None,
                         evidence_refs: Optional[List[str]] = None,
                         missing_evidence: Optional[List[str]] = None,
                         dissent: Optional[List[str]] = None,
                         forecast_distribution: Optional[Dict[str, Any]] = None,
                         replay_cutoff_at: str = "",
                         supersedes_prediction_id: str = "",
                         **extra: Any) -> Optional[Dict[str, Any]]:
    """Create a sealed immutable IssuedDecision in the one Prediction Ledger."""
    if mode not in PREDICTION_MODES or horizon not in HORIZONS or \
            target_type not in TARGET_TYPES:
        return None
    if any(key in _V2_FORBIDDEN_PREDICTION_FIELDS for key in extra):
        return None
    if extra:                         # v2 rejects unsealed/unknown extensions
        return None
    issued_ep, created_ep = _ep(issued_at), _ep(now_iso)
    if issued_ep is None or created_ep is None or issued_ep > created_ep:
        return None
    if mode == "historical_replay":
        cutoff_ep = _ep(replay_cutoff_at)
        if cutoff_ep is None or cutoff_ep != issued_ep:
            return None
        cutoff_at = replay_cutoff_at
    else:
        if replay_cutoff_at:
            return None
        cutoff_at = issued_at
    normalized_truth = _normalize_truth_ref(truth_ref, cutoff_at=cutoff_at)
    normalized_maturity = _normalize_maturity(maturity, horizon=horizon,
                                               cutoff_at=cutoff_at)
    engine = {"engineId": engine_id, "engineVersion": engine_version,
              "buildSha": build_sha}
    normalized_engine = _normalize_engine(engine)
    normalized_policy = _normalize_policy(evaluation_policy)
    if normalized_truth is None or normalized_maturity is None or \
            normalized_engine is None or normalized_policy is None:
        return None
    symbol_text = _v2_string(symbol, 80, required=True)
    market_text = _v2_string(market, 40, required=True)
    forecast_text = _v2_string(forecast_value, 240, required=True)
    action_text = _v2_string(candidate_action, 80)
    supersedes = _v2_string(supersedes_prediction_id, 160)
    evidence = _v2_string_list(evidence_refs, _V2_MAX_EVIDENCE_REFS, 200)
    missing = _v2_string_list(missing_evidence, 16, 200)
    dissent_rows = _v2_string_list(dissent, 16, 240)
    if None in (symbol_text, market_text, forecast_text, action_text,
                supersedes, evidence, missing, dissent_rows):
        return None
    if confidence is not None and (not _v2_number(confidence)
                                   or not 0.0 <= float(confidence) <= 1.0):
        return None
    ladder = _normalize_target_ladder(target_ladder or [], normalized_maturity)
    invalidation_copy = _normalize_invalidation(invalidation, normalized_maturity)
    if ladder is None or \
            (invalidation is not None and invalidation_copy is None):
        return None
    distribution_copy = None
    if forecast_distribution is not None:
        distribution_copy = _normalize_forecast_distribution(
            forecast_distribution)
        if distribution_copy is None:
            return None
    body = {
        "schemaVersion": PREDICTION_LEDGER_V2_SCHEMA,
        "recordType": "issued_decision",
        "mode": mode,
        "symbol": symbol_text.upper(),
        "market": market_text.upper(),
        "issuedAt": issued_at,
        "informationCutoffAt": cutoff_at,
        "replayCutoffAt": replay_cutoff_at or None,
        "forecastHorizon": horizon,
        "targetType": target_type,
        "forecastValue": forecast_text,
        "confidence": (float(confidence) if confidence is not None else None),
        "candidateAction": action_text.upper(),
        "targetLadder": ladder,
        "invalidation": invalidation_copy,
        "truthRef": normalized_truth,
        "maturity": normalized_maturity,
        "engine": normalized_engine,
        "evaluationPolicy": normalized_policy,
        "evidenceRefs": evidence,
        "missingEvidence": missing,
        "dissent": dissent_rows,
        "supersedesPredictionId": supersedes or None,
        "immutableCreatedAt": now_iso,
    }
    # Omitting the optional field preserves identities of already-sealed v2
    # records created before categorical distributions were introduced.
    if distribution_copy is not None:
        body["forecastDistribution"] = distribution_copy
    return _v2_seal(body, "pd")


prediction_record = prediction_record_v2


def verify_prediction_record_v2(rec: Any) -> bool:
    if not _v2_verify_seal(rec, prefix="pd", record_type="issued_decision"):
        return False
    if rec.get("mode") not in PREDICTION_MODES or \
            rec.get("forecastHorizon") not in HORIZONS or \
            rec.get("targetType") not in TARGET_TYPES:
        return False
    if any(key in rec for key in _V2_FORBIDDEN_PREDICTION_FIELDS):
        return False
    issued_ep, created_ep = _ep(rec.get("issuedAt")), _ep(rec.get("immutableCreatedAt"))
    if issued_ep is None or created_ep is None or issued_ep > created_ep:
        return False
    cutoff_at = rec.get("informationCutoffAt")
    if rec.get("mode") == "historical_replay":
        if _ep(rec.get("replayCutoffAt")) != issued_ep or \
                rec.get("replayCutoffAt") != cutoff_at:
            return False
    elif rec.get("replayCutoffAt") is not None or cutoff_at != rec.get("issuedAt"):
        return False
    if _normalize_truth_ref(rec.get("truthRef"), cutoff_at=cutoff_at) is None or \
            _normalize_maturity(rec.get("maturity"),
                                horizon=rec.get("forecastHorizon"),
                                cutoff_at=cutoff_at) is None or \
            _normalize_engine(rec.get("engine")) is None or \
            _normalize_policy(rec.get("evaluationPolicy")) is None:
        return False
    if _normalize_target_ladder(rec.get("targetLadder"),
                                rec.get("maturity")) != rec.get("targetLadder"):
        return False
    if rec.get("invalidation") is not None and \
            _normalize_invalidation(rec.get("invalidation"),
                                    rec.get("maturity")) != rec.get("invalidation"):
        return False
    if "forecastDistribution" in rec and \
            _normalize_forecast_distribution(
                rec.get("forecastDistribution")) != rec.get(
                    "forecastDistribution"):
        return False
    confidence = rec.get("confidence")
    if confidence is not None and (not _v2_number(confidence)
                                   or not 0.0 <= float(confidence) <= 1.0):
        return False
    for key, limit, chars in (("evidenceRefs", _V2_MAX_EVIDENCE_REFS, 200),
                              ("missingEvidence", 16, 200),
                              ("dissent", 16, 240)):
        if _v2_string_list(rec.get(key), limit, chars) != rec.get(key):
            return False
    return True


verify_prediction_integrity = verify_prediction_record_v2


def classify_prediction_record(rec: Any) -> Dict[str, Any]:
    """Read old v1 records without trusting their mutable ``origin`` field."""
    if isinstance(rec, dict) and rec.get("schemaVersion") == PREDICTION_LEDGER_V2_SCHEMA:
        valid = verify_prediction_record_v2(rec)
        return {"recordClass": "sealed_v2" if valid else "invalid_v2",
                "mode": rec.get("mode") if valid else LEGACY_PREDICTION_MODE,
                "modeSealed": bool(valid), "integrityValid": bool(valid),
                "id": rec.get("id")}
    legacy = isinstance(rec, dict) and bool(rec.get("id") or rec.get("issuedAt"))
    return {"recordClass": "legacy_v1" if legacy else "invalid",
            "mode": LEGACY_PREDICTION_MODE,
            "modeSealed": False, "integrityValid": False,
            "id": rec.get("id") if isinstance(rec, dict) else None}


def prediction_mode(rec: Any) -> str:
    return classify_prediction_record(rec)["mode"]


classify_prediction_mode = prediction_mode


def evaluation_metric(*, metric_type: str, family: str, value: Any = None,
                      unit: str, metric_version: str, method_version: str,
                      polarity: str = "contextual", window: str = "",
                      observed_at: str = "", first_observed_at: str = "",
                      observation_ref: str = "", target_ref: str = "",
                      comparator_ref: str = "",
                      evidence_refs: Optional[List[str]] = None,
                      missing_reason: str = "") -> Optional[Dict[str, Any]]:
    """Typed, versioned metric; opportunity names remain extensible/namespaced."""
    metric_name = _v2_string(metric_type, 96, required=True)
    version = _v2_string(metric_version, 80, required=True)
    method = _v2_string(method_version, 120, required=True)
    unit_text = _v2_string(unit, 40, required=True)
    window_text = _v2_string(window, 80)
    observation = _v2_string(observation_ref, 200)
    target = _v2_string(target_ref, 160)
    comparator = _v2_string(comparator_ref, 200)
    missing = _v2_string(missing_reason, 200)
    evidence = _v2_string_list(evidence_refs, _V2_MAX_EVIDENCE_REFS, 200)
    if None in (metric_name, version, method, unit_text, window_text,
                observation, target, comparator, missing, evidence):
        return None
    if not _V2_METRIC_TYPE_RE.match(metric_name) or family not in METRIC_FAMILIES \
            or polarity not in METRIC_POLARITIES:
        return None
    if observed_at and _ep(observed_at) is None:
        return None
    if first_observed_at and _ep(first_observed_at) is None:
        return None
    if observed_at and first_observed_at and \
            _ep(first_observed_at) > _ep(observed_at):
        return None
    if family == "missing":
        if value is not None or not missing:
            return None
    else:
        if value is None or missing:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if family in ("mfe", "mae", "end", "opportunity", "benchmark", "score") \
                and not _v2_number(value):
            return None
        if family in ("target", "invalidation") and \
                not isinstance(value, (bool, int, float, str)):
            return None
        if family in ("target", "invalidation") and not target:
            return None
        if family in ("target", "invalidation") and value is True and \
                not (observation or first_observed_at):
            return None
        if isinstance(value, str) and len(value) > 120:
            return None
        if _v2_json_copy(value, 512) is None:
            return None
    return {
        "schemaVersion": EVALUATION_METRIC_SCHEMA,
        "metricType": metric_name,
        "metricVersion": version,
        "family": family,
        "value": value,
        "unit": unit_text,
        "polarity": polarity,
        "window": window_text,
        "observedAt": observed_at or None,
        "firstObservedAt": first_observed_at or None,
        "observationRef": observation or None,
        "targetRef": target or None,
        "comparatorRef": comparator or None,
        "methodVersion": method,
        "evidenceRefs": evidence,
        "missingReason": missing or None,
    }


metric_record = evaluation_metric


def _normalize_metric(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schemaVersion") != EVALUATION_METRIC_SCHEMA:
        return None
    normalized = evaluation_metric(
        metric_type=value.get("metricType"), family=value.get("family"),
        value=value.get("value"), unit=value.get("unit"),
        metric_version=value.get("metricVersion"),
        method_version=value.get("methodVersion"),
        polarity=value.get("polarity"), window=value.get("window") or "",
        observed_at=value.get("observedAt") or "",
        first_observed_at=value.get("firstObservedAt") or "",
        observation_ref=value.get("observationRef") or "",
        target_ref=value.get("targetRef") or "",
        comparator_ref=value.get("comparatorRef") or "",
        evidence_refs=value.get("evidenceRefs"),
        missing_reason=value.get("missingReason") or "")
    return normalized if normalized == value else None


def _normalize_metrics(values: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(values, (list, tuple)) or not values or \
            len(values) > _V2_MAX_METRICS:
        return None
    out = []
    for value in values:
        metric = _normalize_metric(value)
        if metric is None:
            return None
        out.append(metric)
    return out


def _same_bar_ambiguous(metrics: List[Dict[str, Any]]) -> bool:
    targets = [m for m in metrics if m.get("family") == "target"
               and m.get("value") is True]
    invalidations = [m for m in metrics if m.get("family") == "invalidation"
                     and m.get("value") is True]
    for target in targets:
        for invalidation in invalidations:
            left = target.get("observationRef") or target.get("firstObservedAt")
            right = (invalidation.get("observationRef")
                     or invalidation.get("firstObservedAt"))
            if left and left == right:
                return True
    return False


def _outcome_metric_contract(prediction: Dict[str, Any], status: str,
                             truth_ref: Dict[str, Any],
                             metrics: List[Dict[str, Any]],
                             missing_reasons: List[str]) -> bool:
    families = {m.get("family") for m in metrics}
    metric_types = {m.get("metricType") for m in metrics}
    ambiguous = _same_bar_ambiguous(metrics)
    if ambiguous != (status == "AMBIGUOUS"):
        return False
    if status == "UNSCORABLE":
        if not (missing_reasons and families == {"missing"}):
            return False
        if str(prediction.get("candidateAction") or "").upper() == "WAIT":
            return {_WAIT_AVOIDED_MAE, _WAIT_MISSED_MFE}.issubset(metric_types)
        return True
    if truth_ref.get("observationKind") != "target_session_ohlc":
        return False
    fields = {str(f).lower() for f in truth_ref.get("observedFields") or []}
    if not {"open", "high", "low", "close"}.issubset(fields):
        return False                   # MFE/MAE must use actual target-session OHLC
    if not {"mfe", "mae", "end"}.issubset(families):
        return False
    if prediction.get("targetLadder") and "target" not in families:
        return False
    if prediction.get("invalidation") is not None and "invalidation" not in families:
        return False
    if status == "OBSERVED" and ambiguous:
        return False
    if str(prediction.get("candidateAction") or "").upper() == "WAIT":
        if not {_WAIT_AVOIDED_MAE, _WAIT_MISSED_MFE}.issubset(metric_types):
            return False
    return not missing_reasons


def outcome_resolution_event(*, prediction: Dict[str, Any], recorded_at: str,
                             truth_ref: Dict[str, Any], status: str,
                             metrics: List[Dict[str, Any]],
                             method_version: str, sequence: int = 1,
                             previous_event_id: str = "",
                             missing_reasons: Optional[List[str]] = None) \
        -> Optional[Dict[str, Any]]:
    """Append-only resolution event; a retry creates another event and ID."""
    if not verify_prediction_record_v2(prediction) or \
            status not in OUTCOME_RESOLUTION_STATUSES or \
            not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        return None
    recorded_ep = _ep(recorded_at)
    maturity = prediction.get("maturity") or {}
    if recorded_ep is None or recorded_ep < _ep(maturity.get("maturityAt")):
        return None
    previous = _v2_string(previous_event_id, 160)
    if previous is None or (sequence == 1 and previous) or \
            (sequence > 1 and not previous):
        return None
    method = _v2_string(method_version, 120, required=True)
    missing = _v2_string_list(missing_reasons, 16, 200)
    normalized_truth = _normalize_truth_ref(
        truth_ref, cutoff_at=recorded_at, require_target_session=True)
    normalized_metrics = _normalize_metrics(metrics)
    if method is None or missing is None or normalized_truth is None or \
            normalized_metrics is None:
        return None
    if normalized_truth.get("targetSessionId") != maturity.get("targetSessionId") \
            or _ep(normalized_truth.get("asOf")) != _ep(maturity.get("targetAt")):
        return None                     # never substitute today's/latest observation
    if not _outcome_metric_contract(prediction, status, normalized_truth,
                                    normalized_metrics, missing):
        return None
    body = {
        "schemaVersion": PREDICTION_LEDGER_V2_SCHEMA,
        "recordType": "outcome_resolution",
        "predictionId": prediction.get("id"),
        "predictionIntegrityHash": prediction.get("integrityHash"),
        "mode": prediction.get("mode"),
        "symbol": prediction.get("symbol"),
        "market": prediction.get("market"),
        "forecastHorizon": prediction.get("forecastHorizon"),
        "candidateAction": prediction.get("candidateAction"),
        "targetSessionId": maturity.get("targetSessionId"),
        "targetAt": maturity.get("targetAt"),
        "recordedAt": recorded_at,
        "sequence": sequence,
        "previousEventId": previous or None,
        "status": status,
        "truthRef": normalized_truth,
        "metrics": normalized_metrics,
        "missingReasons": missing,
        "methodVersion": method,
        "immutableCreatedAt": recorded_at,
    }
    return _v2_seal(body, "or")


outcome_event_record = outcome_resolution_event
outcome_event = outcome_resolution_event


def verify_outcome_resolution_event(rec: Any,
                                    prediction: Optional[Dict[str, Any]] = None) -> bool:
    if not _v2_verify_seal(rec, prefix="or", record_type="outcome_resolution") \
            or rec.get("mode") not in PREDICTION_MODES \
            or rec.get("status") not in OUTCOME_RESOLUTION_STATUSES:
        return False
    if not isinstance(rec.get("sequence"), int) or isinstance(rec.get("sequence"), bool) \
            or rec.get("sequence") < 1:
        return False
    if (rec.get("sequence") == 1 and rec.get("previousEventId") is not None) or \
            (rec.get("sequence") > 1 and not rec.get("previousEventId")):
        return False
    truth = _normalize_truth_ref(rec.get("truthRef"), cutoff_at=rec.get("recordedAt"),
                                 require_target_session=True)
    metrics = _normalize_metrics(rec.get("metrics"))
    missing = _v2_string_list(rec.get("missingReasons"), 16, 200)
    if truth is None or metrics is None or missing is None or \
            truth.get("targetSessionId") != rec.get("targetSessionId") or \
            _ep(truth.get("asOf")) != _ep(rec.get("targetAt")):
        return False
    if prediction is not None:
        if not verify_prediction_record_v2(prediction) or \
                rec.get("predictionId") != prediction.get("id") or \
                rec.get("predictionIntegrityHash") != prediction.get("integrityHash") or \
                rec.get("mode") != prediction.get("mode") or \
                rec.get("targetSessionId") != \
                (prediction.get("maturity") or {}).get("targetSessionId") or \
                not _outcome_metric_contract(prediction, rec.get("status"), truth,
                                             metrics, missing):
            return False
    else:
        if not _outcome_metric_contract(
                {"candidateAction": rec.get("candidateAction")},
                rec.get("status"), truth,
                                        metrics, missing):
            return False
    return _ep(rec.get("recordedAt")) is not None


verify_outcome_event = verify_outcome_resolution_event


def evaluation_event_record(*, prediction: Dict[str, Any],
                            outcome: Dict[str, Any], evaluated_at: str,
                            metrics: List[Dict[str, Any]],
                            scoring_policy: Dict[str, Any],
                            evaluator_id: str, evaluator_version: str,
                            build_sha: str) -> Optional[Dict[str, Any]]:
    """Append-only evaluation bound to one immutable prediction and resolution."""
    if not verify_prediction_record_v2(prediction) or \
            not verify_outcome_resolution_event(outcome, prediction):
        return None
    evaluated_ep = _ep(evaluated_at)
    if evaluated_ep is None or evaluated_ep < _ep(outcome.get("recordedAt")):
        return None
    normalized_metrics = _normalize_metrics(metrics)
    policy = _normalize_policy(scoring_policy)
    evaluator = _normalize_engine({"engineId": evaluator_id,
                                    "engineVersion": evaluator_version,
                                    "buildSha": build_sha})
    if normalized_metrics is None or policy is None or evaluator is None:
        return None
    outcome_scoreable = outcome.get("status") == "OBSERVED"
    if not outcome_scoreable and any(m.get("family") != "missing"
                                     for m in normalized_metrics):
        return None
    if outcome_scoreable and all(m.get("family") == "missing"
                                 for m in normalized_metrics):
        return None
    body = {
        "schemaVersion": PREDICTION_LEDGER_V2_SCHEMA,
        "recordType": "evaluation",
        "predictionId": prediction.get("id"),
        "predictionIntegrityHash": prediction.get("integrityHash"),
        "outcomeEventId": outcome.get("id"),
        "outcomeIntegrityHash": outcome.get("integrityHash"),
        "mode": prediction.get("mode"),
        "evaluationStatus": "SCORED" if outcome_scoreable else "UNSCORABLE",
        "evaluatedAt": evaluated_at,
        "truthRef": outcome.get("truthRef"),
        "scoringPolicy": policy,
        "evaluator": evaluator,
        "metrics": normalized_metrics,
        "immutableCreatedAt": evaluated_at,
    }
    return _v2_seal(body, "ev")


evaluation_event = evaluation_event_record


def verify_evaluation_event(rec: Any,
                            prediction: Optional[Dict[str, Any]] = None,
                            outcome: Optional[Dict[str, Any]] = None) -> bool:
    if not _v2_verify_seal(rec, prefix="ev", record_type="evaluation") or \
            rec.get("mode") not in PREDICTION_MODES or \
            rec.get("evaluationStatus") not in ("SCORED", "UNSCORABLE"):
        return False
    if _normalize_truth_ref(rec.get("truthRef"), cutoff_at=rec.get("evaluatedAt"),
                            require_target_session=True) is None or \
            _normalize_policy(rec.get("scoringPolicy")) is None or \
            _normalize_engine(rec.get("evaluator")) is None or \
            _normalize_metrics(rec.get("metrics")) is None:
        return False
    if rec.get("evaluationStatus") == "UNSCORABLE" and any(
            m.get("family") != "missing" for m in rec.get("metrics") or []):
        return False
    if prediction is not None:
        if not verify_prediction_record_v2(prediction) or \
                rec.get("predictionId") != prediction.get("id") or \
                rec.get("predictionIntegrityHash") != prediction.get("integrityHash") or \
                rec.get("mode") != prediction.get("mode"):
            return False
    if outcome is not None:
        if not verify_outcome_resolution_event(outcome, prediction) or \
                rec.get("outcomeEventId") != outcome.get("id") or \
                rec.get("outcomeIntegrityHash") != outcome.get("integrityHash") or \
                rec.get("truthRef") != outcome.get("truthRef") or \
                ((outcome.get("status") == "OBSERVED") !=
                 (rec.get("evaluationStatus") == "SCORED")):
            return False
    return _ep(rec.get("evaluatedAt")) is not None


def aggregate_evaluation_events(events: List[Dict[str, Any]], *, mode: str,
                                purpose: str = "diagnostic") -> Dict[str, Any]:
    """Bounded, explicit-mode aggregate; calibration is forward-live only."""
    if mode not in PREDICTION_MODES:
        raise ValueError("an explicit canonical prediction mode is required")
    if purpose not in ("diagnostic", "calibration"):
        raise ValueError("unsupported aggregate purpose")
    if purpose == "calibration" and mode != "forward_live":
        raise ValueError("calibration aggregates require forward_live mode")
    if not isinstance(events, (list, tuple)) or len(events) > _V2_MAX_AGGREGATE_EVENTS:
        raise ValueError("aggregate input must be a bounded sequence")
    rows: Dict[str, Dict[str, Any]] = {}
    included = excluded_mode = excluded_invalid = unscorable = 0
    for event in events:
        if not verify_evaluation_event(event):
            excluded_invalid += 1
            continue
        if event.get("mode") != mode:
            excluded_mode += 1
            continue
        included += 1
        if event.get("evaluationStatus") != "SCORED":
            unscorable += 1
        for metric in event.get("metrics") or []:
            if purpose == "calibration" and metric.get("family") != "score":
                continue
            key = "|".join((metric.get("metricType"), metric.get("metricVersion"),
                            metric.get("unit"), metric.get("methodVersion")))
            row = rows.setdefault(key, {
                "metricType": metric.get("metricType"),
                "metricVersion": metric.get("metricVersion"),
                "family": metric.get("family"), "unit": metric.get("unit"),
                "methodVersion": metric.get("methodVersion"),
                "count": 0, "missingCount": 0, "numericCount": 0,
                "sum": 0.0, "minimum": None, "maximum": None,
                "trueCount": 0, "falseCount": 0,
            })
            row["count"] += 1
            value = metric.get("value")
            if metric.get("family") == "missing":
                row["missingCount"] += 1
            elif isinstance(value, bool):
                row["trueCount" if value else "falseCount"] += 1
            elif _v2_number(value):
                number = float(value)
                row["numericCount"] += 1
                row["sum"] += number
                row["minimum"] = number if row["minimum"] is None else min(row["minimum"], number)
                row["maximum"] = number if row["maximum"] is None else max(row["maximum"], number)
    output = []
    for key in sorted(rows):
        row = rows[key]
        numeric_count = row.pop("numericCount")
        total = row.pop("sum")
        row["mean"] = (round(total / numeric_count, 8)
                       if numeric_count else None)
        row["numericCount"] = numeric_count
        output.append(row)
    return {
        "schemaVersion": PREDICTION_LEDGER_V2_SCHEMA,
        "recordType": "mode_scoped_evaluation_aggregate",
        "mode": mode, "purpose": purpose,
        "calibrationEligible": purpose == "calibration" and mode == "forward_live",
        "evaluationCount": included, "unscorableCount": unscorable,
        "excludedOtherMode": excluded_mode,
        "excludedInvalid": excluded_invalid, "metrics": output,
    }


mode_scoped_aggregate = aggregate_evaluation_events
