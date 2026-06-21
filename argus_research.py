"""ARGUS Evidence-First Research — deterministic dossier engine (dossier-v2, v10.41.1).

Pure, stdlib-only. Builds the structured research dossier GPT #10/#41.1 asks for,
from signals ARGUS ALREADY has — with NO LLM. Hardened for epistemic honesty:
- facts / observations / reports / derived metrics / inferences / unverified are
  SEPARATE buckets (a flow classification or a news headline is never a
  "confirmed fact");
- catalyst weight is source-TIERED (a generic headline never becomes an official
  catalyst);
- confidence is a labelled-uncalibrated evidence-coverage score (UNCONFIRMED flow
  does NOT count as a signal);
- every probability group is validated + normalized to sum 1 (NaN/inf/neg/missing
  → unknown=1) and carries a calibrationStatus.
Posture is from a research-only set — NEVER a trade instruction.
"""
import math

SCHEMA = "dossier-v2"
CALIB = "uncalibrated_heuristic_v1"        # no outcome calibration yet (honest)
DISCLAIMER_JA = ("これは調査・判断支援であり、自動売買指示ではありません。確率は予言ではなく状況整理で、"
                 "確信度は実績で較正されていないヒューリスティック値です。")

RESEARCH_POSTURES = {
    "IGNORE", "OBSERVE", "VERIFY", "RESEARCH_COMPLETE", "HIGH_ALERT",
    "PRE_MARKET_REVIEW_REQUIRED", "AVOID_CHASING", "GAP_RISK",
    "LIMIT_UP_RISK", "LIMIT_DOWN_RISK", "NO_ACTION",
}

# Source reliability tiers — only the top three can establish an official catalyst.
OFFICIAL_TIERS = {"exchange_or_regulator", "official_filing", "company_ir"}
_TIER_RELIABILITY = {
    "exchange_or_regulator": 0.95, "official_filing": 0.9, "company_ir": 0.85,
    "trusted_newswire": 0.6, "reputable_secondary_media": 0.45, "aggregator": 0.3,
    "social_or_rumor": 0.15, "unknown": 0.2,
}


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_probs(d):
    """Normalize a {label: weight} dict to probabilities summing to 1. Rejects
    NaN/inf/negative/malformed; empty/all-bad → {'unknown': 1.0}. Pure."""
    if not isinstance(d, dict):
        return {"unknown": 1.0}
    clean = {str(k): float(v) for k, v in d.items() if _finite(v) and v >= 0}
    tot = sum(clean.values())
    if tot <= 0:
        return {"unknown": 1.0}
    out = {k: round(v / tot, 3) for k, v in clean.items() if v > 0}
    drift = round(1.0 - sum(out.values()), 3)
    if out and abs(drift) >= 0.001:
        top = max(out, key=out.get)
        out[top] = round(out[top] + drift, 3)
    return out


def has_confirmed_flow_signal(flow_class):
    """A flow classification only counts as evidence when it is an actual class —
    UNCONFIRMED / UNKNOWN / missing do NOT (fixes the bool('UNCONFIRMED') bug)."""
    return flow_class not in (None, "", "UNCONFIRMED", "UNKNOWN", "unknown")


def tier_reliability(tier):
    return _TIER_RELIABILITY.get(tier, 0.2)


def is_official_catalyst(tier):
    return tier in OFFICIAL_TIERS


def market_scope(sym_chg, index_chg, index_fresh=True):
    """company_specific / market_wide / unconfirmed. A stale or missing benchmark
    → unconfirmed (never guessed). sector_wide is NOT claimed (no sector proxy)."""
    if not _finite(sym_chg) or not _finite(index_chg) or not index_fresh:
        return "unconfirmed"
    if abs(index_chg) >= 1.0 and abs(sym_chg - index_chg) <= 1.0:
        return "market_wide"
    if abs(sym_chg) >= 3.0 and abs(index_chg) < 1.0:
        return "company_specific"
    return "unconfirmed"


def probable_cause(event_type, flow_class, catalyst_tier, scope):
    """Ranked cause hypotheses (sum to 1). official_catalyst ONLY from a top-tier
    source; a newswire/aggregator headline supports 'reported_catalyst' instead."""
    w = {"official_catalyst": 0.0, "reported_catalyst": 0.0, "flow_driven": 0.0,
         "sector_or_market": 0.0, "technical_momentum": 0.0, "unknown": 0.6}
    if is_official_catalyst(catalyst_tier):
        w["official_catalyst"] += 1.4
    elif catalyst_tier in ("trusted_newswire", "reputable_secondary_media"):
        w["reported_catalyst"] += 0.8
    elif catalyst_tier in ("aggregator", "social_or_rumor"):
        w["reported_catalyst"] += 0.3        # low reliability — cannot establish cause
    if has_confirmed_flow_signal(flow_class):
        w["flow_driven"] += {"SHORT_COVERING": 1.2, "NEW_LONG_ACCUMULATION": 1.0,
                             "DISTRIBUTION": 0.8}.get(flow_class, 0.5)
    if scope == "market_wide":
        w["sector_or_market"] += 1.3
    if event_type in ("PRICE_SPIKE", "PRICE_CRASH", "LIMIT_UP", "LIMIT_DOWN",
                      "LIMIT_UP_PROXIMITY", "LIMIT_DOWN_PROXIMITY"):
        w["technical_momentum"] += 0.6
    return validate_probs(w)


