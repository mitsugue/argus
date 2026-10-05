# 13.5〜13.7の現行受入（2026-10-05）

現行製品は13.8。旧文書の日時付き記録はその時点の履歴であり、以下を現在欄とする。
本書は受入状態の整理で、13.6の終了宣言ではない。退役機能を復活させず、未達を除外して完了ともしない。

## 13.6の現在

| 追加受入 | 実装・検査 | 本番・未達 |
|---|---|---|
| 指数と業種・登録銘柄の違い | 母集団別騰落・業種ETF比較・相対力・Today説明が存在 | 全17業種の取得と復元、場中の時刻差、指数寄与の合計整合が未確認・未達 |
| 短期と中期の併存 | 対象・期間別の比較と保存が存在 | 類似局面の材料反応、比較が崩れる条件の接続が残る。予測力は未達 |
| EPS更新と予測履歴 | 別IDの追記、入力と結果の不変保存、遠隔復元を検査 | 地図のEPSと指数方式PERは異なる定義。10年系列の全消費先への接続は未完了。実機復元照合も残る |
| イベント前後の追跡 | 事前・公式結果・改訂・反応の記録、CPIの反証検索が存在 | 10/14米CPIで事前基準から5/30/60分後までの本番確認待ち。予想値の出典不足は補造しない |
| 共通の根拠 | Today・チャート・統合AIの保存済み根拠参照と出典検査が存在 | 全系列・全画面の実値での照合は継続。退役済みの対話・保有数量は受入対象から外すが保存は保全 |

