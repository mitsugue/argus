"""ARGUS V12.2.12 — Asset Desk統合の恒久ガード。

個別銘柄情報の一本化(Today/Watchlist分裂の解消)を構造的に守る:
①判断の唯一の正本(domain/assetDecision)をTodayとAsset Deskの両方が通る
②各primary routeは単一pipelineを所有し、子surfaceは共有snapshotだけを読む
③deep-link(App state経由・4ソース) ④ナビ順(route key不変)
⑤移行完全性(旧カードの主要素がAsset Deskに存在してから旧カード削除)
挙動そのもの(AI主判定12ケース等)は web/scripts/asset-desk.test.cjs(lint連結)。
"""
import json
import os

WEB = os.path.join(os.path.dirname(__file__), "web", "src")


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── ① 判断の唯一の正本 ───────────────────────────────────────────────────────

def test_single_source_of_judgment():
    dec = _read("domain", "assetDecision.ts")
    # AI主条件(live/partial + fresh/persisted)は正本にのみ存在
    assert "'live'" in dec and "'partial'" in dec
    assert "'fresh'" in dec and "'persisted'" in dec
    intel = _read("hooks", "useAssetIntel.ts")
    assert "mergeAiPrimary" in intel
    # 旧CommandCenterのインラインAI優先マージが復活していない
    cc = _read("routes", "CommandCenter.tsx")
    assert "aiFinalAction" not in cc
    assert "const aiPrimary" not in cc
    # TodayとHoldingsは同じ組み立てフックを使い、Asset Deskはpropだけを読む。
    assert "useAssetIntel({ publish: true, assets: assetsApi.assets })" in cc
    desk = _read("components", "assetDesk", "AssetDeskList.tsx")
    assert "useAssetIntel(" not in desk
    holdings = _read("routes", "Watchlist.tsx")
    assert holdings.count("useAssetIntel(") == 1
    assert "useAssetIntel({ publish: true, assets })" in holdings


def test_ai_honesty_vocabulary():
    dec = _read("domain", "assetDecision.ts")
    # RULE TEMPORARYの正確な理由+次回実行予定は構造的に必ず埋まる
    assert "RULE TEMPORARY" in dec
    assert "16:05" in dec
    # v12.2.12是正: 16:05の案内は実行を保証できる状態のみ(状態別の正確な文言)
    assert "無効化中" in dec                       # disabled=約束しない
    assert "no_cached_result" in dec               # 未実行のみ16:05を案内
    assert "取得できません" in dec                  # mock/取得不能=約束しない
    # AI理由欠落時にルール理由をAI文章として見せない(source追跡)
    assert "aiReasonJa" in dec
    review = _read("components", "assetDesk", "AssetAIReview.tsx")
    assert "reasonMissing" in review
    assert "ルール理由で代用はしません" in review
    # AI欄は無言で消えない(unavailable時の理由+次回)
    assert "unavailableReasonJa" in review and "nextRunJa" in review


def test_publish_side_effects_gated_to_active_pipeline():
    intel = _read("hooks", "useAssetIntel.ts")
    for fn in ("publishExposure", "publishActionPriorities", "publishSessionBrief",
               "publishScenarios", "publishPlans", "publishStrategy", "publishFireCore"):
        assert f"if (publish) {fn}(" in intel, fn
    # routeから直接publishせず、共有hook内だけで制御する。
    cc = _read("routes", "CommandCenter.tsx")
    for fn in ("publishExposure(", "publishScenarios(", "publishPlans(", "publishStrategy("):
        assert fn not in cc, fn
    for parts in (("components", "assetDesk", "AssetDeskList.tsx"),
                  ("routes", "CorePortfolio.tsx")):
        assert "useAssetIntel(" not in _read(*parts)


# ── ② ナビ順(route key不変) ────────────────────────────────────────────────

