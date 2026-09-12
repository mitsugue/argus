# v13.6.0 引き継ぎ文書（13.5 系の到達点・2026-09-08）

> **現行の範囲・停止条件（2026-09-09更新）**：名称変更と13.5残件を本番確認まで完了し、
> その完成版から13.6へ進む。**13.6の本番受入で停止**する。13.7の調査・実装・試作・PR・配信は、
> 来週以降のオーナーによる明示的な再開指示まで禁止。日付の到来や13.6完了では自動着手しない。
> 現行の詳細要件は [v13.6製品要件・受入台帳](V13_6_REQUIREMENTS.md)。
> 日本株分析の改善と実データの過去チャート重ね描きを13.6初期工程に置く。
> 以下の旧時点の記録と現況が異なる場合は、最新の13.5検証台帳を優先する。


v13.6.0（統合 AI と画面リニューアル、Codex + Astra）に引き継ぐための一枚。13.5 系は
「実データを取得・保存・判断・端末表示する」ことを本番で通し、判断の勝手な合格や見えない
警告を排した状態で終える。新しい統合 AI・新予測エンジンはここには入っていない。

> 2026-09-09 Codex開始後の更新は [13.5系検証台帳](V13_5_CODEX_STATUS.md) を参照。
> 立花認証と海外フローは開始時点で復旧を確認。以下の旧記録を現在の障害と取り違えない。

## 1. 本番の識別情報（この文書の時点）

| 面 | 識別子 | 確認方法 |
|---|---|---|
| バックエンド | Render `argus-backend-3j2m`、`/healthz` の `backendVersion` / `buildSha` | `curl https://argus-backend-3j2m.onrender.com/healthz` |
| フロント | GitHub Pages `https://mitsugue.github.io/argus/`、`__ARGUS_VERSION__` | ページソースの先頭 8KB |
| 製品バージョン | `product-version.json` / `backend-version.json` / `web/package.json` の三点同期 | `test_argus_deploy_scope.py::test_no_stale_version_pin_survives_a_bump` |
| 配信経路 | 製品 PR → `deploy-pages.yml`（証明書・readiness・acceptance）／Recovery PR → Render 自動デプロイ + `backend-warm-after-deploy.yml` | Actions |

到達バージョンと確認結果は末尾「7. 完了時の本番確認」に記す。

## 2. 未解決事項（v13.6.0 で扱うもの）

1. **BUY は構造的に無効のまま。** 反転軸 BUY の検証は 2026-09-07 に FAIL
   （`docs/REVERSAL_BUY_VALIDATION.md`）。有効化には同ドキュメント §7 の計画（条件細分化、
   サンプル延長、モメンタム基準、月次 3 回 PASS）とコードレビューでのレジストリ固定が必要。
2. **予測は「類似局面の頻度」で、検証済み確率ではない。** walk-forward BSS ≈ −0.003〜+0.003。
   `probability-eligibility-v1` の全条件を満たすまで確率表示はしない。
3. **信用需給（二市場信用残）は週次の公式 xls を取り込む運用。** `jpx-credit-weekly.yml`
   （水・木 19:30 JST）が JPX の週次ファイルを取得し Market Ledger に入れる。未公表週は
   gap として報告するのみ。2026-07-17 / 07-24 は JPX 側に公表ファイルが無い。
4. **ニュース取込は 1 プロセス内の逐次処理。** 読み出しはロックを待たない（Recovery PR-7、backend d614c30d）が、
   1 サイクル内の AI 解析は逐次で、バックフィル時は数十分かかる。並列化は未実施。
5. **Recovery ゲート（checkpoint-v2）の測定契約。** allocator の絶対上限は「使用中バイト」と
   「復元元サイズ相対」に分けた（`docs/checkpoint-v2-mapping-attribution.md` v13.5.64）。
   本番スナップショットが今後さらに大きくなれば `allocatorAnonymousBytes`（256 MiB）に
   当たる可能性がある。上限を触る前に同ドキュメントの実測表を更新すること。
6. **Recovery マージは Pages を走らせない。** 証明書を持たないため。代わりに
   `backend-warm-after-deploy.yml` が Render の反映を待ってウォームする。
7. **コスト方針の使用台帳は永続ルートへ write-through**（Recovery PR-7、backend d614c30d）。
   ジャーナルスナップショットが古くても再デプロイ後に union 復元する。並行実行は予約行で防ぐ。
   write-through は AI 実行の予約・確定・スキップ記録の時点で書くため、再起動後に AI 試行が
   一度も無いうちは `ledgerDurability.lastPersistAt` が null のまま（実行回数はジャーナル側で保持）。
8. **Tachibana（立花）ライブは読み取り専用シャドー。** 本番の秘密鍵ファイルの形式問題
   （`AUTH_KEY_PARSE_FAILED`）はオーナー側の再アップロード待ち。
