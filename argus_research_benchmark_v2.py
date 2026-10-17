# -*- coding: utf-8 -*-
"""Protocol v2 for the one-time ARGUS research-system benchmark.

Pure and stdlib-only. Provider calls and URL checks remain in the admin-gated
runtime adapter. Protocol validity is intentionally independent from answer
quality: a weak but successfully transported/parsed answer is a valid scored
answer, not an excuse to replace a consumed holdout case.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = "argus-research-benchmark-v2"
PROTOCOL_VERSION = "v2"
DATASET_NAME = "ARGUS_RESEARCH_BENCHMARK_V2"
RUBRIC_VERSION = "research-benchmark-quality-v2"
SCORER_VERSION = "deterministic-evidence-temporal-v2"
MODE = "RESEARCH_BENCHMARK"
DEFAULT_MODE = "DETERMINISTIC"
HARD_BUDGET_JPY = 2000.0
CALIBRATION_CASES = 6
HOLDOUT_CASES = 12
RESERVE_CASES = 18
EXPECTED_POOL_SIZE = 36

QUALITY_WEIGHTS = {
    "primarySourceUsage": 14,
    "evidenceQuality": 14,
    "temporalDiscipline": 12,
    "factualAccuracy": 16,
    "relevance": 10,
    "reasoningQuality": 12,
    "uncertaintyCalibration": 8,
    "fabricationDiscipline": 8,
    "actionability": 6,
}

PROTOCOL_GATES = (
    "frozenDatasetHash", "unusedHoldout", "exactProviderModel",
    "responseReceived", "parseSuccess", "blindLabelRandomization",
    "noFutureLeakage", "noDuplicateCase", "noCaseSpecificTuning",
    "evaluatorIndependent", "deterministicScorerExecuted",
    "budgetCompliance", "oneTimeHoldout", "appendOnlyResult",
    "remoteJournalReadBack",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def question_fingerprint(value: Any) -> str:
    """Stable comparison key used only to prevent v1/v2 question reuse."""
    return digest(" ".join(str(value or "").split()).casefold())


def _instant(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _candidate(case_id: str, category: str, market: str, question: str,
               as_of: str, source_name: str, source_url: str) -> Dict[str, Any]:
    source = {"sourceId": source_name, "title": source_name,
              "url": source_url, "primary": True,
              "sourcePublishedAt": as_of, "availableFrom": as_of}
    evidence_hash = digest([source])
    return {"caseId": case_id, "category": category, "market": market,
            "ownerQuestion": question, "asOfTimestamp": as_of,
            "allowedEvidenceCutoff": as_of,
            "primarySourceDocuments": [source], "secondarySources": [],
            "evidenceBundleHash": evidence_hash,
            "expectedOutputContract": {
                "format": "json", "required": ["claims"],
                "claimFields": ["titleJa", "url", "publishedAt",
                                "sourceName", "whyRelevant", "confidence"]},
            "rubric": deepcopy(QUALITY_WEIGHTS),
            "exclusionRules": ["future evidence", "anonymous assertion",
                               "automatic trading instruction"],
            "futureLeakageTest": "publishedAt<=allowedEvidenceCutoff",
            "caseVersion": "v2.0"}


_SPECS = (
    ("company_earnings_tdnet", "JP", "トヨタの会社計画の変化を一次資料だけで整理せよ。", "2025-11-05T15:30:00+09:00", "Toyota IR", "https://global.toyota/en/ir/financial-results/"),
    ("company_earnings_tdnet", "JP", "ソニーグループのセグメント別変化を決算資料から整理せよ。", "2025-11-11T15:30:00+09:00", "Sony IR", "https://www.sony.com/en/SonyInfo/IR/library/"),
    ("company_earnings_tdnet", "US", "Appleの売上構成と会社説明をSEC一次資料から整理せよ。", "2025-10-31T21:00:00Z", "SEC Apple", "https://data.sec.gov/submissions/CIK0000320193.json"),
    ("company_earnings_tdnet", "US", "Microsoftのクラウド成長とリスク記述をSEC資料から整理せよ。", "2025-10-30T21:00:00Z", "SEC Microsoft", "https://data.sec.gov/submissions/CIK0000789019.json"),
    ("company_disclosure_ir", "JP", "任天堂の資本政策開示を事実と解釈に分けよ。", "2026-02-03T16:00:00+09:00", "Nintendo IR", "https://www.nintendo.co.jp/ir/en/finance/index.html"),
    ("company_disclosure_ir", "JP", "日立の事業再編開示について確定事項と条件を分けよ。", "2026-01-30T16:00:00+09:00", "Hitachi IR", "https://www.hitachi.com/IR-e/library/"),
    ("company_disclosure_ir", "US", "NVIDIAの8-Kに記載された確定事項と未確定事項を分けよ。", "2025-11-20T22:00:00Z", "SEC NVIDIA", "https://data.sec.gov/submissions/CIK0001045810.json"),
    ("company_disclosure_ir", "US", "Teslaの8-Kと会社資料で一致する事実だけを示せ。", "2026-01-29T22:00:00Z", "SEC Tesla", "https://data.sec.gov/submissions/CIK0001318605.json"),
    ("macroeconomic_event", "US", "CPI公表時点の総合・コアの変化を公式統計から説明せよ。", "2026-01-13T13:35:00Z", "BLS CPI", "https://www.bls.gov/cpi/"),
    ("macroeconomic_event", "US", "雇用統計公表時点の雇用・失業率・賃金を公式値で整理せよ。", "2026-02-06T13:35:00Z", "BLS Employment", "https://www.bls.gov/news.release/empsit.htm"),
    ("macroeconomic_event", "US", "GDP改定値の寄与をBEA一次資料から整理せよ。", "2026-02-26T13:35:00Z", "BEA GDP", "https://www.bea.gov/data/gdp/gross-domestic-product"),
    ("macroeconomic_event", "JP", "日銀短観の大企業製造業と非製造業の差を公式資料から説明せよ。", "2025-12-15T09:00:00+09:00", "BOJ Tankan", "https://www.boj.or.jp/en/statistics/tk/index.htm"),
    ("central_bank_policy", "US", "FOMC声明の決定とフォワードガイダンスを発表時点で整理せよ。", "2025-12-10T19:05:00Z", "Federal Reserve FOMC", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    ("central_bank_policy", "US", "FOMC議事要旨で確認できる意見分布を将来情報なしで整理せよ。", "2026-01-07T19:05:00Z", "Federal Reserve Minutes", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    ("central_bank_policy", "JP", "日銀金融政策決定会合の決定と展望を公式公表から説明せよ。", "2026-01-23T15:45:00+09:00", "BOJ MPM", "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"),
    ("central_bank_policy", "JP", "日銀主な意見から政策の不確実性を過不足なく整理せよ。", "2026-02-02T08:55:00+09:00", "BOJ Opinions", "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"),
    ("positioning_investor_flow", "JP", "海外投資家と個人の売買差を取引所統計から説明せよ。", "2026-01-15T15:30:00+09:00", "JPX Investor Type", "https://www.jpx.co.jp/english/markets/statistics-equities/investor-type/index.html"),
    ("positioning_investor_flow", "JP", "信用残の変化を売買主体の断定なしに整理せよ。", "2026-01-20T17:00:00+09:00", "JPX Margin", "https://www.jpx.co.jp/english/markets/statistics-equities/margin/index.html"),
    ("positioning_investor_flow", "US", "CFTC建玉から確認できるポジション変化と限界を説明せよ。", "2026-01-16T20:30:00Z", "CFTC COT", "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"),
    ("positioning_investor_flow", "US", "米国投信フローについて公式統計で確認できる範囲を示せ。", "2026-01-21T21:00:00Z", "Federal Reserve Z1", "https://www.federalreserve.gov/releases/z1/"),
    ("valuation", "JP", "指数水準と利益の関係を近似と公式値を混同せず説明せよ。", "2026-01-30T15:30:00+09:00", "JPX Index Data", "https://www.jpx.co.jp/english/markets/indices/index.html"),
    ("valuation", "US", "S&P500の利益と評価について一次データの範囲と限界を示せ。", "2026-01-30T21:00:00Z", "SEC Companyfacts", "https://www.sec.gov/edgar/sec-api-documentation"),
    ("valuation", "US", "米10年金利と株式評価の関係を因果断定せず整理せよ。", "2026-02-02T21:00:00Z", "US Treasury Rates", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"),
    ("valuation", "JP", "実質金利と日本株評価の関係を公式データから条件付きで説明せよ。", "2026-02-02T15:30:00+09:00", "BOJ Statistics", "https://www.boj.or.jp/en/statistics/index.htm"),
    ("market_breadth", "JP", "全市場の騰落銘柄数悪化を指数変化と分けて説明せよ。", "2026-01-30T17:00:00+09:00", "J-Quants", "https://jpx-jquants.com/"),
    ("market_breadth", "JP", "旧一部とPrimeを混同せず市場再編後のbreadthを説明せよ。", "2026-02-03T17:00:00+09:00", "JPX Market Structure", "https://www.jpx.co.jp/english/equities/improvements/market-structure/index.html"),
    ("market_breadth", "JP", "6日と25日騰落レシオの交差を予測ではなく観測として説明せよ。", "2026-02-04T17:00:00+09:00", "J-Quants", "https://jpx-jquants.com/"),
    ("cross_asset_break", "US", "株高と長期金利上昇の同時進行について確認可能な関係だけを示せ。", "2026-01-28T21:00:00Z", "Federal Reserve H15", "https://www.federalreserve.gov/releases/h15/"),
    ("cross_asset_break", "JP", "円安と日本株業種差を同時刻の事実と解釈に分けよ。", "2026-01-29T15:30:00+09:00", "BOJ FX", "https://www.boj.or.jp/en/statistics/market/forex/index.htm"),
    ("cross_asset_break", "US", "原油下落とエネルギー株の乖離をEIA一次資料と価格反応に分けよ。", "2026-02-04T21:00:00Z", "EIA Petroleum", "https://www.eia.gov/petroleum/"),
    ("good_news_bad_reaction", "US", "好決算後の株価下落を、材料・期待・価格反応に分けて説明せよ。", "2026-01-30T21:00:00Z", "SEC Meta", "https://data.sec.gov/submissions/CIK0001326801.json"),
    ("good_news_bad_reaction", "JP", "上方修正後の下落について会社開示と市場反応を混同せず説明せよ。", "2026-02-05T15:30:00+09:00", "SoftBank IR", "https://group.softbank/en/ir/presentations"),
    ("good_news_bad_reaction", "US", "悪材料公表後の株価上昇を事実と仮説に分けよ。", "2026-02-05T21:00:00Z", "SEC Amazon", "https://data.sec.gov/submissions/CIK0001018724.json"),
    ("event_driven_risk", "US", "政府閉鎖リスクの確定日程と市場への仮説を分けよ。", "2026-01-29T21:00:00Z", "US Treasury", "https://home.treasury.gov/news/press-releases"),
    ("event_driven_risk", "JP", "衆院選関連イベントを公式日程と市場仮説に分けよ。", "2026-01-29T15:30:00+09:00", "MIC Elections", "https://www.soumu.go.jp/english/"),
    ("event_driven_risk", "US", "企業買収の完了条件と破談リスクをSEC資料から整理せよ。", "2026-02-06T21:00:00Z", "SEC Mergers", "https://www.sec.gov/edgar/search-and-access"),
)


def candidate_pool() -> List[Dict[str, Any]]:
    counters: Dict[str, int] = {}
    rows = []
    for category, market, question, as_of, source_name, source_url in _SPECS:
        counters[category] = counters.get(category, 0) + 1
        rows.append(_candidate(
            f"v2-{category}-{counters[category]:02d}", category, market,
            question, as_of, source_name, source_url))
    return rows


CANDIDATE_POOL_HASH = digest(candidate_pool())


def frozen_manifest(code_sha: str) -> Dict[str, Any]:
    pool = candidate_pool()
    seed = digest("ARGUS_BENCHMARK_V2" + str(code_sha) + CANDIDATE_POOL_HASH)
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for row in pool:
        by_category.setdefault(row["category"], []).append(row)
    ordered: List[Dict[str, Any]] = []
    for category in sorted(by_category):
        ordered.extend(sorted(by_category[category], key=lambda row: digest(
            seed + row["caseId"])))
    calibration, holdout = [], []
    categories = sorted(by_category, key=lambda value: digest(seed + value))
    for category in categories[:CALIBRATION_CASES]:
        row = next(x for x in ordered if x["category"] == category
                   and x not in calibration)
        calibration.append(row)
    remaining = [x for x in ordered if x not in calibration]
    for category in categories:
        row = next((x for x in remaining if x["category"] == category), None)
        if row and len(holdout) < HOLDOUT_CASES:
            holdout.append(row)
            remaining.remove(row)
    holdout.extend(remaining[:HOLDOUT_CASES - len(holdout)])
    reserve = [x for x in pool if x not in calibration and x not in holdout]
    selected = {"calibration": calibration, "holdout": holdout,
                "reserve": reserve}
    dataset_hash = digest({"name": DATASET_NAME, "selected": selected})
    return {"schemaVersion": SCHEMA_VERSION, "protocolVersion": PROTOCOL_VERSION,
            "datasetName": DATASET_NAME, "originMainSha": str(code_sha),
            "candidatePoolHash": CANDIDATE_POOL_HASH,
            "deterministicSeed": seed, "datasetHash": dataset_hash,
            "candidatePoolCount": len(pool), "calibration": deepcopy(calibration),
            "holdout": deepcopy(holdout), "reserve": deepcopy(reserve),
            "rubricVersion": RUBRIC_VERSION, "scorerVersion": SCORER_VERSION,
            "frozen": True}


def validate_manifest(manifest: Dict[str, Any], *, v1_case_ids: Iterable[str] = (),
                      v1_questions: Iterable[str] = (),
                      source_access: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    errors: List[str] = []
    phases = [manifest.get("calibration") or [], manifest.get("holdout") or [],
              manifest.get("reserve") or []]
    rows = [row for phase in phases for row in phase if isinstance(row, dict)]
    ids = [str(row.get("caseId") or "") for row in rows]
    if len(rows) != EXPECTED_POOL_SIZE or len(set(ids)) != EXPECTED_POOL_SIZE:
        errors.append("candidate_count_or_duplicate")
    if len(phases[0]) != CALIBRATION_CASES or len(phases[1]) != HOLDOUT_CASES \
            or len(phases[2]) < RESERVE_CASES:
        errors.append("phase_count")
    if set(ids) & set(v1_case_ids):
        errors.append("v1_overlap")
    v1_question_hashes = {question_fingerprint(value) for value in v1_questions
                          if str(value or "").strip()}
    if any(question_fingerprint(row.get("ownerQuestion")) in v1_question_hashes
           for row in rows):
        errors.append("v1_question_overlap")
    selected_ids = {x.get("caseId") for x in phases[0] + phases[1]}
    if len(selected_ids) != CALIBRATION_CASES + HOLDOUT_CASES:
        errors.append("calibration_holdout_overlap")
    for row in phases[0] + phases[1]:
        cid = str(row.get("caseId") or "")
        required = ("category", "market", "ownerQuestion", "asOfTimestamp",
                    "allowedEvidenceCutoff", "evidenceBundleHash",
                    "expectedOutputContract", "rubric", "futureLeakageTest",
                    "caseVersion")
        if any(not row.get(key) for key in required):
            errors.append(f"missing_contract:{cid}")
        sources = row.get("primarySourceDocuments") or []
        if not sources or any(not x.get("url") or not x.get("sourcePublishedAt")
                              or not x.get("availableFrom") for x in sources):
            errors.append(f"primary_source:{cid}")
        cutoff = _instant(row.get("allowedEvidenceCutoff"))
        if cutoff is None or _instant(row.get("asOfTimestamp")) is None:
            errors.append(f"timestamp:{cid}")
        for source in sources:
            published = _instant(source.get("sourcePublishedAt"))
            available = _instant(source.get("availableFrom"))
            if published is None or available is None:
                errors.append(f"source_timestamp:{cid}")
            elif cutoff is not None and (published > cutoff or available > cutoff):
                errors.append(f"future_leakage:{cid}")
        if digest(sources) != row.get("evidenceBundleHash"):
            errors.append(f"evidence_hash:{cid}")
        if row.get("rubric") != QUALITY_WEIGHTS:
            errors.append(f"rubric:{cid}")
        contract = row.get("expectedOutputContract") or {}
        if (contract.get("format") != "json" or
                "claims" not in (contract.get("required") or []) or
                not isinstance(contract.get("claimFields"), list)):
            errors.append(f"output_contract:{cid}")
        if source_access is not None and not all(
                source_access.get(str(x.get("url"))) is True for x in sources):
            errors.append(f"source_inaccessible:{cid}")
    expected_hash = digest({"name": DATASET_NAME,
                            "selected": {"calibration": phases[0],
                                         "holdout": phases[1],
                                         "reserve": phases[2]}})
    if manifest.get("datasetHash") != expected_hash:
        errors.append("dataset_hash")
    return {"valid": not errors, "errors": sorted(set(errors)),
            "validatedCaseCount": len(phases[0]) + len(phases[1]),
            "datasetHash": expected_hash}


def default_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "protocolVersion": PROTOCOL_VERSION,
            "mode": DEFAULT_MODE, "status": "not_run", "v1Closure": None,
            "manifest": None, "calibrationRuns": [], "calibrationAttemptCount": 0,
            "frozenRun": None,
            "holdoutConsumedBy": None, "holdoutResult": None,
            "results": [], "remoteReceipts": [],
            "runningBenchmarkId": None, "lastCompletedAt": None}


def normalize_state(value: Any) -> Dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    out = default_state()
    for key in out:
        if key in src:
            out[key] = deepcopy(src[key])
    out["mode"] = MODE if src.get("mode") == MODE else DEFAULT_MODE
    out["calibrationRuns"] = [deepcopy(x) for x in (src.get("calibrationRuns") or [])
                              if isinstance(x, dict)][-6:]
    out["results"] = [deepcopy(x) for x in (src.get("results") or [])
                      if isinstance(x, dict) and x.get("benchmarkId")][-4:]
    out["remoteReceipts"] = [deepcopy(x) for x in (src.get("remoteReceipts") or [])
                             if isinstance(x, dict) and x.get("benchmarkId")][-8:]
    return out


def append_remote_receipt(state: Dict[str, Any], *, benchmark_id: str,
                          receipt: Dict[str, Any]) -> Dict[str, Any]:
    st = normalize_state(state)
    row = {"benchmarkId": benchmark_id,
           "remoteCommitSha": receipt.get("remoteCommitSha"),
           "expectedHash": receipt.get("expectedHash"),
           "actualHash": receipt.get("actualHash"),
           "readBackVerified": receipt.get("readBackVerified") is True,
           "verifiedAt": receipt.get("verifiedAt")}
    receipt_id = digest(row)
    row["receiptId"] = receipt_id
    if not any(x.get("receiptId") == receipt_id for x in st["remoteReceipts"]):
        st["remoteReceipts"].append(row)
    return st


def close_v1(state: Dict[str, Any], v1_public: Dict[str, Any], *,
             closed_at: str, remote_receipt: Optional[Dict[str, Any]] = None
             ) -> Dict[str, Any]:
    st = normalize_state(state)
    if st.get("v1Closure"):
        return st
    st["v1Closure"] = {"protocolVersion": "v1", "status": "closed_invalid",
                       "holdoutConsumed": True, "rerunAllowed": False,
                       "twoXClaimAllowed": False, "datasetHash": v1_public.get("datasetHash"),
                       "runId": v1_public.get("benchmarkId"),
                       "exactModels": deepcopy(v1_public.get("modelIds") or {}),
                       "geminiScore": v1_public.get("geminiScore"),
                       "argusScore": v1_public.get("argusScore"),
                       "medianRatio": v1_public.get("medianRatio"),
                       "geometricMeanRatio": v1_public.get("geometricMeanRatio"),
                       "actualCostJpy": (v1_public.get("totalApiCostJpy")
                                         if v1_public.get("totalApiCostJpy") is not None
                                         else v1_public.get("totalCostJpy")),
                       "invalidReasons": ["valid_holdout_5_of_12",
                                          "invalid_holdout_7_of_12",
                                          "quality_gates_failed"],
                       "remoteJournalReceipt": deepcopy(remote_receipt or {}),
                       "closedAt": closed_at}
    return st


def blind_order(run_id: str, case_id: str) -> Dict[str, str]:
    flip = int(digest(run_id + case_id)[-1], 16) % 2
    return {"A": "argus", "B": "gemini"} if flip else {
        "A": "gemini", "B": "argus"}


def _clamp(value: Any) -> float:
    try:
        return min(100.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def score_case(*, run_id: str, case: Dict[str, Any],
               axes_by_label: Dict[str, Dict[str, Any]],
               claims_by_provider: Dict[str, List[Dict[str, Any]]],
               protocol_gates: Dict[str, bool]) -> Dict[str, Any]:
    order = blind_order(run_id, case["caseId"])
    label_for = {provider: label for label, provider in order.items()}
    scored: Dict[str, Any] = {}
    for provider in ("gemini", "argus"):
        axes = axes_by_label.get(label_for[provider]) or {}
        claims = list(claims_by_provider.get(provider) or [])
        cutoff = _instant(case.get("allowedEvidenceCutoff"))
        published_instants = [_instant(x.get("publishedAt")) for x in claims]
        future = sum(1 for published in published_instants
                     if cutoff is not None and published is not None
                     and published > cutoff)
        temporal_unknown = sum(published is None
                               for published in published_instants)
        unsupported = sum(1 for x in claims if x.get("sourceValidated") is not True)
        critical = sum(1 for x in claims if x.get("fabricated") is True)
        dimensions = {key: _clamp(axes.get(key)) for key in QUALITY_WEIGHTS}
        dimensions["primarySourceUsage"] = max(
            0.0, dimensions["primarySourceUsage"] - unsupported * 15)
        dimensions["evidenceQuality"] = max(
            0.0, dimensions["evidenceQuality"] - unsupported * 12)
        dimensions["temporalDiscipline"] = max(
            0.0, dimensions["temporalDiscipline"] - future * 35
            - temporal_unknown * 15)
        if critical:
            dimensions["fabricationDiscipline"] = 0.0
        score = sum(dimensions[k] * QUALITY_WEIGHTS[k]
                    for k in QUALITY_WEIGHTS) / 100.0
        if critical:
            score = 0.0
        scored[provider] = {"score": round(score, 2),
                            "qualityDimensions": dimensions,
                            "criticalFabricationCount": critical,
                            "futureLeakageCount": future,
                            "unknownPublishedAtCount": temporal_unknown,
                            "unsupportedClaimCount": unsupported,
                            "responseClaims": deepcopy(claims),
                            "claimsHash": digest(claims)}
    gates = {key: protocol_gates.get(key) is True for key in PROTOCOL_GATES}
    protocol_valid = all(gates.values())
    ratio = (round(scored["argus"]["score"] / scored["gemini"]["score"], 4)
             if scored["gemini"]["score"] > 0 else None)
    return {"caseId": case["caseId"], "category": case.get("category"),
            "market": case.get("market"),
            "evidenceBundleHash": case.get("evidenceBundleHash"),
            "protocolValid": protocol_valid,
            "protocolGates": gates, "blindOrder": deepcopy(order),
            "blindOrderHash": digest(order),
            "blindEvaluatorResult": deepcopy(axes_by_label),
            "gemini": scored["gemini"], "argus": scored["argus"],
            "ratio": ratio}


def record_calibration(state: Dict[str, Any], *, run_id: str,
                       rows: List[Dict[str, Any]], completed_at: str,
                       models: Dict[str, str], implementation_hash: str) -> Dict[str, Any]:
    st = normalize_state(state)
    valid = len(rows) == CALIBRATION_CASES and all(
        row.get("protocolValid") is True for row in rows)
    record = {"runId": run_id, "caseCount": len(rows),
              "protocolValidCount": sum(row.get("protocolValid") is True for row in rows),
              "valid": valid, "caseResults": deepcopy(rows),
              "models": deepcopy(models), "implementationHash": implementation_hash,
              "completedAt": completed_at}
    if not any(x.get("runId") == run_id for x in st["calibrationRuns"]):
        st["calibrationRuns"].append(record)
    st["status"] = "calibration_passed" if valid else "calibration_failed"
    if valid:
        st["frozenRun"] = {"calibrationRunId": run_id,
                           "implementationHash": implementation_hash,
                           "models": deepcopy(models), "rubricVersion": RUBRIC_VERSION,
                           "scorerVersion": SCORER_VERSION, "frozenAt": completed_at}
    return st


def consume_holdout(state: Dict[str, Any], *, run_id: str) -> Dict[str, Any]:
    st = normalize_state(state)
    if not st.get("frozenRun"):
        return {"allowed": False, "status": "calibration_not_frozen", "state": st}
    if st.get("holdoutConsumedBy") not in (None, run_id):
        return {"allowed": False, "status": "holdout_already_consumed", "state": st}
    st["holdoutConsumedBy"] = run_id
    st["runningBenchmarkId"] = run_id
    st["mode"] = MODE
    st["status"] = "holdout_running"
    return {"allowed": True, "status": "holdout_consumed", "state": st}


def _geometric_mean(values: List[float]) -> Optional[float]:
    if not values or any(value <= 0 for value in values):
        return None
    return math.exp(sum(math.log(value) for value in values) / len(values))


def _bootstrap_ci(values: List[float], seed: str) -> Optional[List[float]]:
    if not values:
        return None
    rng = random.Random(int(digest(seed)[:16], 16))
    samples = []
    for _ in range(2000):
        draw = [values[rng.randrange(len(values))] for _ in values]
        samples.append(statistics.median(draw))
    samples.sort()
    return [round(samples[int(len(samples) * .025)], 4),
            round(samples[min(len(samples) - 1, int(len(samples) * .975))], 4)]


def finalize(state: Dict[str, Any], *, run_id: str, rows: List[Dict[str, Any]],
             models: Dict[str, str], provider_proof: Dict[str, Any],
             pricing: Dict[str, Any], actual_cost_jpy: float,
             completed_at: str, remote_receipt: Optional[Dict[str, Any]] = None
             ) -> Dict[str, Any]:
    st = normalize_state(state)
    valid = (st.get("holdoutConsumedBy") == run_id and
             len(rows) == HOLDOUT_CASES and
             all(row.get("protocolValid") is True for row in rows) and
             models.get("gemini") and models.get("argus") and models.get("referee") and
             models.get("argus") != models.get("referee") and
             0 <= float(actual_cost_jpy) <= HARD_BUDGET_JPY)
    ratios = [float(x["ratio"]) for x in rows
              if isinstance(x.get("ratio"), (int, float)) and x["ratio"] > 0]
    median = statistics.median(ratios) if ratios else None
    geo = _geometric_mean(ratios)
    gemini_score = statistics.mean([x["gemini"]["score"] for x in rows]) if rows else None
    argus_score = statistics.mean([x["argus"]["score"] for x in rows]) if rows else None
    wins = sum(x.get("ratio") is not None and x["ratio"] > 1.0 for x in rows)
    losses = sum(x.get("ratio") is not None and x["ratio"] < 1.0 for x in rows)
    ties = len(rows) - wins - losses
    critical = sum(x["argus"].get("criticalFabricationCount", 0) for x in rows)
    quality_gates = {
        name: (statistics.mean([x["argus"]["qualityDimensions"][name]
                                for x in rows]) >= 80 if rows else False)
        for name in ("primarySourceUsage", "evidenceQuality", "temporalDiscipline")}
    quality_dimensions = {
        provider: {
            name: (round(statistics.mean([
                row[provider]["qualityDimensions"][name] for row in rows]), 2)
                   if rows else None)
            for name in QUALITY_WEIGHTS
        }
        for provider in ("gemini", "argus")
    }
    categories: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        categories.setdefault(str(row.get("category") or "unknown"), []).append(row)
    category_breakdown = {}
    for category, category_rows in sorted(categories.items()):
        category_ratios = [float(row["ratio"]) for row in category_rows
                           if isinstance(row.get("ratio"), (int, float))
                           and row["ratio"] > 0]
        category_breakdown[category] = {
            "caseCount": len(category_rows),
            "geminiScore": round(statistics.mean(
                row["gemini"]["score"] for row in category_rows), 2),
            "argusScore": round(statistics.mean(
                row["argus"]["score"] for row in category_rows), 2),
            "medianRatio": (round(statistics.median(category_ratios), 4)
                            if category_ratios else None),
        }
    two_x = bool(valid and len(ratios) == HOLDOUT_CASES and median is not None
                 and median >= 2.0 and geo is not None and geo >= 1.8
                 and all(quality_gates.values()) and critical == 0)
    status = "achieved" if two_x else "not_achieved" if valid else "invalid"
    ci = _bootstrap_ci(ratios, run_id)
    result = {"schemaVersion": SCHEMA_VERSION, "protocolVersion": PROTOCOL_VERSION,
              "benchmarkId": run_id, "status": status,
              "formalDetermination": ("GEMINI 2X ACHIEVED" if two_x else
                                       "GEMINI 2X NOT ACHIEVED — FORMALLY CLOSED" if valid
                                       else "BENCHMARK INVALID"),
              "datasetHash": (st.get("manifest") or {}).get("datasetHash"),
              "candidatePoolHash": CANDIDATE_POOL_HASH,
              "deterministicSeed": (st.get("manifest") or {}).get("deterministicSeed"),
              "modelIds": deepcopy(models), "providerPreflight": deepcopy(provider_proof),
              "pricing": deepcopy(pricing), "actualCostJpy": round(actual_cost_jpy, 2),
              "calibrationValid": bool(st.get("frozenRun")),
              "holdoutValidCount": sum(x.get("protocolValid") is True for x in rows),
              "holdoutCaseCount": len(rows), "geminiScore": round(gemini_score, 2),
              "argusScore": round(argus_score, 2),
              "medianRatio": round(median, 4) if median is not None else None,
              "geometricMeanRatio": round(geo, 4) if geo is not None else None,
              "confidenceInterval95": ci, "wins": wins, "losses": losses,
              "ties": ties, "qualityClaimGates": quality_gates,
              "qualityDimensions": quality_dimensions,
              "categoryBreakdown": category_breakdown,
              "criticalFabricationCount": critical,
              "twoXClaimAllowed": two_x, "caseResults": deepcopy(rows),
              "remoteJournalReceipt": deepcopy(remote_receipt or {}),
              "completedAt": completed_at}
    if not any(x.get("benchmarkId") == run_id for x in st["results"]):
        st["results"].append(result)
    st.update({"mode": DEFAULT_MODE, "status": status,
               "holdoutResult": result, "runningBenchmarkId": None,
               "lastCompletedAt": completed_at})
    return {"ok": valid, "status": status, "result": result, "state": st}


def public_status(state: Dict[str, Any]) -> Dict[str, Any]:
    st = normalize_state(state)
    result = st.get("holdoutResult") or {}
    return {"schemaVersion": SCHEMA_VERSION, "protocolVersion": PROTOCOL_VERSION,
            "mode": st.get("mode"), "status": st.get("status"),
            "v1Closure": deepcopy(st.get("v1Closure")),
            "candidatePoolCount": len(candidate_pool()),
            "candidatePoolHash": CANDIDATE_POOL_HASH,
            "deterministicSeed": (st.get("manifest") or {}).get("deterministicSeed"),
            "datasetHash": (st.get("manifest") or {}).get("datasetHash"),
            "calibrationValid": bool(st.get("frozenRun")),
            "holdoutConsumed": bool(st.get("holdoutConsumedBy")),
            "formalDetermination": result.get("formalDetermination"),
            "modelIds": deepcopy(result.get("modelIds") or {}),
            "geminiScore": result.get("geminiScore"),
            "argusScore": result.get("argusScore"),
            "medianRatio": result.get("medianRatio"),
            "geometricMeanRatio": result.get("geometricMeanRatio"),
            "confidenceInterval95": result.get("confidenceInterval95"),
            "qualityClaimGates": deepcopy(result.get("qualityClaimGates") or {}),
            "qualityDimensions": deepcopy(result.get("qualityDimensions") or {}),
            "categoryBreakdown": deepcopy(result.get("categoryBreakdown") or {}),
            "criticalFabricationCount": result.get("criticalFabricationCount"),
            "actualCostJpy": result.get("actualCostJpy"),
            "remoteJournalReceipt": deepcopy(
                (st.get("remoteReceipts") or [None])[-1]),
            "twoXClaimAllowed": bool(result.get("twoXClaimAllowed")),
            "automaticExecutionAllowed": False}