def test_nav_order_and_route_keys():
    nav = _read("components", "NavRail.tsx")
    navigation = _read("navigation.ts")
    i_today = navigation.index("route: 'command'")
    i_desk = navigation.index("route: 'watchlist'")
    i_notifications = navigation.index("route: 'notifications'")
    i_settings = navigation.index("route: 'settings'")
    assert i_today < i_desk < i_notifications < i_settings
    app = _read("App.tsx")
    assert "PRIMARY_NAVIGATION" in app     # overscroll順同期
    assert "routeLabel" in app
    # Lean v13 has exactly four primary owner routes; market remains contextual.
    for key in ("'command'", "'watchlist'", "'notifications'", "'settings'"):
        assert key in navigation
    assert "'regime'" not in navigation
    assert "desktopLabel: 'Holdings / Watchlist'" in navigation
    assert "'#positions'" not in navigation
    assert "'#market'" not in navigation
    primary_block = navigation.split("export const NAVIGATION", 1)[1].split("] as const", 1)[0]
    assert primary_block.count("route: '") == 4
    assert "PRIMARY_NAVIGATION" in nav


# ── ③ deep-link(App state経由・4ソース) ─────────────────────────────────────

def test_deep_link_uses_app_state_not_only_event():
    app = _read("App.tsx")
    assert "AssetFocusIntent" in app
    assert "setAssetFocus" in app and "nonce: Date.now()" in app
    assert "onNavigateToAsset={navigateToAsset}" in app
    # 意図はlocalStorage保存しない
    assert "localStorage" not in app.split("navigateToAsset")[1].split("};")[0]
    desk = _read("components", "assetDesk", "AssetDeskList.tsx")
    assert "AssetFocusIntent" in desk
    assert "activeFocus.nonce" in desk               # 同一銘柄の再クリックにも反応
    assert "lastNonce.current" in desk
    assert "scrollIntoView" in desk
    assert "750" in desk                             # 遅延ロード後のsettle再固定


def test_today_market_view_has_no_holding_deep_link():
    cc = _read("routes", "CommandCenter.tsx")
    assert "onOpenAsset={(symbol) => onNavigateToAsset?.(symbol)}" not in cc
    panel = _read("components", "today", "ArgusTodayPanel.tsx")
    # Todayの4/7等は市場表示であり、保有カードや保有警告から独立する。
    # 個別銘柄の確認はAsset Desk、保有全体はPositions & Riskへ集約する。
    assert "onOpenAsset?.(" not in panel
    assert "保有確認" not in panel
    assert "view.recommendations" not in panel
    # 未登録銘柄は捏造スクロールしない
    desk = _read("components", "assetDesk", "AssetDeskList.tsx")
    assert "未登録銘柄" in desk


# ── ④ 移行完全性(マトリクス裏付け — 旧カードの主要素がAsset Deskに存在) ────────

def test_migration_matrix_doc_exists():
    doc = open(os.path.join(os.path.dirname(__file__), "docs",
                            "ARGUS_V12_2_12_ASSET_DESK_MATRIX.md"), encoding="utf-8").read()
    assert "表示情報の完全性マトリクス" in doc


def test_desk_sections_fixed_order():
    card = _read("components", "assetDesk", "AssetDecisionCard.tsx")
    order = ["'decision'", "'chart'", "'evidence'", "'position'"]
    idx = [card.index(f"id: {tab}") for tab in order]
    assert idx == sorted(idx), "決定優先タブは固定順"
    assert card.count("id: '") == 4
    # 移行済みの各詳細機能は削除せず、該当タブ配下で遅延表示する。
    for panel in ("AssetDecisionDetails", "ChartIntelligencePanel", "AssetWhyPanel",
                  "AssetFlowPanel", "AssetPositionPanel", "AssetScenarioPanel",
                  "AssetAIReview", "AssetResearchPanel", "AssetDataQuality"):
        assert f"<{panel}" in card