9. **EC2 ブリッジ（moomoo）は US のみ。** JP はブリッジ対象外（J-Quants / Tachibana）。
10. **GitHub の schedule 起動が遅延・欠落する。** 2026-09-08 は macro-event-analysis の 00:35Z / 02:35Z が
    起動せず、market-watch は 02:00Z が 02:09Z 起動。定期実行の証跡は起動した枠で取る。生成の
    追跡は `generateRun`（running/done/failed/interrupted）で、workflow 側のタイムアウト（600 s）後も残る。
11. **market-watch の intel-collect がコールド起動直後に 90 s で時間切れになる。** 暖機
    （`backend-warm-after-deploy.yml`）が先に走れば起きない。恒久策は v13.6.0 側で検討。
12. **製品全体で人名由来の名称・識別子を廃止する。** 総称は「日本株分析エンジン」/
    `jp_market_engine`。API・保存データ・配布物を含む移行と追加検証候補は
    [正式要件](JP_MARKET_ENGINE_REQUIREMENTS.md)を参照。表示だけの修正では完了としない。

## 3. 利用中のデータ源

| データ | 供給元 | 頻度 / 遅延 | 状態の見方 |
|---|---|---|---|
| 日本株 日足・週足 | J-Quants V2（Standard、`JQUANTS_API_KEY`） | 日次、16:30 JST 更新、完了セッション後 15 分再確認 | `decision-evidence` の `marketTruth.status` |
| 米国株 日足 | Twelve Data（BASIC、9 銘柄 warm、閉場時 6 時間ごと cold fill） | 日次 | `data-quality/status` |
| 指数 ^N225 / ^VIX / SPY | Yahoo v8 chart（OHLCV、PIT 付与） | 日次 | `marketView.sourceStatus` |
| 二市場信用残（D01） | JPX 公式週次 xls → `ops/imports/*.csv`（〜2026-07-10）+ Market Ledger 取込（それ以降） | 週次、金曜締め・水曜公表 | Today「方式と根拠の詳細」の 信用残 行 |
| 1570 信用倍率（D02） | J-Quants 週次 | 週次 | `marketView.projection.families.D02` |
| 海外投資家フロー（D05） | 台帳（現在 missing） | 週次 | `sourceStatus.foreignFlow` |
| VIX（D06） | Yahoo ^VIX（FRED は鍵未設定） | 日次 | `sourceIssues` |
| 決算（D07） | J-Quants fins/summary | 随時 | `families.D07` |
| 為替・金利 | `/api/argus/rates`（FRED / Yahoo） | 日次 | Today MACRO 行 |
| イベント台帳 | `argus_important_events`（BLS/FOMC/BOJ/財務省入札など、31 日先） | 2 時間ごと更新 | `/api/argus/important-events` |
| ニュース | Gmail 購読メール（日経・BOJ・OFAC 等、認証送信元のみ） | 75 秒ごと取込 | `/api/argus/news-intake/health` |
| 仮想通貨 | CoinGecko（SYMBOL_TO_COINGECKO） | 準リアルタイム | Holdings のバッジ |
| 投信 | 投信総合ライブラリー | 日次 | 同上 |

## 4. 利用中の AI モデルと予算

| 用途 | モデル（既定） | 環境変数 | 予算・上限 |
|---|---|---|---|
| イベント事前/事後シナリオ | `gpt-6-astra`（不可時のみ `gpt-5.6-terra` に代替、両方を記録） | `ARGUS_OPENAI_MODEL_EVENT` / `_FALLBACK` | 1 日 6 回、$0.08/回見積、イベント枠予備 $0.50 |
| ニュース解析（news_intel） | `gpt-5.6-terra`（難案件のみ `gpt-5.6-sol` へ 1 回昇格） | `OPENAI_MODEL` / `ARGUS_OPENAI_SOL_MODEL` | SCHEDULED 日次 $2.00 − 予備 $0.50 |
| 見出し翻訳 | Gemini（`GEMINI_API_KEY`） | — | 同上の枠 |
| 単価（公式・2026-09-07 参照） | astra $10/$1(cached)/$50、terra $2/$0.2/$12、sol $4/$0.4/$20 per 1M | `_AI_PRICING` | `OPENAI_PRICE_*` で上書き可 |
| 全体 | 日次 $5、月次 $80、緊急予備 $2（推定値のハード停止） | `AI_DAILY_BUDGET_USD` 等 | `/api/argus/ai-cost`（admin） |

方針モード: `SCHEDULED_AI`（`ARGUS_EVENT_AI_OPT_IN=1`）。公開ステータス
`/api/argus/cost-policy` に 鍵の有無・枠予算・実行回数・直近実行・直近見送り理由・台帳の
耐久性 を分けて出す。

## 5. 既存の判断仕様（SDA v2、変更なし）

- 5 アクション: BUY / HOLD / WAIT / REDUCE / EXIT。BUY は ①リスク制約なし ②需給・トレンドの
  反転状態が反転初期・自律反発・回復試験・上昇確認のいずれかで **検証済み** ③検証済み買い成立
  レジストリ（`VERIFIED_JP_MARKET_ENGINE_BUY_ARTIFACTS`、現在は空）の本番採用 ④保有側の追加許可。
