# -*- coding: utf-8 -*-
"""ARGUS AI Integrity Gate — v12.2.0 Phase 1/2/3 (pure, stdlib only).

中央実行規律: どのAI応答も、実際に検索・検証経路が走っていない限り
「検証済み調査」を名乗れない。
- AiExecutionResult: 全プロバイダ呼び出しの共通結果(store/usage/コスト/適格性)
- model_only は LIVE調査に偽装不可・主因証拠不可・ベンチ基準不可
- 価格不明モデルは $0 ではなく cost_unknown → 高コスト呼び出しをfail-closed
- ModelEpoch: モデル/プロンプト/ツールが変われば別エポック(異条件比較の禁止)
"""
from typing import Any, Dict, List, Optional

AI_EXEC_STATUSES = ("ok", "degraded", "failed", "disabled", "unavailable",
                    "budget_limited", "model_only", "search_failed",
                    "schema_failed")

# 承認済み直接呼び出しサイト(scanner.py の関数名)。これ以外の
# responses.create / chat.completions / generate_content はテストで失敗する。
APPROVED_CALL_SITES = {
    "gemini_score_stocks",      # legacy scoring (gemini flash)
    "_openai_judge",            # AI判定(主)
    "_gemini_check",            # 検算
    "_openai_prose",            # 解説文
    "api_argus_ai_provider_ping",  # adminプロバイダping(最小呼び出し)
    "_openai_research_ex",      # LIVE web調査(中央実行)
    "_gemini_osint",            # OSINTスカウト(grounding)
    "_translate_headlines_ja",  # 翻訳fallback(gemini flash)
    "_ai_capability_probe",     # v12.2.0 モデル能力プローブ(admin)
    "_gemini_capability_probe", # v12.6.3 raw-metadata benchmark preflight(admin)
    "_formal_blind_evaluate",  # v12.3.2 手動限定・匿名固定rubric評価
    "_v2_blind_evaluate",      # v12.7.0 手動限定・validity分離blind評価
}

BENCH_ELIGIBLE_STATUSES = ("ok",)          # ok以外はベンチ基準に使えない
RESEARCH_EVIDENCE_STATUSES = ("ok",)       # ok以外の出力は証拠化不可

MODEL_ONLY_NOTE_JA = ("モデル記憶ベース — 本日のweb検索は未実施。"
                      "検証済み調査ではなく、主因証拠にはなりません。")
SEARCH_FAILED_NOTE_JA = "web検索が失敗 — 検証済み調査として扱いません。"
DEGRADED_NOTE_JA = "互換フォールバック経路(degraded) — ベンチ基準・2x判定に不適格。"


def ai_execution_result(*, provider: str, model: str, role: str, mode: str,
                        status: str, started_at: str, completed_at: str,
                        prompt_version: str = "", input_context_version: str = "",
                        privacy_mode: str = "redacted",
                        store_disabled: bool = True,
                        tool_calls: Optional[List[str]] = None,
                        search_queries: Optional[List[str]] = None,
                        verified_urls: Optional[List[str]] = None,
                        citations: Optional[List[str]] = None,
                        usage: Optional[Dict[str, int]] = None,
                        estimated_cost: Optional[float] = None,
                        actual_cost: Optional[float] = None,
                        cost_status: str = "unknown",
                        cache_hit: bool = False,
                        fallback_used: bool = False,
                        response_id: Optional[str] = None,
                        response_model: Optional[str] = None,
                        failure_reason_redacted: Optional[str] = None) -> Dict[str, Any]:
    st = status if status in AI_EXEC_STATUSES else "failed"
    u = usage or {}
    return {
        "provider": provider, "model": model, "requestedModel": model,
        "responseModel": response_model, "role": role, "mode": mode,
        "status": st, "responseId": response_id,
        "startedAt": started_at, "completedAt": completed_at,
        "promptVersion": prompt_version,
        "inputContextVersion": input_context_version,
        "privacyMode": privacy_mode, "storeDisabled": bool(store_disabled),
        "toolCalls": list(tool_calls or [])[:8],
        "searchQueries": list(search_queries or [])[:8],
        "verifiedUrls": list(verified_urls or [])[:12],
        "citations": list(citations or [])[:12],
        "usage": {"inputTokens": int(u.get("inputTokens") or 0),
                  "cachedInputTokens": int(u.get("cachedInputTokens") or 0),
                  "outputTokens": int(u.get("outputTokens") or 0),
                  "reasoningTokens": int(u.get("reasoningTokens") or 0)},
        "estimatedCost": estimated_cost, "actualCost": actual_cost,
        "costStatus": cost_status if cost_status in ("known", "estimated",
                                                     "unknown") else "unknown",
        "cacheHit": bool(cache_hit), "fallbackUsed": bool(fallback_used),
        "benchmarkEligible": st in BENCH_ELIGIBLE_STATUSES and not fallback_used,
        "evidenceEligible": st in RESEARCH_EVIDENCE_STATUSES,
        "failureReasonRedacted": failure_reason_redacted,
        "noteJa": (MODEL_ONLY_NOTE_JA if st == "model_only"
                   else SEARCH_FAILED_NOTE_JA if st == "search_failed"
                   else DEGRADED_NOTE_JA if fallback_used or st == "degraded"
                   else None),
    }


