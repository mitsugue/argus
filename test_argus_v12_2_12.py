"""ARGUS V12.2.12 — Asset Desk統合の恒久ガード。

個別銘柄情報の一本化(Today/Watchlist分裂の解消)を構造的に守る:
①判断の唯一の正本(domain/assetDecision)をTodayとAsset Deskの両方が通る
②publish副作用はTodayのみ(Asset Desk閲覧で共有ストアを書かない)
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
    # TodayとAsset Deskは同じ組み立てフックを使う
    assert "useAssetIntel({ publish: true })" in cc
    desk = _read("components", "assetDesk", "AssetDeskList.tsx")
    assert "useAssetIntel({ publish: false })" in desk


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


def test_publish_side_effects_gated_to_today():
    intel = _read("hooks", "useAssetIntel.ts")
    for fn in ("publishExposure", "publishActionPriorities", "publishSessionBrief",
               "publishScenarios", "publishPlans", "publishStrategy", "publishFireCore"):
        assert f"if (publish) {fn}(" in intel, fn
    # 旧CommandCenterからpublish呼び出しが消えている(移設済み・二重publishなし)
    cc = _read("routes", "CommandCenter.tsx")
    for fn in ("publishExposure(", "publishScenarios(", "publishPlans(", "publishStrategy("):
        assert fn not in cc, fn


# ── ② ナビ順(route key不変) ────────────────────────────────────────────────

def test_nav_order_and_route_keys():
    nav = _read("components", "NavRail.tsx")
    i_today = nav.index("{ key: 'command',   label: 'Today' }")
    i_desk = nav.index("{ key: 'watchlist', label: 'Asset Desk' }")
    i_core = nav.index("{ key: 'core',      label: 'Positions & Risk' }")
    i_regime = nav.index("{ key: 'regime',    label: 'Market Context' }")
    assert i_today < i_desk < i_core < i_regime
    app = _read("App.tsx")
    assert "'command', 'watchlist', 'core', 'regime'" in app     # overscroll順同期
    assert "watchlist: 'Asset Desk'" in app
    # route keyは不変(localStorage/既存挙動の互換)
    for key in ("'command'", "'watchlist'", "'core'", "'regime'"):
        assert key in nav


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
    assert "focus.nonce" in desk                     # 同一銘柄の再クリックにも反応
    assert "scrollIntoView" in desk
    assert "750" in desk                             # 遅延ロード後のsettle再固定


def test_deep_link_four_sources():
    cc = _read("routes", "CommandCenter.tsx")
    assert "onOpenAsset={(symbol) => onNavigateToAsset?.(symbol)}" in cc
    panel = _read("components", "today", "ArgusTodayPanel.tsx")
    # Today縮約後も、保有注意と推奨アクションの両方からAsset Deskへ遷移できる。
    assert panel.count("onOpenAsset?.(") >= 2
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
    order = ["DECISION", "AI REVIEW / RULE CHECK", "OWNER POSITION", "WHY / DOWNSIDE",
             "FLOW & SUPPLY", "EVENTS & CATALYSTS", "TECHNICAL & ENTRY", "SCENARIOS",
             "RESEARCH & NOTES", "DATA QUALITY"]
    idx = [card.index(f'title="{t}"') for t in order]
    assert idx == sorted(idx), "展開セクションは§7の固定順"


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
    assert "CauseStackCard" in why and "TIMELINE" in why
    flow = _read("components", "assetDesk", "AssetFlowPanel.tsx")
    assert "InstitutionalView" in flow and "逆日歩 未取得" in flow
    # 免責はカード1回
    card = _read("components", "assetDesk", "AssetDecisionCard.tsx")
    assert card.count("売買指示ではありません") == 1


def test_portfolio_wide_features_moved_to_core():
    wl = _read("routes", "Watchlist.tsx")
    assert "WhatIfPanel" not in wl and "ExposureCard" not in wl
    assert "ASSET DESK" in wl
    assert "保有・監視中の個別資産について、現在の判断と根拠を確認します。" in wl
    cp = _read("routes", "CorePortfolio.tsx")
    assert "PortfolioExposureCard" in cp and "WhatIfPanel" in cp


def test_today_exception_summary_replaces_card_list():
    cc = _read("routes", "CommandCenter.tsx")
    assert "AssetCategorySection" not in cc          # 旧全銘柄リストは撤去
    vm = _read("domain", "argusTodayView.ts")
    assert "dedupeHoldings" in vm and ".slice(0, 3)" in vm
    # 集中・高優先度リスクをTodayの少数注意項目へ残す。
    assert "risk.riskType === 'concentration'" in cc
    assert "item.priorityRank === 'P0'" in cc


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
    guide = _read("routes", "Guide.tsx")
    assert f"['v{pkg['version']}'" in guide           # RECENT_UPDATES先頭に当該版