def trap_risks(event_type, flow_class, rsi):
    risks = []
    up = event_type in ("PRICE_SPIKE", "LIMIT_UP", "LIMIT_UP_PROXIMITY")
    if up and flow_class == "DISTRIBUTION":
        risks.append("distribution_into_strength")
    if up and flow_class == "SHORT_COVERING":
        risks.append("squeeze_exhaustion")
    if up and _finite(rsi) and rsi >= 75:
        risks.append("overbought_gap_and_fade")
    if up:
        risks.append("gap_and_fade")
    if event_type in ("PRICE_CRASH", "LIMIT_DOWN", "LIMIT_DOWN_PROXIMITY"):
        risks.append("falling_knife")
        if flow_class == "SHORT_COVERING":
            risks.append("dead_cat_bounce")
    return list(dict.fromkeys(risks))


def next_session_scenarios(event_type, flow_class):
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
    return validate_probs(w)


def evidence_coverage(has_flow, catalyst_tier, scope, have_metrics):
    """0.1–1.0 evidence COVERAGE (not a calibrated success probability) + the
    list of independent evidence classes used. UNCONFIRMED flow does not count."""
    basis = []
    if has_flow:
        basis.append("flow")
    if catalyst_tier and catalyst_tier != "unknown":
        basis.append("catalyst")
    if scope != "unconfirmed":
        basis.append("market_scope")
    if have_metrics:
        basis.append("technical")
    cov = round(min(1.0, max(0.1, 0.18 + 0.2 * len(basis))), 2)
    return cov, basis


def research_posture(event_type, severity, scope, flow_class, coverage, reviewer="CAUTION"):
    if reviewer == "REJECT" or coverage < 0.3:
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
    return "VERIFY" if reviewer == "CAUTION" else "OBSERVE"


def adversarial_review(scope, flow_class, has_official, coverage, trap_list):
    objections = []
    if not has_official:
        objections.append("公式の材料(取引所/開示/IR)で確認できていない — 値動き主導の可能性")
    if scope == "market_wide":
        objections.append("市場全体の動きの可能性(個別材料に帰属できない)")
    if scope == "unconfirmed":
        objections.append("市場全体か個別かを判定する基準データ(指数)が不足")
    if "squeeze_exhaustion" in trap_list:
        objections.append("踏み上げが一巡している可能性(燃料切れ)")
    if "distribution_into_strength" in trap_list:
        objections.append("上昇中の売り抜け(分配)の疑い")
    verdict = ("ACCEPT" if (has_official and coverage >= 0.6 and scope != "unconfirmed")
               else "REJECT" if coverage < 0.3 else "CAUTION")
    return {"verdict": verdict, "objectionsJa": objections}


def classify_evidence(evidence):
    """Bucket each evidence item into the taxonomy by its OWN claimType + its OWN
    evidenceId (fixes the shared-first-id bug). A derived metric / news headline
    can never land in confirmedFacts."""
    buckets = {"confirmedFacts": [], "marketObservations": [], "reportedClaims": [],
               "derivedMetrics": [], "inferences": [], "unverifiedClaims": []}
    for e in evidence or []:
        ct = e.get("claimType")
        item = {"claimJa": e.get("normalizedClaim"), "evidenceIds": [e.get("evidenceId")]}
        if ct == "official_fact":
            buckets["confirmedFacts"].append(item)
        elif ct == "market_observation":
            buckets["marketObservations"].append(item)
        elif ct == "derived_metric":
            buckets["derivedMetrics"].append(item)
        elif ct == "news_report":
            rel = e.get("reliability", 0.3)
            (buckets["reportedClaims"] if rel >= 0.4 else buckets["unverifiedClaims"]).append(item)
        elif ct == "model_inference":
            buckets["inferences"].append(item)
        else:
            buckets["unverifiedClaims"].append(item)
    return buckets


