# ARGUS 全体レビュー依頼書(GPT Pro 用)

> 目的: ARGUS の現状(思想・リサーチ対象・機能・API・自己採点)を余すところなく開示し、
> GPT Pro に「より良くなっているか / 機能は動いているか / API は適正か / 投資エージェントとして
> どうか」を厳しくチェックしてもらう。末尾に Claude(実装担当)からの質問を付す。
> 本書時点の本番バージョン: **v10.73.0**(2026-06-23)。スモーク 30/30 ALL GREEN。

---

## 0. 一言で

ARGUS は**予測エンジンでも自動売買でもない**。「いま市場と各銘柄が**どの行動カテゴリ**にあるか」を
ルールベースで分類し、**今日の判断・リスク・理由・触る/避ける/待つ**を提示する投資コマンドセンター。
さらに、自分の判断を毎日記録して後日採点する**自己校正ループ**を持つ。

中核原則(厳守):
- **正直さ**: 全データに live / partial / mock / delayed を明示。証明できないものは「realtime」と名乗らない。
- **予測でなく分類**: シナリオ確率は予言でなく状況整理。利益保証はしない。
- **自動売買なし**: 注文 API・ブローカー接続・発注ルートを一切実装しない。
- **秘密保持**: API キーは Render 環境変数のみ。保有数量・取得単価は端末内(E2E 暗号化)。admin トークンはフロントに出さない。

---

## 1. アーキテクチャ

- **バックエンド**: 単一ファイル Flask `scanner.py`(約7,200行)。Render Starter。`https://argus-backend-3j2m.onrender.com`。`main` から autoDeploy。`/healthz` の buildSha でデプロイ検証。約66ルート。
- **純ロジック・モジュール**(stdlib・ユニットテスト付き): `argus_rules`(行動分類), `argus_events`(24/7イベント検知), `argus_research`(EDINET等の決定論ドシエ), `argus_event_store`(イベント永続), `argus_ai_cost`(AI予算ハード上限), `argus_calibration`(校正v4: コホート/エポック/採点math), `argus_market_clock`(市場別フォーキャストクロック)。テスト計 **208**。
- **フロントエンド**: React18 + TS + Vite。GitHub Pages `/argus/`。PWA(自己回復アップデータ v10.70)。現 v10.73.0。
- **EC2 ブリッジ**: moomoo OpenD の 15秒スナップショットを HMAC+admin で `/quote-push` に送る。OpenD ポート11111はローカルのみ(非公開)。
- **台帳の保存**: 予測台帳(ledger-v3)は GitHub の `ledger` ブランチ。所有者ウォッチリスト(2B)は公開リポ対策で **private ストア**予定。

---

## 2. データ源と真実性

| 源 | 用途 | 鮮度/制約 |
|---|---|---|
| **J-Quants Standard**(¥3,300/月) | JP 全銘柄日次・信用・財務 | **T-1終値**(リアルタイムでない)。全市場ムーバー(引け後)。レート制限あり |
| **moomoo ブリッジ**(EC2 OpenD) | JP/US ウォッチのリアルタイム push | **entitlement 未証明** → exchangeTs で証明できるまで `unknown`(realtimeと主張しない) |
| **Twelve Data Basic**(無料) | US ウォッチ + レジームETF | 無料枠(過去に枠焼け→キャッシュ45分で是正) |
| **Alpha Vantage**(無料) | US 全市場ムーバー | **25回/日** → 市場時間中 約15分毎で枠を使い切る。公開画面はキャッシュのみ |
| **CoinGecko** | 暗号資産 | 24/7 |
| **FRED** | 金利・VIX | 日次/EOD(イントラデイVIXなし) |
| **EDINET** | 法定開示(大量保有・臨時) | official_fact と official_catalyst を区別 |
| **投信総合ライブラリー** | 国内投信NAV | 日次。eMAXIS Slim 3本 |
| **Yahoo!ファイナンスJP** | JP 全市場ランキング | 約20分遅延(moomoo未収載の穴埋め用) |
| **GDELT** | 危機ニュース監視(News Radar) | 参考情報・事実検証はしない |

JP全市場の三重カバー方針: **① moomoo(リアルタイム・能力テスト待ち) → ② Yahoo(約20分・全銘柄穴埋め) → ③ J-Quants(引け後・確定値で確かめ算)**。

---

## 3. ページ別説明(左ナビ順)