def test_migrated_features_present():
    # 旧Watchlist行の機能
    scout = _read("components", "assetDesk", "AssetEntryScout.tsx")
    assert "/api/argus/entry-scout" in scout
    assert "押した時だけ" in scout                    # オンデマンドのみ(自動AIなし)
    research = _read("components", "assetDesk", "AssetResearchPanel.tsx")
    assert "saveNote" in research and "buildReviewPackMarkdown" in research
    assert "OsintDeepDive" in research and "decisionHistoryFor" in research
    pos = _read("components", "assetDesk", "AssetPositionPanel.tsx")
    assert "onUpdateHolding" in pos and "端末内のみ" in pos
    # 旧Todayカードのセクション
    why = _read("components", "assetDesk", "AssetWhyPanel.tsx")
    assert "TIMELINE" in why and why.count("<AiExplanationBlock") == 1
    assert "CauseStackCard" not in why
    flow = _read("components", "assetDesk", "AssetFlowPanel.tsx")
    assert "InstitutionalView" in flow and "逆日歩 未取得" in flow
    # 免責はカードごとに繰り返さず、ページのDownside Watchで一度だけ示す。
    card = _read("components", "assetDesk", "AssetDecisionCard.tsx")
    downside = _read("components", "dashboard", "DownsideIncidentCard.tsx")
    assert "判断支援のみ" not in card
    assert downside.count("決定支援のみ・自動売買は行いません。") == 1


def test_portfolio_wide_features_moved_to_core():
    wl = _read("routes", "Watchlist.tsx")
    assert "WhatIfPanel" not in wl and "ExposureCard" not in wl
    assert "HOLDINGS / WATCHLIST" in wl
    assert "保有と監視銘柄を、今日確認する順にまとめます。" in wl
    assert "portfolioOpen && <CorePortfolio assetsApi={assetsApi}" in wl
    cp = _read("routes", "CorePortfolio.tsx")
    assert "PortfolioExposureCard" in cp and "WhatIfPanel" not in cp
    # Owner editing remains contextual; no replacement global framework is added.
    assert "FireCoreCard" in cp
    for capability in ("TradeJournalCard", "EntityProfileEditor", "Layer2BSyncCard"):
        assert capability in wl


def test_today_exception_summary_replaces_card_list():
    cc = _read("routes", "CommandCenter.tsx")
    assert "AssetCategorySection" not in cc          # 旧全銘柄リストは撤去
    vm = _read("domain", "argusTodayView.ts")
    assert "dedupeHoldings" in vm and ".slice(0, 3)" in vm
    # 集中・高優先度リスクは市場評価へ混ぜず、保有専用画面へ分離する。
    assert "risk.riskType === 'concentration'" not in cc
    assert "item.priorityRank === 'P0'" not in cc


def test_desk_default_sort_deterministic():
    dom = _read("domain", "assetDesk.ts")
    assert "deskRank" in dom and "sortDesk" in dom
    assert "symbol" in dom                            # 同順位はsymbolで決定論
    # 執行語なし(新規UI)
    for f in ("AssetDecisionSummary.tsx", "AssetDecisionDetails.tsx", "AssetAIReview.tsx"):
        src = _read("components", "assetDesk", f)
        for banned in ("今すぐ買", "今すぐ売", "注文を出"):
            assert banned not in src, (f, banned)


# ── ⑤ バージョン整合(動的 — 固定値ピンなし) ─────────────────────────────────

def test_version_consistency_v12_2_12():
    pkg = json.load(open(os.path.join(os.path.dirname(__file__), "web", "package.json")))
    lock = json.load(open(os.path.join(os.path.dirname(__file__), "web", "package-lock.json")))
    assert pkg["version"] == lock["version"] == lock["packages"][""]["version"]
    assert not os.path.exists(os.path.join(WEB, "routes", "Guide.tsx"))
    manifest = open(os.path.join(os.path.dirname(__file__), "docs",
                                 "ARGUS_B2A_DEFERRED_UI_MANIFEST.md"),
                    encoding="utf-8").read()
    assert "Round 1 deletion completed" in manifest
