# -*- coding: utf-8 -*-
"""Formal Gemini 2X benchmark contract for ARGUS v12.3.3.

Pure/stdlib-only.  This module never performs network I/O.  It freezes the
dataset and rubric, calculates a conservative budget, blinds answer order,
enforces the one-shot holdout, and produces an append-only final result.
"""
import hashlib
import json
import math
import statistics
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = "argus-research-benchmark-v1"
DATASET_VERSION = "gemini-2x-dataset-v1"
RUBRIC_VERSION = "research-benchmark-rubric-v1"
MODE = "RESEARCH_BENCHMARK"
DEFAULT_MODE = "DETERMINISTIC"
HARD_BUDGET_JPY = 2000.0
MAX_EXECUTIONS = 1
CALIBRATION_CASES = 6
HOLDOUT_CASES = 12
TOTAL_CASES = CALIBRATION_CASES + HOLDOUT_CASES
MAX_TOKENS_PER_CALL = 8000

RUBRIC_WEIGHTS = {
    "factualAccuracy": 18,
    "primarySourceGrounding": 14,
    "citationValidity": 10,
    "causalReasoning": 12,
    "uncertaintyCalibration": 10,
    "temporalIntegrity": 10,
    "completeness": 10,
    "decisionUsefulness": 8,
    "unsupportedClaimDiscipline": 4,
    "criticalErrorDiscipline": 4,
}

_SOURCE_SETS = {
    "jp_company": (["tdnet", "company_ir", "jpx"], ["tdnet", "company_ir"]),
    "us_company": (["sec", "company_ir", "official_newsroom"], ["sec", "company_ir"]),
    "macro": (["bls", "bea", "federal_reserve", "boj"], ["bls", "bea", "federal_reserve", "boj"]),
    "market": (["exchange", "official_release", "company_ir", "reputable_news"], ["exchange", "official_release"]),
    "supply": (["jpx", "jsf", "jquants", "company_ir"], ["jpx", "jsf", "company_ir"]),
    "unknown": (["company_ir", "official_release", "reputable_news"], []),
}


def _case(case_id: str, phase: str, category: str, question: str,
          as_of: str, source_set: str, *, leakage: str = "future_sources_forbidden"
          ) -> Dict[str, Any]:
    permitted, primary = _SOURCE_SETS[source_set]
    return {
        "caseId": case_id,
        "phase": phase,
        "category": category,
        "question": question,
        "asOf": as_of,
        "informationCutoff": as_of,
        "permittedSources": list(permitted),
        "expectedPrimarySources": list(primary),
        "leakageGuard": leakage,
        "scoringRubricVersion": RUBRIC_VERSION,
    }


