# V12.2.12 Asset Desk — 表示情報の完全性マトリクス(§14)

目的: Today(UnifiedAssetCard)とWatchlist(AssetStrategySection)に分裂していた個別銘柄情報を
Asset Desk(route key `watchlist` 不変)へ統合するにあたり、**旧UIの全項目が新UIのどこに
存在するか**を先に確定する。ここで「Asset Desk配置」が埋まらない項目がある限り、
Todayの旧カード削除は行わない(§25)。

判断の正本: `web/src/domain/assetDecision.ts`(AI優先マージ+RULE TEMPORARY理由) —
Today/Asset Deskの両方がここを通る。データ組み立ての正本: `web/src/hooks/useAssetIntel.ts`
(旧CommandCenterのuseMemo群を移設・publishはTodayのみ=`publish:true`)。

凡例: ◯=そのまま移設 / ≒=同一データ・表示語彙のみ調整 / 新=v12.2.12新設

## 1. 閉じたカード(collapsed)

| 項目 | 旧Today | 旧Watchlist | Asset Desk配置 | 状態 |
|---|---|---|---|---|
| 保有バッジ(保有/WATCH) | uac-held「保有」 | hpチップ | ヘッダ行 HELD/WATCH | ◯ |
| コード+社名(jpDisplay規則) | uac-sym/name | asset-row__sym/name | ヘッダ行 | ◯ |
| 市場(JP/US/CRYPTO/FUND) | グループ見出し | genreグループ | ヘッダ行チップ+グループ | ◯ |
| 価格+前日比 | uac-price/chg | fmtPrice+SignedValue | ヘッダ行(fmtPrice採用・mockは—) | ◯ |
| データ鮮度(live/delayed Xw/manual/mock) | —(lastUpdateのみ) | freshnessOf(strat) | ヘッダ行(freshnessOf移設) | ◯ |
| as-of(最終更新) | uac-upd 最終更新 | updated Xm ago | ヘッダ行 | ◯ |
| 主アクション(PRIMARY_EN+SignalGauge) | uac-cmd+gauge | resolveSignal labelJa/En+⊘ | ヘッダ行(PRIMARY_EN+gauge採用・sig詳細はDECISION) | ◯ |
| AI PRIMARY / RULE TEMPORARY | uac-jsrc AI/ルール暫定 | (なし=常にルール主) | ヘッダ行 sourceTagEn(assetDecision) | 新 |
| 判断理由1行 | causeOneLineJa | (展開のみ) | ヘッダ行(decision.reasonJa 1行) | ≒ |
| 確度 | (展開のみ) | asset-row__meta % | ヘッダ行 | ◯ |
| リスク(low/med/high) | (色のみ) | asset-row__meta risk | ヘッダ行 | ◯ |
| 優先度(P0〜) | ACTION PRIORITYセクション | (なし) | ヘッダ行チップ(apx.priorityRank) | ◯ |
| 次の確認条件(短) | NEXT(展開) | What to wait for(展開) | ヘッダ行1行(nextConditionJa) | ◯ |
| 警告 最大2(incident/override/hp) | uac--held+EXIT系tone | ⚠OVERRIDE_LABEL_JA+hp | ヘッダ行 警告チップ≤2 | ◯ |
| イベントタグ 最大2(linkedTagJa) | uac-linked | (なし) | ヘッダ行 イベントチップ≤2 | ◯ |
| 新規/追加/既存 permissions | uac-l3 | ⊘のみ | DECISION内(1行) | ◯ |

## 2. 展開セクション(順序は§7固定)

### DECISION
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| 単一の構え(pst: stanceJa+確度+cap+理由) | PRIMARY STANCE | — | ◯ |
| ARGUS VIEW(argusViewJa+overallJa+AIバッジ) | ARGUS VIEW | — | ◯ |
| Strategy/Why/What to wait for/What changes it | — | asset-detail__grid | ◯ |
| POSITION PLAN一式(stance/証拠/summary/役割/入る条件/監視/利確検討/やらないこと/無効化/次の確認/シナリオ連動) | POSITION PLAN | — | ◯ |
| ACTION PRIORITY(rank+label+why+変化条件) | ACTION PRIORITY | — | ◯ |
| NEXT(nextJa) | NEXT | — | ◯ |
| 免責(カード1回) | 末尾免責 | scenario disc | ◯ |

### AI REVIEW / RULE CHECK
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| AI提案(aiFinalAction+確信度+aiView+理由+redFlags+実行age) | (マージ済みのみ) | asset-ai(第二意見) | ◯(decision.ai — AI理由欠落時はreasonMissing表示・ルール理由を代用しない) |
| RULE TEMPORARY理由+次回実行予定 | aiStateJa(ページ単位) | — | 新(decision.ai.unavailableReasonJa+nextRunJa — AI欄を無言で消さない) |
| ルール判定原文(action+理由+次条件)との相違 | — | — | 新(decision.rule.disagreementJa) |

### OWNER POSITION
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| 保有中 数量/取得/損益%/比率/テーマ | POSITION/EXPOSURE(pn) | 評価/損益(valueHolding) | ◯ |
| 買い増し余地(readiness+why) | POSITION/EXPOSURE | — | ◯ |
| 数量/平均取得単価の入力(localStorageのみ) | — | asset-hold input | ◯ |
| 保有者向け構え(hp: label+pl+reason) | — | asset-detail__holder | ◯ |

