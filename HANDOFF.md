# ARGUS 開発引き継ぎ（HANDOFF）— v10.1.0 時点

> **新しいAIアシスタントへ:** これは ARGUS プロジェクトの引き継ぎ書です。開発を再開する前に
> このファイルを最後まで読み、下の「最初にやること」を実行して現状を確認してから作業を始めてください。
> セクション「🔒 セキュリティ制約」と「⚠️ 正確性の絶対制約」は**必ず守る**こと。最終更新: v10.1.0。

---

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

次の実装は **v10.2 moomoo深化（資金フロー/板=大口の動き→ラベル確証シグナル）or ニュース/ブラックスワン原因検知**（下の「ロードマップ」参照）。

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
- **現在バージョン: v10.1.0**

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
- **v10.1.0 What-if + 検索修正（最新）**
  - What-if: `lib/whatif.ts`(SCENARIO_BANDS=下値-10〜-4%/横ばい±2%/反発+3〜+8%の仮定幅×シナリオ確率)。
    Watchlist上のWhatIfPanelで追加投資の配分変化/集中警告(>30%)/損益帯/確率加重中央値。予測ではない表記必須
  - 検索修正: `_jp_query_is_code()` — `isdigit()`が「314A/285A」等の英字入りTSEコードを名前検索に
    回していたバグを修正(コードprefix照合+名前照合の併用)。pytest追加
  - 投信: J-Quantsは上場銘柄のみで投信は構造的に不在 → `lib/fundCatalog.ts`(主要26本・正式名称)の
    ローカル検索をAdd-AssetのCore/Fundタブに追加。基準価額(NAV)は未取得=将来のデータソース課題
  - 次候補: moomoo深化 — ブリッジを拡張し get_capital_distribution(大口/中口/小口フロー)や板情報を
    push→ラベルエンジンの「フロー確証」シグナルへ(v0が欠くtrend/flow confirmationを充足)。
    JP市場での提供範囲はmoomoo口座の気配権限に依存(要実機確認)

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
