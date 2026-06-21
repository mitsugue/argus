"""ARGUS Evidence-First Research — deterministic dossier engine (v10.41, Lean).

Pure, stdlib-only. Builds the structured research dossier GPT's #10 asks for —
what happened / confirmed / probable cause / flow / market scope / trap risks /
next-session scenarios / invalidation / missing data — from signals ARGUS
ALREADY has (entry-scout flow inference, metrics, credit, market-regime, news),
WITHOUT any LLM. AI Gear 2/3 enrichment is a future opt-in; this is the honest
deterministic floor. Every probability group sums to 1. NOT a trade instruction.
"""
DOSSIER_SCHEMA = "dossier-v1"
DISCLAIMER_JA = "これは調査・判断支援であり、自動売買指示ではありません。確率は予言ではなく状況整理です。"

# Research postures (deterministic; NEVER BUY/SELL/EXECUTE).
RESEARCH_POSTURES = {
    "IGNORE", "OBSERVE", "VERIFY", "RESEARCH_COMPLETE", "HIGH_ALERT",
    "PRE_MARKET_REVIEW_REQUIRED", "AVOID_CHASING", "GAP_RISK",
    "LIMIT_UP_RISK", "LIMIT_DOWN_RISK", "NO_ACTION",
}


def _norm(d):
    """Normalize a {label: weight} dict to probabilities summing to 1 (rounded)."""
    tot = sum(v for v in d.values() if v > 0)
    if tot <= 0:
        return {}
    out = {k: round(v / tot, 3) for k, v in d.items() if v > 0}
    # fix rounding drift onto the largest bucket so the group sums to exactly 1
    drift = round(1.0 - sum(out.values()), 3)
    if out and abs(drift) >= 0.001:
        top = max(out, key=out.get)
        out[top] = round(out[top] + drift, 3)
    return out


def market_scope(sym_chg, index_chg):
    """company_specific / market_wide / unconfirmed. Sector attribution needs a
    sector feed we don't reliably have → never claimed."""
    if not isinstance(sym_chg, (int, float)):
        return "unconfirmed"
    if not isinstance(index_chg, (int, float)):
        return "unconfirmed"          # no broad-market reference → honest unknown
    if abs(index_chg) >= 1.0 and abs(sym_chg - index_chg) <= 1.0:
        return "market_wide"
    if abs(sym_chg) >= 3.0 and abs(index_chg) < 1.0:
        return "company_specific"
    return "unconfirmed"


def probable_cause(event_type, flow_class, has_news, scope):
    """Ranked, evidence-anchored cause hypotheses (probabilities sum to 1)."""
    w = {"official_catalyst": 0.0, "flow_driven": 0.0, "sector_or_market": 0.0,
         "technical_momentum": 0.0, "unknown": 0.6}
    if has_news:
        w["official_catalyst"] += 1.4
    if flow_class == "SHORT_COVERING":
        w["flow_driven"] += 1.2
    elif flow_class == "NEW_LONG_ACCUMULATION":
        w["flow_driven"] += 1.0
    elif flow_class == "DISTRIBUTION":
        w["flow_driven"] += 0.8
    if scope in ("market_wide", "sector_wide"):
        w["sector_or_market"] += 1.3
    if event_type in ("PRICE_SPIKE", "PRICE_CRASH", "LIMIT_UP", "LIMIT_DOWN",
                      "LIMIT_UP_PROXIMITY", "LIMIT_DOWN_PROXIMITY"):
        w["technical_momentum"] += 0.6
    return _norm(w)


def trap_risks(event_type, flow_class, rsi):
    """Deterministic hazard flags for a sharp move (no LLM)."""
    risks = []
    up = event_type in ("PRICE_SPIKE", "LIMIT_UP", "LIMIT_UP_PROXIMITY")
    if up and flow_class == "DISTRIBUTION":
        risks.append("distribution_into_strength")
    if up and flow_class == "SHORT_COVERING":
        risks.append("squeeze_exhaustion")
    if up and isinstance(rsi, (int, float)) and rsi >= 75:
        risks.append("overbought_gap_and_fade")
    if up:
        risks.append("gap_and_fade")
    if event_type in ("PRICE_CRASH", "LIMIT_DOWN", "LIMIT_DOWN_PROXIMITY"):
        risks.append("falling_knife")
        if flow_class == "SHORT_COVERING":
            risks.append("dead_cat_bounce")
    return list(dict.fromkeys(risks))   # dedup, keep order


