# 13.5 系 Codex 引継ぎ・検証台帳

2026-09-09 JST 開始。これは項目ごとの証跡であり、13.5 系全体の完了宣言ではない。
実装済み、テスト済み、本番確認済みを分け、本番でまだ発生していない条件は観測待ちとする。

## 開始時点

- GitHub main: `4715fa09684091f00850a366d3ffcbfe73349bc9`（#311、2026-09-08 06:20:37 UTC）。
- GitHub 認証: オーナーの既存認証で repo / workflow 操作が可能。秘密値は記録しない。
- 未完了 PR: #237、draft #158 / #154 / #152 / #146 / #134 / #132。既存実装との重複を避けて扱う。
- 開始時の running / queued Actions は 0 件。main の ruleset `Protect main` が有効。
  PR 経由、最新 base 必須、backend-rules / frontend / gate が必須。通常の追加ゲートも省略しない。
- 本番 backend: 13.5.66 `87bf4ec264f8ce53408f9e8efb38cc6cd42fffc9`。
  #310 / #311 は資料・workflow 修正のため、main SHA とバックエンド SHA の差だけを障害としない。
- 本番 frontend: 実ブラウザで初回にキャッシュ版 13.5.61、その後の再読み込みで 13.5.66。
  旧版を一切表示しないことまで確認したわけではない。
- 元チェックアウトの未コミット 2 ファイルを変更せず、binary patch と SHA-256 を別途保全。
  作業は最新 main から作成した独立 Worktree。

## 項目別の状態

追記：#312は全対象CI成功後、2026-09-08 23:22:12 UTCにマージ。
本番 `/healthz` は23:25:50 UTCに `75c34f1537129b1c71ffd42aa56763ff32b54a92` を返した。
再起動前後で当日費用$1.714266、月次$3.194912、Gemini73回・OpenAI8回、
イベント6回、未決済予約0件が一致。`lastRestoreAt=2026-09-08T23:24:27Z`、エラーなし。
`restoredRows=0` は先に復元したjournalとの差分追加が0件という意味で、復元失敗ではない。
費用台帳の再起動後保持を本番確認済みとする。新しいAI生成と収集の終端確認は別途必要。
GitHub CLI認証は同日オーナーの再認証後、アカウントAPIでも復旧を確認した。

配信後の暖機run `34290332943` は23:25:52 UTCに成功。
market-scanと収集はHTTP 200、公開6経路（ニュースを含む）も200を確認した。
実ブラウザでは再起動直後の取得失敗表示がいったん残り、ニュースは自動回復、
チャートは画面の再試行で更新を確認。初回の失敗表示まで解消済みとはしない。
この後続workflow変更はバックエンドの再起動を伴わず、既存の配信指定に従う。

| 項目 | 実装・テスト | 本番で確認したこと | 残件 |
|---|---|---|---|
| 実ブラウザ | 既存13.5.66 | Today のWAIT、評価済みリスク制約、BUY無効、実チャート、頻度と確率の区別、信用残8/28週・9/2公表、ニュース表示を確認 | 配信後に再確認。旧版キャッシュの初回表示を追跡 |
| 定期生成 #311 | 既存修正を維持 | schedule run 34222075523：11:42:14開始→11:47:03 done、pre=1。クライアント接続断後の追跡で成功。16件をledgerへ保存。実ブラウザ Notifications の米10年債入札に保存された日本語シナリオ・織り込み・サプライズ条件を確認 | GitHub schedule の遅延・欠落自体は残る |
| AI結果と予算拒否の矛盾 | #312で呼出単位の診断へ修正。並行リクエストの回帰テスト | 開始時点では米10年債入札が generated と scheduled_daily_budget_exhausted を同時記録 | 新版配信後の新しい生成結果を確認。過去記録は書き換えない |
| 費用台帳 | #307の予約・write-through実装を維持。既存復元テスト合格 | 16:13 UTC：当日$1.714266、Gemini73/OpenAI8、イベント6回、予約0、lastPersistAt=11:42:32、lastRestoreAt=null、restoredRows=0 | 次の実デプロイ後に復元元・回数・金額を照合。数値を満たすために既存台帳を削らない |
| ニュース閲覧 | 外部AI待機中の公開GET非ブロック回帰テスト合格 | 公開 health/list とも200、約2.1秒。40イベント・AI解析38・重複抑止83 | 本番ではニュース枠が尽きており、外部AI実呼出と重なった観測は未実施。処理中ラベルだけでは実呼出の証拠にしない |
| コールド収集 | #312で収集から全暖機までを実行IDで追跡。再要求・同時実行・失敗・再起動での記録消失をテスト。後続workflowで接続予定 | 現行market-watchには90秒同期HTTPが残る | backend反映→workflow接続→コールド条件と通常利用中の終端確認 |
| 立花 | 既存実装を維持 | 16:15 UTC：AUTH_SUCCESS、lastAuthResult=PASS、閉場時価格/日付検査PASS（14:31 UTC）、lastErrorClass=null。実画面も接続確認済 | 閉場状態。3銘柄の保存値をライブ更新と誤認しない。次の開場中の鮮度は別確認 |
| 海外投資家フロー | 既存自動取込を維持 | marketView.sourceStatus.foreignFlow=market_ledger、D05 AVAILABLE / UNVALIDATED。実画面の海外4週=-7,391億 | 「未取得」は開始時点では解消。予測的有効性は未検証のまま |

