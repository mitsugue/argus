"""ARGUS V11.2 — Evidence Pack (the decision spine's canonical input).

Pure, stdlib-only, DETERMINISTIC. Folds ALREADY-COLLECTED data for ONE symbol into the
single canonical object that every downstream judge reads — the rule engine, the GPT
primary judgment, the Gemini challenge, TodayCall, and the ledgers. It never fetches,
never calls an LLM, and never contains private holdings / cost basis / P&L.

Discipline baked in (not left to callers):
  * a single-source CAOS association can ground a HYPOTHESIS, never a confirmed cause;
  * an official disclosure confirms a FACT — it does not by itself confirm the PRICE
    CAUSE (that needs market/timing confirmation);
  * theme-only links cannot justify ADD/ENTER unless corroborated;
  * missing data is stated explicitly — "no data" is information, not silence.
"""
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "evidence-pack-v1"

# The六 discipline lines every AI prompt must carry (kept here so the prompt builder,
# the pack, and the tests all quote ONE source of truth).
DISCIPLINE_JA = [
    "単一ソースのC.A.O.S.連想は「候補」止まり — 原因確定として扱わない。",
    "公式開示（TDnet/EDINET）は事実の確認であり、それだけでは価格変動の原因確定ではない（market/timingの確認が必要）。",
    "テーマ連想だけの根拠でADD/ENTERを正当化しない（裏取りがある場合のみ）。",
    "可視性ガードがENTERをブロックしている間はENTERを推奨しない。",
    "Market Depthの実証が欠けている主張は確信度を下げる。",
    "校正がburn-inの間は確信度を過大表示しない。",
]

_CONFIRMED_ROLES = {"confirmed_cause"}
_GROUNDABLE_CORR = {"multi_source", "official", "market_confirmed",
                    "official_and_market_confirmed", "corroborated"}


def pack_id(symbol: str, as_of: str) -> str:
    """Deterministic id: same symbol + same (UTC) date → same id, so labels, ledgers
    and the endpoint all reference the identical pack without coordination."""
    d = str(as_of or "")[:10].replace("-", "") or "00000000"
    return f"ep-{str(symbol or '').strip().upper()}-{d}"


def infer_market(symbol: str, market: Optional[str] = None) -> str:
    m = (market or "").strip().upper()
    if m in ("JP", "US", "CRYPTO", "FUND"):
        return m
    s = (symbol or "").strip().upper()
    if len(s) == 4 and s[:1].isdigit():
        return "JP"
    if s in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA"):
        return "CRYPTO"
    return "US"


def _proj_card(c: Dict[str, Any]) -> Dict[str, Any]:
    di = c.get("decisionImpact") or {}
    return {
        "cardId": c.get("cardId"), "eventType": c.get("eventType"),
        "headline": (c.get("headline") or "")[:120],
        "corroborationLevel": c.get("corroborationLevel"),
        "triggerRole": c.get("triggerRole"),
        "confidenceFinal": c.get("confidenceFinal"),
        "missingConfirmations": list(c.get("missingConfirmations") or []),
        "canAffectTodayCall": bool(di.get("canAffectTodayCall")),
    }


def _proj_disclosure(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"title": (d.get("title") or "")[:120], "category": d.get("category"),
            "categoryJa": d.get("categoryJa"), "sentiment": d.get("sentiment"),
            "material": bool(d.get("material")), "time": d.get("time") or d.get("disclosedAt"),
            "official": bool(d.get("official")), "provider": d.get("provider")}


def _proj_caos(l: Dict[str, Any]) -> Dict[str, Any]:
    return {"linkType": l.get("linkType"), "triggerRole": l.get("triggerRole"),
            "corroborationLevel": l.get("corroborationLevel"),
            "whyJa": (l.get("whyJa") or "")[:100],
            "nonCausalityCaveatJa": l.get("nonCausalityCaveatJa")}