- 確度 = min(基準値 {BUY 70, HOLD 60, WAIT 45, REDUCE 70, EXIT 80}%, riskKernel 上限)。
  データ不足時は 25% 固定。
- REDUCE は保有の含み損 −25% 以下（`positionExposure`）で `REDUCE_RISK`。
- WAIT の 3 種: データ不足（評価未了）／リスク制約／買い条件不成立。
- 判断の正本は `decision-evidence`（8 銘柄/要求、端末側は 8 件ずつ全登録銘柄）。
- MARKET SIGNALS（7 条件、日本固有）は市場観であり行動権限を持たない
  （`actionAuthority=false`）。米国選択時は「日本市場の値」と明示。

## 6. 既存の予測仕様（変更なし）

- チャート予測: `argus_today_intelligence`（today-replay-calibration-v3-market-conditioned）。
  10 年日足の類似局面 kNN（trend20 / momentum5 / atrPct / closeLocation / volumeRatio）に、
  日本は 信用倍率・売り残高・VIX 水準・VIX 10 日変化・対 SPY 相対力、米国は VIX 水準・
  VIX 10 日変化・対 SPY 相対力 で条件付け（知識ラグ付き PIT 結合、結合窓 信用 45 日・VIX 10 日）。
  出力は 1/5/20 営業日先の方向の **出現頻度**、ATR14 帯、支持抵抗。
- 反転/下方軸: `jp_market_engine.build_reversal_engine`（^N225 と ^VIX の MACD/SAR/BB/RSI）、
  状態 REVERSAL_EARLY / TECHNICAL_REBOUND / RECOVERY_TEST / CONFIRMED_ADVANCE / FALSE_RALLY /
  MIXED。行動権限なし。
- 対応表: `docs/forecast-method-jp-us.md`。BUY 検証: `docs/REVERSAL_BUY_VALIDATION.md`。

## 7. 完了時の本番確認（記入）

完了報告の各項目（配信識別子・実画面・定期実行での生成→保存→表示・再デプロイ後の台帳・
取込中のニュース応答）は最終報告に記載し、ここには識別子のみを残す。

- バックエンド: Render `argus-backend-3j2m` = 13.5.66 `87bf4ec2`（2026-09-08 04:0xZ 反映、PR #309）。
  直前の Recovery PR-7 は 13.5.65 `d614c30d`（02:58Z）。
- フロント: GitHub Pages = 13.5.66（`__ARGUS_VERSION__="13.5.66"`、バンドル `assets/index-Bu-stlo0.js`、
  Pages run 34185049990: scope → acceptance-runtime-admission → build → readiness → deploy →
  candidate-identity → business-snapshot-trigger → seed-warm-profile → business-snapshot-acceptance →
  public-acceptance が全て success、04:08Z 完了）。
- 本番の信用需給結合（13.5.66、04:07Z）: 1306/1321 は `credit` joined（periodEnd 2026-08-28、
  availableFrom 2026-09-02、age 10 d / 45 d）、`vix` 9/3、`us` 9/4。QQQ は credit not_applicable、
  SPY は credit / us not_applicable。特徴量に `creditRatio` `creditShortTn` が復帰。

## 2026-09-12 旧AI費用集計の復元修正（13.5残件）

旧 `/api/argus/ai-cost` は中核の `cost-policy` と別のメモリ内集計であり、
復元に必要なimportの欠落と例外の無視、復元前に発生した利用分を落とすmax合成、
日次ワークフロー前の再起動で記録を失う問題があった。

`costPolicy.legacyAiCost` に `argus-ai-cost-accounting-v1` を保存する。
JSTの日別・起動単位の単調な累計を、既存の費用ファイルの原子的保存と
暗号化チェックポイントへ接続する。同じ起動の古いスナップショットは前方の
累計へ統合し、独立した起動分は加算する。直近20/50件の表示枠は累計に影響しない。
新版の保護APIにも同じ保存形式を含め、日次ワークフロー経由の再取込みで重複計上しない。

旧形式の保存済み月次・日次総額は、報告値と出典ハッシュを保持する。
移行前の全履歴を再構成した総額とは表示しない。不明な過去のトークン・モデル・
重複関係を推定で補わない。旧集計と中核の費用台帳を単純加算しない。
旧形式の月次読取りは、保存済みの現行月と再取込み対象が新形式へ移行したことを
確認するまで必要であり、撤去時には別途移行証跡を残す。旧版へ戻す場合も新形式を
保持できる版を使い、最新の費用保存原本を保全する。

この項目は13.5の保存・復元修正で、13.7のコスト最適化ではない。
13.6の機能別トークン・実応答モデル等の全呼出し履歴は別途接続・受入が必要。
本修正の実装・検査と本番配信・再起動後の確認は区別して受入台帳に記録する。
13.6本番受入後の全機能総点検・不具合の再検証までで停止し、13.7は明示再開まで保留する。