## 追加で発見した失敗

- breadth-freshness run 34228625014：job `fj-c70dc3ecc9550f30ab4f` が `MemoryError`。
  データは2026-09-08へ更新され、rowCount 40→20,831、lag=0になったが、job failed のため検査は失敗。
  backend / soak identity と readiness は前後とも安定。実際には full_5y / 1,305単位を処理した。例外の正確な発生行は未確認。
  cold台帳からincrementalが5年全体へ拡張した理由と、子プロセスの最終計算のメモリを追加調査する。
  更新されたという理由でジョブ失敗を合格にしない。
- smoke-test run 34217970198：68/69、NFPカード検査のみ失敗。
  検査が8/7の保存済みNFP結果を取り出し、9/9の現在欄に同じeventCodeを要求していた。
  現在欄の72時間窓と同じイベントIDで照合する検査へ修正。最近の結果の欠落・別月イベント・誤ったpre表示は引き続き失敗させる。

## 開発順序・権限

名称変更と13.5残件を本番確認まで完了し、完成版から13.6へ進む。
今回の停止点は13.6の本番受入。13.7の調査・実装・試作・PR・配信は、来週以降に
オーナーが明示的に再開を指示するまで着手しない。日付や13.6完了による自動再開は禁止。
起動時費用判定・費用台帳の保存復旧・収集の不具合は13.5として完了する。
詳細は [v13.6製品要件・受入台帳](V13_6_REQUIREMENTS.md) を参照。
通常の検証・PRマージ・本番配信はオーナー許可済み。取引実行、新規契約、失敗ゲートの省略は含まない。
BUYの検証レジストリと未検証の予測確率は有効化しない。13.6から機能・モデル別のAI使用量と費用を記録する。


## 2026-09-09 11:50 UTC 時点の追加確認

- #314 / #315 / #316は全対象CI成功後に通常マージ。#316の本番SHAは
  `72e74abedeb758e5ad3b646b7d62720b76bcdc2f`。名称移行は3セクション・
  1,065件の識別子変更を適用。11:40:27 UTCに115,847,154バイトの現行checkpointを
  保存し、読み戻し検証に成功（WAL 9,141）。外部ポリシーN001の現行ファイル一致は0件。
  再起動による再復元・iPhoneホーム画面版の移行は未確認。旧原本は製品外へ保全。
- ニュースメールの複数記事を個別URL・見出し・本文に分離する修正は本番反映済み。
  9/9 9:36のメールから12件の別記事を実APIで確認。従来の12件上限は維持しており、
  メール内16件すべてを取得したという証拠ではない。外部AI処理中の閲覧は引き続き観測待ち。
- #314後の実生成4件と費用記録、05:11 UTCのschedule成功を確認。
  後者は保存済み分析が新鮮だったため、新規生成成功の証跡には数えない。
  05:25 UTCには立花3銘柄のLIVE応答を確認。海外フローは取得済み・有効性未検証。
- #316の再起動では、小さい費用台帳の復元前に翻訳2件が実行された。
  当日費用1.650378→1.690378ドル、Gemini72→74回。台帳は合流され欠落していないが、
  復元前の空台帳を使った予算判定が残っていた。schedulerを復元完了後に起動し、
  本番の中央AI認可も復元完了まで拒否する追加修正・関連テストは実装済み。本番は未反映。