def _proj_view(v: Dict[str, Any]) -> Dict[str, Any]:
    return {"title": (v.get("title") or "")[:110], "institutionId": v.get("institutionId"),
            "stance": v.get("stance"), "category": v.get("category"),
            "sourceTier": v.get("sourceTier"), "publishedAt": v.get("publishedAt")}


def build_pack(*, symbol: str, as_of: str, market: Optional[str] = None,
               quote: Optional[Dict[str, Any]] = None,
               event_cards: Optional[List[Dict[str, Any]]] = None,
               official_disclosures: Optional[List[Dict[str, Any]]] = None,
               filings: Optional[List[Dict[str, Any]]] = None,
               caos_links: Optional[List[Dict[str, Any]]] = None,
               institutional_views: Optional[List[Dict[str, Any]]] = None,
               source_coverage: Optional[Dict[str, Any]] = None,
               market_depth_proof: Optional[Dict[str, Any]] = None,
               visibility_guard: Optional[Dict[str, Any]] = None,
               calibration_status: Optional[Dict[str, Any]] = None,
               decision_value_status: Optional[Dict[str, Any]] = None,
               past_failure_patterns: Optional[List[Dict[str, Any]]] = None,
               official_event_refs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Fold already-collected inputs into the canonical Evidence Pack. Pure +
    deterministic: same inputs → byte-identical output. Lists are sorted/capped."""
    sym = str(symbol or "").strip().upper()
    mkt = infer_market(sym, market)
    cards = sorted((event_cards or []), key=lambda c: str(c.get("cardId") or ""))[:8]
    discs = sorted((official_disclosures or []),
                   key=lambda d: (str(d.get("time") or d.get("disclosedAt") or ""),
                                  str(d.get("title") or "")), reverse=True)[:8]
    caos = sorted((caos_links or []), key=lambda l: str(l.get("asOf") or ""), reverse=True)[:6]
    views = sorted((institutional_views or []),
                   key=lambda v: str(v.get("publishedAt") or ""), reverse=True)[:6]
    fil = sorted((filings or []), key=lambda f: str(f.get("time") or f.get("date") or ""),
                 reverse=True)[:6]

    # market confirmations = cards that carry one (an observed move confirming itself).
    market_conf = sorted({mc for c in cards for mc in (c.get("marketConfirmations") or [])})

    # missing confirmations: union of per-card gaps + structural notes.
    missing = {m for c in cards for m in (c.get("missingConfirmations") or [])}
    if not discs and not fil:
        missing.add("official_confirmation")
    if not market_conf:
        missing.add("market_confirmation")
    dp = (market_depth_proof or {}).get("summary") or {}
    if not dp.get("trueDepthLiveCount"):
        missing.add("market_depth:true_depth")
    vg = visibility_guard or {}
    for code in (vg.get("reasonCodes") or []):
        missing.add(f"visibility:{code}")
    missing_sorted = sorted(missing)

    has_official = bool(discs) or bool(fil) or any(
        (c.get("corroborationLevel") or "").startswith("official") for c in cards)
    confirmed_cause = any((c.get("triggerRole") in _CONFIRMED_ROLES) for c in cards)
    groundable = has_official or bool(quote) or any(
        (c.get("corroborationLevel") in _GROUNDABLE_CORR) for c in cards)
    can_today = confirmed_cause or any(
        bool((c.get("decisionImpact") or {}).get("canAffectTodayCall")) for c in cards) \
        or any(d.get("material") and d.get("official") for d in discs)

    disclaimers = list(DISCIPLINE_JA)
    if (calibration_status or {}).get("reliabilityStage") == "burn_in":
        disclaimers.append("校正はburn-in段階 — 精度は未実証。分類であって利益保証ではない。")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "evidencePackId": pack_id(sym, as_of),
        "symbol": sym,
        "market": mkt,
        "asOf": as_of,
        "quote": {k: (quote or {}).get(k) for k in
                  ("price", "changePct", "volume", "date", "status", "name")} if quote else {},
        "eventCards": [_proj_card(c) for c in cards],
        "officialDisclosures": [_proj_disclosure(d) for d in discs],
        "filings": fil,
        "caosLinks": [_proj_caos(l) for l in caos],
        "institutionalViews": [_proj_view(v) for v in views],
        "marketConfirmations": market_conf,
        "missingConfirmations": missing_sorted,
        "sourceCoverage": {
            "totalItems": ((source_coverage or {}).get("summary") or {}).get("totalItems"),
            "canGroundJudgmentItems": ((source_coverage or {}).get("summary") or {}).get("canGroundJudgmentItems"),
            "weakSignalItems": ((source_coverage or {}).get("summary") or {}).get("weakSignalItems"),
        } if source_coverage else {},
        "marketDepthProof": {
            "trueDepthLiveCount": dp.get("trueDepthLiveCount"),
            "computedIndicatorsLiveCount": dp.get("computedIndicatorsLiveCount"),
            "requiresContractCount": dp.get("requiresContractCount"),
        } if market_depth_proof else {},
        "visibilityGuard": {
            "visibilityLevel": vg.get("visibilityLevel"),
            "confidenceCap": vg.get("confidenceCap"),
            "blockedActions": list(vg.get("blockedActions") or []),
            "reasonCodes": list(vg.get("reasonCodes") or []),
        } if visibility_guard else {},
        "calibrationStatus": {
            "isActive": (calibration_status or {}).get("isActive"),
            "reliabilityStage": (calibration_status or {}).get("reliabilityStage"),
        } if calibration_status else {},
        "decisionValueStatus": {
            "phase": (decision_value_status or {}).get("phase"),
            "sampleStage": (decision_value_status or {}).get("sampleStage"),
        } if decision_value_status else {},
        "pastFailurePatterns": list(past_failure_patterns or [])[:5],
        # v11.3: lifecycle-tracked official disclosures (compact refs — the full records
        # live at /api/argus/official-events). Sorted for determinism.
        "officialEventRefs": sorted((official_event_refs or []),
                                    key=lambda r: str(r.get("officialEventId") or ""))[:5],
        "allowedUse": {
            "canGroundJudgment": bool(groundable),
            "canConfirmCause": bool(confirmed_cause),   # CAOS candidates can NEVER set this
            "canAffectTodayCall": bool(can_today),
        },
        "disclaimersJa": disclaimers,
    }


def compact_for_ai(pack: Dict[str, Any], max_chars: int = 1400) -> str:
    """One symbol's evidence, compressed for prompt injection (pure, deterministic).
    Leads with what the LLM cannot know: corroboration, missing data, allowed use."""
    p = pack or {}
    L: List[str] = []
    au = p.get("allowedUse") or {}
    L.append(f"■ {p.get('symbol')} evidence[{p.get('evidencePackId')}] "
             f"cause確定可={'yes' if au.get('canConfirmCause') else 'NO'}")
    for c in (p.get("eventCards") or [])[:3]:
        L.append(f"  ev:{c.get('eventType')} {c.get('headline')} "
                 f"[{c.get('corroborationLevel')}/{c.get('triggerRole')}]")
    for d in (p.get("officialDisclosures") or [])[:3]:
        L.append(f"  官:{d.get('categoryJa')}「{(d.get('title') or '')[:40]}」"
                 f"{'★material' if d.get('material') else '(fact)'}")
    for l in (p.get("caosLinks") or [])[:2]:
        L.append(f"  連想:{l.get('linkType')}[{l.get('triggerRole')}] {l.get('whyJa')}")
    miss = p.get("missingConfirmations") or []
    if miss:
        L.append("  不足: " + ", ".join(miss[:6]))
    vg = p.get("visibilityGuard") or {}
    if vg.get("confidenceCap") is not None or vg.get("blockedActions"):
        L.append(f"  可視性: cap={vg.get('confidenceCap')} blocked={vg.get('blockedActions')}")
    cal = p.get("calibrationStatus") or {}
    if cal:
        L.append(f"  校正:{cal.get('reliabilityStage')} / DV:{(p.get('decisionValueStatus') or {}).get('phase')}")
    out = "\n".join(L)
    return out[:max_chars]
