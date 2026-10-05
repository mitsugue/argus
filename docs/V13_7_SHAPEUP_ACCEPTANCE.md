# 13.7 機能整理・受入台帳（2026-09-17）

現行要件: [オーナー確定指示](V13_7_SHAPEUP_REQUIREMENTS.md)。
この台帳は全体完了を意味しない。実装・検査・本番利用・予測力を分けて記録する。

## 引けピン撤去の変更単位

- GitHub 専用 workflow `closepin-pin.yml`（ID 293874164）は 2026-09-17 に
  `disabled_manually` を確認。過去の完了済み実行・台帳は削除していない。
- 候補コード: 専用 workflow の定期起動・取得・書込み・通知を除去し、手動入口は無処理。
  `bridge/trigger_closepin.sh` は無処理で終了。予測台帳 workflow の専用採点を除去。
- 候補コード: 専用 API は HTTP 410 を返し、価格取得・予測計算を実行しない。
  台帳健全性画面の専用読出し、Today の専用要因を除去。
- 保全: `ledger` ブランチの既存記録、通常の予測台帳、Scout の集計、
  共用の銘柄集合・米国技術株の関連付け、認証・保存・復旧は維持。
  旧計算式の参照元は変更前 main `ad1a6e2158c5b2ba2c0cbe6a66739f49475cbc81`。
- 関連検査: 予測台帳・通知対象・計算ルールの 147 件 PASS。
  廃止 API が価格取得に進まないことも検査。
- 未確認: 本番 API 410、配信後の画面、EC2 配置済みスクリプト／crontab。
  GitHub 側の起動停止だけで専用機能の全面撤去完了とはしない。

## 長期研究・価格尺度の本番観測

2026-09-17 12:56 UTC 時点、backend 13.7.23 / build
`bc9ac9fb19986363f5e4ebdb6614aca8eb33f5ef`、ready=true。

- 日経比較 API: 実績 2442 本、2016-09-20〜2026-09-17。
  候補 2360、条件適合 192、選択 3。過去全指標 10 年検証済みフラグは false。
- 保存済み背景計算を参照。応答内の historicalFetches=0、fullRecalculations=0、
  automaticAiCalls=0。これは当該応答の観測であり、全経路の無実行証明ではない。
- 信用評価損益率、日経レバ信用残、海外フロー、金利、NT 倍率、
  材料反応などに候補時点の欠損あり。価格 10 年と全特徴量 10 年を区別する。
- EPS/PER 取得は HTTP 403、valuation=UNAVAILABLE、EPS/PER は null。
  利用許諾を再度の阻害理由とせず、取得経路と定義整合の未解決事項として扱う。
- 489 営業日前後の保存済み日経予測研究と、2442 本の価格履歴は別資産。
  既存成果の検証状態は保持し、未検証頻度を予測確率へ昇格しない。

## その他の未完了項目

対話 UI／実行、保有管理、FIRE、My Trades、外部 AI 相談、個別リアルタイム監視の
撤去は未完了。会話と同じ API に存在する復旧・通知・費用照会・統合銘柄説明を
維持する必要がある。数量を使わない登録銘柄、当日業種ヒートマップ、長期研究の
全指標被覆、統合説明の再利用、実契約削減、本番全体受入も未完了。
金額削減の実績はまだ測定しておらず、月数百円達成とは報告しない。

## 対話撤去の変更単位（候補 13.7.24）

- Today、銘柄、イベントから質問入力・仮定の操作・会話履歴 UI を除去。
  統合AIの説明、同じ根拠の比較チャート、ARGUSの正式な判断履歴は維持。
- 旧クライアントの `action=ask` は認証後に 410 で終了。外部取得・AI・保存の新規実行なし。
  会話専用のイベント検索・仮定・旧見立てへの質問生成経路を削除。
- 同じAPIにある vault / notifications / usage / 保存済み history・status・save と、
  定期的な銘柄統合説明は維持。保存済みの会話・所有者記録を削除しない。
- 関連92検査とフロントエンドビルド成功。実機・本番APIは未確認。
- 残件: 銘柄説明はまだ画面側から更新要求できる。登録銘柄の定期生成と保存済み説明の
  読取りだけへの移行を次に行う。保有数量・損益・FIRE等の撤去も別途未完了。