- breadth子プロセスは、Python spawnが親scannerを再実行してSDKを先に読み込む経路を確認。
  専用Pythonエントリと私有IPCで起動し、Linuxの既存1,280MiB上限を先に設定する修正を実装。
  親の台帳commit責任、計算式・判断条件は維持。実際のサーバー起動を模した再実行防止、
  子の早期終了時の大容量IPC停止、親終了時の子終了を検証。過去MemoryErrorの解消は
  本番の実ジョブ成功まで未確認。メモリ上限は引き上げない。
- Git到達可能15,336 blobの監査で911 blob、316件のGitHub issue/PR本文で31件、
  保全されたSQLite4世代で各3,421件の残存を確認。履歴・旧世代・外部記録を削除していない。
  暗号文の偶然の一致は認証付き復号後の内容で判定し、暗号文を書き換えない。
  現行成果物の検査と履歴全体の除去を同一の完了として報告しない。


### 個別株チャートの収集後更新（本番受入待ち）

本番5803は9月9日の価格5493円が取得済みでも、保存済みチャートは9月7日のままで、
HTTP 200を理由に「更新済」と表示していた。起動ウォームは欠損レポートだけを対象とし、
その後の価格収集から既存レポートへの反映が遅れる経路が残っていた。

既存のウォーム巡回で変更済みの価格キャッシュを既存のチャート生成・保存経路へ渡す。
1巡回は最大3銘柄・45秒の開始期限とし、公開GET・追加AI・追加プロバイダー取得は増やさない。
復元前と定期処理のロック保持中は開始しない。欠測時は前の図を保持する。
更新をまとめた後にロックを解放し、既存ジャーナルを1回記録して保存する。
保存後の復旧計測を外側のロック保持中に確定しない。
HTTP取得状態とデータ時点を分け、データ日とセッション期限を過ぎた再計算待ちを表示する。

関連バックエンド56件、フロントエンド既存lint、製品ビルドは成功。
命名検査はソース875 UTF-8ファイルと配布物12ファイルで成功。
本番の新しい価格線・保存・再読み出しは配信後に確認するため、現時点では未確認。

本番収集の追加観測では23配信のうち19が記事を返した。残る4配信は本番ホストで
日本語金融ニュースの旧サイトマップがHTTP 404、経産省Atomと日本語通信社の
2つの既存集約フィードがHTTP 403だった。取得済み他系列とは分けて制約を記録する。


### iPhone Settingsで判明した要約成功表示の残件

本番の要約ワーカーは、要約0件・予算拒否でも巡回完了時に `lastSuccessAt` を
更新していた。巡回時刻と要約保存時刻を分け、成功時刻と起動後の要約件数は
実際に保存した要約があるときだけ更新する。対象なし・未取得・実行見送り・
巡回失敗を区別する。予算拒否時には通常レーンの試行数を消費せず、
代替レーンも個別呼出しの診断が拒否・未設定なら恒久的な試行済みにしない。
予算上限、価格計算、売買判断は変更しない。

実装済み。ニュースパイプライン29件の回帰検査は合格。
本番配信とiPhoneの新表示確認は未実施。過去に試行済みとなった記録は、
実際の失敗と予算拒否を記録だけで判別できないため一括リセットしない。

## PR #316適用後の確認（2026-09-09）

現在の名称移行・本番保存・読み戻し・実モデルの証跡は
[名称移行状況](JP_MARKET_ENGINE_MIGRATION_STATUS.md) を参照する。
PR #316の本番識別情報は72e74abedeb758e5ad3b646b7d62720b76bcdc2f。
定期生成run34347406512では新しい米30年債入札分析の実応答・保存・画面反映を確認した。

起動時に費用復元より先に翻訳が2回走った経路をPR #317で修正中。
費用は失われず合算復元されたが、復元前の予算判定は本番で再検証する。
breadthの専用子プロセス起動も同PRで検証中。メモリ上限を増やして合格にはしない。

EC2の既存systemd定期処理は12:07 UTCに本番で実行された。
4つの収集元は本番から404・403を返し、他19配信とは分けて制約として残す。
個別株5803のチャートは9月7日の保存内容で、9月9日の価格取得と一致しておらず、
更新反映とデータ日表示をPR #319で修正中。

ニュースの実外部AI処理中の閲覧、iPhone保存データの移行照合は未確認。
これらの13.5受入後に13.6だけの見積もりを更新し、その完成版から13.6へ進む。