### WHY / DOWNSIDE
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| WHY DOWN?(changePct/Rule→Override/causeBuckets/reasonJa/やってはいけない/確認条件/欠損データ) | (DownsideIncidentCardページ上部) | asset-detail__downside | ◯ |
| 原因1行(causeOneLineJa) | ヘッダ | — | ◯(閉じたカードへ) |
| TIMELINE(値動き) | 詳細データ内 | — | ◯ |
| CAUSE(原因スライス%) | 詳細データ内 | — | ◯ |
| 原因スタック(CauseStackCard) | 詳細データ内 | — | ◯ |
| 今の動きを調べる(AiExplanationBlock即時調査) | 今の動きを調べる | — | ◯ |

### FLOW & SUPPLY
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| 需給ランク+状態+直接性+確度+why+生数値(信用買残/売残/貸借倍率/日数/逆日歩未取得) | SUPPLY/DEMAND(sdg) | — | ◯ |
| 大口純流入率(bigFlowRatio) | — | Big-money flow行 | ◯ |
| 機関ビュー(InstitutionalView) | カード内 | — | ◯ |

### EVENTS & CATALYSTS
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| 関連イベントタグ全件(linkedTagJa) | uac-foot | — | ◯(閉じ=2件・展開=全件) |
| Catalyst(catalystNoteJa) | — | asset-detail__grid Catalyst | ◯ |

### TECHNICAL & ENTRY(オンデマンドのみ・自動実行なし)
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| エントリー診断(Entry Scout一式: call/narrative/stance/score/track/reasons/フロー推定/材料/metrics/gaps/note) | — | scout(⚡ボタン) | ◯ |

### SCENARIOS
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| 条件付き分岐(scn: dominant/summary/cases帯/無効化/次の確認/何が変われば) | SCENARIOS | — | ◯ |
| ルールシナリオ確率(strat.scenarios+horizon+免責) | — | asset-scen | ◯ |

### RESEARCH & NOTES
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| リサーチメモ(getNote/saveNote・端末内/同期) | — | asset-detail__note | ◯ |
| AI相談(copyLlmConsult モート起点プロンプト) | — | 🧠 AI相談 | ◯ |
| この銘柄をAIに相談(Review Pack フル/短縮/redacted) | AskAIAsset | — | ◯ |
| OSINT Deep Dive | OsintDeepDive | — | ◯ |
| DECISION HISTORY(過去判断+その後+pastPatternLine) | DECISION HISTORY | — | ◯ |
| Remove(登録解除) | — | Removeボタン | ◯ |

### DATA QUALITY
| 項目 | 旧Today | 旧Watchlist | 状態 |
|---|---|---|---|
| Data limitations(strat.dataLimitations) | — | asset-detail__limits | ◯ |
| AI鮮度バッジ+RULE+GPT+GEMINIソース行 | ARGUS VIEW内 | — | ◯(DECISION内に併記) |

## 3. ページ/リスト単位

| 項目 | 旧配置 | 新配置 | 状態 |
|---|---|---|---|
| AIReviewカード(ページ全体AI総評) | Watchlist上部 | Asset Desk上部 | ◯ |
| DownsideIncidentCard | Watchlist上部 | Asset Desk上部 | ◯ |
| 校正行(cal.basisJa) | AssetStrategySection | Asset Deskリスト上 | ◯ |
| フィルタ(all/risk/held) | AssetStrategySection | Asset Desk(+並び: 優先順/手動順) | ◯ |
| DnD並べ替え | AssetStrategySection | 手動順モードのみ有効(優先順は§8決定論ソート) | ≒ |
| rescan/+ Add Asset/AddAssetModal | Watchlistツールバー | Asset Deskツールバー | ◯ |
| EntityProfileEditor/TradeJournalCard/ProHandoffButton | Watchlist下部 | Asset Desk下部 | ◯ |
| **Portfolio Exposure(ExposureCard)** | AssetStrategySection | **Positions & Risk(CorePortfolio)へ移動** | ◯計算/localStorage不変 |
| **What-ifシミュレーション(WhatIfPanel)** | AssetStrategySection | **Positions & Riskへ移動** | ◯同上 |
| Todayの銘柄カード全リスト(AssetCategorySection×3) | Today RESEARCH & SIGNALS | 例外サマリー+Asset Deskへの導線に置換(判断・件数はuseAssetIntel経由で同一) | ≒ |
| OWNER CRITICAL(保有×EXIT/DEFEND) | Todayトップ | Todayに残置+クリックでAsset Deskの当該銘柄へ | ◯ |

## 4. 判断の一致(§5)

- 主判断のaction/理由/確度/judgmentSourceは `mergeAiPrimary()`(assetDecision.ts)の出力のみを使用。
  旧CommandCenterインラインマージは削除済み(同一ロジックを移設・aiPrimary条件は
  status live|partial かつ freshness fresh|persisted で不変)。
- AI理由欠落時は `aiReasonJa=null` — ルール理由をAI文章として表示しない(reasonMissing表示)。
- AI非表示時は必ず「RULE TEMPORARY — 正確な理由+次回実行予定(平日16:05)」を表示。