## 外部相談・ユーザー売買入力の撤去（後続候補、未配信）

- Today、銘柄メモ、保有詳細の外部AI用コピー入口と専用リクエストを除去。
  銘柄メモは既存の保存キー・内容を維持し、通常のメモとして利用する。
- 旧 `/api/argus/pro-handoff` は410で終了し、相談用データの収集・構築を実行しない。
- My Tradesの表示と新規登録・決済・削除処理を除去。既存の保存キーと
  バックアップ／読取りは維持し、ARGUSの正式な予測・判断履歴には変更しない。
- 残件: 保有数量・FIRE・ライブ取得等の撤去、配信証明、後続の版更新、本番画面。
  本変更だけでウォッチリスト整理完了や料金削減実績とはしない。


## Quantity-free watchlist candidate (2026-09-18, not deployed)

- Product-facing asset reads use a whitelist of registration fields; quantity,
  cost basis, allocation, contributions and purchase/horizon records remain in
  the original protected store. Mounting, toggling registration and restoring
  a backup do not erase those archived fields or reactivate portfolio analysis.
- Holdings entry, allocation/FIRE route and portfolio daily snapshot generation
  are disconnected. Exposure, FIRE and portfolio strategy calculators remain
  preserved for archival research, but active Asset Intel does not call them.
  Shared market scenarios, evidence, data quality and formal SDA history remain.
- Existing full encrypted/export recovery remains. The old partial-portfolio
  import/export is recovery compatibility, labelled as archived records; it
  does not create new valuation snapshots. Remove this compatibility entry only
  after full archive export/restore is verified on the owner's iPhone and any
  remaining legacy partial backups have a verified migration path.
- Registered symbols can receive P1 and worsening-scenario notifications
  without quantities; existing throttle, preferences and deduplication remain.
  The private integrated-overview request sends WATCHING context without old
  quantity, cost, purchase-reason or holding-period inputs.
- Local checks: actual asset-store mount/edit/restore preservation, notification
  execution/deduplication, all frontend lint steps (resumed after updating
  obsolete portfolio/label expectations), production build, source/artifact
  naming guards passed. Existing archived numerical tests were retained.
- This is a local frontend candidate, not production acceptance or measured
  monetary savings. Pending: integration with the separately prepared live-feed
  retirement, exact provenance registration, version bump and release checks,
  actual desktop/mobile/iPhone acceptance, backend handling of legacy private
  context, view-triggered generation retirement, bridge/job/provider contracts.
  A quantity-free warning is not a validated prediction or a BUY permission.


### Backend registration-only context candidate

All active subject-overview construction paths (request and background refresh)
now use quantity-free registration context. Old-client quantities/costs and
purchase/horizon notes are not generation inputs or cache-invalidation reasons.
Legacy previous records retain their original digest/content; their personal
facts and old generated prose are excluded from a new watchlist explanation,
with the original record ID and exclusion reason retained. New market facts and
previous market facts remain bound to the same subject and horizon.

116 focused backend tests passed, including the actual constructed provider
prompt, immutable original archive, no repeat generation after migration, and
changed materials/rules still causing a new edition. This is local validation;
production prompt, saved-answer read-only operation and cost reduction remain
unconfirmed. No hosted provider call or paid recalculation was made for tests.


### Unchanged-hour generation removal candidate

The subject-overview reuse key no longer includes a wall-clock hour. The prior
implementation could regenerate the same explanation each hour even if source
facts, event status, model and rules were unchanged. Input-key version v2 retains
source vintages, missingness, event facts and calculation/model/rule changes.
The saved answer's completion time is never refreshed merely because it was read.

117 focused backend tests passed. A background-tick test crosses multiple hours
and the next day with unchanged facts and observes no extra generation, then
changes an event-state fact and observes one new generation with the previous
record linked. Provider calls were stubs: production call counts and dollar
savings are not yet measured. This does not complete cached-only page reads;
first-visit generation and durable watchlist registration remain pending.
### 個別ライブ取得の廃止（実装候補）