### PR #317の再起動確認（2026-09-09 13:35 UTC）

27成功・予定された1スキップで全28チェックが完了し、13:29 UTCに通常マージ。
本番backendは `c68a1a5c56628158e5bb6fa67ac73e6fb0527a62`、
13:32:50 UTCにREADYを確認。費用台帳は13:32:08 UTCに復元され、
当日1.733518ドル・当月4.92843ドル・Gemini74回/OpenAI7回を維持した。
今回の起動では復元前の余分な費用は増えなかった。116,846,416バイトの現行
checkpointの再起動後検査はN001一致0。新プロセスのcheckpoint書込・読戻し検証は別途確認中。

公開費用APIの合計は復元されている一方、管理診断は別の旧集計を読み0ドルを表示していた。
管理診断も同じ復元済み費用台帳の集計を読むように修正し、非ゼロの当日・当月合計が
公開APIと一致する回帰検査を追加した。予算判定・費用記録自体は変更しない。

配信直前の定期breadth run34354205856は、9月9日・20,848行まで収集後に
MemoryErrorで失敗（旧backend72e74）。最新日を取得しただけで完了と扱わず、
新プロセスでの最終処理・読戻しを引き続き確認する。


## 2026-09-09 14:10 UTC：収集の再開処理を追加検証

- #317は全28検査（27成功・既定のスキップ1件）後にマージ。本番識別子は
  `c68a1a5c56628158e5bb6fa67ac73e6fb0527a62`。前後の費用台帳は
  日次$1.733518・月次$4.92843で一致。公開・モバイル受入と12組の生成検査も合格。
- 実収集の最終照合 `fj-0f76b6336d53cbb22b4f` は13:48:38 UTC完了。
  直近10営業日の照合合格。新しい独立プロセスではMemoryErrorが再現しなかった。
- 次の1日差分 `fj-6ac8094cc4f7ef4dd03d` は13:52:06 UTCに処理完了だが、
  全市場の18銘柄分が比較不能となり、保存済み集計との照合は不一致。
  訂正済みの保存値は維持されている。処理完了をデータ確認合格と扱わない。
- ローカル修正：既存の比較可能終値の計算を使って直前最大10営業日を再生する。
  欠測・無出来をまたいだ基準を保ち、上場区分の不連続をまたいで値を流用しない。
  読み取り対象は45暦日以内で、基準期間全体に値がなければ不明のままにする。
  基準期間を新たな台帳観測として保存せず、計算式や売買条件は変更しない。
- 1日差分の標本照合と10営業日の履歴検証を別項目にし、不一致はジョブ失敗とする。
  独立execプロセスを既存の完了判定に追加するが、他の受入条件は保持する。
- Linuxのピーク計測を`/proc/self/status`のVmHWMへ修正。exec以前の親の
  `ru_maxrss`を子の使用量として報告しない。測定不能はnullで、0にしない。
  実プロセスの計測はVmHWM 371,872 KiB、データ領域の上限1,280 MiBを確認。
  RSSとデータ領域の制限は異なる指標であり、この観測だけで全負荷を保証しない。
- 関連テスト63件合格。14:09:46 UTCの本番読み取り専用再計算で、
  プライム・全市場の騰落4項目ずつ、計8項目が保存値と一致した。
  この診断は本番コード更新や配信後の定期収集合格の代わりにはしない。
- この追加修正は未配信。#319の承認待ち候補とは別Worktreeに保全。
  同候補の配信許可リストを変更・拡張していない。
- ローカルcheckpoint読み戻しは確認済みだが、remote journalは14件待機・
  readBackVerified=falseで、外部保存の確認完了とはしない。
  iPhoneの更新後保存データ、ニュースの実AI通信中の閲覧も引き続き未確認。


### 2026-09-09 21:20 UTC：追加修正の配信前検査

収集再開修正のバックエンド全体は4,823件・20 subtests合格、1件は既定スキップ。
公開境界とソース来歴140件、収集関連63件も合格。#319の最新候補とローカルで統合し、
同PRのチャート更新・要約成功表示・費用診断・13.6要件文書を維持した。
本番での差分収集・定期実行と保存読戻しは未確認で、配信後に確認する。


### 端末の移行開始経路（追加修正・本番未確認）

