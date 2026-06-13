# ARGUS 開発引き継ぎ（HANDOFF）— v10.19.0 時点

> **新しいAIアシスタントへ:** これは ARGUS プロジェクトの引き継ぎ書です。開発を再開する前に
> このファイルを最後まで読み、下の「最初にやること」を実行して現状を確認してから作業を始めてください。
> セクション「🔒 セキュリティ制約」と「⚠️ 正確性の絶対制約」は**必ず守る**こと。最終更新: v10.19.0。

---

## 0-b. 2026-06-11の検証待ち（スマホ/クラウドセッション向け引き継ぎ）

- **16:05 JSTの台帳ラン**(GitHub cron遅延で数時間ずれる可能性): 初のledger-v3記録+AI永続化初回。
  検証: ① Actions prediction-ledger が success ② raw `ledger/days/2026-06-11.json` の engineVersion=ledger-v3
  ③ raw `ledger/ai/latest.json` が存在 ④ GET /api/argus/ai-judgment が live(これで「not run yet」恒久解消)
- **22:00 JST**: 夜ダイジェストの「定時配信」初回テスト(ntfy Delayヘッダ方式。06:49/19:49発火→定時配信)
- **22:30 JST〜**: USセッションで15秒価格更新の実地検証(ブリッジ15秒化はAWS反映済み・サーバー側計測で確認済み)
- **翌朝08:30**: 朝ダイジェスト定時テスト
- ユーザー操作待ち: Finnhubキー(任意)・Vercel旧プロジェクト削除確認・端末統合(スマホ→Mac→プレビューの復元手順)
- ~~次の開発フェーズ: Close Pin Intraday Ledger~~ → **v10.11.0で実装済み**(下記)
- **cron-reliability-v1 導入済み**: GitHub cronは時間単位で遅延するため、台帳ランの正トリガーは
  EC2のcron(07:05 UTC)→workflow_dispatch(bridge/trigger_ledger.sh、fine-grained PAT使用)。
  workflowに二重実行ガード(gateジョブ: 当日記録済み+schedule起動なら即終了)。
  **ユーザー操作待ち: PAT発行+EC2セットアップ(スクリプト冒頭の手順3行)**。
  morning-digestはDelayヘッダで2h11mの遅延まで吸収(超過時は即時送信=遅着)。digestの外部トリガー化は
  二重通知防止の設計が必要なため見送り中(やるならGH scheduleの削除とセット)

- v10.11.0 Close Pin Intraday Ledger(closepin-v1) — 3層アーキテクチャの第二台帳
  - 毎営業日14:30 JST: `/api/argus/closepin-snapshot`(2分キャッシュ)が JPセンサー6+実戦7(計12ユニーク)の
    リアルタイム価格をピン+`_closepin_scenarios`(pure・pytest4件)で終値シナリオ分布(バンド±0.25/±0.8%
    ≈1時間σ、モメンタム継続+大口フローの微傾斜、capped)。**source=moomoo-rt の行のみ**(T-1除外・正直設計)
  - closepin-pin.yml: 時刻窓ガード(JST14:20-15:20以外は拒否=遅延cronの後出しピン防止)+1日1ピン不可変。
    正トリガー=EC2 cron 05:30 UTC(bridge/trigger_closepin.sh、**ユーザーのcrontab追加待ち**)
  - 採点: prediction-ledger.yml(16:05)内のステップで同日採点 — 終値はブリッジの引け後push
    (source=moomoo-rt & date=today の行のみ採点)。closepin/scores/ + closepin/summary.json
    (overall/byPosture/byLayer/byMember)。日次台帳とは完全に独立した系統
  - ブリッジのデフォルト銘柄にJPセンサー5本(1306/1321/8306/7203/9432)追加 → 計16コード。
    **ユーザー操作待ち: AWSで git pull && sudo systemctl restart argus-bridge + crontab に closepin行追加**
  - UIなし(データ蓄積優先)。蓄積後にTodayへ引けピン成績表示を検討

- v10.19.0 entry-scout v2.3 日証金(JSF)統合 — **本番検証: ユーザーのJ-Quantsプランはweekly_margin未提供(margin=null確認)** →
  無料の日証金CSV(taisyaku.jp/data/zandaka.csv・Shift_JIS・列構成を実ファイルで検証済み)で代替。
  `_jsf_balance_table`(6hキャッシュ・cp932)+`_jsf_for`+`_jsf_assess_lines`(pure・pytest3件):
  日証金倍率=融資残(9列)/貸株残(12列)、<1売り長→踏み上げ燃料(+0.5)、≥3買い長→戻り売り(-0.5)、
  本日新規vs返済の方向(±0.3)。貸借銘柄のみ(非掲載は正直に未取得)。72テスト