個別ライブサービスの製品起動口を停止し、旧設定が有効でも認証・接続・専用スレッドを開始しない。
共用のチャート履歴準備は同じ起動口から維持する。旧クライアント向けの読取りはDISABLEDと
feature_retiredを返し、保存済み研究コード・既存履歴は削除しない。Todayのライブ帯、
銘柄詳細の板・VWAP、チャートの現在値重ね描き、遅延価格へのライブ上書きを外す。
当日の業種取得、既存の遅延価格、判断根拠と履歴は別経路として維持する。
本項目はローカル実装・検証段階。配信、専用スレッド停止の本番確認、他のライブ取得経路の
廃止、契約縮小は未完了であり、個別ライブ全体の停止済みとはしない。
## 長期特徴量の再起動時再利用 — 未配信候補

既存の特徴量計算結果を、入力ハッシュ・計算コード4ファイルの版・内容ハッシュと
ともに既存永続ディスクへ保存し、背景収集時に読み戻す。画面GETで復元や計算を開始しない。
同日・同じ入力であれば、再起動後も全期間の計算を再実行せず元の値・出典・計算時刻を使う。
破損・未来時刻・コード版変更は拒否し、訂正された入力は再計算する。

実装・関連17検査は確認済み。本番の保存・再起動後の読み戻し、実コスト削減は未確認。
これは再計算可能な派生成果のキャッシュであり、原データ・過去判断台帳は変更しない。
日付の進行や入力訂正後の差分計算、全系列10年被覆、予測力実証は未完了。

## 長期特徴量の差分計算（後続候補・未配信）

計算済み履歴に評価した時点と系列別の入力件数・内容ハッシュを保存する。
元入力が内容・順序とも同じ接頭部分を持ち、新規行の対象日と公表時点が
再利用する最後の評価時点より後である場合だけ、その過去計算を再利用する。
訂正、過去への追加、削除、順序変更、系列追加、旧形式は全再計算へ戻す。
前回の場中時点が今回の評価時点に含まれない場合、その場中結果を引き継がない。
現在時点の鮮度・欠損は再評価し、原記録・予測の書換えは行わない。

関連22検査成功。60時点から62時点への更新では2時点だけ計算し、全再計算と
数値・条件・出典・改訂履歴・最新状態が一致することを確認した。
これはテストデータでの計算量削減であり、本番実行回数・費用削減は未確認。
不足系列の10年被覆や予測力を検証済みへ昇格しない。新たな取得・LLM呼出しは追加しない。

### Explanation reuse across display-only releases (candidate)

Saved subject explanations now bind to the exact generation implementation and
validators, provider/model/settings, and the existing material input digest.
An unrelated frontend or patch-identity update no longer changes the generation
rule identity. Missing generation sources fail closed; the original saved
context, completion, and execution provenance remain immutable. Changes to the
provider implementation, prompt, validators, facts, or model still invalidate
reuse. This is independent of the remaining saved-only viewing work.

Validation: 57 focused tests passed, including all generation-source changes,
release-only stability, missing-source rejection, effective rule/model/input
invalidation, pending public editions, and immutable saved completions.
Production use and measured invoice savings for this candidate are not yet verified.


## Saved-only subject viewing and durable registration (13.7.29 candidate)

Production overview reads return the existing successful edition without acquiring
company materials, creating a request, or invoking GPT. The saved completion and
input context remain unchanged, including after restart and public context changes.
When no edition exists, the screen states that it is waiting for the scheduled
analysis of a privately synced registration. Existing numerical period views remain;
a missing narrative for another period is not fabricated or generated on selection.

The existing background worker now includes privately synced JP/US registrations
without a prior edition (default five-session horizon), retains existing supported
periods, and stops refreshing removed registrations while preserving their history.
One new job per tick, existing deduplication/provider limits, and bounded rotation
remain. Failed subjects do not indefinitely block later registered subjects.
Private membership reads are cached for five minutes; a successful explicit sync
updates that cache immediately. Missing membership is a waiting state, not an empty
watchlist or permission to generate from old archived subjects.

Validation: 48 focused backend checks, frontend build, owner UI/retirement and
backup protection checks passed using stub providers. No hosted AI was invoked for
these tests. This candidate is not yet production accepted or measured bill savings.
Remaining: automatic propagation of registration edits (existing explicit sync is
still required), crypto/fund explanation coverage, production generation/read receipts,
and full requirement acceptance. No claim of all watchlist work being complete.


## Shared bridge retirement (13.7.30 candidate)