既存の端末履歴変換は、新しい有効な判断を保存する経路で呼ばれていた。
判断待ちのまま閲覧する端末でも検証・移行できるよう、Appの初回表示後に
同じ履歴リーダーを呼ぶ。変換式・署名検証・移行証跡・破損／保存失敗時の保全は
既存処理を再利用し、新たな判断の生成、保有・設定の変更、履歴の切捨ては行わない。
iPhoneの本番起動後に実際の保存データを確認するまで、移行完了とは報告しない。

フロントエンドlint/buildと既存の移行・保全テストは合格。21:38:41 UTCに
ビルド済みアプリを実Chromiumで起動し、Settingsのみを表示する条件で合成履歴1件の
移行を確認した。判断・時刻・数値、合成保有の数量7・取得価格1000と設定を維持し、
再読込で履歴のバイト列が一致、破損させた履歴は原文を保持した。ネットワークPOSTは0件。
これはローカルの合成データ検査であり、iPhone実機の保存内容確認を代替しない。


### 2026-09-10: oversized chart publication follow-up

Production 8c258233 held the Sep 7 chart while the cached 5803 closes reached Sep 10 (2,434 rows); warm refresh reported ValueError. A same-scale fixture using actual dates/closes but synthetic OHLC, volume and provenance produced 2,503,217 bytes, exceeding the unchanged 2 MiB report limit.
Oversized display reports now retain the last 600 calculated bars and explicitly disclose the window. Engine input, all other analysis results, turning points and original history remain intact. Normal-size reports are unchanged; the 2 MiB/32 MiB limits still reject other excess. One failed instrument no longer stops later instruments; partial success is explicit.
The fixture now publishes and reads back 1,219,588 bytes with exact analysis-result and latest-bar parity. This is not a live full-OHLC replay. Related tests: 35 PASS; admission/provenance tests: 47 PASS. Production refresh and actual screens remain unverified. This does not complete 13.5. Stop after 13.6 production acceptance; 13.7 remains on explicit-owner-resume hold.


### 2026-09-10: partial release seed retry (local verification only)

PR320 deployed as 097085f6 but its 12-snapshot acceptance timed out. The saved trigger response was 409 with a partial matching matrix. The current producer rejected any matching subset as a duplicate, preventing the built-in retry from producing the missing instruments after a partial failure. The original first failure is not identified by the final 409 artifact.
The fix retains verified instruments from the same build, trigger and original time, produces only missing instruments, re-verifies all 12 and requires the existing persistent read-back before success. Mixed bindings fail closed. A complete duplicate remains 409 and is not reported as new success. No certificate, nonce, freshness or durability condition is relaxed.
Five targeted tests and 87 persistence/snapshot tests with 11 subtests pass. The partial-failure regression preserves the first six snapshots exactly and resumes only SPY/QQQ. Production acceptance remains unverified. Stop after 13.6 production acceptance; 13.7 requires explicit owner restart.

### Release retry durability final review (2026-09-11)

The complete 12-view duplicate path previously skipped persistence. A regression
reproduced HTTP 409 even when the durable readback would fail. The duplicate path
now requires the existing checkpoint verified/read-back checks before returning
409; failure remains HTTP 503 so the same release attempt can retry. No snapshot
is regenerated and the original binding/time is preserved. Local reproduction
failed before the fix and passes afterward. Production acceptance remains pending.

### Material news retention and pending AI analysis (2026-09-11)

Production received the ECB policy-rate decision at 2026-09-10T12:37:11Z
and processed it at 12:37:58Z. Event nie-fa86d64ae698a39c was stored as WATCH,
AI_ANALYSIS_UNAVAILABLE, with only family_central_bank as its severity reason.
It ranked 25th by receipt and was excluded by the 12-item public window.
At processing time retained daily usage was USD1.535688; replay of the existing
policy with retained usage and the current unchanged USD2 cap reproduced
scheduled_daily_budget_exhausted (the news lane ceiling is USD1.50). The original
per-event failure reason was not retained, so this is a reconstruction.

Candidate changes: explicit authenticated policy decisions remain material without
AI; recent material events have priority within the existing 40/12 item caps;
separate events are no longer deduplicated by source and family alone. Stored
decisions are re-evaluated without changing their identity, receipt, facts or
trading authority, with a prior-severity record and no retroactive alert.
Failed important analyses retry at most one item per cycle, with a 15-minute
backoff and three actual attempts per UTC day, through the existing budget gate.
Each attempt retains its diagnostic. A retry using a stored headline is explicitly
labeled headline-only, not a reading of the full original article.

