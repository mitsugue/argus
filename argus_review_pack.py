"""ARGUS V11.20.0 — Pro Handoff 2.0 / AI Review Pack (pure, deterministic).

GPT Pro/Gemini/Claudeに貼る「セカンドオピニオン用パック」を、全レイヤーから
重複なく・階層的に・プライバシー配慮つきで合成する。売買指示ではなく、
反対意見と不足証拠の指摘を外部AIに依頼する文書。

HARD RULES:
  - パックを外部AIへ自動送信しない(コピーはオーナーの手で)。サーバー保存もしない。
  - 秘密(パスフレーズ/vault暗号文/HMAC/OpenD/moomoo資格情報/トークン/バックアップ
    JSON生データ)は絶対に含めない — FORBIDDEN_SECRETSで構造検査。
  - 執行語(今すぐ買え/売れ・注文)は絶対に含めない。
  - redactedモードは保有・数量・損益・比率・投信評価額・積立額・口座区分・
    オーナーメモを含めない。
  - 同じイベント要約・同じ需給文を複数セクションに繰り返さない(銘柄別は
    Assetsに集約し、モジュール別セクションは集計一行のみ)。
  - 欠落データは Missing Evidence に正直に列挙(捏造しない)。
  - 必ず「最強の反対view」と「レビュアーへの指示」で締める。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "ai-review-pack-v1"

PACK_TYPES = ("daily", "asset", "portfolio", "event", "emergency", "custom")
AUDIENCES = ("gpt_pro", "gemini", "claude", "generic_ai")
LANGUAGES = ("ja", "en", "bilingual")
PRIVACY_MODES = ("redacted", "local_private", "owner_copy")
LENGTHS = ("full", "short")
SECTION_TYPES = ("session_brief", "action_priority", "important_events",
                 "market_regime", "scenario", "entry_exit_plan",
                 "portfolio_strategy", "fire_core", "position_exposure",
                 "supply_demand", "flow_attribution", "institutional_intelligence",
                 "decision_quality", "learning_dashboard", "notifications",
                 "backup_safety", "data_quality", "missing_data", "opposing_view",
                 "prompt_instruction")
HELD_STATUSES = ("held", "watch_only", "unknown")

# 秘密・実行語 — 全出力に対してテストが検査する
FORBIDDEN_SECRETS = ("vaultPass", "passphrase", "HMAC", "X-ARGUS-ADMIN-TOKEN",
                     "login_pwd", "ct\":", "OPEND_", "moomoo_pwd", "api_key",
                     "Bearer ")
FORBIDDEN_EXECUTION = ("今すぐ買", "今すぐ売", "buy now", "sell now",
                       "place order", "注文を出", "成行で買", "全力買い")
# redactedモードで含めてはならない私的語彙(検査用)
PRIVATE_MARKERS = ("保有中", "含み益", "含み損", "取得単価", "口数", "積立",
                   "評価額", "全体の", "比率が高", "NISA", "iDeCo")

COMPLIANCE = ("これはセカンドオピニオン用のレビュー資料であり、売買指示・自動売買・"
              "免許業の助言ではない。外部AIへの自動送信はしない。")
PRIVACY_LABEL_JA = "この内容には個人投資情報が含まれる可能性があります。共有先に注意してください。"

INSTRUCTIONS_JA = {
    "daily": ("あなたは経験豊富な投資リスクレビュアーです。以下のARGUS出力を前提に、"
              "売買指示ではなく、判断の弱点・反対シナリオ・不足データ・確認すべき条件を"
              "日本語で整理してください。ARGUSの結論をそのまま肯定せず、特に過剰に"
              "楽観/悲観になっている点を指摘してください。"),
    "asset": ("この銘柄について、ARGUSの判断の弱点と見落としを中心にレビューして"
              "ください。特に「入っていいか/待つべきか」の分岐条件が妥当か、需給・"
              "フロー解釈に代替説明がないかを検討してください。売買指示は不要です。"),
    "portfolio": ("ポートフォリオ構成とFIRE整合について、集中リスク・コア/戦術枠の"
                  "バランス・不足データの影響を中心にレビューしてください。数値は概算・"
                  "帯であり、退職時期や確率の計算は求めません。売買指示は不要です。"),
    "event": ("このイベントについて、ARGUSの事前シナリオの弱点・見落としている波及経路・"
              "発表後に真っ先に確認すべき指標を整理してください。売買指示は不要です。"),
    "emergency": ("保有銘柄に複合リスク信号が出ています。ARGUSの判断が過剰反応か過小反応か、"
                  "いま確認すべき事実の優先順位、やってはいけない行動を整理してください。"
                  "パニック的な即断を勧めないでください。売買指示は不要です。"),
}

QUESTION_TEMPLATES_JA = {
    "daily": "今日の全体をプロ目線でレビューしてほしい。ARGUSの見落としはないか。",
    "asset": "この銘柄、ARGUSの判断は合っているか。弱点を中心に見てほしい。",
    "portfolio": "この構成でFIRE計画として無理はないか。集中しすぎていないか。",
    "event": "このイベントの前後で何を確認すべきか。ARGUSの事前シナリオに穴はないか。",
    "emergency": "保有銘柄に警報が出た。冷静に、何を確認しどう構えるべきか。",
}


def _sec(sec_type: str, title: str, content: str = "", bullets: Optional[List[str]] = None,
         priority: int = 5, privacy: str = "public_safe") -> Dict[str, Any]:
    assert sec_type in SECTION_TYPES, sec_type
    return {"id": f"sec-{sec_type}", "titleJa": title, "sectionType": sec_type,
            "contentJa": content[:400], "bulletsJa": (bullets or [])[:8],
            "assets": [], "priority": priority,
            "includeInClipboard": True, "privacyLevel": privacy}


def build_asset_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """ReviewAsset — 銘柄別情報はここに1回だけ集約(モジュール毎に繰り返さない)。"""
    held = raw.get("heldStatus") if raw.get("heldStatus") in HELD_STATUSES else "unknown"
    return {"symbol": str(raw.get("symbol") or "").upper(),
            "market": raw.get("market"), "assetName": raw.get("assetName"),
            "heldStatus": held, "role": raw.get("role") or "unknown",
            "actionPriority": raw.get("actionPriority"),
            "scenarioSummaryJa": raw.get("scenarioSummaryJa"),
            "planSummaryJa": raw.get("planSummaryJa"),
            "supplyDemandSummaryJa": raw.get("supplyDemandSummaryJa"),
            "flowSummaryJa": raw.get("flowSummaryJa"),
            "positionRiskSummaryJa": raw.get("positionRiskSummaryJa"),
            "institutionalSummaryJa": raw.get("institutionalSummaryJa"),
            "eventSummaryJa": raw.get("eventSummaryJa"),
            "missingEvidenceJa": list(raw.get("missingEvidenceJa") or [])[:3],
            "opposingViewJa": raw.get("opposingViewJa"),
            "reviewQuestionJa": raw.get("reviewQuestionJa")}


def _redact_asset(a: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(a)
    r["heldStatus"] = "unknown"                 # 保有/監視の区別も伏せる
    r["positionRiskSummaryJa"] = None           # 保有リスク(比率/損益由来)は除外
    return r


def build_pack(pack_type: str, ctx: Dict[str, Any], *, privacy_mode: str = "owner_copy",
               length: str = "full", now_iso: str = "", app_version: str = "") -> Dict[str, Any]:
    """ctx (device-side facts; 欠落はNone/[]のまま — 捏造しない):
      commandJa, sessionBriefJa, regimeJa, eventsJa[] (イベントはここ1回のみ),
      apLinesJa[], scenarioLinesJa[], planLinesJa[], strategyJa, strategyWarningsJa[],
      fireCoreJa, sdAggregateJa, flowAggregateJa, instAggregateJa,
      dqCaveatJa, lrCaveatJa, notifLinesJa[], backupSafeJa,
      assets[] (build_asset_row形式), topRisksJa[], topOpportunitiesJa[],
      blockedJa[], missingJa[], contradictionsJa[], opposingJa,
      eventFocus{...}(eventパック), emergencyChecksJa[]/emergencyAvoidJa[](emergency)
    """
    assert pack_type in PACK_TYPES
    assert privacy_mode in PRIVACY_MODES
    assert length in LENGTHS
    redacted = privacy_mode == "redacted"

    def strip_private(lines):
        """redactedモード: 私的語彙(保有/損益/積立/投信/口座等)を含む行を落とす。"""
        if not redacted:
            return list(lines or [])
        return [x for x in (lines or [])
                if not any(m in str(x) for m in PRIVATE_MARKERS)]

    assets = [build_asset_row(a) for a in (ctx.get("assets") or [])]
    if redacted:
        assets = [_redact_asset(a) for a in assets]
        ctx = dict(ctx)
        for k in ("topRisksJa", "topOpportunitiesJa", "blockedJa",
                  "apLinesJa", "scenarioLinesJa", "planLinesJa",
                  "notifLinesJa", "eventsJa"):
            ctx[k] = strip_private(ctx.get(k))

    missing = strip_private(ctx.get("missingJa"))
    opposing = ctx.get("opposingJa") or (
        "ARGUSの各レイヤーは公表遅延データ(需給)と推定(フロー)に依存しており、"
        "実測フローの転換一つで支配シナリオ・計画が入れ替わり得る。結論の固定を疑うこと。")

    sections: List[Dict[str, Any]] = []
    if ctx.get("sessionBriefJa"):
        sections.append(_sec("session_brief", "Session Brief / 今日の作戦",
                             ctx["sessionBriefJa"], priority=1))
    if ctx.get("apLinesJa"):
        sections.append(_sec("action_priority", "Action Priority / 今日これを見る",
                             bullets=ctx["apLinesJa"], priority=2))
    if ctx.get("eventsJa"):
        # イベント要約はこのセクションにのみ置く(CAOS/機関側では繰り返さない)
        sections.append(_sec("important_events", "Important Events / 重要イベント",
                             bullets=ctx["eventsJa"], priority=2))
    if ctx.get("regimeJa"):
        sections.append(_sec("market_regime", "Market Regime / 地合い",
                             ctx["regimeJa"], priority=3))
    if ctx.get("scenarioLinesJa"):
        sections.append(_sec("scenario", "Scenarios / 条件付き分岐(帯のみ)",
                             bullets=ctx["scenarioLinesJa"], priority=3))
    if ctx.get("planLinesJa"):
        sections.append(_sec("entry_exit_plan", "Entry / Exit Planning / 計画(指示ではない)",
                             bullets=ctx["planLinesJa"], priority=3))
    if not redacted and ctx.get("strategyJa"):
        sections.append(_sec("portfolio_strategy", "Portfolio Strategy / FIRE整合(概算)",
                             ctx["strategyJa"],
                             bullets=list(ctx.get("strategyWarningsJa") or []),
                             priority=3, privacy="private_local"))
    if not redacted and ctx.get("fireCoreJa"):
        sections.append(_sec("fire_core", "FIRE Core / 投資信託(本丸資産)",
                             ctx["fireCoreJa"], priority=3, privacy="private_local"))
    if ctx.get("sdAggregateJa"):
        sections.append(_sec("supply_demand", "Supply / Demand 集計(銘柄別はAssets欄)",
                             ctx["sdAggregateJa"], priority=4))
    if ctx.get("flowAggregateJa"):
        sections.append(_sec("flow_attribution", "Big Money / Flow 集計(銘柄別はAssets欄)",
                             ctx["flowAggregateJa"], priority=4))
    if ctx.get("instAggregateJa"):
        sections.append(_sec("institutional_intelligence", "Institutional Intelligence 集計",
                             ctx["instAggregateJa"], priority=4))
    if ctx.get("dqCaveatJa") or ctx.get("lrCaveatJa"):
        sections.append(_sec("learning_dashboard", "Decision Quality / Learning(注意書き)",
                             " ".join(x for x in (ctx.get("dqCaveatJa"), ctx.get("lrCaveatJa")) if x),
                             priority=5))
    if ctx.get("notifLinesJa"):
        sections.append(_sec("notifications", "Attention Changes / 通知",
                             bullets=ctx["notifLinesJa"], priority=5))
    if ctx.get("backupSafeJa") and not redacted:
        sections.append(_sec("backup_safety", "Backup(状態のみ)", ctx["backupSafeJa"],
                             priority=6, privacy="private_local"))
    if ctx.get("dataQualityJa"):
        # v11.22.0: 外部レビュアーに「どのデータが古いか」を先に伝える(全モード)
        sections.append(_sec("data_quality", "Data Quality / データ鮮度の注意",
                             bullets=list(ctx["dataQualityJa"])[:5], priority=6))
    sections.append(_sec("missing_data", "Missing Evidence / 不足データ",
                         bullets=missing or ["特筆すべき欠落なし(各レイヤーの注意書き参照)"],
                         priority=7))
    sections.append(_sec("opposing_view", "Strongest Opposing View / 最強の反対view",
                         opposing, priority=8))
    instruction = INSTRUCTIONS_JA.get(pack_type, INSTRUCTIONS_JA["daily"])
    sections.append(_sec("prompt_instruction", "Instructions for reviewer",
                         instruction, priority=9))

    if length == "short":
        keep = {"session_brief", "action_priority", "missing_data",
                "opposing_view", "prompt_instruction"}
        sections = [s for s in sections if s["sectionType"] in keep]
        assets = assets[:3]

    pack = {
        "schemaVersion": SCHEMA_VERSION,
        "id": "rp-" + hashlib.md5(f"{pack_type}:{now_iso[:16]}:{privacy_mode}:{length}".encode()).hexdigest()[:10],
        "asOf": now_iso, "appVersion": app_version,
        "packType": pack_type, "audience": "generic_ai", "language": "ja",
        "summaryJa": (ctx.get("commandJa") or "")[:200],
        "ownerQuestionTemplateJa": QUESTION_TEMPLATES_JA.get(pack_type, ""),
        "sections": sections,
        "assets": assets,
        "topRisks": list(ctx.get("topRisksJa") or [])[:5],
        "topOpportunities": list(ctx.get("topOpportunitiesJa") or [])[:4],
        "blockedDecisions": list(ctx.get("blockedJa") or [])[:5],
        "missingEvidence": missing[:6],
        "contradictionList": list(ctx.get("contradictionsJa") or [])[:4],
        "strongestOpposingViewJa": opposing,
        "privacyMode": privacy_mode, "lengthMode": length,
        "generatedLocally": True, "publicLeakSafe": redacted,
        "sourceModules": [s["sectionType"] for s in sections],
        "privacyLabelJa": ("(redactedモード: 個人投資情報は除外済み — ウォッチリスト水準のみ)"
                           if redacted else PRIVACY_LABEL_JA),
        "complianceNote": COMPLIANCE,
    }
    return pack


def render_markdown(pack: Dict[str, Any]) -> str:
    """§8のコピー書式。日本語ファースト・英語ヘッダー・階層固定・重複なし。"""
    L: List[str] = []
    L.append(f"# ARGUS AI Review Pack ({pack['packType']} / {pack.get('lengthMode')} / {pack['privacyMode']})")
    L.append(f"asOf: {pack['asOf']} · v{pack['appVersion']} · {pack['privacyLabelJa']}")
    L.append("")
    L.append("## Owner question")
    L.append(pack["ownerQuestionTemplateJa"])
    if pack["summaryJa"]:
        L.append("")
        L.append("## Current command")
        L.append(pack["summaryJa"])
    if pack["topRisks"]:
        L.append("")
        L.append("## Top risks")
        L += [f"- {x}" for x in pack["topRisks"]]
    if pack["topOpportunities"]:
        L.append("")
        L.append("## Top opportunities")
        L += [f"- {x}" for x in pack["topOpportunities"]]
    if pack["blockedDecisions"]:
        L.append("")
        L.append("## Blocked decisions")
        L += [f"- {x}" for x in pack["blockedDecisions"]]
    for s in sorted(pack["sections"], key=lambda x: x["priority"]):
        if s["sectionType"] in ("missing_data", "opposing_view", "prompt_instruction"):
            continue                               # 末尾固定(階層ルール)
        L.append("")
        L.append(f"## {s['titleJa']}")
        if s["contentJa"]:
            L.append(s["contentJa"])
        L += [f"- {b}" for b in s["bulletsJa"]]
    if pack["assets"]:
        L.append("")
        L.append("## Assets(銘柄別はここに1回だけ集約)")
        for a in pack["assets"]:
            head = f"### {a['symbol']} {a['assetName'] or ''}".rstrip()
            L.append(head + (f" [{a['heldStatus']}/{a['role']}]" if a["heldStatus"] != "unknown" else ""))
            for k, label in (("scenarioSummaryJa", "シナリオ"), ("planSummaryJa", "計画"),
                             ("supplyDemandSummaryJa", "需給"), ("flowSummaryJa", "フロー"),
                             ("positionRiskSummaryJa", "保有リスク"),
                             ("institutionalSummaryJa", "機関"), ("eventSummaryJa", "イベント")):
                if a.get(k):
                    L.append(f"- {label}: {a[k]}")
            for m in a.get("missingEvidenceJa") or []:
                L.append(f"- 不足: {m}")
    for st in ("missing_data", "opposing_view", "prompt_instruction"):
        s = next((x for x in pack["sections"] if x["sectionType"] == st), None)
        if not s:
            continue
        L.append("")
        L.append(f"## {s['titleJa']}")
        if s["contentJa"]:
            L.append(s["contentJa"])
        L += [f"- {b}" for b in s["bulletsJa"]]
    L.append("")
    L.append(f"注意: {pack['complianceNote']}")
    return "\n".join(L)


def public_status(*, now_iso: str) -> Dict[str, Any]:
    """PUBLIC — flags only. Packs are generated and copied ON DEVICE; the server
    never sees, stores, or forwards them."""
    return {
        "schemaVersion": "review-pack-status-v1", "asOf": now_iso,
        "featureEnabled": True,
        "packTypesSupported": list(PACK_TYPES[:5]),
        "generatedLocally": True,
        "serverStoresPacks": False,
        "autoExternalAICall": False,
        "storageMode": "public_redacted",
        "publicLeakSafe": True,
        "noteJa": "レビューパックは端末内で合成され、コピーはオーナーの手で行う。"
                  "サーバーは内容を保存も転送もしない。外部AIへの自動送信もない。",
        "complianceNote": COMPLIANCE,
    }