def next_session_scenarios(event_type, flow_class):
    """Next-session scenario distribution (sums to 1). Flow tilts the odds."""
    up = event_type in ("PRICE_SPIKE", "LIMIT_UP", "LIMIT_UP_PROXIMITY")
    down = event_type in ("PRICE_CRASH", "LIMIT_DOWN", "LIMIT_DOWN_PROXIMITY")
    if up:
        w = {"large_gap_up": 1.0, "gap_and_fade": 1.0, "no_follow_through": 0.8}
        if flow_class == "NEW_LONG_ACCUMULATION":
            w["large_gap_up"] += 0.6
        if flow_class in ("DISTRIBUTION", "SHORT_COVERING"):
            w["gap_and_fade"] += 0.7
    elif down:
        w = {"continued_weakness": 1.0, "rebound_attempt": 0.9, "stabilize": 0.8}
        if flow_class == "SHORT_COVERING":
            w["rebound_attempt"] += 0.5
        if flow_class == "DISTRIBUTION":
            w["continued_weakness"] += 0.5
    else:
        w = {"follow_through": 1.0, "mean_revert": 1.0, "no_change": 1.0}
    return _norm(w)


def research_confidence(have_flow, have_news, have_scope, have_metrics):
    """0.1–0.9 confidence from how many independent signals are present."""
    c = 0.25 + 0.18 * sum([bool(have_flow), bool(have_news), have_scope != "unconfirmed", bool(have_metrics)])
    return round(min(0.9, max(0.1, c)), 2)


def research_posture(event_type, severity, scope, flow_class, confidence, reviewer="CAUTION"):
    """Deterministic final posture (code, never an LLM). Downgrades on weak data
    or a reject. NEVER emits a trade instruction."""
    if reviewer == "REJECT" or confidence < 0.3:
        return "OBSERVE"
    if event_type in ("LIMIT_UP", "LIMIT_UP_PROXIMITY"):
        return "LIMIT_UP_RISK"
    if event_type in ("LIMIT_DOWN", "LIMIT_DOWN_PROXIMITY"):
        return "LIMIT_DOWN_RISK"
    if event_type == "PRICE_SPIKE":
        return "AVOID_CHASING" if flow_class in ("DISTRIBUTION", "SHORT_COVERING") else "PRE_MARKET_REVIEW_REQUIRED"
    if event_type == "PRICE_CRASH":
        return "PRE_MARKET_REVIEW_REQUIRED" if severity >= 4 else "VERIFY"
    if severity >= 5:
        return "HIGH_ALERT"
    if reviewer == "CAUTION":
        return "VERIFY"
    return "OBSERVE"


def adversarial_review(scope, flow_class, has_news, confidence, trap_list):
    """Deterministic stand-in for the adversarial reviewer (Gear 2 AI later).
    ACCEPT / CAUTION / REJECT + objections — challenges the easy story."""
    objections = []
    if not has_news:
        objections.append("確認できる公式の材料(開示/ニュース)が無い — 値動きだけの可能性")
    if scope == "market_wide":
        objections.append("市場全体の動きの可能性(個別材料に帰属できない)")
    if scope == "unconfirmed":
        objections.append("市場全体か個別かを判定する基準データが不足")
    if "squeeze_exhaustion" in trap_list:
        objections.append("踏み上げが一巡している可能性(燃料切れ)")
    if "distribution_into_strength" in trap_list:
        objections.append("上昇中の売り抜け(分配)の疑い")
    verdict = "ACCEPT" if (has_news and confidence >= 0.6 and scope != "unconfirmed") \
        else "REJECT" if (confidence < 0.3) else "CAUTION"
    return {"verdict": verdict, "objectionsJa": objections}