1. **Today(今日の判断)**: 市場セッションランプ(JP/US/Crypto)→総合判断(WAIT/HOLD等+リスク+理由+触る/避ける/次の条件)→24/7イベント(S高/急変・タップで「何が起きた/原因/シナリオ/罠」のドシエ)→判断ログ(自己採点成績)。10秒で全体把握。
2. **Watchlist(個別銘柄)**: JP株/米株/投信/暗号資産を検索追加・並べ替え。各行に行動ラベル+戦略カード(理由/次の条件/シナリオ確率)。日米株は「⚡エントリー診断」。保有数量・取得単価で評価額/含み損益(端末内のみ)。What-if試算。
3. **Market Context(地合い+予定)**: 資金ローテーション+レジーム(RISK_ON〜EVENT_WAIT)+金利/VIX/HY OAS、公式カレンダー(FOMC/CPI/日銀/入札 D-7→D+1)、News Radar、US/JP 全市場ムーバー。
4. **Core Portfolio(資産配分)**: 実配分(円換算・含み損益)+8資産クラスのライブ判断+姿勢連動の積立方針+投信NAV(前日比)。
5. **Guide**: 使い方・用語・**自己採点の読み方(Brier/RPS/スキルスコアの基準)**・Ledger Health・情報源レジストリ・暗号化バックアップ。更新ごとに自動刷新。

---

## 4. 自己採点システム(Calibration Ledger v4)— 本セッションの主作業

「校正(確率予測が統計的に当たっているか)」を測る。**「校正が良い ≠ 儲かる」**を前提に、別途 Decision Value Ledger(下記)を計画。

### 4.1 コホート(旧 Layer1/2/3 を再設計)
- **regime_sensor_fixed(16・regime_sensor_v2)**: JP4(1306 TOPIX / 1321 日経225 / 1615 東証銀行業 / 1343 東証REIT)+ US11(SPY/QQQ/IWM/SMH/XLF/XLE/XLU/TLT/LQD/HYG/GLD)+ BTC。校正の背骨・不変。
- **tactical_benchmark_fixed(14・tactical_benchmark_v2)**: JP7(8306/7203/8058/9432/9984/7011/5803)+ US7(NVDA/AAPL/TSLA/JPM/XOM/PG/CAT)。**会社タイプを分散**(旧:相関の高いメガキャップ成長4本に偏っていた)。**5803 フジクラを固定ベンチに意図的に保持**(日本のAIインフラ高ベータ代表)。5801/META は所有者ウォッチリスト(2B)で利用可。
- **owner_watchlist_dynamic(2B)**: あなたの実ウォッチリストを採点する枠。**まだ非稼働**(公開リポ対策で private ストア構築後に有効化)。
- **experimental_cohort**: 旧「Layer3=6584固定」を廃止し、**直交フラグ制**(small_cap/high_volatility/event_driven/policy_sensitive 等・証拠付き)へ。

### 4.2 Context Variables(文脈変数・等加重リターン採点に混ぜない)
USDJPY / VIX / US10Y / US2Y / US Real10Y / HY OAS。VIXは逆相関リスク、USDJPYは文脈依存、金利/OASは水準でリターンでないため、センサーと別扱い。

### 4.3 市場別フォーキャストクロック
JP=TSE引け / US=NYSE引け(EDT/EST自動) / crypto=24/72/120h / FX=NY引け / VIX=CBOE。土日+祝日カレンダー(2026 JPX/NYSE・要公式照合)。「全部16:05 JST固定で採点」を廃止。

### 4.4 採点(proper scoring が主・argmaxは補助)
多クラス Brier(raw+正規化)/ 順序付き RPS / スキルスコア(1−model/baseline)/ ベースライン(naive_sideways/expanding_climatology/prev_day_momentum・前方視リークなし)/ 前方視なしボラバンド band(h)=k·σ·√h / ファクターグループ等加重(相関銘柄の過大評価回避)。

### 4.5 エポックと正直さ
現 **n≈133 は `burn_in_legacy_v3` として保存・ヘッドライン指標から除外**(データ不安定期+台帳ワイプ復旧中に収集)。綺麗なエポックは readiness ゲート+管理者有効化の後に開始。信頼段階は burn_in/early/provisional/regime_level の4段階で、**「proven(証明済み)」とは決して表示しない**。

### 4.6 第二台帳: Close Pin(別系統)
14:30 にその日の終値方向を予想 → 同日15:30終値で即採点(最速の校正ループ)。

---

## 5. 計画中: Decision Value Ledger v1(未着手)