- v10.18.0 entry-scout v2.2 信用残統合(Phase 2着手) — `_jq_weekly_margin`(J-Quants v2
  /markets/weekly_margin_interest・12hキャッシュ・**プラン非対応なら403/404→None で正直に未提供表示**)、
  `_margin_signal`+`_margin_assess_lines`(pure・pytest5件): 信用倍率<1=売り長→踏み上げ余地(+0.5)、
  ≥5=買い長→戻り売り圧力(-0.5)、売り残前週比+15%→買い戻し圧力蓄積(+0.5)、買い残前週比+15%→過熱(-0.5)。
  全件reasonsJa明示。本番でプラン可否を要確認(取れなければ日証金公開データ統合が次の代替)。
  **Phase 3バックログ継続: 診断の台帳記録→校正された確率表示(ユーザーの「全情報を一つの答え%」)**
- v10.17.0 entry-scout v2.1 テクニカル統合 — _entry_metricsにMACD(12,26,9)ヒスト+直近クロス、
  MA5/25クロス、ボリンジャー%b(25日±2σ)。assessで各±0.5・全件理由表示。AIReviewに日本語社名
  (useAssetsのdisplayNameJaから解決)。本格的なパターン形状認識(ダブルボトム等)は引き続き未対応(正直表示)
- v10.16.1 ナビ順を判断フロー化 — Today→Watchlist→(Alerts/Regime/Events/Core)→Guide。
  NavRail.NAV と App.NAV_ORDER は同期必須
- v10.16.0 entry-scout v2(全能力集約 — ユーザー「限界を勝手に決めるな」) — 診断にレジーム/VIXスパイク/
  TOPIX相対力(ブリッジ同時刻比較)/決算接近(earnings.date必須ガード — daysUntilは欠損時0のため)/
  AI二重チェック見解を統合。寄与は全て±0.5〜1で理由に明示。62テスト
- v10.15.1 オーバースクロール・ページ送り — .shell__mainの底で追加プル(タッチ90px/ホイール累積350)
  →次のnavページへ。インジケータ表示・800msクールダウン(短いページの連鎖ジャンプ防止)・Guide(最終ページ)では無効
- v10.15.0 ⚡エントリー診断(entry-scout-v1) — ユーザーの9984エントリー振り返り(2026-06-13)から。
  `_jq_price_history`(60-90営業日・6hキャッシュ)→`_entry_metrics`(pure: RSI14/MA乖離/続落/出来高比)→
  `_entry_scout_assess`(pure: 寄与±0.5〜1を全て理由に明示・金曜アノマリーはノートのみで点数化しない)→
  GET /entry-scout?symbol=(JP 4桁のみ・30分キャッシュ・heavyレート枠)。戦略カードに⚡ボタン+診断ブロック。
  **Phase 2 バックログ: 日証金・信用残(買い戻しvs新規の区別)、チャートパターン形状、米国株対応、
  診断結果の台帳記録(診断自体を採点して信頼を育てる)、マイトレード記録(ユーザー自身の判断を採点)**
- v10.14.0 ニュース日本語化(news-v2.1) — `_translate_headlines_ja`(Gemini flash・10分毎の
  キャッシュ充填時に1回・失敗時は英語フォールバック)。⚡語彙に地政学(iran/israel/taiwan/strike等)追加。
  Event RadarセクションをTodayの判断ログ直下へ移動(ユーザー要望)。
  残P1: 金利/ボラカード統合+前日比、News Radar+Market News統合
- v10.13.0 資産クラス司令室(command-center-v1、ユーザー承認の案A)
  - CorePortfolio.tsx 全面刷新(旧mock indexFundStatus廃止): ①buildExposureによる実配分(円換算合計・
    含み損益・ジャンル別バー・unpriced正直表示) ②useActionAlertsの8クラス判断(AlertCard再利用)
    ③coreActionForの姿勢連動積立方針。Action Alertsページは当面併存(ユーザーの使用感を見て統廃合判断)
- v10.12.2 銘柄ごとPro相談ボタン(戦略カードのフッター・クライアント側でプロンプト生成)+
  通知タイトルにJST配信時刻(iOSの「昨日」問題対応。今夜22:00便から有効)
- v10.12.1 Finnhub USフォールバック — TD無料プラン対象外銘柄(IONQで発覚)を /quote で補完
  (_finnhub_quote_row: 10分キャッシュ・銘柄毎・name=symbol)。投信の基準価額は依然データ源なし
  (fund-nav-v1候補: MUFG AMの公開API — fund_cdの正確な特定が必要、推測禁止)
- v10.12.0 Market News速報(news-v2) — ユーザー指摘「ECB利上げ速報が見えない」への対応
  - GET `/api/argus/market-news`: Finnhub general news(10分キャッシュ・5分fail back-off)、
    `_NEWS_MAJOR_RE`(中銀/金利/介入/危機キーワード、pure・pytest1件)でmajorフラグ。最大14件
  - Today(CommandCenter)に Market News カード(6件表示・⚡=major強調・5分毎更新+visibility即時)。
    英語・参考情報・**判断エンジンには非入力**(reaction-based主義は維持)と明記
  - v10.11.1: Todayに台帳成績常設(センサー1日的中率+引けピン行、蓄積前は「蓄積開始前」表示)

## 0-c. ユーザーレビュー(2026-06-11夜)からの改善バックログ — 次セッションはここから