# ── Phase 3: 価格 fail-closed ────────────────────────────────────────────────

def price_status(model: str, pricing_table: Dict[str, Any]) -> str:
    """モデル価格の既知性。不明は$0ではなくunknown(高コスト呼び出しをブロック)。"""
    m = (pricing_table or {}).get(str(model))
    if isinstance(m, dict) and isinstance(m.get("in"), (int, float)) \
            and isinstance(m.get("out"), (int, float)):
        return "known"
    return "unknown"


def can_execute_external(model: str, pricing_table: Dict[str, Any],
                         *, allow_unknown_price: bool = False) -> Dict[str, Any]:
    st = price_status(model, pricing_table)
    ok = st == "known" or bool(allow_unknown_price)
    return {"allowed": ok, "priceStatus": st,
            "reasonJa": (None if ok else
                         f"価格不明モデル({model}) — cost_unknownのため外部呼び出しを"
                         "ブロック(fail-closed)。管理側で価格設定または明示override"
                         "が必要。")}


def reserve_budget(*, day_spent: float, day_budget: float,
                   estimated_max_cost: float,
                   reserved: float = 0.0) -> Dict[str, Any]:
    """呼び出し前予約: spent+reserved+今回最大 <= budget。"""
    total = float(day_spent) + float(reserved) + float(estimated_max_cost)
    ok = total <= float(day_budget)
    return {"allowed": ok, "wouldTotal": round(total, 4),
            "dayBudget": float(day_budget),
            "reasonJa": (None if ok else
                         "予算予約が上限超過 — 外部呼び出しをスキップ"
                         "(決定論収集は継続・結果はbudget_limited表示)")}


# ── Phase 2: モデルエポック(異条件比較の禁止) ────────────────────────────────

def model_epoch_id(*, provider: str, model: str, prompt_version: str,
                   tool_mode: str, schema_version: str = "v1") -> str:
    return f"{provider}:{model}:{prompt_version}:{tool_mode}:{schema_version}"


def model_epoch_record(*, provider: str, model: str, prompt_version: str,
                       tool_mode: str, schema_version: str,
                       source_universe_version: str, started_at: str,
                       state: str = "active") -> Dict[str, Any]:
    return {"epochId": model_epoch_id(provider=provider, model=model,
                                      prompt_version=prompt_version,
                                      tool_mode=tool_mode,
                                      schema_version=schema_version),
            "provider": provider, "model": model,
            "promptVersion": prompt_version, "toolMode": tool_mode,
            "sourceUniverseVersion": source_universe_version,
            "schemaVersion": schema_version,
            "startedAt": started_at, "endedAt": None,
            "state": state if state in ("active", "shadow", "retired") else "shadow"}


def filter_runs_to_epoch(records: List[Dict[str, Any]], epoch_id: str,
                         legacy_epoch_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """基準runを現行エポックに限定。epoch欄のない旧記録はlegacy_epoch_idと
    一致する場合のみ採用(異エポック混在の校正を作らない)。"""
    out = []
    for r in records or []:
        e = r.get("epochId")
        if e == epoch_id or (e is None and legacy_epoch_id == epoch_id):
            out.append(r)
    return out


# ── Phase 2: シャドウ判定(決定論サンプリング・Date/random不使用) ─────────────

def shadow_should_sample(key: str, rate_pct: int) -> bool:
    if rate_pct <= 0:
        return False
    h = 0
    for ch in str(key):
        h = (h * 131 + ord(ch)) % 1000003
    return (h % 100) < min(100, int(rate_pct))
