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

# v12.1.1: 優位性判定の正直文言(テストで固定)
SUPERIORITY_STATUSES = ("exceeds_gemini", "matches_gemini", "below_gemini", "insufficient_data")
SUPERIORITY_JA = {"exceeds_gemini": "Gemini超過", "matches_gemini": "Gemini同等",
                  "below_gemini": "Gemini未満", "insufficient_data": "判定保留"}
GAP_JA = "Gemini単発に対して未回収のOSINTギャップがあります。"
CONTEXT_EDGE_JA = "Gemini単発との差分: ARGUSは保有/需給/Flow/イベント文脈を統合しています。"

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
        f'"publishedAt":"YYYY-MM-DD または unknown","directness":"direct|sector_theme|value_chain|macro",'
        f'"whyRelevantJa":"なぜこの銘柄に関係するか","quoteOrParaphraseJa":"許諾範囲の短い引用または要約",'
        f'"confidence":"high|medium|low","whatWouldDisproveJa":"この説を否定する材料",'
        f'"summaryJa":"…"}}],"toVerifyJa":["…"],"notFoundJa":["…"]}}。'
        f'URLが不明な候補はurlをnullにし、その旨を明記すること(捏造URL禁止)。'
    )
    base += ("\n探索対象を必ず含める: 英語の海外テック/半導体ニュース・日本語の市場コメンタリー・"
             "公式開示(IR/TDnet/SEC)・顧客/供給網/競合のニュース。"
             "「今日のこの値動きを説明できるものは何か」を軸に探すこと。")
    if provider == "gpt":
        base += ("\n追加指示: 矛盾する報道と反証(negative evidence)を積極的に探し、"
                 "古い記事の再掲に警告を付けること。Geminiのような単発検索が"
                 "見落としがちな公式開示(IR/TDnet/SEC)を重点確認し、"
                 "公式ソースのチェックリストも返してください。")
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


# ── v12.1.1 Part F: 頑健スカウト出力パーサ ──────────────────────────────────