P1(高・すぐやる):
1. Market News見出しの日本語化 — Gemini flashで10分毎のキャッシュ充填時に一括翻訳(headlineJa追加)。リンク先翻訳は不可(ブラウザ翻訳を案内済み)
2. 金利/ボラカード統合 — Rates backdrop と FRED rate snapshot は重複(ユーザー指摘)。1枚に統合し、**全指標に前日比±%**と「VIXの60日レンジ内位置」を表示(高い/低いが一目で分かるように)
3. ニュース統合 — News Radar(危機カウンター)と Market News(速報)を1セクションに。0件=平穏の正常表示である旨も明記
4. Event Radar を Today の上部へ移動(売買判断の主要材料とのこと)。「イベント=方向ではなくリスク窓」の説明行も追加
P2(中):
5. fund-nav-v1 — 投信の基準価額。MUFG AMの公開API(fund_cd要検証・推測絶対禁止)。Watchlist投信行+Exposureに反映
6. Data limitations 等の英語文字列の和訳総点検
7. Regime glossary に「投資にどう使うか」1行を各用語へ
8. Corporate Catalysts の日本株開示の充実(J-Quants)
P3(要議論/ユーザー判断):
9. Core Portfolio 再設計 — Watchlist投信との役割が不明瞭(ユーザー)。金/BTC/債券/ドル円のベーシック資産はAction Alertsと重複するため、統合 or 明確な役割分担を設計から
10. Render Starter($7/月)課金 — コールドスタート(15分スリープ→30-60秒)の根治。ユーザー判断待ち
11. _NEWS_MAJOR_RE に地政学語彙追加(iran/strike/attack等 — Trump/Iran見出しが⚡にならなかった)

## 0. 最初にやること（現状確認）

新セッションを始めたら、まずこの3つで現状を把握する:

```bash
# 1. 直近の開発履歴
cd /Users/mitsugumatsumoto/argus/.claude/worktrees/youthful-hopper
git log --oneline -8

# 2. 現在のフロントエンド版数（真実は package.json）
grep '"version"' web/package.json

# 3. 本番バックエンドの全プロバイダ健全性（鍵の有無・live/partial/missing が一目で分かる）
curl -s https://argus-backend-3j2m.onrender.com/api/argus/integrations | python3 -m json.tool
```

次の実装は **ニュース/ブラックスワン原因検知 or 判断ログのoutcome tracking（精度測定ループ）**（下の「ロードマップ」参照）。

---

## 1. プロジェクト概要

**ARGUS（A.R.G.U.S. — Autonomous Risk and Global Uncertainty Scanner）** = 個人の日次投資の「行動判断エンジン」。

- **予測エンジンではない。** 現在の市場・銘柄の状況を「行動カテゴリ」に分類し、今日の判断・リスク・理由・
  触るもの・避けるもの・待つもの・何が判断を変えるか、を示す投資コマンドセンター。
- 思想: Bloomberg Terminal + Linear + Raycast + Stripe Dashboard。落ち着いた濃紺。
  **HUD / サイバーパンク / ネオン / 偽ターミナル装飾は禁止。**
- **English chrome + Japanese reasoning**（UIラベル等は英語、解説・理由・市況コメントは日本語）。これは意図的。
- 「10秒ルール」: アプリを開いて10秒で「今日の判断」が分かること。

---

## 2. リポジトリ / 環境

- **Repo:** `mitsugue/argus`
- **ローカルパス:** `/Users/mitsugumatsumoto/argus/.claude/worktrees/youthful-hopper`
  （branch: `claude/youthful-hopper`）。**旧 `/Users/mitsugumatsumoto/stock-scanner` は使わない。**
- **バックエンド:** https://argus-backend-3j2m.onrender.com
  （Python Flask、単一ファイル `scanner.py`、Render、`main` push で auto-deploy）
- **フロントエンド:** https://mitsugue.github.io/argus/
  （React 18 + TypeScript + Vite、GitHub Pages、base `/argus/`、`web/` 配下）
- **現在バージョン: v10.19.0**

---

## 3. デプロイ手順（必ずこの順番）

```bash
git push origin claude/youthful-hopper          # ① feature branch へ
git push origin claude/youthful-hopper:main     # ② main へ FF → Render(backend) と Pages(frontend) が両方デプロイ
```

- フロントのビルド: `web/` 内で `DEPLOY_BASE=/argus/ npm run build`
- バージョンは Vite の transformIndexHtml プラグインが `globalThis.__ARGUS_VERSION__` を index.html に注入。
  **`web/package.json` の `version` が唯一の真実。**新機能ごとに必ず上げる。
- **📖 説明書ルール（ユーザー指示・恒久）: バージョンアップのたびに、Guide ページの
  「ARGUS でできること」(`CAPABILITIES`) と「最近のアップデート」(`RECENT_UPDATES`)
  （`web/src/routes/Guide.tsx` 冒頭）を必ず同時に更新する。**
  アプリ内の説明書は常に現在の実力を正確に語ること（直近6リリース程度を保持）。