def build_dossier(*, event, flow_inf, rsi, sym_chg, index_chg, index_fresh,
                  catalyst_tier, evidence, times, evidence_hash, asset_name=None):
    """Assemble the full dossier-v2. Pure — all timestamps/hashes are passed in
    (the caller preserves true source times; this never fabricates a clock)."""
    et = event.get("eventType")
    sev = event.get("severity") or 1
    flow_class = (flow_inf or {}).get("classification") if isinstance(flow_inf, dict) else None
    scope = market_scope(sym_chg, index_chg, index_fresh)
    has_flow = has_confirmed_flow_signal(flow_class)
    cause = probable_cause(et, flow_class, catalyst_tier, scope)
    scenarios = next_session_scenarios(et, flow_class)
    traps = trap_risks(et, flow_class, rsi)
    coverage, basis = evidence_coverage(has_flow, catalyst_tier, scope, _finite(rsi))
    has_official = is_official_catalyst(catalyst_tier)
    review = adversarial_review(scope, flow_class, has_official, coverage, traps)
    posture = research_posture(et, sev, scope, flow_class, coverage, review["verdict"])

    fi = (flow_inf or {}).get("probabilities") if isinstance(flow_inf, dict) else None
    flow_probs = validate_probs({
        "newLongAccumulation": (fi or {}).get("newLongAccumulation"),
        "shortCovering": (fi or {}).get("shortCovering"),
        "distribution": (fi or {}).get("distribution"),
        "retailNoise": (fi or {}).get("retailNoise"),
        "unknown": (fi or {}).get("unconfirmed", 1.0 if not fi else 0.0),
    }) if fi else {"unknown": 1.0}

    tax = classify_evidence(evidence)

    missing = []
    if catalyst_tier in (None, "unknown"):
        missing.append("公式開示/ニュース確認(TDnet/EDINET未接続 — News Radar範囲のみ)")
    elif not has_official:
        missing.append("一次情報(取引所/開示/IR)による材料の裏取り — 現状は報道のみ")
    if scope == "unconfirmed":
        missing.append("指数/セクター比較の基準データ(市場全体か個別かを確定できない)")
    if not _finite(rsi):
        missing.append("テクニカル指標(価格履歴未取得)")

    invalidation = []
    if et in ("PRICE_SPIKE", "LIMIT_UP", "LIMIT_UP_PROXIMITY"):
        invalidation.append("翌セッションで寄り後に上値を切り下げ、出来高が伴わなければ上昇仮説は無効")
    if flow_class == "SHORT_COVERING":
        invalidation.append("貸株残の縮小が止まり出来高が細れば踏み上げ一巡とみなす")

    return {
        "schemaVersion": SCHEMA, "eventId": event.get("eventId"),
        "rootEventId": event.get("rootEventId") or event.get("eventId"),
        "revision": event.get("eventVersion", 1), "eventVersion": event.get("eventVersion", 1),
        "status": event.get("lifecycleState"), "currentGear": event.get("currentGear", 1),
        "symbol": event.get("symbol"), "assetName": asset_name, "session": event.get("session"),
        # ── temporal integrity (true source/event times; never the GET clock) ──
        "asOf": times.get("asOf"), "dossierGeneratedAt": times.get("dossierGeneratedAt"),
        "eventObservedAt": times.get("eventObservedAt"), "eventDetectedAt": times.get("eventDetectedAt"),
        "evidenceAsOf": times.get("evidenceAsOf"), "nextReviewAt": times.get("nextReviewAt"),
        "evidenceHash": evidence_hash, "dossierMode": times.get("mode", "event_time_snapshot"),
        "sourceFreshness": times.get("sourceFreshness"),
        # ── posture + confidence (labelled uncalibrated) ──
        "researchPosture": posture, "researchConfidence": coverage, "evidenceCoverage": coverage,
        "confidenceCalibrationStatus": CALIB, "confidenceBasis": basis,
        "whatHappenedJa": event.get("reasonJa"),
        # ── evidence taxonomy (separate buckets) ──
        "confirmedFacts": tax["confirmedFacts"], "marketObservations": tax["marketObservations"],
        "reportedClaims": tax["reportedClaims"], "derivedMetrics": tax["derivedMetrics"],
        "inferences": tax["inferences"], "unverifiedClaims": tax["unverifiedClaims"],
        # ── probabilistic inferences (validated, calibration-tagged) ──
        "probableCause": [{"label": k, "probability": v, "calibrationStatus": CALIB} for k, v in cause.items()],
        "flowInference": flow_probs, "flowCalibrationStatus": CALIB,
        "marketScope": scope, "crossMarketConfirmation": [],
        "trapRisks": traps,
        "nextSessionScenarios": [{"label": k, "probability": v, "calibrationStatus": CALIB} for k, v in scenarios.items()],
        "scenarioCalibrationStatus": CALIB,
        "invalidationConditions": invalidation, "missingData": missing,
        "reviewVerdict": review["verdict"], "reviewObjectionsJa": review["objectionsJa"],
        "dataLimitations": ["決定論的分析(LLM未使用)。AIによる深掘りは将来オプション。",
                            "PTS・板(L2)・VWAP・公式開示フィード(TDnet/EDINET)は未接続。",
                            "確信度は実績未較正のヒューリスティック(0.72は過去72%的中を意味しない)。"],
        "evidence": evidence,
        "engine": "deterministic", "disclaimerJa": DISCLAIMER_JA,
    }