「校正が良い」と「コスト後に純期待値がプラス」は別問題、という発想。明示的な不変ポリシー(entry/exit/invalidation)+ 現実的コスト(spread/slippage/手数料/FX)+ R正規化 + 純期待値 + リスクオブルイン(クラスタ別ブートストラップMonte Carlo)+ no-trade価値 + Kelly(既定無効・research only)。**絶対安全境界: 自動売買/ブローカーAPI/注文ルートは一切作らない(shadow simulation のみ)**。

---

## 6. 主要 API(抜粋・約66ルート)

公開(read): `/healthz` `/api/argus/action-labels` `/market-regime` `/japan-watchlist` `/us-watchlist` `/crypto-watchlist` `/fund-nav` `/market-movers`(US全市場・cache) `/jp-market-movers` `/entry-scout` `/events` `/event-snapshot` `/prediction-snapshot`(90sキャッシュ) `/calibration`(deprecated→branch summary) **`/calibration/cohorts` `/calibration/epochs` `/calibration/clock`** `/source-registry` `/system-health`(公開・$非表示) `/integrations`。

admin限定(401ゲート + 失敗回数でソフトロック): `/ai-cost` `/ai-provider-status` `/security-status` `/tdnet-metrics` `/moomoo-capability` `/market-scan` `/crypto-scan` など。AI実行は ARGUS側ハード予算(日$5/月$80)で停止。

---

## 7. 既知の限界(正直に)

- **JP はリアルタイムでない**(J-Quants T-1)。moomoo リアルタイム全市場は能力テスト未実施(明日のJPザラ場で実測予定・entitlement 未証明)。
- **校正は burn-in 段階**。意味のある数値は新エポックで約120営業日(相関クラスタ補正後)蓄積が必要。サンプルは独立試行でない。
- **2B(あなたの実ウォッチリスト採点)は未稼働**(private ストア待ち)。現在の固定ベンチ 2A は「あなたの銘柄」ではない。
- 無料枠依存(AV 25/日・Twelve Data)。
- 2026 祝日テーブルは best-effort(要公式照合)。

---

## 8. Claude(実装担当)からの質問 — ぜひ厳しく

1. **固定ベンチ vs 実ウォッチリスト**: 校正の妥当性として、固定14銘柄ベンチ(2A)が正解か、それとも所有者の実ウォッチ(2B)を主軸に採点すべきか? 入れ替わる watchlist を採点すると統計の連続性は壊れないか?
2. **Context Variables の扱い**: USDJPY/VIX/金利を「リターン採点しない文脈変数」に分離したのは正しいか? それとも各々の次元(例: VIX方向、金利方向)で別途スコアすべきか?
3. **サンプルサイズ**: 1日約13予測 × 横断相関ありで、統計的に意味のある校正判定に必要な営業日数は? 「約120営業日」は楽観的すぎないか? クラスタ別ブートストラップで十分か?
4. **3クラス境界**: 「横ばい vs 方向」を ±1日σ(k=1)で切るのは妥当か? 銘柄/資産クラスで k を変えるべきか?
5. **EODベース校正の意味**: JPがT-1終値ベースだと、「イントラデイで行動するエージェント」を測れているのか? Close Pin(同日)だけで十分か?
6. **投資エージェントとして欠けているもの**: ポジションサイジング、リスクバジェット、相関を考慮したポートフォリオ・ビュー、ドローダウン管理 — Decision Value Ledger で埋める計画だが、優先順位や設計に穴は?
7. **moomoo entitlement の honesty-gating**: exchangeTs で証明するまで realtime と名乗らない方針は妥当か? 能力テストの合格基準(98%カバー/p95≤5秒)は適切か?
8. **Layer 2A の新構成**: 分散14銘柄(JP7+US7)の選定に、校正目的として明らかな偏り・欠落(例: JPに小型/グロースが薄い、セクター網羅性)はないか?
9. **API設計**: 公開/admin の線引き、キャッシュ戦略(prediction-snapshot 90s 等)、レート制限耐性は適切か?
10. **全体として**: これは「より良い投資エージェント」に向かっているか? それとも測定・校正に凝りすぎて、実際の意思決定支援(今日何をすべきか)が弱くなっていないか?

---

## 9. GPT へのお願い

上記を踏まえ、(a) 設計の妥当性、(b) 機能が実際に役立つか、(c) API/データ源の適正、(d) 投資エージェントとしての完成度と次の一手、を**忖度なく**評価してください。誤り・過大主張・統計的な穴があれば具体的に指摘してください。