- コミットメッセージ末尾は `Co-Authored-By: Claude ...` を付ける運用。

---

## 4. 検証パターン（毎回実施）

1. `python3 -m py_compile scanner.py`（ローカルは `python` 不可、必ず `python3`。`flask_cors` 等は `pip3 install --user` 済み）
2. `npm run lint`（= `tsc -b --noEmit`、`web/` 内）
3. `DEPLOY_BASE=/argus/ npm run build`（`web/` 内）
4. **secret-grep:** `dist/` に `sk-` / `AIza` 等の**鍵の値**が無いこと
   （env変数の*名前* "OPENAI_API_KEY" 等が説明文として出るのはOK。鍵の*値*が無ければ良い）
5. 本番 `curl` で各エンドポイント status 確認
6. Claude_Preview MCP でブラウザ描画確認（dev サーバは本番バックエンドを叩く。
   新規エンドポイント未デプロイ時は mock fallback で描画される）

---

## 5. 🔒 セキュリティ制約（厳守・絶対）

- APIキー / 認証情報は **Render の環境変数のみ**。フロントに出さない・ログに出さない・
  **チャットに貼らない**・コミットしない。
- `ARGUS_ADMIN_TOKEN` はフロントに出さない。admin専用エンドポイントは `X-ARGUS-ADMIN-TOKEN` ヘッダ必須。
- 公開フロントエンドは**高コストなAI呼び出しを自動で行わない**（キャッシュ読み取りのみ）。
- AIステータスは**フラグではなく真実ベース**で表示する（v9.6.0で確立、後述）。

## 6. ⚠️ 正確性の絶対制約

- **8058 = 三菱商事（Mitsubishi Corporation）。三菱重工(7011)ではない。** symbol↔name は推測しない。
  新しいコードを足す前に必ず公式の銘柄リストで確認する。
- Watchlist 初期シード:
  - JP 7銘柄: 8058(三菱商事), 9984(ソフトバンクグループ), 5801(古河電気工業), 5803(フジクラ),
    6584(三櫻工業), 285A(キオクシアHD), 9501(東京電力HD)
  - US 4銘柄: NVDA, AAPL, TSLA, META
  - コア投信2: eMAXIS Slim 全世界株式 / eMAXIS Slim 米国株式(S&P500)
  - 暗号資産: BTC, ETH
  - localStorage キー `argus.assets.v1`（上限50、端末ごと・クロスデバイス同期なし）

---

## 7. 行動ラベル語彙（単一の真実: `web/src/domain/actions.ts`）

- 戦術ラベル: **EXIT / TRIM / WAIT / WAIT FOR PULLBACK / BUY DIP / ADD / HOLD**
- コア(投信)ラベル: **CONTINUE / GRADUAL ADD / DEFER LUMP SUM / NO SELL ACTION**

---

## 8. バックエンド エンドポイント（`/api/argus/*`）

| endpoint | 内容 | status |
|---|---|---|
| `/rates` | FRED 10Y/2Y/Real10Y/VIX（HY OAS は内部利用） | live |
| `/japan-watchlist` | J-Quants V2（`x-api-key` ヘッダ、base `https://api.jquants.com/v2`） | live |
| `/us-watchlist` | Twelve Data `/quote`（複数シンボル1リクエスト） | live |
| `/events` | Event Radar（FOMC/CPI/PPI/雇用/BOJ/国債入札等、official calendar） | live/partial |
| `/action-labels` | Action Label Engine v0（ルールベース、Market Regime を統合済） | live |
| `/market-regime` | Market Regime / Capital Rotation v1（`regime-v1`） | live |
| `/catalysts` | Corporate Catalyst（SEC EDGAR + Finnhub + J-Quants） | partial(Finnhub未設定) |
| `/pro-handoff` | GPT-5.5 Pro 用コピペ生成（**API呼び出しなし・無料**） | live |
| `/ai-judgment` | GET=キャッシュ読みのみ（モデル呼び出さない） / POST `/run`=admin限定 | disabled |
| `/integrations` | プロバイダ健全性（公開・secret-free、`integrations-v1`） | live |
| `/ai-provider-status` | AI診断（admin限定、`X-ARGUS-ADMIN-TOKEN`） | 503(token未設定) |
| `/symbol-search` | 銘柄検索 JP(J-Quants master)/US(Twelve Data)/Crypto(CoinGecko search) | live |
| `/security-status`, `/security-unlock` | admin限定 | — |

### バックエンド実装メモ
- キャッシュは `{"data":..., "expires":...}` の in-memory TTL パターンで統一（dyno再起動でリセット）。
  TTL例: rates 10min / us 10min / jp 10min / market-regime **6h** / integrations 2min。
- FRED: `fetch_fred_series(series_id)` + `_FRED_SERIES` dict。HY OAS = `BAMLH0A0HYM2`。
- Market Regime: 8銘柄ETF（SPY/QQQ/IWM/XLK/XLU/GLD/TLT/HYG）を Twelve Data `time_series` 1バッチ取得
  （8 credits ≤ 無料枠の毎分上限、6hキャッシュで credit-safe）。1d/5d/20d モメンタムを±10%capで正規化しスコア化。
  **ETFローテーションは資金フローの proxy であって直接フローではない。**
