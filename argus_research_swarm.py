"""ARGUS — §12 Multi-Agent Research Mission orchestrator (pure, DETERMINISTIC).

WHY: a "swarm" of analyst roles can produce a far richer Research Mission than a
single pass — BUT only if it spends nothing it doesn't have to. This module runs
the roles as DETERMINISTIC reducers over already-collected evidence (Gear 0/1):
zero model calls, zero network, zero secrets. It does NOT call any LLM; it merely
STRUCTURES existing signals so a downstream gear (or a human) sees both sides, the
adversarial flags, and a gated ARGUS view.

Hard rules (inherited from argus_research_mesh / argus_attribution):
  * A NAMED institutional VIEW is never a NAMED TRADING POSITION.
  * A report published AFTER the move is an AMPLIFIER, never the immediate trigger.
  * FINRA short-sale VOLUME is never short INTEREST.
  * Two outlets repeating one wire are ONE origin, not two confirmations.
  * Confidence is labelled and HONEST — never a calibrated probability. When the
    Narrative Integrity Gate rejects a synthesis, confidence is downgraded, the
    violations are kept, and the view is marked not-publishable.
  * No trade instruction, ever. Decision-support only.

DYNAMIC staffing: plan_mission does NOT run every role for every event — it scales
the roster and the gear by severity, owner-relevance and evidence gaps. Only
ADVERSARIAL_REVIEWER and SYNTHESIS_EDITOR always run.

Stdlib-only; the single import is the already-implemented research mesh.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import argus_research_mesh as M

SCHEMA = "research-swarm-v1"
CALIB = "uncalibrated_heuristic_v1"  # never a calibrated probability

# ── §12 the deterministic analyst roles ──────────────────────────────────────
# 並び順 = ミッションでの実行順。証拠系ロールが先、ADVERSARIAL→SYNTHESIS が最後。
ROLES: List[str] = [
    "INSTITUTIONAL_SOURCE_HUNTER",   # 関連インテリ収集(資産/機関で絞り込み)
    "OFFICIAL_SOURCE_VERIFIER",      # 公式系(規制/IR/中銀)に印
    "NEWS_CORROBORATION",            # 独立確認 vs 同一ワイヤー転載
    "MARKET_REACTION",               # 動意との時刻整合 → 因果ロール集計
    "POSITIONING",                   # ポジショニング(あれば pass-through)
    "BULL_CASE",                     # 強気の主張(両論保持)
    "BEAR_CASE",                     # 弱気の主張(両論保持)
    "ADVERSARIAL_REVIEWER",          # 反証・過剰主張の検出(常時)
    "SYNTHESIS_EDITOR",              # 統合 + Narrative Integrity Gate(常時)
]

# 常時実行(動的編成でも必ず入る)。
_ALWAYS = ("ADVERSARIAL_REVIEWER", "SYNTHESIS_EDITOR")


# ── helpers ──────────────────────────────────────────────────────────────────
def _assets(d: Dict[str, Any]) -> set:
    """event/item の linkedAssets を UPPER の集合に。"""
    return {str(a).upper() for a in (d.get("linkedAssets") or [])}


def _severity_rank(sev: Any) -> int:
    """severity を 0..3 に正規化(文字列/数値どちらでも)。"""
    if isinstance(sev, (int, float)):
        return max(0, min(3, int(sev)))
    s = str(sev or "").strip().upper()
    return {"CRITICAL": 3, "HIGH": 3, "ELEVATED": 2, "MEDIUM": 2,
            "MODERATE": 2, "LOW": 1, "MINOR": 1, "INFO": 0, "NONE": 0}.get(s, 1)


# ── plan_mission — DYNAMIC staffing (§12) ────────────────────────────────────
def plan_mission(event: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """どのロールを、どのギアで走らせるかを動的に決める。

    全イベントで全ロールを走らせない。severity / ownerRelevant / 証拠ギャップ
    (novelty・既存インテリの薄さ)で編成とギア(0..3)を引き上げる。
    ADVERSARIAL_REVIEWER と SYNTHESIS_EDITOR は常に含める。
    """
    context = context or {}
    sev = _severity_rank(event.get("severity"))
    owner = bool(context.get("ownerRelevant"))
    # novelty / 証拠ギャップ: 既知が薄い・新規性が高いほど深掘り。
    novelty = float(event.get("novelty", context.get("novelty", 0.0)) or 0.0)
    evidence_gap = bool(context.get("evidenceGap")) or novelty >= 0.6
    n_intel = int(context.get("intelCount", 0) or 0)

    reasons: List[str] = []
    roles: List[str] = []

    # --- 証拠系ロールは「必要なときだけ」入れる ---
    # ハンター: 何か事象がある時点で常に有用(severity>=1 か owner か 既知インテリあり)。
    if sev >= 1 or owner or n_intel > 0:
        roles.append("INSTITUTIONAL_SOURCE_HUNTER")
        reasons.append("関連インテリの収集が必要")
    # 公式検証: severity が中以上、または owner 関連、または証拠ギャップ。
    if sev >= 2 or owner or evidence_gap:
        roles.append("OFFICIAL_SOURCE_VERIFIER")
        reasons.append("公式系の裏取りが必要")
    # 報道の独立確認: 複数報道が絡みうる中以上 / owner。
    if sev >= 2 or owner:
        roles.append("NEWS_CORROBORATION")
        reasons.append("独立確認 vs 転載の判別")
    # 市場反応: 動意の時刻があるなら常に。なくても severity>=2 で試す。
    if event.get("moveStartedAt") or sev >= 2:
        roles.append("MARKET_REACTION")
        reasons.append("動意との時刻整合を確認")
    # ポジショニング: 提供があるか、owner+高severity のときだけ。
    if (context.get("positioning") is not None) or (owner and sev >= 2):
        roles.append("POSITIONING")
        reasons.append("ポジショニングの参照")
    # 強気/弱気: 中以上 or owner or 証拠ギャップ(両論を組む価値があるとき)。
    if sev >= 2 or owner or evidence_gap:
        roles.append("BULL_CASE")
        roles.append("BEAR_CASE")
        reasons.append("両論(強気/弱気)を保持")

    # --- 常時ロール ---
    for r in _ALWAYS:
        if r not in roles:
            roles.append(r)
    reasons.append("反証レビューと統合ゲートは常時実行")

    # ROLES の正準順に並べ替え(決定的)。
    order = {r: i for i, r in enumerate(ROLES)}
    roles = sorted(set(roles), key=lambda r: order[r])

    # --- ギア(0..3): severity を土台に owner / 証拠ギャップで加点、上限3 ---
    gear = sev
    if owner:
        gear += 1
    if evidence_gap:
        gear += 1
    gear = max(0, min(3, gear))

    reason_ja = (
        f"severity={sev}/owner={'有' if owner else '無'}/"
        f"証拠ギャップ={'有' if evidence_gap else '無'} → "
        f"{len(roles)}ロール・ギア{gear}。" + "; ".join(reasons)
    )
    return {"roles": roles, "gear": gear, "reasonJa": reason_ja,
            "severityRank": sev, "ownerRelevant": owner, "evidenceGap": evidence_gap}


# ── individual deterministic roles (each pure) ───────────────────────────────
def _role_hunter(event: Dict[str, Any], intel_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """INSTITUTIONAL_SOURCE_HUNTER: 対象資産が交差 OR institutionId 付きのインテリ。"""
    ev_assets = _assets(event)
    out = []
    for it in intel_items:
        hit_asset = bool(ev_assets & _assets(it))
        has_inst = bool(it.get("institutionId"))
        if hit_asset or has_inst:
            out.append(it)
    return out


def _role_official(hunter_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OFFICIAL_SOURCE_VERIFIER: source_rights の kind=='official' を抽出。"""
    out = []
    for it in hunter_items:
        sid = it.get("sourceId") or "unknown"
        if M.source_rights(sid).get("kind") == "official":
            out.append(it)
    return out