The production bridge entry point now acquires only the fixed eight shared US
market ETFs, no faster than five-minute intervals during the existing calendar's
regular session. Old individual-symbol lists, flow settings, mover and capability
flags do not reenable dedicated acquisition. Health heartbeats, original quote
timestamps and HMAC signing remain. Historical helper code is retained but has no
production entry path. Existing sector heatmap acquisition is not modified.

59 related bridge, calendar, production-entry and explanation checks passed with
stub I/O. A public explanation validator's old holdings fallback was also changed
to quantity-free registration language; missing subject evidence remains UNKNOWN.
These are implementation checks, not EC2 deployment or actual invoice savings.
The documented existing EC2 host rejected this Mac's existing public-key auth.
No credentials, accounts, firewall rules, service state or contracts were changed.
Deployment and runtime proof require the existing owner's EC2 access path.

## 13.7.31 candidate — selected news translation

- Market-news cache refill and institutional collection reuse saved translations and do not call an LLM. Existing original metadata, provenance, severity, and histories remain intact.
- Scheduled translation selects server-observed fresh HIGH/CRITICAL intake headlines and fresh market headlines meeting the existing major/relevance rules. Browser visibility, arbitrary public queue entries, and all-company caches do not expand paid work.
- Existing content-hash reuse, failed-attempt bounds, provider accounting and important-headline fallback remain in force. This change does not claim that all news analysis or Deep Dive costs are resolved.
- 60 related checks PASS using mocked providers: repeated cache refills make no translation call; a browser-only priority claim cannot purchase translation; an important headline is translated once; unrelated/old items remain metadata without translation.
- Not deployed. Exact source registration and admission proofs must complete before release; actual billing reduction remains unmeasured.

## Sector heatmap candidate (not production accepted)

Display-only 8 TOPIX-sector ETF proxies plus TOPIX-linked 1306, not official33 sector indices. Cached public GET makes no provider/LLM calls; scheduler performs bounded20-minute session collection and one closing fill. Existing durable volume atomic writer/readback restores original timestamps. Offsite backup inclusion remains unverified.

Eight focused calculation/runtime/API/durable-restore checks pass. Real source probe recovered all9 instruments with source time2026-09-18 15:30JST; Saturday is labeled closed/previous session. Actual browser checks changed1 to20 sessions and return tobenchmark-relative, openedbank detail (+3.61% versus +3.09 percentage points relative), and verified390px mobile width. No live-session latency claim. Frontend build and source/built naming checks pass. Registered-sector association uses existing confirmed classifications only; unknown mappings remain unknown.


## 13.7 最終報告(要件書 10 章の 8 項目・2026-10-03 作成)

「実装済み」「テスト済み」「本番で確認済み」「完了」を分けて書く。本報告は 13.7 の全体完成宣言ではない。
13.8 の設計書(`V13_8_REQUIREMENTS.md`)が、残る改善と統合AIの位置づけを引き継ぐ。

### 1. 残した機能・削除した機能

| 区分 | 機能 | 状態 |
|---|---|---|
| 残した | 統合AIの見立て(市況ブリーフ・銘柄別説明)、日本株分析エンジン(長期研究・類似局面・条件付き計算)、七つの警戒条件、重要イベント(予定→事前→結果→反応→答え合わせ)、重要ニュース、登録銘柄の現在地と危険信号、日米需給、当日の業種ヒートマップ、企業プロフィール、通知、判断履歴と予測の検証、バックアップ、データ品質・費用の確認 | 本番稼働 |
| 削除した | 対話(action=ask は 410)、個別銘柄のリアルタイム表示と専用取得、保有・ポートフォリオ管理、FIRE・積立、売買記録、外部AI相談(pro-handoff は 410)、引けピン(API は RETIRED)、立花証券API(feature_retired)、個別銘柄チャート生成 | 本番で確認済み(13.8.16 で画面部品も削除) |
| 保全 | 保存済みの会話・保有・売買・引けピン・立花の記録は削除していない。読み出しだけ残る | 確認済み |

### 2. 停止したジョブ・API呼び出し・常駐処理