- ルートは `@app.route("/api/argus/...")` 直書き、`return jsonify(...)`、CORS は `@app.after_request` でグローバル。

---

## 9. フロントエンド構成

- ルーター: `web/src/App.tsx` の state-based `RouteKey`。
  ルート: `command`(Today/Daily Command Center) / `alerts`(Action Alerts) / `regime`(Market Regime) /
  `events`(Event Radar) / `watchlist`(Watchlist) / `core`(Core Portfolio) / `guide`(Glossary/Guide + API status)。
  AIReview は `#review` ハッシュ。
- live fetch フックの型: `{ data, error, loading, phase, attempt }`、
  `phase` = connecting/live/partial/mock、retry 3回 + mock fallback。
  バックエンドURLは `import.meta.env.VITE_ARGUS_BACKEND_URL` から構築（`.env.production` に本番URL）。
- 型は `web/src/types/`、フックは `web/src/hooks/`、mock は `web/src/mock/`。
- CSS は主に `web/src/components/dashboard/Dashboard.css`。テーマ変数(`--bg`/`--green`/`--red`/`--amber`/
  `--text-main`/`--font-mono` 等)を使う。
- Watchlist はジャンル分け（Japanese Stocks / US Stocks / Investment Trusts / Crypto）+ @dnd-kit ドラッグ並べ替え。
  新規追加はそのジャンルの先頭に来る。

---

## 10. バージョン履歴（直近）

- v9.0.0 Corporate Catalyst Layer
- v9.1.0 自動AI判断 v1（OpenAI GPT-5.5 + Gemini double-check）。**コードのみ。Renderに鍵なし→ disabled。**
- v9.2.0 統合 Watchlist + Strategy Cards（8058=三菱商事 修正が重要）
- v9.3.0 Add-Asset 銘柄検索（名前/コードで候補表示）
- v9.4.0 Watchlist ジャンル分け + ドラッグ並べ替え（@dnd-kit）
- v9.5.0 Live Market Regime + Capital Rotation スコアリング（`regime-v1`）
- v9.6.0 Integration Health + AI provider 真実ステータス
- v9.7.0 Today実データ化 + CoinGecko crypto live
  - Todayのヒーロー判断/ピル/優先リスト/イベント/コアは `web/src/lib/todayCall.ts` が
    `/action-labels` + `/market-regime` + `/events` + 価格から**ルールベース合成**（手書き判断ゼロ、LLMなし）
  - `GET /api/argus/crypto-watchlist?ids=…`（CoinGecko、キー不要、10分キャッシュ、ids sanitize済み）。
    crypto資産は memo の `coingecko:<id>` で対応付け
- v9.8.0 ユーザーWatchlist⇔エンジン接続 + 鮮度の正直表示
  - `/japan-watchlist?symbols=` `/us-watchlist?symbols=` `/action-labels?jp=&us=` が動的銘柄対応
    （sanitize + JP≤20 / US≤8 + per-set bounded cache）。UI追加銘柄に価格+ルールラベルが付く。
    名前はJ-Quants masterから解決、未知銘柄は保守的に高ベータ扱い、取得失敗行は省略（偽価格なし）
  - 鮮度: quote が7日超古い → ラベル confidence×0.5 + 【価格データn日遅れ】prefix +
    supportingData.quoteDate/quoteLagDays。UIは amber の `delayed Xw` ピル、mock行は数字を「—」表示
    （実測: 現プランのJ-Quantsは T-1。12週遅れは現在発生していない）
- v9.9.0 判断ログ + 朝ダイジェスト
  - 判断ログ: `web/src/lib/judgmentLog.ts`、localStorage `argus.judgmentLog.v1`（JST日付ごと1件、
    live/partialのみ記録・mockは記録しない）。Todayに「昨日からの変化」+直近7日ストリップ表示
  - `GET /api/argus/daily-digest`（digest-v1、ルールベース合成・LLMなし、textJa=通知用日本語）
  - `.github/workflows/morning-digest.yml`: JST平日7:15に digest を ntfy.sh へ push
    （repo secret `NTFY_TOPIC` 設定時のみ。未設定なら安全にスキップ。workflow_dispatchで手動テスト可）
  - 注: サーバ側の永続DB(Postgres)はまだ。日次差分は端末ログが担当（クロスデバイス同期なし）
- v9.10.0 変化検知アラート + ルールテスト + レート制限 + AI ping
  - `market-alerts.yml`: JST平日7〜24時に毎時digestをポーリングし、**変化時のみ** ntfy push
    （姿勢フリップ / 重要イベントのD-1・D入り。状態はActions cacheで持ち回り。初回はseedのみ）
  - `test_rules.py`(pytest 17件)が判断コアを保護 + `ci.yml`(push毎にbackendテスト+frontend build+secret-grep)
  - per-IPレート制限: `/api/argus/*` 120/min、cache-busting系(symbols/jp/us/ids/q付き)30/min、429 JSON
  - `POST /api/argus/ai-provider-status/ping`(admin): OpenAI/Geminiへ最小"pong"呼び出しでキー疎通確認
  - v9.10.1 Guideに「できること/最近のアップデート」(📖説明書ルールの開始)
