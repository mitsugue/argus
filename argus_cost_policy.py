# -*- coding: utf-8 -*-
"""Central generative-AI cost policy for ARGUS v12.3.0.

Pure/stdlib-only.  Market-data providers are deliberately outside this policy.
The default is fail-closed DETERMINISTIC: cached AI output remains readable, but
no OpenAI/Gemini/Anthropic request is authorized automatically.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

MODES = ("DETERMINISTIC", "EVENT_OPT_IN", "MANUAL", "RESEARCH_BENCHMARK")
PROVIDERS = ("openai", "gemini", "anthropic")
EVENT_PHASES = ("pre", "post")
SCHEMA_VERSION = "argus-cost-policy-v1"


def default_state(mode: str = "DETERMINISTIC", event_opt_in: bool = False) -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": mode if mode in MODES else "DETERMINISTIC",
        "eventOptIn": bool(event_opt_in),
        "events": {},
        "usage": [],
        "lastExecution": None,
    }


def normalize_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = state if isinstance(state, dict) else {}
    out = default_state(str(src.get("mode") or "DETERMINISTIC"),
                        bool(src.get("eventOptIn")))
    out["events"] = dict(src.get("events") or {})
    out["usage"] = [x for x in (src.get("usage") or []) if isinstance(x, dict)][-500:]
    out["lastExecution"] = src.get("lastExecution") if isinstance(
        src.get("lastExecution"), dict) else None
    return out


def configure(state: Dict[str, Any], *, mode: str, event_opt_in: bool,
              event_id: str = "", event_enabled: bool = False,
              providers: Optional[list] = None, event_budget_usd: float = 1.0,
              event_token_limit: int = 12000) -> Dict[str, Any]:
    """Return validated operator configuration; never enables an unknown provider."""
    if mode not in MODES:
        raise ValueError("invalid_mode")
    st = normalize_state(state)
    st["mode"] = mode
    st["eventOptIn"] = bool(event_opt_in)
    if event_id:
        selected = [str(p).lower() for p in (providers or [])
                    if str(p).lower() in PROVIDERS]
        if not selected:
            raise ValueError("provider_required")
        st["events"][str(event_id)] = {
            **dict(st["events"].get(str(event_id)) or {}),
            "enabled": bool(event_enabled), "providers": selected,
            "budgetUsd": max(0.0, float(event_budget_usd)),
            "tokenLimit": max(1, int(event_token_limit)),
            "phaseRuns": dict((st["events"].get(str(event_id)) or {}).get("phaseRuns") or {}),
        }
    return st


def _skip(mode: str, reason: str, purpose: str) -> Dict[str, Any]:
    return {"allowed": False, "classification": "expected_skip",
            "status": "deterministic_mode" if reason == "deterministic_mode" else reason,
            "reason": reason, "mode": mode, "purpose": purpose}


def authorize(state: Dict[str, Any], *, provider: str, purpose: str,
              automatic: bool, now_iso: str = "", event_id: str = "",
              event_phase: str = "", confirmation: bool = False,
              estimated_cost_usd: Optional[float] = None,
              estimated_tokens: Optional[int] = None,
              provider_enabled: bool = True,
              event_budget_usd: float = 1.0,
              event_token_limit: int = 12000) -> Dict[str, Any]:
    """Return an authorization without performing I/O or mutating state."""
    st = normalize_state(state)
    mode = st["mode"]
    p = str(provider).lower()
    if p not in PROVIDERS:
        return _skip(mode, "provider_not_supported", purpose)
    if not provider_enabled:
        return _skip(mode, "provider_disabled", purpose)
    if mode == "DETERMINISTIC":
        return _skip(mode, "deterministic_mode", purpose)
    if mode == "MANUAL":
        if automatic:
            return _skip(mode, "manual_only", purpose)
        if not confirmation:
            return _skip(mode, "confirmation_required", purpose)
        if purpose != "manual_api":
            return _skip(mode, "manual_api_only", purpose)
    if mode == "RESEARCH_BENCHMARK":
        if automatic:
            return _skip(mode, "manual_only", purpose)
        if not confirmation:
            return _skip(mode, "confirmation_required", purpose)
        if purpose != "research_benchmark":
            return _skip(mode, "benchmark_scope_required", purpose)
    if mode == "EVENT_OPT_IN":
        if not st.get("eventOptIn"):
            return _skip(mode, "event_opt_in_disabled", purpose)
        if purpose != "event_analysis" or not event_id or event_phase not in EVENT_PHASES:
            return _skip(mode, "event_scope_required", purpose)
        ev = (st.get("events") or {}).get(event_id) or {}
        if not ev.get("enabled"):
            return _skip(mode, "event_not_enabled", purpose)
        if p not in (ev.get("providers") or [p]):
            return _skip(mode, "provider_not_enabled_for_event", purpose)
        if int((ev.get("phaseRuns") or {}).get(event_phase) or 0) >= 1:
            return _skip(mode, "event_phase_already_run", purpose)
        event_budget_usd = min(event_budget_usd, float(ev.get("budgetUsd") or event_budget_usd))
        event_token_limit = min(event_token_limit, int(ev.get("tokenLimit") or event_token_limit))
    if estimated_cost_usd is None or estimated_cost_usd < 0:
        return _skip(mode, "cost_unknown", purpose)
    if estimated_cost_usd > event_budget_usd:
        return _skip(mode, "event_budget_exceeded", purpose)
    if estimated_tokens is None or estimated_tokens < 0:
        return _skip(mode, "tokens_unknown", purpose)
    if estimated_tokens > event_token_limit:
        return _skip(mode, "event_token_limit", purpose)
    return {"allowed": True, "classification": "success", "status": "allowed",
            "reason": None, "mode": mode, "purpose": purpose,
            "provider": p, "eventId": event_id or None,
            "eventPhase": event_phase or None, "authorizedAt": now_iso}


def record_execution(state: Dict[str, Any], *, provider: str, purpose: str,
                     at: str, estimated_cost_usd: float = 0.0,
                     event_id: str = "", event_phase: str = "") -> Dict[str, Any]:
    st = normalize_state(state)
    row = {"provider": str(provider).lower(), "purpose": purpose, "at": at,
           "estimatedCostUsd": round(max(0.0, float(estimated_cost_usd)), 6),
           "eventId": event_id or None, "eventPhase": event_phase or None}
    st["usage"].append(row)
    st["usage"] = st["usage"][-500:]
    st["lastExecution"] = row
    if event_id and event_phase in EVENT_PHASES:
        ev = dict(st["events"].get(event_id) or {})
        phases = dict(ev.get("phaseRuns") or {})
        phases[event_phase] = int(phases.get(event_phase) or 0) + 1
        ev["phaseRuns"] = phases
        st["events"][event_id] = ev
    return st


def _day(s: str) -> str:
    return str(s or "")[:10]


def _month(s: str) -> str:
    return str(s or "")[:7]


def public_status(state: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    st = normalize_state(state)
    today, month = _day(now_iso), _month(now_iso)
    day_rows = [x for x in st["usage"] if _day(x.get("at")) == today]
    month_rows = [x for x in st["usage"] if _month(x.get("at")) == month]
    counts = {p: sum(1 for x in day_rows if x.get("provider") == p)
              for p in PROVIDERS}
    mode = st["mode"]
    next_allowed = ("重要イベントの明示opt-in後" if mode == "EVENT_OPT_IN"
                    else "明示確認付きmanual APIのみ" if mode == "MANUAL"
                    else "固定benchmark実行中のみ" if mode == "RESEARCH_BENCHMARK"
                    else "なし(相談パックはAPIなしで随時生成可)")
    return {
        "schemaVersion": SCHEMA_VERSION, "asOf": now_iso, "mode": mode,
        "eventOptIn": bool(st.get("eventOptIn")),
        "automaticAiEnabled": mode == "EVENT_OPT_IN" and bool(st.get("eventOptIn")),
        "todayRuns": counts,
        "todayEstimatedCostUsd": round(sum(float(x.get("estimatedCostUsd") or 0)
                                            for x in day_rows), 6),
        "monthEstimatedCostUsd": round(sum(float(x.get("estimatedCostUsd") or 0)
                                            for x in month_rows), 6),
        "lastExecutionReason": (st.get("lastExecution") or {}).get("purpose"),
        "nextAllowedAiExecution": next_allowed,
        "messageJa": {
            "DETERMINISTIC": "市場データ、イベント、台帳、ルール判断は動作します。自動AIは実行しません。",
            "EVENT_OPT_IN": "有効化した重要イベントの前後だけAIを実行します。",
            "MANUAL": "明示的に深掘りを実行した場合だけAIを使用します。",
            "RESEARCH_BENCHMARK": "固定済み研究benchmarkだけを上限内で手動実行します。",
        }[mode],
    }
