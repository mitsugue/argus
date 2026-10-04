# FUTURE MAP の受け渡し(2026-10-04)

FUTURE MAP は「外部の見立て」の一覧で、ARGUS の判断ではありません(確率なし・BUY 無効のまま)。
表のデータは研究側が作り、アプリは検証して表示するだけです。毎週の更新に版上げ・配信は要りません。

## 流れ(人の手を介さない)

1. 研究側の週次更新(月〜土の夜24時=火〜日の 0:00 JST)が、点検に合格した `future_map.v1` を
   既存の非公開保存先(`ARGUS_LAYER2B_PRIVATE_REPO`)の `market-analysis/v1/future-map/current.json` に書く。
2. 続けて(書き込みがあった時も「変更なし」の時も)、同じ Mac のログイン済み gh で知らせを1回送る:
   `gh workflow run caos-scan.yml -R mitsugue/argus -f only=future_map`
   新しい鍵ファイル・新しいルート・新しいワークフローは使わない。
3. 既存の収集ワークフロー `caos-scan` の `future-map` ジョブ(`only=future_map` の時だけ動く)が、
   GitHub の Secrets にある既存の管理者キーで、既存の管理者向け収集ルート
   `POST /api/argus/institutional-intelligence/collect` に `{"only": "future_map"}` を送る。
   この指定の時は保存先を1回読むだけで、収集の他の処理は動かない。アプリは
   `argus_future_map.validate` と名前の点検を通してから、メモリと保存ディスク(`future_map.json`)に置き、
   `lastError` / `lastChangedAt` / `sha` / `lastReadOkAt` / `lastTrigger` を返す。
   読み込めなければ応答は 502 で、ワークフローは失敗になる。点検に落ちた文書は表示に使わず、前の版を出し続ける。
4. 公開の読み取り口 `/api/argus/future-map` はメモリの値を返すだけ(取得しない)。

## 予備

- 収集の巡回では読まない。
- 毎朝 6:00 JST ごろに1日1回だけ予備の読み込みを判断する(`_future_map_fallback_tick`)。
  その日の 0:00 JST 以降に読み込みが成功していれば何もしない(`skipped_already_read`)。
- 再起動直後は保存ディスクの版を出す。保存された版が1つも無い時だけ、1時間に1回読みに行く。

## 守ること

- 出どころは中立の記号(`src_a` など)だけで、公開の応答には出さない。人の名前・字幕本文は入れない。
- 受け口は文書を受け取らない。入力は既存の非公開保存先だけ。
- 採点(期日を過ぎた行の到達判定)は別の変更単位。

## 確かめ方

- `gh run list -R mitsugue/argus --workflow caos-scan.yml --event workflow_dispatch --limit 1` が success で、
  `future-map` ジョブの記録の `ok` が true、`sha` が保存先の版と一致すること。
- `/api/argus/future-map` の `lastReadOkAt` が知らせの時刻、`lastTrigger` が `notification`、`fallback` が
  `{"decision": "skipped_already_read"}`(知らせが届いた日)であること。