- v9.11.0 moomooブリッジ = リアルタイム価格
  - `POST /api/argus/quote-push`(admin token): ブリッジからのJP/USリアルタイム価格を受領
    (sanitize/上限50/価格検証)。`_overlay_pushed` が watchlist 系の全経路で
    「10分以内のpush > J-Quants(T-1)/Twelve Data」の優先で上書き(キャッシュ非破壊・自動フォールバック)
  - `bridge/` ディレクトリ: moomoo_push.py(OpenD横で常駐) + systemd unit + README(セットアップ手順)。
    ユーザーのAWS(52.195.168.61)でOpenD 24h稼働中。**ポート11111は公開しない**(ブリッジは127.0.0.1接続)
  - /integrations の moomoo: push鮮度で live(≤15min)/stale/pending を表示
  - 通知改善: digest文面を通知向け再設計(絵文字セクション・短い行)。morning-digestは
    JP寄り前8:30 + US寄り前22:00 の2本。market-alertsに市場ストレス急変検知
    (backdrop→stress遷移、VIX 26上抜け)。全通知にClickヘッダ(タップでアプリ起動)
  - ブラックスワンの「原因」(会見/戦争等のヘッドライン)検知は未実装 → 次候補(GDELT/ニュースAPI)
- v9.12.0 VIX通知の本質化
  - ユーザー指摘「固定の26はダメ。本質的に判断して」→ `_vix_assess(closes)`(純関数・テスト済):
    急騰速度(前日比+15%かつ+2pt、or +5pt) × 自身の直近60日分布のパーセンタイル × 広い絶対バンド
    → zone = calm/normal/elevated/shock。**アラートは圏域の上方遷移とスパイクで発火**(数字の上抜けでは発火しない)
  - `_fred_vix_history()`(FRED VIXCLS 70日・1hキャッシュ)。digestに `volatility` ブロック+文脈付きVIX行
  - market-alerts.yml は zone遷移+spike(日付dedup)ベースに書き換え。固定26ルール撤廃
- v10.0.0 Portfolio Exposure
  - AssetItem に quantity/avgCost(端末localStorageのみ・送信しない)。useAssets.updateHolding
  - `web/src/lib/portfolio.ts`(純関数): valueHolding/buildExposure — ¥/$別合計+USD/JPY円換算
    (FRED DEXJPUS を /rates に `usdJpy` として追加=additive)・ジャンル配分・mock価格では評価しない
  - 戦略カード展開部に保有入力、Watchlist上部に ExposureCard(評価額/含み損益/配分バー)
  - moomooブリッジ稼働確認済み(AWS・systemd・1分毎push・全11銘柄 moomoo-rt live)。GEMINI_JUDGE_MODEL=gemini-2.5-pro
- v10.1.0 What-if + 検索修正
  - What-if: `lib/whatif.ts`(SCENARIO_BANDS=下値-10〜-4%/横ばい±2%/反発+3〜+8%の仮定幅×シナリオ確率)。
    Watchlist上のWhatIfPanelで追加投資の配分変化/集中警告(>30%)/損益帯/確率加重中央値。予測ではない表記必須
  - 検索修正: `_jp_query_is_code()` — `isdigit()`が「314A/285A」等の英字入りTSEコードを名前検索に
    回していたバグを修正(コードprefix照合+名前照合の併用)。pytest追加
  - 投信: J-Quantsは上場銘柄のみで投信は構造的に不在 → `lib/fundCatalog.ts`(主要26本・正式名称)の
    ローカル検索をAdd-AssetのCore/Fundタブに追加。基準価額(NAV)は未取得=将来のデータソース課題
- v10.2.0 大口フロー確証
  - ブリッジ: get_capital_distribution で大口(super+big)の流入/流出を毎サイクル取得し
    quote-push payload に flow={bigIn,bigOut,allIn,allOut} を添付(銘柄毎try・30分back-off・0.25sペーシング)
  - バックエンド: bigNetRatio=(bigIn-bigOut)/(allIn+allOut) を正規化して行に保持。
    `_flow_adjust()`(pure・pytest5件): 緩い押し目(-5<chg≤-2)+ratio≥+0.20+イベント/金利/レジーム障害なし
    → **BUY DIP解禁**(conf≤0.6)。ratio≤-0.25でHOLD→WAIT。±0.20超は理由に注記のみ
  - フロント: 戦略カード詳細に「大口純流入率 X%(本日累計・moomoo)」行(±20%で緑/赤)
  - **注意: ブリッジ側の反映には AWS で git pull + systemctl restart argus-bridge が必要**。
    JP市場のcapital_distribution提供可否は口座の気配権限依存 — 未提供銘柄はflowなし(自動スキップ)で安全