- GitHub workflow `closepin-pin` は `disabled_manually`(2026-09-17 以降継続。2026-10-03 の一覧で確認)。
- 引けピンの取得・予測・採点・通知、対話用のLLM呼び出し、外部相談用のデータ組み立て、個別ライブの認証・接続・専用スレッド、個別銘柄チャートの事前生成(missions/tick 内)は停止。
- 共有ブリッジは固定8本の米国ETFのみ・5分間隔以上(bridge-status は heartbeat null = EC2 側は停止中。EC2 の状態は SSH 不可のため AWS の画面での確認が未了)。
- ニュースの翻訳は重要見出しだけ(選択翻訳)。Deep Dive は重要な変化時のみ。
- 残っている定期ジョブ(2026-10-03): caos-scan, caos-watchtower, market-watch, market-alerts, macro-event-analysis, news-intake-ops, prediction-ledger, event-ledger, learning-memory, jpx-credit-weekly, breadth-freshness, mover-causes, crypto-watch, osint-check, smoke-test, vault-sync ほか。caos-scan は 3 回に 1 回「劣化」で終わる(13.8 の残作業)。

### 3. 長期研究データの系列別完成状況と残る不足

- `docs/ops/jp-market-condition-series.md` に 16 系列の出所・入手時刻の規則・状態を記録。2026-10-03 の本番で 14/16 系列に当日値があり、欠けは 1570 信用残の週次変化率 2 系列(次の公表待ち)。
- 価格: 日経平均 2,442 営業日(2016-10-03〜2026-10-03)。特徴履歴は同じ 2,442 時点で、再起動・再取得で作り直さない(13.8.16 配信後に `unchanged_known_inputs` を本番で確認)。
- 指数 EPS/PER: 公式値は 403 で取得不可のため、月末ウエート CSV と J-Quants 予想 EPS から再構成した代理値(`FORECAST_COVERED_ONLY`、実測誤差 +0.76%)が本番稼働(2026-09-29)。過去の月末ウエート表がないため、過去データの延長は未完(データ待ち)。
- 不足: 信用評価損益率の公式値(ARGUS 代理計算で代替)、1570 信用残の過去 10 年(週次取り寄せで追記中)、系列ごとの期待件数と実件数の自動照合(未実装)。
- 予測力: 類似局面の方向一致率 44.0% は単純予想 48.4% を上回らず `UNVALIDATED`(2026-10-01)。画面では「参考経路(未検証)」と表示し、初期表示では隠す。未検証の頻度を確率として出していない。

### 4. 研究パックが本番で使われた証拠

- 2026-10-03 診断(run 37087538499): `marketFeatureAcquisition.status=AVAILABLE`、`lastSuccessfulCalculationAt=2026-10-03T01:09:22Z`、`calculationWork={evaluatedCutoffs:1, reusedCutoffs:2442}`、`reuseDecision.reason=unchanged_known_inputs`。
- 日経比較の応答に `historicalFetches=0`、`fullRecalculations=0`、`automaticAiCalls=0`(2026-09-17 以降の観測と同じ)。
- 画面の Today(判定欄・類似局面・七つの警戒条件の成績)は、この同じ計算結果を読む(13.8.16 で成績表示を配信、Pages 受入合格)。

### 5. EPS/PER と 7 警戒条件の実装・検証状況

- EPS/PER: 代理値を本番で計算・表示(上記 3)。公式値がある場合は公式値を優先する作り。17倍・18倍を恒久の支持線としては扱っていない。
- 七つの警戒条件(D01〜D07): 原典の定義で判定し、7 段階の総合評価とは別物として表示。条件イベントの過去成績(`jp_market_sign_event_study`)は 13.8.16 で配信。D07 は原典に点灯規則がなく `NOT_EVALUABLE`。本番の成績の数字をオーナーに報告する作業は未了(13.8 の残作業)。
- 個人名由来の旧名称: コード・画面・配信物から除去し、命名ガードが毎 PR で検査(PASS)。

### 6. ヒートマップの更新間隔・実際の遅延・取得元

- 取得元: Yahoo Finance の業種 ETF 8 本(代替指標)+ TOPIX 連動 1306 を基準。正式な 33 業種指数ではないことを画面に明記。
- 更新間隔: 場中 20 分(`refreshIntervalSeconds=1200`)+引け後 1 回。休場日は前営業日と明記(2026-10-03 土曜の診断: `session=WEEKEND_CLOSED`, `targetDate=2026-10-02`, `isToday=false`)。
- 実際の遅延: 元価格の時刻 15:30 JST の行が引け後に取得されることは確認済み。**場中の遅延の実測は東証が開いている時間にしかできず未了**(次の取引日 2026-10-05 に計測)。