def parse_scout_output(text: str):
    """LLM出力からclaimsを頑健に抽出。```fence/前置きprose耐性。JSONが壊れて
    いてもURL/行からのフォールバック抽出で全損させない(捏造はしない — 元テキスト
    にある文字列だけを使う)。returns (dict, warnings[])."""
    warnings: List[str] = []
    raw = str(text or "").strip()
    if not raw:
        return {"claims": []}, ["empty_output"]
    body = re.sub(r"```(?:json)?", "", raw).strip()
    # 最初の { から対応する } までを試す
    cand = None
    i = body.find("{")
    if i >= 0:
        depth = 0
        for j in range(i, len(body)):
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    cand = body[i:j + 1]
                    break
    if cand:
        try:
            import json as _json
            out = _json.loads(cand)
            if isinstance(out, dict):
                out.setdefault("claims", [])
                return out, warnings
        except Exception:
            warnings.append("json_parse_failed")
    # フォールバック1: markdown表(Gemini/GPTが表で返すケース)
    table_rows = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(table_rows) >= 3:
        claims = []
        for ln in table_rows[2:]:            # ヘッダ+罫線をスキップ
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if not cells or all(not c for c in cells):
                continue
            m = re.search(r"https?://[\w./%\-?=&#]+", ln)
            title = next((c for c in cells if len(c) >= 8 and not c.startswith("http")), "")
            date = next((c for c in cells if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", c)), None)
            if title or m:
                claims.append({"titleJa": re.sub(r"\[|\]|\(.*?\)", "", title)[:120],
                               "url": m.group(0) if m else None,
                               "publishedAt": date, "sourceName": None, "directness": None})
            if len(claims) >= 10:
                break
        if claims:
            warnings.append("markdown_table_extraction")
            return {"claims": claims}, warnings
    # フォールバック2: URL行/箇条書き行をclaims化(部分抽出・要検証扱い)
    claims = []
    for line in body.splitlines():
        ln = line.strip(" -・*​")
        if not ln or len(ln) < 8:
            continue
        m = re.search(r"https?://[\w./%\-?=&#]+", ln)
        title = re.sub(r"https?://\S+", "", ln).strip()[:120]
        if m or (len(title) >= 12 and not title.startswith("{")):
            claims.append({"titleJa": title or (m.group(0) if m else "")[:120],
                           "url": m.group(0) if m else None,
                           "sourceName": None, "publishedAt": None,
                           "directness": None})
        if len(claims) >= 8:
            break
    if claims:
        warnings.append("fallback_extraction")
    else:
        warnings.append("no_claims_extracted")
    return {"claims": claims}, warnings


# ── v12.1.1 Part B: 学習語のsanitize ────────────────────────────────────────

def sanitize_query_term(term: str) -> Optional[str]:
    t = str(term or "").strip()
    if not t or len(t) < 2:
        return None
    if re.search(r"https?://|login_pwd|passphrase|token|保有中|取得単価|口数|積立", t, re.I):
        return None
    return t[:40]


# ── v12.1.1 Part D: 追撃クエリ生成 ──────────────────────────────────────────

def followup_queries(unresolved_claims: List[Dict[str, Any]], cap: int = 6) -> List[str]:
    """Gemini/GPTだけが出した未回収claimから、決定論再探索用の追撃語を作る。"""
    out: List[str] = []
    for c in unresolved_claims:
        t = str(c.get("titleJa") or c.get("title") or "")
        for w in re.findall(r"[A-Z][A-Za-z0-9\-]{2,20}|[ァ-ヶー]{3,12}|[一-龠]{2,6}", t):
            w2 = sanitize_query_term(w)
            if w2 and w2 not in out:
                out.append(w2)
        u = str(c.get("url") or "")
        m = re.search(r"https?://(?:www\.)?([\w\-]+)\.", u)
        if m and sanitize_query_term(m.group(1)) and m.group(1) not in out:
            out.append(m.group(1))
        if len(out) >= cap:
            break
    return out[:cap]


def unresolved_agent_claims(agent_runs: List[Dict[str, Any]],
                            argus_titles: List[str]) -> List[Dict[str, Any]]:
    """エージェントだけが出し、まだ検証されていない重要claim(=P1ギャップ)。
    重要=日付が新しい(3営業日内)か、direct/value_chain主張。日付不明でも
    direct主張は重要扱い(見逃すと危険な側に倒す)。"""
    a_keys = {_title_hash(t) for t in argus_titles if t}
    out = []
    for r in agent_runs:
        if r.get("provider") not in ("gemini", "gpt") or r.get("status") != "ok":
            continue
        for c in (r.get("claims") or []):
            t = str(c.get("titleJa") or c.get("title") or "")
            if not t or _title_hash(t) in a_keys:
                continue
            if c.get("verified"):
                continue
            fresh = c.get("_freshness")
            important = fresh in ("today", "within_3_trading_days") or                 str(c.get("directness") or "") in ("direct", "direct_company", "value_chain")
            if important or fresh is None:
                out.append({**c, "provider": r["provider"]})
    return out


# ── v12.1.1 Part A: OSINT優位性メトリクス ───────────────────────────────────

def superiority_metrics(verified: List[Dict[str, Any]], agent_runs: List[Dict[str, Any]],
                        benchmark: Dict[str, Any], coverage: Dict[str, Any],
                        *, argus_titles: List[str],
                        context_added: bool = False) -> Dict[str, Any]:
    agents_ok = [r for r in agent_runs if r.get("provider") in ("gemini", "gpt")
                 and r.get("status") == "ok"]
    ver = [v for v in verified if v.get("verificationStatus") == "verified"]
    vrate = round(len(ver) / len(verified), 2) if verified else 0.0
    unresolved = unresolved_agent_claims(agent_runs, argus_titles)
    gem_unres = sum(1 for c in unresolved if c.get("provider") == "gemini")
    gpt_unres = sum(1 for c in unresolved if c.get("provider") == "gpt")
    a_keys = {_title_hash(t) for t in argus_titles if t}
    agent_keys = {_title_hash(str(c.get("titleJa") or c.get("title") or ""))
                  for r in agents_ok for c in (r.get("claims") or [])}
    ver_keys = {_title_hash(v.get("titleJa") or "") for v in ver}
    overlap_verified = len(a_keys & agent_keys & ver_keys)
    argus_only_verified = len((a_keys - agent_keys) & ver_keys)

    if not agents_ok:
        status = "insufficient_data"
    elif unresolved:
        status = "below_gemini"
    elif overlap_verified > 0 and (argus_only_verified > 0 or context_added):
        status = "exceeds_gemini"
    elif overlap_verified > 0 or benchmark.get("missedByArgusCount", 0) == 0:
        status = "matches_gemini"
    else:
        status = "insufficient_data"

    verdict_ja = {
        "exceeds_gemini": "Gemini超過: 外部AIのソースを検証済みで回収し、ARGUS独自の検証済みソース/文脈を追加。",
        "matches_gemini": "Gemini同等: 外部AIの検出を概ねカバー(未回収の重要ギャップなし)。",
        "below_gemini": f"Gemini未満: {GAP_JA}(未回収 {len(unresolved)}件 — 再探索と学習で回収します)",
        "insufficient_data": "判定保留: 外部AIベンチマーク未実行または材料不足。",
    }[status]
    return {
        "argusVerifiedSourceCount": len(ver),
        "geminiSourceCount": benchmark.get("geminiCount", 0),
        "gptSourceCount": benchmark.get("gptCount", 0),
        "geminiOnlyUnverifiedCount": gem_unres,
        "gptOnlyUnverifiedCount": gpt_unres,
        "argusMissedImportantCount": len(unresolved),
        "verifiedOverlapCount": overlap_verified,
        "argusOnlyVerifiedCount": argus_only_verified,
        "sourceVerificationRate": vrate,
        "retrievalCoverageScore": coverage.get("totalCoverage"),
        "valueChainCoverageScore": coverage.get("valueChainCoverage"),
        "officialCoverageScore": coverage.get("officialDisclosureCoverage"),
        "globalNewsCoverageScore": coverage.get("globalNewsCoverage"),
        "superiorityStatus": status,
        "superiorityJa": SUPERIORITY_JA[status],
        "ownerReadableVerdictJa": verdict_ja,
        "contextEdgeJa": CONTEXT_EDGE_JA if context_added else None,
    }


# ── v12.1.1 Part B: 恒久メモリレコード ──────────────────────────────────────

def memory_record(*, symbol: str, theme: str = "", query_term: str = "",
                  source_url: str = "", source_title: str = "",
                  learned_from: str, verified: bool, now_iso: str,
                  privacy_level: str = "public_safe") -> Optional[Dict[str, Any]]:
    qt = sanitize_query_term(query_term) if query_term else ""
    if query_term and not qt:
        return None                      # sanitize失敗語は保存しない
    title = str(source_title or "")[:160]
    dom = ""
    m = re.search(r"https?://(?:www\.)?([\w.\-]+)/?", str(source_url or ""))
    if m:
        dom = m.group(1)[:60]
    rid = hashlib.sha256(f"{symbol}|{qt}|{source_url}|{title}".encode()).hexdigest()[:12]
    return {"id": f"om-{rid}", "symbol": str(symbol).upper(), "theme": str(theme)[:40],
            "queryTerm": qt, "sourceUrl": str(source_url or "")[:200] or None,
            "sourceTitle": title or None, "sourceDomain": dom or None,
            "learnedFrom": learned_from if learned_from in
            ("gemini", "gpt", "owner_feedback", "deterministic", "canary") else "deterministic",
            "verified": bool(verified), "createdAt": now_iso, "lastUsedAt": now_iso,
            "privacyLevel": privacy_level if privacy_level in
            ("public_safe", "private_local", "redacted") else "public_safe"}


# ━━━ v12.1.2 Gap Closure — 正規化/クラスタ/ギャップ台帳/優位性v2 ━━━━━━━━━━━━

RESOLUTION_STATUSES = ("verified_integrated", "duplicate_existing", "stale_rejected",
                       "unsupported_rejected", "inaccessible", "missing_url",
                       "missing_date", "irrelevant", "low_value_background",
                       "still_unresolved_important")
RESOLUTION_JA = {
    "verified_integrated": "検証済みで統合",
    "duplicate_existing": "既存ソースと同一ニュース",
    "stale_rejected": "古い背景記事として却下",
    "unsupported_rejected": "裏付けなしとして却下",
    "inaccessible": "参照不能(ペイウォール等)",
    "missing_url": "URLなし(証拠にできない)",
    "missing_date": "日付なし",
    "irrelevant": "銘柄/テーマと無関係",
    "low_value_background": "低価値の背景情報",
    "still_unresolved_important": "重要だが未回収",
}
DUP_NOTE_JA = "Gemini提示記事はARGUS既存ソースと同一ニュースでした"
CAP_REACHED_JA = "検証上限到達"

# モード別予算(オーナー可視)
OSINT_BUDGETS = {
    "fast":     {"maxUrls": 0,  "maxLoops": 0, "maxSeconds": 30,
                 "maxCostLabel": "外部AIなし(巡回のみ)"},
    "balanced": {"maxUrls": 4,  "maxLoops": 1, "maxSeconds": 120,
                 "maxCostLabel": "控えめ(スカウト1周+URL検証4件)"},
    "deep":     {"maxUrls": 8,  "maxLoops": 2, "maxSeconds": 240,
                 "maxCostLabel": "標準(スカウト+再探索2周+URL検証8件)"},
    "war_room": {"maxUrls": 20, "maxLoops": 3, "maxSeconds": 420,
                 "maxCostLabel": "積極(URL検証20件・3周 — コスト高)"},
}

_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "cmpid", "smid", "ref=", "src=", "mc_cid")
_DOMAIN_ALIASES = {
    "m.youtube.com": "youtube.com", "mobile.twitter.com": "twitter.com",
    "finance.yahoo.com": "yahoo.com", "news.yahoo.co.jp": "yahoo.co.jp",
    "jp.reuters.com": "reuters.com", "www.reuters.com": "reuters.com",
}


def canonicalize_url(url: str) -> str:
    """トラッキングパラメータ除去+ドメイン別名正規化(シンジケーション対策)。"""
    u = str(url or "").strip()
    if not u:
        return ""
    u = re.sub(r"^https?://(www\.)?", "", u.lower())
    host = u.split("/")[0]
    host = _DOMAIN_ALIASES.get(host, host)
    path = u[len(u.split("/")[0]):]
    if "?" in path:
        base, q = path.split("?", 1)
        keep = [kv for kv in q.split("&")
                if kv and not any(kv.startswith(t) or t in kv[:12] for t in _TRACKING_PARAMS)]
        path = base + ("?" + "&".join(keep) if keep else "")
    return (host + path).rstrip("/")


def _bigrams(t: str) -> set:
    t2 = re.sub(r"[\s\W]+", "", str(t).lower())
    return {t2[i:i + 2] for i in range(len(t2) - 1)} if len(t2) >= 2 else set()


def title_similarity(a: str, b: str) -> float:
    g1, g2 = _bigrams(a), _bigrams(b)
    return (len(g1 & g2) / max(1, len(g1))) if g1 else 0.0


def _entities(t: str) -> set:
    return set(re.findall(r"[A-Z][A-Za-z0-9\-]{2,20}|[ァ-ヶー]{3,12}|[一-龠]{2,8}", str(t)))


def cluster_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一ニュース(URL正規化一致/タイトル類似≥0.5/エンティティ重なり)をクラスタ化。
    Reuters/Yahoo等のシンジケーション二重計上を防ぐ。"""
    clusters: List[Dict[str, Any]] = []
    for src in sources or []:
        title = str(src.get("titleJa") or src.get("title") or "")
        curl = canonicalize_url(src.get("url") or "")
        ents = _entities(title)
        hit = None
        for cl in clusters:
            if curl and curl == cl["canonicalUrl"]:
                hit = cl
                break
            sim = title_similarity(title, cl["canonicalTitle"])
            ent_ov = (len(ents & set(cl["entities"])) / max(1, len(ents))) if ents else 0.0
            if sim >= 0.5 or (sim >= 0.3 and ent_ov >= 0.5):
                hit = cl
                break
        if hit:
            hit["sources"].append(src)
            for e in ents:
                if e not in hit["entities"]:
                    hit["entities"].append(e)
            pub = src.get("publishedAt")
            if pub:
                hit["latestPublishedAt"] = max(hit.get("latestPublishedAt") or "", str(pub))
                hit["firstPublishedAt"] = min(hit.get("firstPublishedAt") or str(pub), str(pub))
        else:
            clusters.append({
                "clusterId": hashlib.sha256((curl or title).encode()).hexdigest()[:10],
                "canonicalTitle": title[:160], "canonicalUrl": curl or None,
                "sources": [src], "entities": list(ents)[:10],
                "firstPublishedAt": src.get("publishedAt"),
                "latestPublishedAt": src.get("publishedAt"),
                "claimSummaryJa": title[:120],
            })
    return clusters


def gap_targeted_queries(claim: Dict[str, Any], symbol: str = "",
                         name_ja: str = "") -> List[str]:
    """Gemini/GPT-onlyギャップ1件の標的再探索クエリ(正確なタイトル/エンティティ/
    ドメイン/日英バリアント)。"""
    title = str(claim.get("titleJa") or claim.get("title") or "").strip()
    out = []
    if title:
        out.append(title[:60])
        if name_ja and name_ja not in title:
            out.append(f"{title[:40]} {name_ja}")
    for e in list(_entities(title))[:3]:
        q = sanitize_query_term(e)
        if q and q not in out:
            out.append(q if not symbol else f"{q} {symbol}")
    u = str(claim.get("url") or "")
    m = re.search(r"https?://(?:www\.)?([\w\-]+)\.", u)
    if m:
        out.append(f"{m.group(1)} {name_ja or symbol}".strip())
    return out[:6]


def resolve_gap(claim: Dict[str, Any], provider: str, argus_clusters: List[Dict[str, Any]],
                *, symbol: str, investigation_id: str, now_iso: str,
                live_meta: Optional[Dict[str, Any]] = None,
                verification_attempts: int = 0,
                cap_reached: bool = False,
                theme_entities: Optional[set] = None) -> Dict[str, Any]:
    """エージェント提示ソース1件の解決判定 — 必ず理由つき。
    優先順: 重複 > 検証済み統合 > stale > URL/日付なし > 無関係 > 参照不能 >
    上限到達 > 重要未回収。"""
    title = str(claim.get("titleJa") or claim.get("title") or "").strip()
    url = str(claim.get("url") or "").strip()
    pub = claim.get("publishedAt")
    age_h = argus_news_freshness.age_hours(pub, now_iso) if pub and str(pub).lower() != "unknown" else None
    ents = _entities(title)
    # テーマ集合は複合語(浜松ホトニクス等)を分解して照合(部分一致も許容)
    th = set()
    for t in (theme_entities or set()):
        th |= _entities(str(t))
        th.add(str(t))
    theme_hit = bool(ents & th) or any(str(t) in title for t in (theme_entities or set()))

    status, reason = None, None
    verified_id = None
    # ① 既存クラスタと同一?
    curl = canonicalize_url(url)
    for cl in argus_clusters:
        if (curl and curl == cl["canonicalUrl"]) or title_similarity(title, cl["canonicalTitle"]) >= 0.5:
            status, reason = "duplicate_existing", DUP_NOTE_JA
            verified_id = cl["clusterId"]
            break
    # ② ライブ検証で統合済み?
    if status is None and claim.get("verified"):
        status, reason = "verified_integrated", "検証済み — 証拠台帳へ統合"
    if status is None and live_meta and live_meta.get("status") == "metadata_only" \
            and live_meta.get("title") and title_similarity(title, live_meta["title"]) >= 0.35:
        status, reason = "verified_integrated", "ライブ取得titleと一致 — 統合"
    # ③ stale
    if status is None and age_h is not None and age_h > 14 * 24:
        status, reason = "stale_rejected", f"{int(age_h // 24)}日前の記事 — 当日の主因にならない"
    # ④ URL/日付なし
    if status is None and not url:
        status, reason = "missing_url", "URLなし — 標的再探索でも発見できず証拠にできない"
    if status is None and (pub is None or str(pub).lower() == "unknown") and age_h is None \
            and verification_attempts >= 1 and (live_meta or {}).get("publishedAt") is None:
        status, reason = "missing_date", "日付を特定できない — 主因候補にできない"
    # ⑤ 無関係(銘柄/テーマエンティティと重なりゼロ)
    if status is None and theme_entities and ents and not theme_hit:
        status, reason = "irrelevant", "銘柄/テーマとエンティティの重なりなし"
    # ⑥ 参照不能
    if status is None and live_meta and live_meta.get("status") == "inaccessible":
        status, reason = "inaccessible", "取得不能(ペイウォール/ブロック) — 証拠にできない"
    # ⑦ 低価値背景(direct主張でなく一般論)
    if status is None and str(claim.get("directness") or "") in ("macro",) and age_h is None:
        status, reason = "low_value_background", "日付のない一般マクロ解説 — 背景参考のみ"
    # ⑧ 残り
    if status is None:
        if cap_reached:
            status = "still_unresolved_important"
            reason = f"{CAP_REACHED_JA}(検証予算切れ) — 次回War Roomで回収"
        else:
            status = "still_unresolved_important"
            reason = "重要候補だが未検証 — 標的再探索/URL検証の継続対象"

    return {
        "id": "gap-" + hashlib.sha256(f"{investigation_id}|{title}|{url}".encode()).hexdigest()[:10],
        "investigationId": investigation_id, "symbol": symbol,
        "sourceClaim": str(claim.get("summaryJa") or "")[:160] or None,
        "sourceTitle": title[:160], "sourceUrl": url or None,
        "sourceDomain": (re.search(r"https?://(?:www\.)?([\w.\-]+)/?", url).group(1)[:60]
                         if url and re.search(r"https?://(?:www\.)?([\w.\-]+)/?", url) else None),
        "providedBy": provider if provider in ("gemini", "gpt", "owner", "deterministic") else "gemini",
        "initialStatus": f"{provider}_only" if provider in ("gemini", "gpt") else "agent_only",
        "resolutionStatus": status,
        "resolutionStatusJa": RESOLUTION_JA[status],
        "resolutionReasonJa": reason,
        "followUpQueries": gap_targeted_queries(claim, symbol=symbol),
        "verificationAttempts": verification_attempts,
        "verifiedSourceId": verified_id,
        "confidenceImpact": ("raises" if status == "verified_integrated"
                             else "lowers" if status == "still_unresolved_important"
                             else "neutral"),
        "ownerReadableJa": f"[{RESOLUTION_JA[status]}] {title[:60]} — {reason}",
    }


def gap_ledger_summary(ledger: List[Dict[str, Any]]) -> Dict[str, Any]:
    by = {}
    for g in ledger or []:
        by[g["resolutionStatus"]] = by.get(g["resolutionStatus"], 0) + 1
    unresolved = [g for g in (ledger or [])
                  if g["resolutionStatus"] == "still_unresolved_important"]
    lines = []
    if ledger:
        lines.append(f"Gemini/GPT-only {len(ledger)}件を追跡中")
    for st, n in sorted(by.items(), key=lambda x: -x[1]):
        if st != "still_unresolved_important":
            lines.append(f"{n}件は{RESOLUTION_JA[st]}")
    if unresolved:
        lines.append(f"{len(unresolved)}件は未検証重要ソースとして残存")
    return {"byStatus": by, "unresolvedImportant": len(unresolved),
            "unresolvedImportantItems": [g["ownerReadableJa"] for g in unresolved][:6],
            "progressLinesJa": lines[:6]}


def superiority_v2(gap_ledger: List[Dict[str, Any]], *, agents_ok: bool,
                   argus_only_verified: int, verified_overlap: int,
                   context_advantages: List[str], coverage_total: str,
                   verification_rate: float) -> Dict[str, Any]:
    """優位性判定v2 — 生件数では絶対に超過にならない。
    exceeds = still_unresolved_important ゼロ かつ 文脈/独自検証の優位が1つ以上。"""
    summ = gap_ledger_summary(gap_ledger)
    unresolved = summ["unresolvedImportant"]
    has_advantage = argus_only_verified > 0 or bool(context_advantages)
    if not agents_ok:
        status = "insufficient_data" if coverage_total in ("weak", "insufficient", "failed") \
            else "insufficient_data"
    elif unresolved > 0:
        status = "below_gemini"
    elif has_advantage:
        status = "exceeds_gemini"
    else:
        status = "matches_gemini"
    adv_ja = "+".join(context_advantages[:3]) if context_advantages else "独自検証済みソース"
    verdict_ja = {
        "exceeds_gemini": f"Gemini超過: Gemini/GPTソースを全て回収/理由付き却下し、{adv_ja}を追加。",
        "matches_gemini": "Gemini同等: 重要ギャップは全て解決(独自の文脈優位はまだ薄い)。",
        "below_gemini": f"Gemini未満: {GAP_JA}(重要未回収 {unresolved}件 — 理由は台帳参照)",
        "insufficient_data": "判定保留: 外部AI未実行または探索不足。",
    }[status]
    return {"superiorityStatus": status, "superiorityJa": SUPERIORITY_JA[status],
            "ownerReadableVerdictJa": verdict_ja,
            "unresolvedImportant": unresolved,
            "gapByStatus": summ["byStatus"],
            "gapProgressLinesJa": summ["progressLinesJa"],
            "unresolvedItemsJa": summ["unresolvedImportantItems"],
            "contextAdvantages": context_advantages,
            "argusOnlyVerifiedCount": argus_only_verified,
            "verifiedOverlapCount": verified_overlap,
            "sourceVerificationRate": round(verification_rate, 2)}