- v10.6.1 株価の自動更新 + Vercel遺物対応
  - useJapanWatchlist / useUSWatchlist: 60秒毎のサイレント自動更新(タブ非表示中はスキップ、
    visibilitychange で復帰時に即時更新)。失敗時は最後の正常データを保持(connecting/mockへ落とさない)
  - ledgerブランチに vercel.json {"git":{"deploymentEnabled":false}} を配置 — 旧 "stock-scanner"
    Vercelプロジェクトが日次ledgerコミットでビルド失敗("No Flask entrypoint")していた件の恒久止血。
    プロジェクト自体の削除はユーザー操作(Vercel→Settings→Delete Project)
- v10.7.0 AI永続化(ai-persist-v1) + 通知の定時配信
  - AI判断のキャッシュは30分TTL+メモリのみ → 16:35以降と再起動後は「not run yet」になっていた。
    prediction-ledger.yml が実行後の public GET payload を ledger/ai/latest.json に永続化し、
    scanner.py の `_ai_cached_result()` が「メモリ→ledger復元(`_ai_try_restore`)」の順で解決。
    復元は10分back-off・6秒timeout・最大120h(週末耐性)・runMode="restored"。検証は `_ai_restore_validate`(pure・pytest4件)
  - morning-digest.yml: GitHub無料cronの2〜3.5h遅延対策 — 06:49/19:49 JSTに早発火し、
    ntfyのDelayヘッダで08:30/22:00 JSTちょうどにサーバー側配信(目標時刻超過時は即時送信)
  - 通知のClickヘッダ削除(digest+alerts) — タップでntfy内で全文表示、アプリへ飛ばない(ユーザー要望)
- v10.8.0 校正ループ(calibration-v1)
  - 台帳の summary.json(byPosture別の的中率)を `_ledger_summary()`(30分キャッシュ・10分back-off)で取得し、
    `_calibration_for(summary, posture)`(pure・pytest5件)が確信度係数を返す:
    bucket n≥33(≈3日分)が必要、hitRate≥60%→×1.05 / <40%→×0.85 / それ以外×1.0(ノイズ域)。
    係数適用後の確信度は0.05〜0.9にクランプ。蓄積不足の間は中立×1.0+「蓄積中」表示
  - /action-labels レスポンスに `calibration: {factor, basisJa, n, hitRate}` を追加。
    資産戦略ページ先頭に「🎯 校正: …」の1行(常時表示・正直設計)
  - 採点データが貯まると自動で効き始める(コード変更不要)。これが「予測→採点→確信度への還元」ループの配管
- v10.9.0 学習対象の3層構造化(ledger-v3) — ChatGPT/Gemini協議でユーザー確定(2026-06-11)
  - **Layer 1 = 固定16センサー**(変更禁止の校正背骨): JP 1306/1321/8306/7203/8058/9432 +
    US ETF SPY/QQQ/SMH/IWM/TLT/HYG/GLD + BTC + USDJPY + VIX。
    特異リスクの9984/7011は意図的にL2へ。`_L1_SENSORS_JP/_L1_SENSORS_US`(scanner.py)
  - Layer 2 = 実戦銘柄(入替自由・action-labelsの銘柄が自動でL2扱い)、Layer 3 = 高ノイズ実験枠(6584、
    `_LAYER3_SYMBOLS`)。**L3はL1/L2の校正集計に混ざらない**(byPosture等から除外)
  - バンドはσ単位: equity/ETF 2%・BTC 3%・FX 0.5%・VIX 8%(`_SENSOR_BAND_PCT`、固定値でなく資産種別の日次σ近似)。
    `_scenarios_scaled()`が±2%調整済み分布をバンド比でスケール
  - 採点は1/3/5営業日ホライズン(土日除外のtdays)。scores/{d}.jsonはv3形式
    {horizons:{1,3,5}:{layer1:{sensors,stocks},layer2,layer3,(h1のみ)classes/posture/aiDirectional}}で
    ラン毎に漸進的に埋まる。v2スコアファイルとの併存OK(旧ループはv3日をスキップ)
  - `/sensor-quotes`(public): 16センサーの現在値(JP=J-Quants/moomoo、ETF=TD stash+SMH 6hキャッシュ、
    BTC=CoinGecko、USDJPY/VIX=FRED)。summary.layers.{layer1,2,3}.byHorizon.{1,3,5}にbyMember学習表
  - 校正(calibration-v1)へはv3のh1のL1+L2が合成されて継続供給(legacy_item)。
    スコアラーは合成フィクスチャでローカル実行検証済み
  - 残タスク: Close Pin Intraday Ledger(15:30引けピン)の分離実装は未着手(次フェーズ)