### 7. 変更前後の固定費と変動費

| 項目 | 変更前 | 変更後 | 根拠 |
|---|---|---|---|
| Render | 2026年9月 $214.17(8GB プラン中心) | 2GB(1CPU)に切替済み。10月見込み $65〜75 | 請求書・プラン画面(オーナー確認) |
| AI(OpenAI 等) | 9月 約$300(9/14〜16 に $222 の山) | 10月 1〜3日の実測 $12.62(418 呼び出し、1日 $2.3〜6)。月換算 約$120〜150 の見込み | 本番 `ai-cost.json`(SDK 呼び出し単位の参考推定) |
| J-Quants | Standard + TDnet アドオン ¥11,000/月 | Standard のみ(アドオン解約) | 2026-09-29 |
| Twelve Data | Grow | 変更なし(ブリッジ停止中は米国個別の唯一の経路) | |
| EC2 | 稼働 | 状態未確認(SSH 不可) | AWS 画面での確認が必要 |

月数百円には到達していない。到達していない金額を約束しない。

### 8. 本番反映されたバージョンと確認結果

- 2026-10-03 時点の本番: backend/frontend 13.8.17(13.8.18 = 予測記録の遠隔バックアップ修正を取り込み中)。
- Pages 受入検査: 13.8.15 で全合格に回復、13.8.16・13.8.17 も全合格。
- 本番で確認済み: 退役 API の 410/RETIRED、長期特徴量の再利用、夜間先物の取得、EPS/PER 代理値、ヒートマップの休場表示。
- 未確認: EC2 の状態、場中のヒートマップ遅延(10/5)、iPhone の通知到達(オーナー確認)、発表直前基準の反応(次の指標 10/14 CPI)。

## 2026-10-05：残件と参照系列の再照合

この節は上記の日付付き記録の訂正・更新であり、全体完了宣言ではない。

- 系列別の期待件数・取得件数・欠測の照合は実装済み。`docs/ops/jp-market-condition-series.md` の更新記録と `_jp_market_series_acquisition_status` を参照する。「未実装」の旧記載を現状の判定に使わない。本番の全系列充足は別の確認事項。
- D07は現行実装で決算後の正の騰落率を候補規則として評価する。従来の「常に NOT_EVALUABLE」という記載は現在と異なる。D03・D05・D06にも上昇支持の規則があるため、点灯数を検証済み暴落確率・強度としては扱わない。数式と閾値は今回変更していない。
- 指数方式のEPS/PERは `argus_index_valuation_proxy`、価格の目盛りは `jp_market_level_map` の時価総額加重方式。目的と算式が違う別系列であり、長い方で短い方を上書きしない。4番の規則は指数方式を維持する。
- 日経平均の約2年の表示用キャッシュは、約10年の保存履歴から切り出す用途がある。長期比較は `_N225_ANALOG_HISTORY` を優先し、短い表示配列を長期保存の正本にしない。PER再計算はその価格履歴とは別の進捗として数える。
- セブンサインの信用残・海外フロー・VIXは既存の改善済み取得経路を参照する。D03のETF相対力と研究用の現物指数相対力は商品が違う。単に同名という理由で交換しない。
- イベントの影響表示は共通部品に統一。Todayは見通しの図の直後に価格の目盛り、日本株の内訳の後に他市場を置く。
- 価格の目盛りは既存EPS保存記録から同じ方式・締切以前のPER中央値、範囲、上の倍率以上の日数を計算する。再計算した過去の位置比較であり、将来の到達確率にはしない。表示は60件以上・取得済み価格との対応率80%以上を要する。過去の休場日を近年だけの祝日表で欠測扱いしない。
- 業種価格は同一営業日の取得済み値と更新遅延を分ける。遅延値は時刻付きの灰色表示に残し、現在値・相対比較への採用条件は緩めない。前営業日の値を当日に置換しない。

残る本番確認は、取得巡回の最終実行・失敗種別、各条件の現在の値と対象日、全系列の充足、保存復旧、実機の通知受信、発表直前と直後の記録。保護された本番応答や所有者情報を公開診断ログへ追加しない。EC2・契約の実状態はコードから完了を宣言しない。退役済み機能の旧要件を復活させない。