def _role_corroboration(hunter_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """NEWS_CORROBORATION: クラスタ化して独立確認数 + 転載注記を集計。

    同一ワイヤーの転載は ONE origin。independentSourceCount>=2 のクラスタのみ
    「独立確認あり」とみなす。
    """
    clusters = M.cluster_items(hunter_items) if hunter_items else []
    independent = [c for c in clusters if c.get("independentSourceCount", 0) >= 2]
    syndication_total = sum(c.get("syndicationCount", 0) for c in clusters)
    return {
        "clusters": clusters,
        "clusterCount": len(clusters),
        "independentlyCorroboratedCount": len(independent),
        "syndicationCount": syndication_total,
        "note": ("複数の独立系統で確認されたクラスタあり" if independent
                 else "独立確認なし(単一系統/同一ワイヤー転載のみ)"),
    }


def _role_market_reaction(event: Dict[str, Any], hunter_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """MARKET_REACTION: 各アイテムの因果ロールを link_to_event で判定し集計。

    moveStartedAt との時刻整合で AMPLIFIER / LIKELY_RELATED / UNCONFIRMED などを数える。
    published-after-move は AMPLIFIER(引き金ではない)。
    """
    links = [M.link_to_event(it, event) for it in hunter_items]
    counts: Dict[str, int] = {}
    for lk in links:
        role = lk.get("causalRole", "UNCONFIRMED")
        counts[role] = counts.get(role, 0) + 1
    return {
        "links": links,
        "roleCounts": counts,
        "amplifierCount": counts.get("AMPLIFIER", 0),
        "likelyRelatedCount": counts.get("LIKELY_RELATED", 0),
        "unconfirmedCount": counts.get("UNCONFIRMED", 0),
        # 引き金として扱える候補(動意の前で時刻整合)。実装上 IMMEDIATE_TRIGGER は
        # mesh が published-after では出さないので、ここでは LIKELY_RELATED を上限とする。
        "triggerCandidateCount": counts.get("IMMEDIATE_TRIGGER", 0),
    }


def _join_titles(items: List[Dict[str, Any]]) -> str:
    """両論分析用に、関連アイテムのタイトル(+短いスニペット)を結合。"""
    parts = []
    for it in items:
        t = (it.get("title") or "").strip()
        s = (it.get("publicSnippet") or "").strip()
        if t:
            parts.append(t if not s else f"{t}. {s}")
    return " ".join(parts)


def _role_bull_bear(hunter_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """BULL_CASE / BEAR_CASE: 結合タイトルを analyze_report で両論抽出(両側保持)。"""
    joined = _join_titles(hunter_items)
    rep = M.analyze_report(joined, "")
    bull = {"claims": rep.get("bullishClaims", []), "count": len(rep.get("bullishClaims", []))}
    bear = {"claims": rep.get("bearishClaims", []), "count": len(rep.get("bearishClaims", []))}
    return {"bull": bull, "bear": bear,
            "balanced": bool(rep.get("balanced")),
            "conditionalClaims": rep.get("conditionalClaims", []),
            "risks": rep.get("risks", [])}


def _role_positioning(context: Dict[str, Any]) -> Dict[str, Any]:
    """POSITIONING: context.positioning の pass-through(無ければ unavailable)。"""
    pos = context.get("positioning")
    if pos is None:
        return {"status": "unavailable",
                "note": "ポジショニングデータ未提供(空売り出来高は残高ではない)"}
    out = dict(pos) if isinstance(pos, dict) else {"value": pos}
    out.setdefault("status", "provided")
    return out


# ── ADVERSARIAL_REVIEWER — runs AFTER evidence is assembled ──────────────────
def _adversarial_flags(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """過剰主張・偽の確証を検出。クリーンなら []。

    検査:
      * stale-report-as-trigger : AMPLIFIER のアイテムを引き金扱いしている兆候。
      * named-institution-trade : 機関名 + 売買断定(NAMED VIEW を NAMED TRADE 化)。
      * short-volume!=short-interest : 出来高=残高の混同。
      * duplicate-source false confirmation : count>1 だが independentSourceCount<2。
      * one-sided evidence : 強気 xor 弱気のみ。
      * unsupported certainty : 断定的な言い切り。
    """
    flags: List[Dict[str, Any]] = []
    mr = evidence.get("marketReaction") or {}
    corro = evidence.get("corroboration") or {}
    bull = (evidence.get("bull") or {})
    bear = (evidence.get("bear") or {})
    hunter = evidence.get("hunter") or []

    # 1) stale / amplifier-as-trigger: 動意後(AMPLIFIER)なのに「引き金」と読みうる。
    if mr.get("amplifierCount", 0) > 0:
        flags.append({
            "flag": "stale-report-as-trigger",
            "severity": "high",
            "reasonJa": (f"{mr['amplifierCount']}件が動意の後に出た情報(AMPLIFIER)。"
                         "増幅であり即時の引き金として扱ってはならない。"),
        })

    # 2) named-institution-trade & 3) short-volume!=short-interest & 6) unsupported
    #    → アイテム本文/タイトル + 機関名を Narrative gate の禁止表現で検査。
    blob_parts = []
    named_inst_present = False
    for it in hunter:
        blob_parts.append(it.get("title") or "")
        blob_parts.append(it.get("publicSnippet") or "")
        if it.get("institutionId"):
            named_inst_present = True
    blob = " ".join(blob_parts)
    for reason in M.narrative_violations(blob):
        # mesh の理由文を分類してフラグ化。
        rl = reason.lower()
        if "空売り出来高" in reason or "short" in rl:
            flags.append({"flag": "short-volume!=short-interest", "severity": "high", "reasonJa": reason})
        elif "trade claim" in rl or "自己売買" in reason or "売買" in reason:
            flags.append({"flag": "named-institution-trade", "severity": "high", "reasonJa": reason})
        else:
            flags.append({"flag": "unsupported-certainty", "severity": "medium", "reasonJa": reason})

    # named-institution-trade の追加チェック: 機関名 + 売買語が本文に同居。
    if named_inst_present:
        low = blob.lower()
        if any(w in low for w in ("sold", "bought", "売った", "買った", "建玉", "ポジションを")):
            if not any(f["flag"] == "named-institution-trade" for f in flags):
                flags.append({
                    "flag": "named-institution-trade", "severity": "high",
                    "reasonJa": "機関名と売買語が同居。発表された見解(VIEW)を建玉/売買(TRADE)と断定してはならない。",
                })

    # 4) duplicate-source false confirmation: count>1 だが独立は <2。
    for c in corro.get("clusters", []):
        if c.get("count", 0) > 1 and c.get("independentSourceCount", 0) < 2:
            flags.append({
                "flag": "duplicate-source-false-confirmation",
                "severity": "medium",
                "reasonJa": ("同一ワイヤーの転載が複数あるが独立確認は1系統のみ。"
                             "転載は確証の数を増やさない。"),
            })
            break  # 1回で十分(注意喚起目的)

    # 5) one-sided evidence: 強気 xor 弱気のみ(片側だけ証拠がある)。
    has_bull = bull.get("count", 0) > 0
    has_bear = bear.get("count", 0) > 0
    if has_bull != has_bear and (has_bull or has_bear):
        side = "強気" if has_bull else "弱気"
        flags.append({
            "flag": "one-sided-evidence",
            "severity": "medium",
            "reasonJa": f"{side}側の証拠のみ。両論が揃っていない(反対側の不在を明示せよ)。",
        })

    # 決定的な並び(同一入力で同一出力)。
    flags.sort(key=lambda f: (f["flag"], f.get("reasonJa", "")))
    return flags


# ── SYNTHESIS_EDITOR — assemble + gate ───────────────────────────────────────
def _synthesis_editor(event: Dict[str, Any], evidence: Dict[str, Any],
                      adversarial_flags: List[Dict[str, Any]]) -> Dict[str, Any]:
    """証拠から synthesis を組み、M.gate_synthesis に通す。

    publishable=False なら confidence を 'UNCONFIRMED'/'LOW' に格下げし、violations
    を保持する。argusView = ゲート結果 + synthesis 本文。
    """
    official = evidence.get("official") or []
    corro = evidence.get("corroboration") or {}
    mr = evidence.get("marketReaction") or {}
    bull = evidence.get("bull") or {}
    bear = evidence.get("bear") or {}
    positioning = evidence.get("positioning") or {}

    # confirmedFacts: 公式裏取り or 独立確認があるときのみ「確認済み事実」を立てる。
    confirmed_facts: List[str] = []
    if official:
        confirmed_facts.append(f"公式系で裏取りされたインテリ {len(official)}件。")
    if corro.get("independentlyCorroboratedCount", 0) > 0:
        confirmed_facts.append(
            f"独立 {corro['independentlyCorroboratedCount']}系統で確認されたクラスタあり。")
    if event.get("moveStartedAt"):
        confirmed_facts.append(f"動意開始時刻: {event.get('moveStartedAt')}(時刻整合の基準)。")

    # reportedView: 発表された見解(両論)。NAMED VIEW であって NAMED TRADE ではない。
    reported_view = (
        f"強気の主張 {bull.get('count', 0)}件 / 弱気の主張 {bear.get('count', 0)}件 "
        "(発表された見解であり、当該機関の建玉/売買ではない)。"
    )

    # interpretation: 因果ロールの集計を反映。引き金とは断定しない。
    interpretation = (
        f"市場反応の因果ロール集計: AMPLIFIER={mr.get('amplifierCount', 0)}, "
        f"LIKELY_RELATED={mr.get('likelyRelatedCount', 0)}, "
        f"UNCONFIRMED={mr.get('unconfirmedCount', 0)}。"
        "動意後の情報は増幅であり即時の引き金ではない。"
    )

    # alternative: 反対側 / 不在を必ず明示(片側証拠なら特に)。
    alt_bits = []
    if bull.get("count", 0) and not bear.get("count", 0):
        alt_bits.append("弱気側の証拠が不足している可能性。")
    elif bear.get("count", 0) and not bull.get("count", 0):
        alt_bits.append("強気側の証拠が不足している可能性。")
    else:
        alt_bits.append("反対側の解釈(逆方向の見解)も成立しうる。")
    if mr.get("unconfirmedCount", 0):
        alt_bits.append("因果不明のアイテムが残る。")
    alternative = " ".join(alt_bits)

    # notConfirmed: 断定していない事項を列挙(常に非空 = 正直さの担保)。
    not_confirmed = ["直接の引き金", "当該機関の建玉/売買の変化"]
    if positioning.get("status") == "unavailable":
        not_confirmed.append("ポジショニングデータ(未提供)")
    if not official:
        not_confirmed.append("公式系の裏取り")

    # 初期 confidence: 公式裏取り + 独立確認 + 反証フラグの有無で素朴に決める。
    has_official = bool(official)
    has_indep = corro.get("independentlyCorroboratedCount", 0) > 0
    high_flags = [f for f in adversarial_flags if f.get("severity") == "high"]
    if has_official and has_indep and not adversarial_flags:
        confidence = "MODERATE"
    elif (has_official or has_indep) and not high_flags:
        confidence = "LOW"
    else:
        confidence = "UNCONFIRMED"

    synthesis = {
        "confirmedFacts": " ".join(confirmed_facts) if confirmed_facts else "",
        "reportedView": reported_view,
        "interpretation": interpretation,
        "alternative": alternative,
        "notConfirmed": not_confirmed,
        "confidence": confidence,
    }

    gated = M.gate_synthesis(synthesis)

    # ゲート不合格なら格下げ + violations 保持。
    final_conf = gated.get("confidence", confidence)
    if not gated.get("publishable"):
        # high 反証フラグがあれば UNCONFIRMED、そうでなければ LOW に。
        final_conf = "UNCONFIRMED" if high_flags else "LOW"

    argus_view = {
        "synthesis": synthesis,
        "publishable": bool(gated.get("publishable")),
        "violations": gated.get("violations", []),
        "missingSections": gated.get("missingSections", []),
        "downgradeReason": gated.get("downgradeReason"),
        "confidence": final_conf,
        "schema": SCHEMA,
        "calibration": CALIB,
        "decisionSupportOnly": True,
        "noTradeInstruction": True,
    }
    return argus_view


# ── run_mission — orchestrate the deterministic swarm ────────────────────────
def run_mission(event: Dict[str, Any], intel_items: List[Dict[str, Any]],
                context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """既収集の証拠上で、決定的なアナリスト・ロール群を走らせる(LLM呼び出し0)。

    返り値:
      rolesRun, evidence{hunter, official, corroboration, marketReaction, bull,
      bear, positioning}, adversarialFlags, argusView{...gated...}, confidence,
      cost{llmCalls:0, deterministic:True}。
    """
    context = context or {}
    intel_items = list(intel_items or [])

    # どのロールを走らせるかは plan に従う(動的編成)。
    plan = plan_mission(event, context)
    planned = set(plan["roles"])
    roles_run: List[str] = []

    # --- 証拠系ロール(順序は ROLES の正準順) ---
    # ハンターは下流の前提なので、編成に入っていれば最初に走らせる。
    hunter_items: List[Dict[str, Any]] = []
    if "INSTITUTIONAL_SOURCE_HUNTER" in planned:
        hunter_items = _role_hunter(event, intel_items)
        roles_run.append("INSTITUTIONAL_SOURCE_HUNTER")

    official_items: List[Dict[str, Any]] = []
    if "OFFICIAL_SOURCE_VERIFIER" in planned:
        official_items = _role_official(hunter_items)
        roles_run.append("OFFICIAL_SOURCE_VERIFIER")

    corroboration: Dict[str, Any] = {}
    if "NEWS_CORROBORATION" in planned:
        corroboration = _role_corroboration(hunter_items)
        roles_run.append("NEWS_CORROBORATION")

    market_reaction: Dict[str, Any] = {}
    if "MARKET_REACTION" in planned:
        market_reaction = _role_market_reaction(event, hunter_items)
        roles_run.append("MARKET_REACTION")

    positioning: Dict[str, Any] = {}
    if "POSITIONING" in planned:
        positioning = _role_positioning(context)
        roles_run.append("POSITIONING")

    bull: Dict[str, Any] = {}
    bear: Dict[str, Any] = {}
    if "BULL_CASE" in planned or "BEAR_CASE" in planned:
        bb = _role_bull_bear(hunter_items)
        bull, bear = bb["bull"], bb["bear"]
        if "BULL_CASE" in planned:
            roles_run.append("BULL_CASE")
        if "BEAR_CASE" in planned:
            roles_run.append("BEAR_CASE")

    evidence = {
        "hunter": hunter_items,
        "official": official_items,
        "corroboration": corroboration,
        "marketReaction": market_reaction,
        "bull": bull,
        "bear": bear,
        "positioning": positioning,
    }

    # --- ADVERSARIAL_REVIEWER(常時・証拠組み立て後) ---
    adversarial_flags = _adversarial_flags(evidence)
    roles_run.append("ADVERSARIAL_REVIEWER")

    # --- SYNTHESIS_EDITOR(常時・最後) ---
    argus_view = _synthesis_editor(event, evidence, adversarial_flags)
    roles_run.append("SYNTHESIS_EDITOR")

    return {
        "schema": SCHEMA,
        "rolesRun": roles_run,
        "gear": plan["gear"],
        "evidence": evidence,
        "adversarialFlags": adversarial_flags,
        "argusView": argus_view,
        "confidence": argus_view["confidence"],
        "cost": {"llmCalls": 0, "deterministic": True, "network": False},
        "decisionSupportOnly": True,
    }