監視修復は[PR657](https://github.com/mitsugue/argus/pull/657)。本番確認実行
[37271682770](https://github.com/mitsugue/argus/actions/runs/37271682770)で67/67合格、約50秒。
これは動作監視の回復であり、上記の分析受入・予測精度の証明ではない。
予測台帳は任意のAI処理が失敗しても正本保存へ進む構造に修正済み。自然定期での保存確認は別途記録する。

## 13.7の旧記述の更新

- EPSの過去延長は「未着手・データ待ち」のままではない。構成復元と2016年までの取得処理が存在する。ただし全期間の本番充足、D04との定義統一は未完了。
- 系列被覆診断は実装済み。全系列の開始・終了・期待数・実数を本番値で埋める作業は残る。
- 七条件のD01/D02/D03/D05は既存の10年検証結果があり、基準を上回らなかった。D06の更新後の結果は製品外の確認記録で管理し、全体未検証の扱いを維持する。成績の確認と基準を上回ることは区別する。
- D07は個別銘柄の利益反応の規則があるが、市場全体の成立規則がなく成績を評価できない。「点灯規則が全くない」「原典そのもの」と断定しない。原典との照合表は製品外で管理し、原典へ合わせるか独自条件へ分けるかの判断と数式変更は未完了。
- CPIの反証検索は接続済み。FOMC・日銀への拡張はCPIの本番確認後。
- VIXの3000件窓は取得停止上限ではなくなった。3001日目を採用し、以前の原記録を保存する検査が存在する。信用残の上限は60000行へ拡張し、80%で保守の必要を知らせる。元の履歴を切り捨てない。実際の長期保存量と運用の容量確認は残る。

## 復元できない履歴と検証上の限界

2026-10-03 12:28 UTC〜10-04 03:42 UTCの見立ては保存上限超過で未保存となり、復元不能。
PR633で再発要因を修復したが、現在の材料から当時の見立てを作って埋めない。

過去データの当時の版の証明は未達（historicalVintageVerified=false）。
その時点までの情報で計算する検査と、配信元の未改訂原本が保存されていた証明を区別する。
長い履歴の取得だけでこの限界を解消したとは扱わない。

## 統合設計§14の14ケースと13.8への対応

下記は既存の自動検査への対応付け。全ケースの本番受入を一括で合格にはしない。

| ケース | 再利用する検査 | 残る受入 |
|---|---|---|
| 重要な変化なし | test_argus_market_brief.py: test_brief_reuse_ignores_hour_and_release_but_not_future_input_eligibility | 取得遅延時の画面との照合 |
| 重要発表の前後 | test_argus_market_position_memory.py: test_release_reaction_and_pricing_become_measured_entries | 10/14の実イベント追跡 |
| 突発ニュース | test_argus_news_intelligence.py: test_ai_unavailable_keeps_event_with_pending_state | 実通知の遅延とiPhone到達 |
| 重複・転載・再試行 | 同: test_duplicate_and_revision_policy、test_verified_history_restore_preserves_evidence_and_is_idempotent | 自然定期で記録が増殖しない確認 |
| 訂正・遅延到着 | test_argus_analysis_history.py: test_input_update_keeps_original_explanation_and_calculation | 本番の改訂と旧IDの照合 |
| 反証・相反情報 | test_argus_causal_event_memory.py: test_reasoning_retrieval_retains_contradiction_only_after_it_was_known | CPIの実反応との照合 |
| 過去判断の再現 | test_argus_analysis_history.py: test_later_result_is_appended_and_wrong_session_or_preissue_data_cannot_score | 原本の当時版の証明は未達 |
| 前提変更 | test_argus_private_membership.py と画面の自動保存・旧アーカイブ保全の検査。数量なし登録文脈を受領後に分析へ反映。保有管理は退役済み | 本人の登録操作での保存確認と別端末照合 |
| 数値とAIの不一致 | test_argus_market_brief.py: test_validate_ai_brief_rejects_invented_numbers_and_orders | BUYは引き続き無効 |
| 予測満期・結果不足 | test_jp_market_candidates.py: test_per_line_target_moves_with_the_eps_and_same_session_both_is_ambiguous、test_scoreboard_marks_thin_candidates_and_the_two_without_data | 実際の採点追記数 |
| 取得障害 | test_prediction_ledger_workflow.py、test_smoke_execution.py、test_run_intel_collect.py、test_argus_public_feed_fetch.py | 収集停滞箇所の実測。総額上限で止める旧要件は撤廃済み |
| 再起動・復旧 | test_argus_analysis_history.py: test_worker_restart_restores_previous_inputs_and_history_read_is_readonly、test_verified_remote_head_survives_a_restart_and_skips_the_full_restore | EC2遠隔記録の滞留解消、実機復元 |
| iPhone | 13.8.38のPages受入のモバイル・PWA検査 | 実機の通知、ピンチ、復元を未確認のまま保持 |
| 履歴の増大 | test_argus_analysis_history_backup.py: test_large_snapshot_is_split_and_limits_never_truncate_history、test_argus_causal_event_memory.py: test_analog_retrieval_cost_is_bounded | 本番の長期保存量・請求実測 |

手元全体検査と配信検査の結果は各変更の実行記録で確認する。個々の自動検査が通っても、右欄を完了へ変えない。
オーナー判断の必要な変更は選択肢と根拠を揃えて提示する。原典との不一致を、説明文だけで解消した扱いにしない。


## 13.8.51への継続分（2026-10-06）

旧版の「信用入力が未接続」「公表日まで未実装」「保存量を測る処理がない」は、
以下のコードと合成検査の存在に合わせて読み替える。実データの受領・利用・復旧は
対応する非公開確認帳で別々に追跡し、旧版全体の終了宣言へ置き換えない。

| 対象 | 実装・検査の到達点 | 引き続き確認すること |
|---|---|---|
| JPX信用残 | 新旧公式書式、公表日の再試行、公表済み取得漏れの失敗判定、認証付き読戻し照合（PR669・671） | 自然定期の公表当日受領・保存と本人画面 |
| 信用評価入力 | 公式六入力の算式、入力と計算digest、既存台帳保存・読戻し、D01への受け渡し、月報の不足週補完（PR672・674〜676） | D01の実利用、有効性、当時の資料版。新しい取込時刻を当時の公表時刻にしない |
| 公表予定と古さ | 収集側と利用側で同じ公式営業日暦を使用。対象週・次の予定・公表後の未取得を点検（PR673・679） | 実公表時刻、系列ごとの実測、本人向け統合表示 |
| 運用点検 | 既存管理認証の中で取得更新と点検時刻を分離、名前の点検、分析窓の8割警告、SQLite原本の固定表件数とDB/WAL容量の読取り（PR678・680） | 本番実測、長期容量と遠隔復元。3000件窓と40件の巡回上限を原本保存上限と呼ばない |
| FUTURE MAP | 日本時間の更新日と古さの表示、既存キャッシュへの受領記録と当日の補完判定保存、読取未実行を成功応答しない保護（PR677・681） | 通知・朝の自然実行と再起動後の照合。過去に失われた成功時刻は作らない |

13.8.51の配布識別をそろえる更新は、上記の計算式・閾値・保存処理・受領記録を
再変更しない。BUYは無効のまま。端末復元・通知・CPIの反応・請求照合などの
未実施項目を版番号から完了とは扱わない。