Validation: 205 related tests including public-route concurrency and persisted
retry outcomes passed. Frontend lint/build passed; source876 and built12 UTF-8
name checks passed before the final input-scope label (repeat final checks before
release). Production migration, actual AI retry, screen acceptance and detailed
source verification remain pending. This is a 13.5 correction, not 13.7 cost work.


### 2026-09-11: GPT primary and material-news retry candidate (not yet production)

The owner approved rereading authenticated news-mail excerpts (at most 1,500 characters)
for the same stored article and sending them to the existing OpenAI API. Fingerprint and
sender authentication must both match; raw mail is never persisted. A missing or mismatched
source is disclosed as headline-only analysis. This approval resolves the earlier review block.

Primary explanations, news and production research now default to GPT-6 Astra. Existing
Terra extraction/referee/rollback and the fixed research benchmark baseline remain separate.
A repeated same-model escalation is suppressed; cache keys include requested model roles and
per-article diagnostics do not borrow another article's response model. Official migration and
pricing checked 2026-09-11: https://developers.openai.com/api/docs/guides/latest-model and
https://developers.openai.com/api/docs/pricing (Astra standard short input/output $10/$50 per
million tokens, cached input $1). Existing prices already match. No budget cap change.
Gemini's production checker now only compares supplied values/claims, uses Flash without
search, and does not lead analysis. Production OSINT calls GPT; its unused Gemini stage is
explicitly not selected, not fabricated as completed. Failed GPT research remains partial.
Historical benchmark models/results are unchanged. The legacy pipeline still contains
Anthropic phases and compatibility storage keys; it is not proof of latest-GPT adoption
across every historical/manual mode. Do not reactivate that pipeline or unvalidated BUY.

Related tests before final refinements: 310 passed, including refusal to use mismatched or
unauthenticated mail, same-model dedup, actual model attribution, and public read boundaries.
Frontend lint/build passed after model labels changed. Full final validation and deployment,
actual ECB Astra response/save/readback/browser, and Gemini role observation remain pending.
13.5 is incomplete; 13.6 implementation has not begun; stop after 13.6 production acceptance.

Final local review: full backend run 4,846 PASS / 1 skip / 2 failures (424.58s). The failures exposed coupling to the old benchmark model and a stale worker-copy assertion. The benchmark epoch is now explicitly frozen, the copy assertion follows the new provider role, and final affected checks passed (379 related checks plus the corrected benchmark set: 25 PASS). Primary judge records the provider response model and usage; mailbox retry IDs are removed at public projection. Source naming guard: 876 UTF-8 files PASS; built artifact: 12 UTF-8 files PASS. Full final-head CI and production remain pending.

### 2026-09-11: bounded official-event refresh candidate (not production)

Production ai-rejudge run 34552978703 returned scheduled_scope_required at
02:01:29Z but its HTTP wrapper called this success. Official-event tracking then
exhausted three 120-second requests; later independent refreshes never ran.
The candidate reports known scheduled-policy refusals as expected skips, keeps
HTTP/business failures as failures, and separates each refresh into its own
workflow step so unrelated failures do not suppress later lanes. A failed step
still fails the job. A running refresh is allowed to finish within its bounded
job rather than being cancelled by the next schedule.

Official-event tracking uses a cooperative 25-second work budget and at most
100 records, with non-overlapping admin calls and a saved continuation cursor.
Provider pagination honors the remaining work budget; an incomplete paginated
response cannot overwrite the existing price cache. Missing reactions remain
pending and are revisited on the next cycle. Calculations and evidence records
are unchanged. This fixes timeout/starvation; it does not enable blocked AI
purposes or unvalidated trading decisions. The cursor uses the existing runtime
cache; it is not a new claim of recovery across loss of that cache.

194 related tests passed, including continuation, deadline/cache preservation,
non-overlap, official-event persistence, public-route boundaries and HTTP result
classification. Source naming check passed for 876 UTF-8 files. Full candidate
CI, production tracking and execution of later lanes are still unverified.

### 2026-09-11: freeze the cost ledger during full checkpoint construction

After PR321, the exact 12-snapshot public/API acceptance and Pages workflow
34558204494 passed. Its producer HTTP response timed out; reconciliation recovered
all 12, so that workflow alone does not prove the final disk checkpoint. Runtime
logs reported recovery_post_genesis_checkpoint_candidate_invalid at 03:38:24Z.
At 03:47:12Z the last verified checkpoint was still 03:30:26Z, before the new
release snapshots. Final disk acceptance remains separate.