- v10.10.0 端末間の自動同期(sync-v1)
  - 同一パスフレーズの端末同士でウォッチリスト/保有/判断ログを自動同期。暗号文のみ送受信(従来どおり)
  - バックエンド: GET `/vault-relay?vaultId=`(非破壊・public・正規表現検証) + vault-pullがスロットを
    クリアしない化(relayが日次コミットの間も読めるように。再ドレインはgit的に無害)
  - フロント: `markLocalEdit()`(useAssetsの実変更時のみ・マウント時persistは除外)→45秒デバウンスpush。
    `cloudSyncNow()`=relay優先+セッション初回のみGitHub rawフォールバック→exportedAtのLWW比較→
    リモートが新しければ`restoreBackup`+`argus:data-synced`イベント(useAssetsが再読込)。
    `startCloudSync()`(App起動時): 初回sync+90秒ポーリング(タブ可視時)+visibilitychange即時
  - 自分のpushの再適用防止: cloudBackupNowがappliedExportedAtを記録。sync適用直後の3秒は
    markLocalEditを抑制(エコーpush防止)
  - **制限(v1)**: 全体LWW — 2端末で同時編集すると新しいpushが勝つ(per-itemマージは将来課題)
- v10.10.1 価格更新の15秒化
  - bridge/moomoo_push.py: PUSH_INTERVAL_SEC デフォルト60→15(下限10)。FLOW_INTERVAL_SEC=60を新設し
    大口フローは従来周期のまま(flow_cacheで前回値を毎push添付→バックエンド行がflow欠落でチラつかない)。
    moomooクォータ: snapshotは1リクエスト/サイクル=2/30秒で余裕
  - useJapanWatchlist/useUSWatchlist: REFRESH_INTERVAL_MS 60秒→15秒(2エンドポイント≈8req/分、heavy上限30/分内)
  - **要ユーザー操作: AWSで git pull && sudo systemctl restart argus-bridge**(未実施だとブリッジは60秒のまま。
    画面側15秒化だけでも反映遅延は最大60+15→60秒に短縮)
  - 1秒ティックは未対応(WebSocket/SSE化が必要 — 将来課題としてロードマップ記載)
- v10.10.2 sync安全装置 — ①cloudSyncNow: ローカルにデータがあり一度も同期/編集していない端末へは
  自動適用しない(復元かローカル編集で初参加 — 「Macで先に有効化→スマホが上書きされる」事故を防止)。
  ②cloudRestoreがrelay優先(16:05の台帳コミットを待たず他端末の直近pushから復元可能)+復元後に
  appliedExportedAt記録&data-syncedイベント(リロード不要で画面反映)

---

## 11. v9.6.0で確立した「AI真実ステータス」（重要）

`scanner.py` の `_ai_judgment_truth()` が**単一の真実源**。`AI_JUDGE_ENABLED=true` だけでは `live` にしない。

状態: `disabled`(フラグoff) / `missing_keys`(鍵なし) / `partial`(片方のみ) /
`no_cached_result`(鍵あり実行なし) / `live`(adminラン成功のキャッシュあり)。

**現在の本番の真実: OpenAI鍵=未設定、Gemini鍵=未設定、AI_JUDGE_ENABLED=false、
ARGUS_ADMIN_TOKEN=未設定 → 自動AI判断は disabled。**
GPT-5.5 Pro Handoff は手動コピペで無料・API呼び出しなし（ChatGPT Pro 課金とは別物）。

→ Render に `OPENAI_API_KEY` + `GEMINI_API_KEY` + `AI_JUDGE_ENABLED=true`（+ `ARGUS_ADMIN_TOKEN`）を
入れれば、Guide の API status パネルと全ステータスが**自動で実状態に切り替わる（コード変更不要）。**

---

## 12. ロードマップ（2026-06-10 のレビューで改訂。README / Guide の旧版と差異あり — こちらが最新）

1. **v9.12 ニュース/ブラックスワン原因検知** ← 候補。市場反応(ストレス急変)はv9.11で検知済み。
   原因側: GDELT(無料)等のヘッドライン+キーワードルール(戦争/介入/緊急会見)で「何が起きたか」を通知。
2. v10.0 Portfolio Exposure Layer(保有・数量・平均取得・評価・含み損益・配分、端末内計算)
3. v10.1 What-if Simulator(シナリオ分析)
   （将来: 判断ログのサーバ永続化=無料Postgres。outcome tracking=「あの判断は当たったか」の照合。
     ブリッジのPUSH_SYMBOLSとアプリWatchlistの自動同期）
4. v10.0 Portfolio Exposure Layer（保有・数量・平均取得単価・評価・含み損益・配分。
   保有額は機微情報なので localStorage + クライアント側計算を基本に）
5. v10.1 What-if Simulator（**シナリオ分析であって決定論的予測ではない** — シナリオ帯×配分変化で表現）
6. 随時: Alerts Scanner ページのlive化、moomoo/VWAP/板・テープ検証、AI自動判断（キー設定後）

---

## 13. Render 環境変数（参考・値はチャットに貼らない）

`FRED_API_KEY` / `JQUANTS_API_KEY` / `TWELVEDATA_API_KEY` /（任意）`FINNHUB_API_KEY` /
（未設定）`OPENAI_API_KEY`,`OPENAI_MODEL`,`GEMINI_API_KEY`,`GEMINI_JUDGE_MODEL`,
`ARGUS_ADMIN_TOKEN`,`AI_JUDGE_ENABLED` ほか AI ゲート系。