def build_dossier(*, event, flow_inf, rsi, sym_chg, index_chg, has_news,
                  news_items, evidence, asset_name=None):
    """Assemble the full deterministic Research Dossier (GPT #10 shape). Pure."""
    et = event.get("eventType")
    sev = event.get("severity") or 1
    flow_class = (flow_inf or {}).get("classification")
    scope = market_scope(sym_chg, index_chg)
    cause = probable_cause(et, flow_class, has_news, scope)
    traps = trap_risks(et, flow_class, rsi)
    scenarios = next_session_scenarios(et, flow_class)
    conf = research_confidence(bool(flow_class), has_news, scope, rsi is not None)
    review = adversarial_review(scope, flow_class, has_news, conf, traps)
    posture = research_posture(et, sev, scope, flow_class, conf, review["verdict"])

    # flow probabilities (reuse the scout's probabilistic flow inference if present)
    fi = (flow_inf or {}).get("probabilities") or {}
    flow_out = {
        "newLongAccumulation": fi.get("newLongAccumulation", 0.0),
        "shortCovering": fi.get("shortCovering", 0.0),
        "distribution": fi.get("distribution", 0.0),
        "retailNoise": fi.get("retailNoise", 0.0),
        "unknown": fi.get("unconfirmed", 1.0 if not fi else 0.0),
    }

    missing = []
    if not has_news:
        missing.append("公式開示/ニュースの確認(TDnet/EDINET未接続 — News Radar範囲のみ)")
    if scope == "unconfirmed":
        missing.append("指数/セクターとの比較基準(市場全体か個別かの確定不可)")
    if rsi is None:
        missing.append("テクニカル指標(価格履歴未取得)")

    invalidation = []
    if et in ("PRICE_SPIKE", "LIMIT_UP", "LIMIT_UP_PROXIMITY"):
        invalidation.append("翌セッションで寄り後に上値を切り下げ、出来高が伴わなければ上昇仮説は無効")
    if flow_class == "SHORT_COVERING":
        invalidation.append("貸株残の縮小が止まり出来高が細れば踏み上げ一巡とみなす")

    confirmed = []
    if flow_class and flow_class != "UNCONFIRMED":
        confirmed.append({"claimJa": (flow_inf or {}).get("reasonsJa", [None])[0] or f"フロー推定: {flow_class}",
                          "evidenceIds": [e["evidenceId"] for e in evidence if e.get("claimType") == "derived_metric"][:2]})
    for n in (news_items or [])[:2]:
        confirmed.append({"claimJa": n, "evidenceIds": [e["evidenceId"] for e in evidence if e.get("claimType") == "news_report"][:1]})

    return {
        "schemaVersion": DOSSIER_SCHEMA, "eventId": event.get("eventId"),
        "rootEventId": event.get("rootEventId") or event.get("eventId"),
        "revision": event.get("eventVersion", 1), "status": event.get("lifecycleState"),
        "currentGear": event.get("currentGear", 1),
        "symbol": event.get("symbol"), "assetName": asset_name, "session": event.get("session"),
        "researchPosture": posture, "researchConfidence": conf,
        "whatHappenedJa": event.get("reasonJa"),
        "confirmedFacts": confirmed, "unconfirmedClaims": [],
        "probableCause": [{"label": k, "probability": v} for k, v in cause.items()],
        "flowInference": flow_out,
        "marketScope": scope, "crossMarketConfirmation": [],
        "trapRisks": traps,
        "nextSessionScenarios": [{"label": k, "probability": v} for k, v in scenarios.items()],
        "invalidationConditions": invalidation, "missingData": missing,
        "reviewVerdict": review["verdict"], "reviewObjectionsJa": review["objectionsJa"],
        "dataLimitations": ["決定論的分析(LLM未使用)。AIによる深掘りは将来オプション。",
                            "PTS・板(L2)・VWAP・公式開示フィード(TDnet/EDINET)は未接続。"],
        "evidence": evidence,
        "engine": "deterministic", "disclaimerJa": DISCLAIMER_JA,
    }