A local concurrency regression reproduced a real integrity failure: the full
checkpoint retained references to mutable cost usage rows, and settlement after
sealing invalidated that checkpoint. The bounded cost ledger is now copied under
its own lock before inclusion. The test confirms the first disk image retains
the original reservation, the live ledger retains the settlement, and the next
verified disk image includes it. No budget limit, accounting rule or recovery
verification is weakened. The test failed before and passes after the fix;
26 cost/concurrency checks pass. This is a proven race, not proof that it is the
only cause of the production error. Production correction remains unverified.


### 2026-09-11: Retry deferred cached chart publication

Production 53ad2487 retained the September 7 report for 5803 despite newer
collected history, while chartRefresh reported busy. The warm worker previously
waited its full 600-second provider cycle after losing the checkpoint lock.
During the existing 60-second interest scan it now retries only a busy,
restore-pending, or bounded cached publication. Successful unchanged results and
permanent failures retain the regular cycle. Provider/AI cadence, startup restore
checks, checkpoint authority lock, 45-second/three-publication limits and journal
ownership are unchanged. No analysis formula or trade decision changes.

A real competing-thread regression reproduces the missed opportunity before the
change; after it, cached publication proceeds at the next scan without repeating
provider or AI work. Restore-pending, bounded continuation, repeated contention,
and permanent-error cases are also covered: 35 chart/bootstrap tests PASS.
This does not guarantee acquisition during a continuously held lock. Production
rollout and latest-date chart readback remain unverified; do not mark this closed.


### 2026-09-11: remaining operational fixes integrated with PR322

The later PR321 operational readback at 03:58:05Z confirmed a new verified
checkpoint, readBackVerified at 03:45:52Z, integrity ok, with two successful
writes and one earlier failure. The release-trigger identifier was also present
in the stable physical checkpoint file. This closes that pending observation;
it does not erase the earlier integrity failure or prove the local race fix
has reached production. The 5803 chart remains dated September 7 in the last recorded public readback.

The bounded event refresh, stable cost snapshot and cached chart retry have
been integrated with the PR322 news/GPT candidate in a separate worktree.
170 integrated tests plus 11 subtests pass. Source admission records exact blob
identities for the reviewed workflow and its two regression files; those paths
are not added to the permanent allowlist. Full current-candidate CI, both
certificates, merge, production collection/AI/save/readback and browser acceptance
remain required. No 13.6 completion or iPhone migration acceptance is claimed.


### 2026-09-11: release spent/completed event reservations within the same budget

The 09:21:18Z production public cost response reported USD1.530078 scheduled
spend, six of six event runs, USD0.469922 total remaining, but zero news remaining.
The policy subtracted the original USD0.50 reserve from the shared budget even
after event spending had already been counted and after no event runs remained.
The candidate reserves only the outstanding event allocation and releases it
when the daily event quota is consumed. Pending reservations still count against
the shared budget. Daily USD2.00, the USD0.50 initial reserve, six event runs,
mode/purpose restrictions and trading gates are unchanged. No contract or
architecture cost optimization is included.

Public newsRemainingUsd and authorization now use the same calculation; the
public view additionally reports eventSpentTodayUsd/eventReserveRemainingUsd.
Four regressions fail before the change and all 18 pure policy checks pass
after it, including shared hard cap, next UTC day, remaining event protection
and purpose restrictions. 183 cost/reservation/restore/public/news integration
checks pass. The previous integrated version passed the whole backend suite
(4,869 passed, one skip, 20 subtests); that whole-suite result predates this
additional pure budget calculation, so final candidate CI remains required.
Actual production re-analysis using the released allowance is still unverified.


### 2026-09-11: reserve batch translation before calling its provider

The batch translator checked the remaining allowance but did not reserve it.
With USD0.03 left, two overlapping USD0.02-estimated calls could both start and
exceed the shared cap. A real competing-thread regression reproduced this.
The translator now uses the existing atomic reserve/settle path. A returned
reply is counted before content/translation validation, and a failed request
releases its pending reservation. The existing fixed USD0.02 estimate, model,
retry policy and daily cap are unchanged; this is not a claim of invoice-level
or returned-token cost measurement. Per-function usage detail remains a13.6
requirement.

195 news/cost/public/naming integration tests passed. The concurrency regression
also passes with provider failure and confirms there is no leftover pending
reservation. Production behavior remains unverified until the next release.


