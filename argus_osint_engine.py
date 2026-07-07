"""ARGUS V12.1.0 — Multi-Agent OSINT Engine (pure, deterministic core).

「Gemini単体に聞けば見つかるニュースをARGUSが見つけられない」への根治。
ARGUS自身が 計画→決定論収集→Gemini/GPTスカウト→検証→矛盾→統合 を編成し、
単体AIチャットを上回る(かつ負けたら正直に記録して学習する)ためのエンジン。

このモジュールは純関数のみ: LLM呼び出し・fetchは一切しない(scannerが注入)。

HARD RULES:
  - LLMの出力は検証されるまで証拠ではない(verificationStatus=verified以外は未検証)。
  - 未検証/14日超(stale)/日付不明ソースは主因(primary)になれない。
  - 直接材料が無ければ「直接材料は未確認」、テーマ連想は「テーマ連想」、
    バリューチェーンは「バリューチェーン推論」と必ず明示 — 弱い推測を事実にしない。
  - 「ニュースなし」はcoverageがmedium以上の時だけ言える。弱ければ
    「ARGUSの探索範囲では未確認」。
  - GeminiがARGUS未検出のソースを出したら missed_by_argus として記録し、
    探索語の拡張候補に回す(負けを隠さない)。
  - ソース・日付を捏造しない。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Dict, List, Optional

import argus_news_freshness
import argus_osint_attribution

SCHEMA_VERSION = "osint-investigation-v1"

MODES = ("fast", "balanced", "deep", "war_room")
PRIVACY_MODES = ("redacted", "owner_context", "full_private")
PROVIDERS = ("gemini", "gpt", "deterministic", "manual")
AGENT_STATUSES = ("ok", "failed", "disabled", "unavailable")
VERIFICATION_STATUSES = ("verified", "metadata_only", "inaccessible",
                         "contradicted", "stale", "unknown")
VERDICTS = ("direct_cause_found", "likely_sector_theme", "possible_value_chain",
            "macro_driven", "flow_or_supply_driven", "conflicting_evidence", "unknown")
VERDICT_JA = {
    "direct_cause_found": "直接材料を確認",
    "likely_sector_theme": "セクター/テーマ連想が有力",
    "possible_value_chain": "バリューチェーン推論の可能性",
    "macro_driven": "マクロ主導の可能性",
    "flow_or_supply_driven": "フロー/需給主導の可能性",
    "conflicting_evidence": "証拠が矛盾",
    "unknown": "原因未特定",
}
COVERAGE_LEVELS = ("strong", "medium", "weak", "insufficient", "failed")
RELIABILITY_LEVELS = ("high", "medium", "low", "unknown")

MODE_JA = {"fast": "高速(通常巡回)", "balanced": "標準(有意な変動)",
           "deep": "深掘り(保有/P0-P1/手動)", "war_room": "War Room(緊急)"}
COST_LABEL_JA = "Gemini/GPTを使った深掘りOSINT — 外部AIに送信する内容を確認してください"

# 負け・見逃しの正直文言(テストで固定)
MISSED_BY_ARGUS_JA = "GeminiがARGUS未検出のニュースを提示しました。検証後、今後の探索語に追加します。"
ARGUS_ONLY_JA = "ARGUS独自検出"
NOT_FOUND_WEAK_JA = "ARGUSの探索範囲では未確認"
BENCH_DISABLED_JA = "外部AIベンチマーク未実行"
BENCH_FAILED_JA = "外部AIベンチマーク失敗"
NO_DIRECT_JA = "直接材料は未確認"

_NEGATIVE_JA = ("下落理由", "急落", "売られる", "懸念", "失望", "利益確定",
                "採算", "需給悪化")
_NEGATIVE_EN = ("downgrade", "selloff", "concern", "margin pressure", "profitability")
_DIRECT_SUFFIX_JA = ("IR", "適時開示", "決算", "業績予想", "格付け", "受注", "提携", "規制")
_GLOBAL_TERMS = ("custom silicon", "hyperscaler capex", "AI chip", "AI capex")


def make_id(symbol: str, as_of: str, mode: str) -> str:
    return "osint-" + hashlib.sha256(f"{symbol}|{as_of[:16]}|{mode}".encode()).hexdigest()[:12]


# ── Part D: Query Planner ────────────────────────────────────────────────────

def build_query_plan(profile: Dict[str, Any], *, move_pct: Optional[float] = None,
                     extra_terms: Optional[List[str]] = None) -> Dict[str, Any]:
    """profile: {symbol,nameJa,nameEn,sector,themes[],valueChain[],competitors[],
    aliases[]} → 多段クエリ(日本語+英語)。再利用可能な合成規則のみでハードコードなし。"""
    sym = str(profile.get("symbol") or "").upper()
    name_ja = str(profile.get("nameJa") or "").strip()
    name_en = str(profile.get("nameEn") or "").strip()
    sector = str(profile.get("sector") or "").strip()
    themes = [t for t in (profile.get("themes") or []) if t]
    vchain = [t for t in (profile.get("valueChain") or []) if t]
    comps = [t for t in (profile.get("competitors") or []) if t]
    aliases = [t for t in (profile.get("aliases") or []) if t]
    extras = [t for t in (extra_terms or []) if t][:8]
    names = [n for n in [name_ja, name_en, sym] + aliases if n]

    direct = []
    for n in [name_ja or sym, name_en]:
        if not n:
            continue
        for sfx in _DIRECT_SUFFIX_JA:
            direct.append(f"{n} {sfx}")
    down = "下落" if (isinstance(move_pct, (int, float)) and move_pct < 0) else "急変"
    negative = [f"{n} {w}" for n in names[:2] for w in _NEGATIVE_JA[:4]] \
        + [f"{name_en or sym} {w}" for w in _NEGATIVE_EN[:3]] \
        + [f"{name_ja or sym} {down}理由" if down == "下落" else f"{name_ja or sym} 急変 理由"]
    sector_q = [f"{s} 懸念" for s in ([sector] if sector else [])] \
        + [f"{t} ニュース" for t in themes[:4]] + [f"{t} 採算" for t in themes[:2]]
    vchain_q = [f"{v}" for v in vchain[:6]] \
        + [f"{v} {name_ja or sym}" for v in vchain[:4]] \
        + [f"{v} 影響" for v in vchain[:3]] + [f"{c} 競合" for c in comps[:2]]
    global_q = [f"{name_en or sym} stock news" if (name_en or sym) else ""] \
        + [f"{t}" for t in _GLOBAL_TERMS] \
        + [f"{v}" for v in vchain if re.search(r"[A-Za-z]", str(v))][:4]
    global_q = [q for q in global_q if q]

    plan = {
        "direct": direct[:12], "sector": sector_q[:8], "valueChain": vchain_q[:14],
        "globalCatalyst": global_q[:10], "negative": negative[:10],
        "extraFromOwner": extras,
    }
    plan["all"] = [q for k in ("direct", "sector", "valueChain", "globalCatalyst",
                               "negative", "extraFromOwner") for q in plan[k]]
    plan["queryCount"] = len(plan["all"])
    return plan


# ── Part B: Scout prompts(送信文の合成 — 送るのはscanner/admin側) ──────────────

def build_scout_prompt(provider: str, profile: Dict[str, Any], plan: Dict[str, Any],
                       *, move_pct: Optional[float], privacy_mode: str,
                       owner_context_ja: str = "") -> str:
    """redacted(既定)は銘柄コード/社名/公開文脈のみ。保有・数量・口座等は
    owner_context_ja に含めない限り構造的に入らない(入れるのはfull_private時のみ)。"""
    sym = profile.get("symbol")
    name = profile.get("nameJa") or profile.get("nameEn") or sym
    move = f"{move_pct:+.1f}%" if isinstance(move_pct, (int, float)) else "有意な変動"
    qs = " / ".join(plan.get("all", [])[:18])
    base = (
        f"あなたはOSINT調査員です。銘柄 {sym} {name} が本日 {move} 動いた原因候補を、"
        f"公開情報から調査してください。\n"
        f"必須: ①各候補にURLまたはソース名と日付(timestamp)を付ける ②直接材料"
        f"(この会社固有)とテーマ連想(セクター/バリューチェーン)を明確に分ける "
        f"③裏取りが必要な点を列挙する ④根拠のない断定はしない(不明は不明と言う)。\n"
        f"参考クエリ: {qs}\n"
        f'出力はJSON: {{"claims":[{{"titleJa":"…","url":"…","sourceName":"…",'
        f'"publishedAt":"YYYY-MM-DD","directness":"direct|sector_theme|value_chain|macro",'
        f'"summaryJa":"…"}}],"toVerifyJa":["…"],"notFoundJa":["…"]}}'
    )
    if provider == "gpt":
        base += ("\n追加指示: クエリを自分でさらに拡張し、矛盾する報道・"
                 "Geminiのような単発検索が見落としがちな公式開示(IR/TDnet/SEC)を"
                 "重点確認してください。公式ソースのチェックリストも返してください。")
    if privacy_mode == "full_private" and owner_context_ja:
        base += f"\n(オーナー文脈: {owner_context_ja[:400]})"
    elif privacy_mode == "owner_context" and owner_context_ja:
        base += f"\n(文脈: {owner_context_ja[:200]})"
    return base


def redacted_prompt_is_safe(prompt: str) -> bool:
    """redactedプロンプトに私的情報が乗っていないかの検査(テスト用)。"""
    banned = ("保有中", "取得単価", "口数", "積立", "評価額", "quantity", "avgCost",
              "NISA", "iDeCo", "含み益", "含み損", "vaultPass", "passphrase",
              "login_pwd", "X-ARGUS-ADMIN-TOKEN")
    return not any(b in prompt for b in banned)


# ── Part F: Source Verifier ─────────────────────────────────────────────────

def verify_source(claim: Dict[str, Any], known_index: Dict[str, Dict[str, Any]],
                  now_iso: str) -> Dict[str, Any]:
    """claim: {titleJa/title, url?, sourceName?, publishedAt?, directness?, summaryJa?}
    known_index: 既知メタデータ(intel store/ニュースキャッシュ等) — キーは
    正規化URL と タイトルハッシュ の両方。LLMの主張は一致して初めてverified。"""
    title = str(claim.get("titleJa") or claim.get("title") or "").strip()
    url = str(claim.get("url") or "").strip()
    pub = claim.get("publishedAt")
    age_h = argus_news_freshness.age_hours(pub, now_iso) if pub else None

    hit = None
    if url:
        hit = known_index.get(_norm_url(url))
    if hit is None and title:
        hit = known_index.get("t:" + _title_hash(title))

    if hit is not None:
        status = "verified"
        pub = pub or hit.get("publishedAt")
        age_h = argus_news_freshness.age_hours(pub, now_iso) if pub else age_h
    elif url and re.match(r"^https?://[\w.\-]+/", url) and pub:
        status = "metadata_only"       # 形式は妥当だが手元ストアで裏取りできず=未検証
    elif url or pub:
        status = "unknown"
    else:
        status = "inaccessible"        # URLも日付もない主張は検証不能

    if age_h is not None and age_h > 14 * 24:
        status = "stale" if status in ("verified", "metadata_only") else status

    fresh = ("today" if age_h is not None and age_h <= 24
             else "within_3_trading_days" if age_h is not None and age_h <= 96
             else "stale_14d_plus" if age_h is not None and age_h > 14 * 24
             else "unknown")
    strength = ("strong" if status == "verified" and fresh in ("today", "within_3_trading_days")
                else "medium" if status == "verified"
                else "weak")
    return {
        "titleJa": title[:160], "originalTitle": str(claim.get("title") or "")[:160] or None,
        "url": url or None, "sourceName": str(claim.get("sourceName") or "")[:40] or None,
        "sourceType": claim.get("sourceType") or "unknown",
        "publishedAt": pub, "detectedAt": now_iso, "verifiedAt": now_iso if hit else None,
        "ageHours": round(age_h, 1) if age_h is not None else None,
        "freshness": fresh,
        "supportsClaim": bool(title),
        "supportStrength": strength,
        "directness": claim.get("directness") or "unsupported",
        "verificationStatus": status,
        "primaryEligible": status == "verified" and fresh in ("today", "within_3_trading_days"),
        "labelJa": {"verified": "検証済み", "metadata_only": "未検証(メタデータのみ)",
                    "inaccessible": "未検証(参照不能)", "contradicted": "矛盾",
                    "stale": "古い(主因不可)", "unknown": "未検証"}[status],
    }


def _norm_url(url: str) -> str:
    u = re.sub(r"^https?://(www\.)?", "", str(url).strip().lower())
    return "u:" + u.split("?")[0].rstrip("/")


def _title_hash(title: str) -> str:
    t = re.sub(r"\s+", "", str(title).lower())[:80]
    return hashlib.sha256(t.encode()).hexdigest()[:16]


def build_known_index(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """ストア(intel/ニュース/TDnet)から検証用インデックスを作る。"""
    idx: Dict[str, Dict[str, Any]] = {}
    for it in items or []:
        meta = {"publishedAt": it.get("publishedAt") or it.get("time"),
                "title": it.get("titleJa") or it.get("title")}
        url = it.get("canonicalUrl") or it.get("url")
        if url:
            idx[_norm_url(str(url))] = meta
        t = it.get("titleJa") or it.get("title")
        if t:
            idx["t:" + _title_hash(str(t))] = meta
        t2 = it.get("titleOriginal")
        if t2:
            idx["t:" + _title_hash(str(t2))] = meta
    return idx


# ── Part B-6: Contradiction Judge(決定論) ───────────────────────────────────

def judge_contradictions(verified: List[Dict[str, Any]],
                         agent_runs: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    cats = {v.get("directness") for v in verified if v.get("primaryEligible")}
    if "direct_company" in cats and "macro" in cats:
        out.append("直接材料とマクロ要因の両説が並存 — どちらが主因かは未確定")
    stale_used = [v for v in verified if v.get("verificationStatus") == "stale"]
    if stale_used:
        out.append(f"古いソース{len(stale_used)}件は主因から除外(背景参考のみ)")
    unverified_claims = sum(
        1 for r in agent_runs for c in (r.get("claims") or [])
        if not c.get("verified"))
    if unverified_claims:
        out.append(f"外部AIの主張{unverified_claims}件が未検証(証拠として扱わない)")
    directs = [v for v in verified if v.get("directness") == "direct_company"
               and v.get("primaryEligible")]
    theme_asserted = any(
        (c.get("directness") == "direct" and not c.get("verified"))
        for r in agent_runs for c in (r.get("claims") or []))
    if not directs and theme_asserted:
        out.append("外部AIが直接材料を主張したが検証できず — テーマ連想として扱う")
    return out


# ── Part E: ベンチマーク比較 ─────────────────────────────────────────────────

def compare_benchmark(argus_titles: List[str], agent_runs: List[Dict[str, Any]],
                      verified_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """タイトルハッシュ基準の重なり比較。GeminiだけがARGUS未検出の(検証可能な)
    ソースを出したら missed_by_argus(負けの記録)。"""
    a_keys = {_title_hash(t) for t in argus_titles if t}
    per: Dict[str, set] = {}
    for r in agent_runs:
        prov = r.get("provider")
        if prov not in ("gemini", "gpt") or r.get("status") != "ok":
            continue
        per[prov] = {_title_hash(str(c.get("titleJa") or c.get("title") or ""))
                     for c in (r.get("claims") or []) if (c.get("titleJa") or c.get("title"))}
    gem = per.get("gemini", set())
    gpt = per.get("gpt", set())
    overlap = a_keys & (gem | gpt)
    gem_only = gem - a_keys - gpt
    gpt_only = gpt - a_keys - gem
    argus_only = a_keys - gem - gpt
    missed = sorted(gem_only | gpt_only)
    notes = []
    if missed:
        notes.append(MISSED_BY_ARGUS_JA)
    if argus_only:
        notes.append(f"{ARGUS_ONLY_JA}: {len(argus_only)}件")
    if not per:
        notes.append(BENCH_DISABLED_JA)
    return {
        "argusCount": len(a_keys), "geminiCount": len(gem), "gptCount": len(gpt),
        "overlapCount": len(overlap),
        "geminiOnlyCount": len(gem_only), "gptOnlyCount": len(gpt_only),
        "argusOnlyCount": len(argus_only),
        "missedByArgusCount": len(missed),
        "missedByArgus": missed[:8],
        "retrievalScorePenalty": min(0.3, 0.1 * len(missed)),
        "notesJa": notes,
    }


def extract_expansion_terms(agent_runs: List[Dict[str, Any]], cap: int = 8) -> List[str]:
    """外部AIが出した(ARGUSが持っていない)固有語を探索語候補として抽出。"""
    terms: List[str] = []
    for r in agent_runs:
        for c in (r.get("claims") or []):
            t = str(c.get("titleJa") or c.get("title") or "")
            for w in re.findall(r"[A-Z][A-Za-z0-9\-]{2,20}|[ァ-ヶー]{3,12}", t):
                if w not in terms:
                    terms.append(w)
    return terms[:cap]


# ── Part G: Coverage / Reliability ──────────────────────────────────────────

def coverage_score(plan: Dict[str, Any], retrieved_counts: Dict[str, int],
                   agent_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    def level(n, need):
        return "strong" if n >= need * 2 else "medium" if n >= need else "weak" if n > 0 else "insufficient"
    axes = {
        "directCompanyCoverage": level(retrieved_counts.get("direct", 0), 1),
        "officialDisclosureCoverage": level(retrieved_counts.get("official", 0), 1),
        "sectorCoverage": level(retrieved_counts.get("sector", 0), 1),
        "valueChainCoverage": level(retrieved_counts.get("valueChain", 0), 1),
        "globalNewsCoverage": level(retrieved_counts.get("globalNews", 0), 1),
        "japaneseNewsCoverage": level(retrieved_counts.get("jaNews", 0), 1),
        "agentCoverage": ("strong" if sum(1 for r in agent_runs if r.get("status") == "ok"
                                          and r.get("provider") in ("gemini", "gpt")) >= 2
                          else "medium" if any(r.get("status") == "ok"
                                               and r.get("provider") in ("gemini", "gpt")
                                               for r in agent_runs)
                          else "insufficient"),
    }
    rank = {"strong": 3, "medium": 2, "weak": 1, "insufficient": 0}
    vals = [rank[v] for v in axes.values()]
    avg = sum(vals) / len(vals)
    total = ("strong" if avg >= 2.4 else "medium" if avg >= 1.6
             else "weak" if avg >= 0.7 else "insufficient")
    axes["totalCoverage"] = total
    axes["totalCoverageJa"] = {"strong": "広い", "medium": "標準", "weak": "弱い",
                               "insufficient": "不足", "failed": "失敗"}[total]
    return axes


def reliability_score(verified: List[Dict[str, Any]], contradictions: List[str],
                      dq_penalty: bool = False) -> Dict[str, Any]:
    ver = [v for v in verified if v.get("verificationStatus") == "verified"]
    total_claims = len(verified)
    vr = (len(ver) / total_claims) if total_claims else 0.0
    fresh = sum(1 for v in ver if v.get("freshness") in ("today", "within_3_trading_days"))
    diversity = len({v.get("sourceName") for v in ver if v.get("sourceName")})
    direct = any(v.get("directness") == "direct_company" and v.get("primaryEligible")
                 for v in verified)
    score = vr + (0.2 if fresh else 0) + min(0.2, 0.1 * diversity) \
        + (0.2 if direct else 0) - 0.15 * len(contradictions) - (0.2 if dq_penalty else 0)
    overall = ("high" if score >= 0.9 and direct else
               "medium" if score >= 0.5 else
               "low" if total_claims else "unknown")
    return {"sourceFreshness": fresh, "sourceDiversity": diversity,
            "verificationRate": round(vr, 2), "directEvidence": direct,
            "contradictionPenalty": len(contradictions),
            "dataQualityPenalty": bool(dq_penalty), "overall": overall,
            "overallJa": {"high": "高", "medium": "中", "low": "低", "unknown": "不明"}[overall]}


# ── Part B-7: Synthesis Judge ───────────────────────────────────────────────

def synthesize_verdict(verified: List[Dict[str, Any]], coverage: Dict[str, Any],
                       contradictions: List[str], *, flow_hint: Optional[str] = None,
                       macro_hint: bool = False) -> Dict[str, Any]:
    eligible = [v for v in verified if v.get("primaryEligible")]
    directs = [v for v in eligible if v.get("directness") == "direct_company"]
    themes = [v for v in eligible if v.get("directness") == "sector_theme"]
    vchain = [v for v in eligible if v.get("directness") == "value_chain"]
    macro = [v for v in eligible if v.get("directness") == "macro"]
    cov_ok = coverage.get("totalCoverage") in ("strong", "medium")

    if len(contradictions) >= 3:
        verdict = "conflicting_evidence"
        primary = None
    elif directs:
        verdict, primary = "direct_cause_found", directs[0]
    elif vchain:
        verdict, primary = "possible_value_chain", vchain[0]
    elif themes:
        verdict, primary = "likely_sector_theme", themes[0]
    elif macro or macro_hint:
        verdict, primary = "macro_driven", (macro[0] if macro else None)
    elif flow_hint in ("panic_selling", "distribution", "short_covering"):
        verdict, primary = "flow_or_supply_driven", None
    else:
        verdict, primary = "unknown", None

    if verdict == "direct_cause_found":
        owner = f"直接材料を確認: {primary['titleJa']}"
    elif verdict == "possible_value_chain":
        owner = f"バリューチェーン推論の候補: {primary['titleJa']}(直接材料は未確認)"
    elif verdict == "likely_sector_theme":
        owner = f"テーマ連想の候補: {primary['titleJa']}(直接材料は未確認)"
    elif verdict == "macro_driven":
        owner = "マクロ/イベント主導の可能性(銘柄固有の直接材料は未確認)"
    elif verdict == "flow_or_supply_driven":
        owner = "フロー/需給主導の可能性(ニュース材料は確認できず)"
    elif verdict == "conflicting_evidence":
        owner = "証拠が矛盾 — 主因の断定を保留"
    else:
        owner = ("該当ニュースなし(探索は十分に実施)" if cov_ok else NOT_FOUND_WEAK_JA)

    confidence = ("high" if verdict == "direct_cause_found" and cov_ok
                  else "medium" if primary is not None and cov_ok
                  else "low" if primary is not None or cov_ok
                  else "unknown")
    return {
        "verdict": verdict, "verdictJa": VERDICT_JA[verdict],
        "primaryCauseJa": primary["titleJa"] if primary else None,
        "secondaryCausesJa": [v["titleJa"] for v in (themes + vchain + macro)
                              if not primary or v["titleJa"] != primary["titleJa"]][:3],
        "rejectedCausesJa": [f"{v['titleJa']}({v['labelJa']})" for v in verified
                             if not v.get("primaryEligible")][:4],
        "missingEvidenceJa": ([] if directs else [NO_DIRECT_JA]),
        "confidence": confidence,
        "sourceDiversity": len({v.get("sourceName") for v in eligible if v.get("sourceName")}),
        "directEvidencePresent": bool(directs),
        "ownerReadableJa": owner,
        "whyThisMightBeWrongJa": ("単一ソースの誤報/織り込み済みの可能性" if directs else
                                  "連想であり直接材料ではない — 実際は需給/地合い要因の可能性"),
    }


# ── Part J: Canary ──────────────────────────────────────────────────────────

def evaluate_canary(topics: List[Dict[str, Any]],
                    found_fn: Callable[[List[str]], bool],
                    agent_found: Optional[Dict[str, Dict[str, bool]]] = None) -> Dict[str, Any]:
    """topics: [{topic, expectedKeywords[]}] / found_fn(keywords)->ARGUSストアで検出?
    agent_found: {topic: {gemini: bool, gpt: bool}}(ベンチ実行時のみ)。"""
    rows = []
    missed_by_argus = 0
    for t in topics or []:
        kws = t.get("expectedKeywords") or []
        by_argus = bool(found_fn(kws))
        af = (agent_found or {}).get(t.get("topic") or "", {})
        by_gem, by_gpt = bool(af.get("gemini")), bool(af.get("gpt"))
        if by_argus:
            status = "ok"
        elif by_gem or by_gpt:
            status = "missed_by_argus"
            missed_by_argus += 1
        elif af:
            status = "missed_by_agents"
        else:
            status = "unknown"
        rows.append({"topic": t.get("topic"), "expectedKeywords": kws[:6],
                     "foundByArgus": by_argus, "foundByGemini": by_gem,
                     "foundByGPT": by_gpt, "status": status,
                     "ownerReadableImpactJa": t.get("impactJa") or ""})
    degraded = missed_by_argus > 0
    return {"rows": rows, "missedByArgusCount": missed_by_argus,
            "degraded": degraded,
            "noteJa": "OSINT監視に見落としの可能性 — 原因確度に上限をかけています"
                      if degraded else "canary正常(既知トピックを検出できています)"}


# ── Part C: Investigation assembler ─────────────────────────────────────────

def build_investigation(*, symbol: str, asset_name: str, as_of: str, mode: str,
                        trigger: str, privacy_mode: str,
                        plan: Dict[str, Any], retrieved_counts: Dict[str, int],
                        verified: List[Dict[str, Any]], agent_runs: List[Dict[str, Any]],
                        benchmark: Dict[str, Any], flow_hint: Optional[str] = None,
                        macro_hint: bool = False, dq_penalty: bool = False,
                        canary_degraded: bool = False) -> Dict[str, Any]:
    contradictions = judge_contradictions(verified, agent_runs)
    coverage = coverage_score(plan, retrieved_counts, agent_runs)
    reliability = reliability_score(verified, contradictions, dq_penalty)
    verdict = synthesize_verdict(verified, coverage, contradictions,
                                 flow_hint=flow_hint, macro_hint=macro_hint)
    if canary_degraded and verdict["confidence"] == "high":
        verdict["confidence"] = "medium"
        verdict["whyThisMightBeWrongJa"] += "(canary見落としにより確度に上限)"
    missing_areas = []
    for k, ja in (("directCompanyCoverage", "直接材料の探索"),
                  ("officialDisclosureCoverage", "公式開示"),
                  ("valueChainCoverage", "バリューチェーン"),
                  ("globalNewsCoverage", "海外ニュース"),
                  ("agentCoverage", "外部AIベンチマーク")):
        if coverage.get(k) in ("weak", "insufficient"):
            missing_areas.append(ja)
    next_research = [f"探索語に追加候補: {w}" for w in
                     extract_expansion_terms(agent_runs, cap=4)]
    if not verdict["directEvidencePresent"]:
        next_research.append("公式開示(TDnet/IR)の再確認")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": make_id(symbol, as_of, mode),
        "symbol": str(symbol).upper(), "assetName": asset_name, "asOf": as_of,
        "mode": mode, "modeJa": MODE_JA.get(mode, mode), "trigger": trigger,
        "investigationQuestionJa": f"{asset_name}({symbol})の値動きの原因は何か(公開情報ベース)",
        "queryPlan": {k: plan.get(k) for k in ("direct", "sector", "valueChain",
                                               "globalCatalyst", "negative",
                                               "extraFromOwner", "queryCount")},
        "retrievalRuns": retrieved_counts,
        "agentRuns": agent_runs,
        "verifiedSources": [v for v in verified if v.get("verificationStatus") == "verified"][:10],
        "rejectedSources": [v for v in verified if v.get("verificationStatus") != "verified"][:10],
        "evidenceLedger": verified[:16],
        "catalystVerdict": verdict,
        "contradictionReport": contradictions,
        "coverageScore": coverage,
        "reliabilityScore": reliability,
        "benchmark": benchmark,
        "ownerReadableSummaryJa": verdict["ownerReadableJa"],
        "missingAreasJa": missing_areas,
        "nextResearchJa": next_research[:5],
        "privacyMode": privacy_mode,
        "costLabelJa": COST_LABEL_JA if mode in ("deep", "war_room") else None,
        "complianceNote": "OSINT調査の分類であり事実の断定・売買指示ではない。",
    }