FORMAL_DATASET = (
    _case("cal-jp-earnings", "calibration", "日本株決算",
          "2025年3月期決算発表時点で、トヨタの業績変化と会社計画を一次資料から説明せよ。",
          "2025-05-08T15:30:00+09:00", "jp_company"),
    _case("cal-jp-disclosure", "calibration", "日本株適時開示",
          "浜松ホトニクスの当日時点の重要適時開示を、推測と事実を分けて説明せよ。",
          "2025-05-12T18:00:00+09:00", "jp_company"),
    _case("cal-us-earnings", "calibration", "米国株",
          "NVIDIAの2025年2月決算発表時点で確認できた需要・供給制約を説明せよ。",
          "2025-02-27T00:00:00Z", "us_company"),
    _case("cal-cpi", "calibration", "マクロイベント",
          "2025年5月CPI発表時点の結果を公式統計だけで要約し、未発表情報を混ぜるな。",
          "2025-06-11T13:00:00Z", "macro"),
    _case("cal-selloff", "calibration", "市場急落原因",
          "2025年4月4日の米国株下落について確認済み要因と未確認要因を分離せよ。",
          "2025-04-05T00:00:00Z", "market"),
    _case("cal-material-reaction", "calibration", "材料と価格反応",
          "企業材料と当日の価格反応を分け、値動きだけから原因を創作しないで説明せよ。",
          "2025-03-14T15:30:00+09:00", "market"),
    _case("hold-jp-guidance", "holdout", "日本株決算",
          "ソフトバンクグループの2025年5月決算時点の確認可能な投資損益要因を説明せよ。",
          "2025-05-13T18:00:00+09:00", "jp_company"),
    _case("hold-tdnet-capital", "holdout", "日本株適時開示",
          "資本政策に関する適時開示を一次資料に限定して評価せよ。",
          "2025-06-02T18:00:00+09:00", "jp_company"),
    _case("hold-us-sec", "holdout", "米国株",
          "米国企業の8-Kと決算資料で一致する事実、不一致、未確認事項を示せ。",
          "2025-05-01T23:00:00Z", "us_company"),
    _case("hold-fomc", "holdout", "マクロイベント",
          "2025年5月FOMC声明時点の決定と根拠を公式資料から説明せよ。",
          "2025-05-07T19:30:00Z", "macro"),
    _case("hold-boj", "holdout", "マクロイベント",
          "2025年5月の日銀会合時点で確認できる政策判断を、将来情報なしで説明せよ。",
          "2025-05-01T18:00:00+09:00", "macro"),
    _case("hold-shock-cause", "holdout", "市場急落原因",
          "急落日の引き金・脆弱性・増幅要因・不明を分けて説明せよ。",
          "2025-04-07T23:00:00Z", "market"),
    _case("hold-news-reaction", "holdout", "材料と価格反応",
          "材料公表時刻と価格反応時刻を分離し、時間順序を検証せよ。",
          "2025-05-20T15:30:00+09:00", "market"),
    _case("hold-jsf", "holdout", "機関投資家・需給",
          "日証金・取引所の一次データから需給を説明し、売買主体を断定するな。",
          "2025-06-06T18:00:00+09:00", "supply"),
    _case("hold-multi-cause", "holdout", "複数原因の切り分け",
          "企業材料、マクロ、需給が併存する局面で因果の強弱と不明点を分けよ。",
          "2025-06-13T23:00:00Z", "market"),
    _case("hold-stale", "holdout", "鮮度規律",
          "14日超の関連記事を当日の主因として扱わず、除外理由を示せ。",
          "2025-06-20T15:30:00+09:00", "market"),
    _case("hold-primary-conflict", "holdout", "一次情報競合",
          "企業資料と二次報道が食い違う場合の採用根拠と留保を説明せよ。",
          "2025-06-24T18:00:00+09:00", "jp_company"),
    _case("hold-unknown", "holdout", "不明と答えるべきケース",
          "一次情報と信頼できる報道で材料を確認できない場合、原因不明と回答せよ。",
          "2025-06-27T15:30:00+09:00", "unknown"),
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


DATASET_HASH = digest(list(FORMAL_DATASET))


def _epoch(value: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def validate_dataset(cases: Iterable[Dict[str, Any]] = FORMAL_DATASET) -> Dict[str, Any]:
    rows = list(cases)
    required = ("caseId", "phase", "category", "question", "asOf",
                "informationCutoff", "permittedSources",
                "expectedPrimarySources", "leakageGuard",
                "scoringRubricVersion")
    errors: List[str] = []
    ids = [str(c.get("caseId") or "") for c in rows]
    if len(rows) != TOTAL_CASES:
        errors.append("case_count")
    if len(set(ids)) != len(ids) or any(not x for x in ids):
        errors.append("case_id_unique")
    if sum(c.get("phase") == "calibration" for c in rows) != CALIBRATION_CASES:
        errors.append("calibration_count")
    if sum(c.get("phase") == "holdout" for c in rows) != HOLDOUT_CASES:
        errors.append("holdout_count")
    for c in rows:
        if any(k not in c for k in required):
            errors.append(f"missing_field:{c.get('caseId')}")
        if c.get("scoringRubricVersion") != RUBRIC_VERSION:
            errors.append(f"rubric:{c.get('caseId')}")
        if _epoch(c.get("asOf")) is None or _epoch(c.get("informationCutoff")) is None:
            errors.append(f"time:{c.get('caseId')}")
    return {"valid": not errors, "errors": sorted(set(errors)),
            "datasetHash": digest(rows), "caseCount": len(rows),
            "calibrationCount": sum(c.get("phase") == "calibration" for c in rows),
            "holdoutCount": sum(c.get("phase") == "holdout" for c in rows)}


def frozen_dataset() -> Dict[str, Any]:
    check = validate_dataset()
    return {"schemaVersion": SCHEMA_VERSION, "datasetVersion": DATASET_VERSION,
            "datasetHash": DATASET_HASH, "rubricVersion": RUBRIC_VERSION,
            "cases": deepcopy(list(FORMAL_DATASET)), **check}


def execution_plan() -> List[Dict[str, Any]]:
    """Calibration is always completed before the untouched holdout."""
    return [deepcopy(c) for c in FORMAL_DATASET
            if c["phase"] == "calibration"] + [deepcopy(c) for c in FORMAL_DATASET
                                                  if c["phase"] == "holdout"]


def estimate_cost(*, gemini_model: str, argus_model: str, evaluator_model: str,
                  pricing: Dict[str, Dict[str, float]], usd_jpy_ceiling: float,
                  input_tokens_per_call: int = 6000,
                  output_tokens_per_call: int = 1800,
                  grounding_usd_per_call: float = 0.0,
                  existing_budget_usd: Optional[float] = None,
                  providers_configured: bool = True) -> Dict[str, Any]:
    """Conservative 4-call/case estimate; no provider is contacted."""
    models = (gemini_model, gemini_model, argus_model, evaluator_model)
    missing_models = [m for m in models if not m or m not in pricing]
    per_case = 0.0
    if not missing_models:
        for model in models:
            rate = pricing[model]
            per_case += (input_tokens_per_call * float(rate.get("in") or 0)
                         + output_tokens_per_call * float(rate.get("out") or 0)) / 1_000_000
        per_case += max(0.0, float(grounding_usd_per_call)) * 2
    total_usd = per_case * TOTAL_CASES
    fx = max(1.0, float(usd_jpy_ceiling))
    configured_cap = (HARD_BUDGET_JPY if existing_budget_usd is None else
                      min(HARD_BUDGET_JPY, max(0.0, float(existing_budget_usd)) * fx))
    total_jpy = total_usd * fx
    if not providers_configured:
        status = "provider_blocked"
    elif missing_models:
        status = "invalid"
    elif total_jpy > configured_cap:
        status = "budget_blocked"
    else:
        status = "ready"
    body = {"mode": MODE, "status": status, "caseCount": TOTAL_CASES,
            "callsPerCase": 4, "maximumCalls": TOTAL_CASES * 4,
            "inputTokensPerCall": int(input_tokens_per_call),
            "outputTokensPerCall": int(output_tokens_per_call),
            "maximumTokensPerCall": MAX_TOKENS_PER_CALL,
            "estimatedCostUsd": round(total_usd, 6),
            "estimatedCostJpy": round(total_jpy, 2),
            "hardBudgetJpy": HARD_BUDGET_JPY,
            "effectiveBudgetJpy": round(configured_cap, 2),
            "usdJpyCeiling": fx, "models": {"gemini": gemini_model,
            "argus": argus_model, "evaluator": evaluator_model},
            "missingPricingModels": sorted(set(missing_models)),
            "datasetHash": DATASET_HASH, "rubricVersion": RUBRIC_VERSION,
            "providersConfigured": bool(providers_configured)}
    body["dryRunHash"] = digest(body)
    return body


def default_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "mode": DEFAULT_MODE,
            "status": "not_run", "datasetHash": DATASET_HASH,
            "rubricVersion": RUBRIC_VERSION, "dryRun": None,
            "executionCount": 0, "firstStartedAt": None,
            "runningBenchmarkId": None, "holdoutConsumedBy": None,
            "results": [], "lastCompletedAt": None}


def normalize_state(value: Any) -> Dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    out = default_state()
    out["mode"] = MODE if src.get("mode") == MODE else DEFAULT_MODE
    out["status"] = str(src.get("status") or "not_run")[:40]
    out["dryRun"] = deepcopy(src.get("dryRun")) if isinstance(src.get("dryRun"), dict) else None
    try:
        out["executionCount"] = max(0, int(src.get("executionCount") or 0))
    except (TypeError, ValueError):
        out["executionCount"] = 0
    out["firstStartedAt"] = src.get("firstStartedAt")
    out["runningBenchmarkId"] = src.get("runningBenchmarkId")
    out["holdoutConsumedBy"] = src.get("holdoutConsumedBy")
    out["results"] = [deepcopy(r) for r in (src.get("results") or [])
                      if isinstance(r, dict) and r.get("benchmarkId")][-20:]
    out["lastCompletedAt"] = src.get("lastCompletedAt")
    return out


def begin(state: Dict[str, Any], *, dry_run: Dict[str, Any], benchmark_id: str,
          trigger_source: str, confirmed: bool, started_at: str) -> Dict[str, Any]:
    st = normalize_state(state)
    if trigger_source != "manual":
        return {"allowed": False, "status": "scheduled_execution_rejected", "state": st}
    if not confirmed:
        return {"allowed": False, "status": "confirmation_required", "state": st}
    if dry_run.get("status") != "ready" or dry_run.get("datasetHash") != DATASET_HASH:
        return {"allowed": False, "status": dry_run.get("status") or "dry_run_required", "state": st}
    expected_hash = digest({k: v for k, v in dry_run.items() if k != "dryRunHash"})
    if dry_run.get("dryRunHash") != expected_hash:
        return {"allowed": False, "status": "dry_run_hash_mismatch", "state": st}
    if st.get("runningBenchmarkId"):
        return {"allowed": False, "status": "already_running", "state": st}
    if int(st.get("executionCount") or 0) >= MAX_EXECUTIONS:
        return {"allowed": False, "status": "execution_limit_reached", "state": st}
    if st.get("holdoutConsumedBy"):
        return {"allowed": False, "status": "holdout_already_consumed", "state": st}
    st.update({"mode": MODE, "status": "running", "dryRun": deepcopy(dry_run),
               "executionCount": int(st.get("executionCount") or 0) + 1,
               "firstStartedAt": st.get("firstStartedAt") or started_at,
               "runningBenchmarkId": benchmark_id,
               "startedAt": started_at})
    return {"allowed": True, "status": "running", "state": st}


def consume_holdout(state: Dict[str, Any], *, benchmark_id: str) -> Dict[str, Any]:
    """Atomically consume the one-shot holdout immediately before its first case."""
    st = normalize_state(state)
    if st.get("runningBenchmarkId") != benchmark_id:
        return {"allowed": False, "status": "benchmark_id_mismatch", "state": st}
    if st.get("holdoutConsumedBy") not in (None, benchmark_id):
        return {"allowed": False, "status": "holdout_already_consumed", "state": st}
    st["holdoutConsumedBy"] = benchmark_id
    return {"allowed": True, "status": "holdout_consumed", "state": st}


def blind_order(benchmark_id: str, case_id: str) -> Dict[str, str]:
    flip = int(digest({"benchmarkId": benchmark_id, "caseId": case_id})[-1], 16) % 2
    return ({"A": "argus", "B": "gemini"} if flip else
            {"A": "gemini", "B": "argus"})


def _clamp(value: Any) -> float:
    try:
        return min(100.0, max(0.0, float(value)))
    except Exception:
        return 0.0


def _future_claims(claims: List[Dict[str, Any]], cutoff: str) -> int:
    cut = _epoch(cutoff)
    if cut is None:
        return len(claims)
    return sum(1 for c in claims if c.get("publishedAt") and
               _epoch(c.get("publishedAt")) is not None and
               _epoch(c.get("publishedAt")) > cut)


def score_answer(*, axes: Dict[str, Any], claims: List[Dict[str, Any]],
                 case: Dict[str, Any]) -> Dict[str, Any]:
    weighted = sum(_clamp(axes.get(k)) * w for k, w in RUBRIC_WEIGHTS.items()) / 100
    unsupported = sum(1 for c in claims
                      if not (c.get("url") or c.get("sourceId"))
                      or c.get("sourceValidated") is False)
    fabricated = sum(1 for c in claims if c.get("fabricated") is True)
    future = _future_claims(claims, case["informationCutoff"])
    expected = set(case.get("expectedPrimarySources") or [])
    observed = {str(c.get("sourceId") or "") for c in claims}
    primary_ok = not expected or bool(expected & observed)
    penalty = unsupported * 4 + fabricated * 35 + future * 30
    if expected and not primary_ok:
        penalty += 15
    score = round(max(0.0, weighted - penalty), 2)
    return {"score": score, "unsupportedClaims": unsupported,
            "criticalFabrications": fabricated, "futureLeakageCount": future,
            "primarySourceGatePassed": primary_ok,
            "evidenceGatePassed": unsupported == 0,
            "temporalIntegrityGatePassed": future == 0,
            "claimCount": len(claims), "claimsHash": digest(claims)}


def case_result(*, benchmark_id: str, case: Dict[str, Any],
                evaluator_axes_by_label: Dict[str, Dict[str, Any]],
                claims_by_provider: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    order = blind_order(benchmark_id, case["caseId"])
    label_for = {provider: label for label, provider in order.items()}
    scored = {}
    for provider in ("gemini", "argus"):
        scored[provider] = score_answer(
            axes=evaluator_axes_by_label.get(label_for[provider]) or {},
            claims=list(claims_by_provider.get(provider) or []), case=case)
    ratio = (round(scored["argus"]["score"] / scored["gemini"]["score"], 4)
             if scored["gemini"]["score"] > 0 else None)
    return {"caseId": case["caseId"], "phase": case["phase"],
            "blindOrderHash": digest(order), "argus": scored["argus"],
            "gemini": scored["gemini"], "ratio": ratio,
            "valid": ratio is not None}


def _geometric_mean(values: List[float]) -> Optional[float]:
    if not values or any(v <= 0 for v in values):
        return None
    return math.exp(sum(math.log(v) for v in values) / len(values))


def finalize(*, state: Dict[str, Any], benchmark_id: str,
             research_epoch: str, code_sha: str, models: Dict[str, str],
             provider_settings: Dict[str, Any], total_cost_jpy: float,
             case_results: List[Dict[str, Any]], completed_at: str,
             limitations: Optional[List[str]] = None) -> Dict[str, Any]:
    st = normalize_state(state)
    if st.get("runningBenchmarkId") != benchmark_id:
        return {"ok": False, "status": "benchmark_id_mismatch", "state": st}
    by_id = {r.get("caseId"): r for r in case_results if isinstance(r, dict)}
    hold_ids = {c["caseId"] for c in FORMAL_DATASET if c["phase"] == "holdout"}
    cal_ids = {c["caseId"] for c in FORMAL_DATASET if c["phase"] == "calibration"}
    hold = [by_id[i] for i in sorted(hold_ids) if i in by_id]
    cal = [by_id[i] for i in sorted(cal_ids) if i in by_id]
    ratios = [float(r["ratio"]) for r in hold if r.get("valid") and
              isinstance(r.get("ratio"), (int, float))]
    required_models = ("gemini", "argus", "evaluator", "argusVersion")
    identity_complete = bool(research_epoch and code_sha and
                             all(models.get(k) for k in required_models) and
                             provider_settings.get("costStatus"))
    valid = len(hold) == HOLDOUT_CASES and len(cal) == CALIBRATION_CASES \
        and len(ratios) == HOLDOUT_CASES and identity_complete \
        and 0 <= float(total_cost_jpy) <= HARD_BUDGET_JPY
    median = statistics.median(ratios) if ratios else None
    geo = _geometric_mean(ratios)
    all_rows = hold + cal
    primary_gate = valid and all(r["argus"].get("primarySourceGatePassed") for r in hold)
    evidence_gate = valid and all(r["argus"].get("evidenceGatePassed") for r in hold)
    temporal_gate = valid and all(r["argus"].get("temporalIntegrityGatePassed") for r in hold)
    fabrications = sum(int(r["argus"].get("criticalFabrications") or 0)
                       for r in all_rows)
    two_x = bool(valid and median is not None and median >= 2.0 and
                 geo is not None and geo >= 1.8 and primary_gate and
                 evidence_gate and temporal_gate and fabrications == 0)
    classification = ("achieved" if two_x else "not_achieved" if valid else "invalid")
    result = {"schemaVersion": SCHEMA_VERSION, "benchmarkId": benchmark_id,
              "researchEpoch": research_epoch, "datasetHash": DATASET_HASH,
              "rubricVersion": RUBRIC_VERSION, "codeSha": code_sha,
              "modelIds": dict(models), "providerSettings": deepcopy(provider_settings),
              "totalCostJpy": round(max(0.0, float(total_cost_jpy)), 2),
              "calibrationCaseCount": len(cal), "holdoutCaseCount": len(hold),
              "caseResults": deepcopy(case_results),
              "geminiScore": round(statistics.mean(
                  [r["gemini"]["score"] for r in hold]), 2) if hold else None,
              "argusScore": round(statistics.mean(
                  [r["argus"]["score"] for r in hold]), 2) if hold else None,
              "medianRatio": round(median, 4) if median is not None else None,
              "geometricMeanRatio": round(geo, 4) if geo is not None else None,
              "primarySourceGatePassed": primary_gate,
              "evidenceGatePassed": evidence_gate,
              "temporalIntegrityGatePassed": temporal_gate,
              "criticalFabricationCount": fabrications,
              "twoXClaimAllowed": two_x, "resultClassification": classification,
              "limitations": list(limitations or []), "completedAt": completed_at}
    if not any(r.get("benchmarkId") == benchmark_id for r in st["results"]):
        st["results"].append(result)
    st.update({"mode": DEFAULT_MODE, "status": classification,
               "runningBenchmarkId": None, "lastCompletedAt": completed_at})
    return {"ok": valid, "status": classification, "result": result, "state": st}


def fail_closed(state: Dict[str, Any], *, status: str, completed_at: str) -> Dict[str, Any]:
    st = normalize_state(state)
    st.update({"mode": DEFAULT_MODE, "status": status[:40],
               "runningBenchmarkId": None, "lastCompletedAt": completed_at})
    return st


def public_status(state: Dict[str, Any]) -> Dict[str, Any]:
    st = normalize_state(state)
    latest = st["results"][-1] if st["results"] else None
    return {"schemaVersion": SCHEMA_VERSION, "mode": st["mode"],
            "status": st["status"], "datasetHash": DATASET_HASH,
            "rubricVersion": RUBRIC_VERSION,
            "benchmarkDate": (latest or {}).get("completedAt"),
            "researchEpoch": (latest or {}).get("researchEpoch"),
            "geminiModel": ((latest or {}).get("modelIds") or {}).get("gemini"),
            "argusVersion": ((latest or {}).get("modelIds") or {}).get("argusVersion"),
            "holdoutCaseCount": (latest or {}).get("holdoutCaseCount", 0),
            "geminiScore": (latest or {}).get("geminiScore"),
            "argusScore": (latest or {}).get("argusScore"),
            "medianRatio": (latest or {}).get("medianRatio"),
            "geometricMeanRatio": (latest or {}).get("geometricMeanRatio"),
            "primarySourceGatePassed": (latest or {}).get("primarySourceGatePassed", False),
            "evidenceGatePassed": (latest or {}).get("evidenceGatePassed", False),
            "temporalIntegrityGatePassed": (latest or {}).get("temporalIntegrityGatePassed", False),
            "twoXClaimAllowed": (latest or {}).get("twoXClaimAllowed", False),
            "totalApiCostJpy": (latest or {}).get("totalCostJpy", 0),
            "resultClassification": (latest or {}).get("resultClassification"),
            "limitations": list((latest or {}).get("limitations") or []),
            "automaticExecutionAllowed": False,
            "noteJa": ("GEMINI 2X ACHIEVED" if (latest or {}).get("twoXClaimAllowed")
                       else "GEMINI 2X NOT ACHIEVED" if latest
                       else "GEMINI 2X FORMAL BENCHMARK NOT RUN")}
