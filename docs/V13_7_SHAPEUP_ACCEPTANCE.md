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