### 2026-09-11: one production candidate for news and operational recovery

The final candidate combines PR322's important-news/GPT changes with the tested
remaining operational fixes above. Production inspection showed that the old
reserve calculation would keep the new news analysis blocked, so a separate
intermediate deployment would not satisfy acceptance. The same commits and
local evidence are retained; there is one combined PR and one final deployment.
Previous separate-candidate admission pins and certificates do not certify this
combined head. Its exact diff, source proof, both certificates and current-head
CI must pass before normal merge. Production/UI/iPhone acceptance remains open.


### 2026-09-11: PR322 production and index-switch discrepancy

PR322 merged as 5f9700db9609018f75d76c0804fff32ab27d7134 after all 27 checks
passed and the one planned public-acceptance skip. Exact backend readiness was
verified at 12:12:21Z. Pages run 34597448152 passed all 11 stages, including the
12 snapshot combinations and mobile browser acceptance. These browser checks
are not the owner's iPhone acceptance.

The recovered central-bank article retained its original receipt and was
analysed by requested/returned gpt-6-astra at 12:19:33–12:19:40Z. Its bounded
mail excerpt and authenticated fingerprint are recorded; full article retrieval
and market-reaction confirmation are not claimed. A separate actual Astra call
allowed 14 pairs of public news/health reads wholly inside its execution span.
The scheduled budget reserve now releases the spent event allocation. Existing
usage survived restart; subsequent usage was added, not reset. Production full
checkpoint completion at 12:24:25Z reported no error. Direct physical-file and
owner device verification remain separate pending observations.

Manual verification run 34598877298 reached all seven scheduled-workflow steps.
Three AI purposes were skipped for scheduled scope and event analysis for the
daily event quota. Official tracking processed 27 records and retained a cursor
for 573 remaining; eight translations completed. Workflow success does not mean
all AI purposes executed. Natural scheduled execution remains a separate check.

Inspection of the public browser evidence exposed a display mismatch despite
its overall PASS: QQQ's 1D selection temporarily retained the previous S&P500
index series. useIndexChart carried data from the old key while awaiting the
new request, and the acceptance heading check only looked for the appended
ETF name. A real React/Chromium regression reproduced this with a held NDX
response: selected NDX still returned SPX data.

The follow-up binds visible hook state and cache entries to backend/index/
timeframe, rejects response identity mismatches, and keeps visibility refresh
attached when a matching cache is reused. Projection markup and public
acceptance also identify the drawn series independently from the ETF decision
anchor. Calculations, thresholds, snapshots and trading authority are unchanged.
The focused browser regression passes delayed switches, late responses, cached
returns, timeframe changes, mismatched responses, unavailable/disabled indices
and same-index refresh, with no mixed committed render. Full candidate checks
and production deployment/acceptance of this follow-up are still pending.

Local follow-up checks passed: the actual React/Chromium regression, frontend
lint/type checks, production build, and 68 admission/provenance tests. The
external naming audit passed for source text and all 12 built text artifacts.
These checks do not yet certify a merged or deployed follow-up.


### 2026-09-11: important-news history remains a production acceptance gap

At 12:56Z an independent Chromium session displayed Today, Notifications,
Settings and asset 5803 without page errors or horizontal overflow. It did not
use the owner's device or credentials and issued no write requests. The ECB
article was absent from the public 12-item list after its original receipt
became more than 24 hours old. The previously observed successful Astra
analysis does not prove that the owner can still read the article.

The follow-up separates seven-day important-news retention priority from the
unchanged 24-hour current-news/AI-retry window. The existing bounded 40-record
store and persistence are reused. A public read-only history view and an
on-demand Notifications reader expose retained older HIGH/CRITICAL articles,
with original receipt, past interpretation, explicit age and retention limits.
Reading old records does not renew freshness, alerts, analysis or SDA authority;
a failed history refresh retains the last loaded view. This is not a complete
news archive, and existing evicted records are not claimed restored.

Related backend tests: 205 passed. The React/Chromium history test passed
on-demand reads, original receipt, past labels and failed-refresh retention.
The chart and news follow-ups are combined for final CI and production
acceptance. The first chart-only candidate failed the Render skip-marker
contract; the combined change now requires backend deployment. No gate is
bypassed. Actual ECB history restoration/readback, owner device checks, final
candidate certificates and production acceptance remain open.
