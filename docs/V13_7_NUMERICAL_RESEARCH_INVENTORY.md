# 数値研究資産の回収台帳

2026-09-15。本番13.7.8（602a5a9f33cb47a882f00abce962145a02ffecdc）の
永続ファイルを読み取り調査した。再取得・全期間再計算・LLM呼出しは行っていない。
本台帳は探索と回収の証跡であり、追加接続の本番受入完了ではない。

| 区分 | 所在・ID | 確認内容 |
|---|---|---|
| 原データ | `ops/imports/jpx_two_market_credit_20020802_20260710.csv` | 898,419 bytes。2002-08-02〜2026-07-10の二市場信用残。評価損益率や全指標の被覆ではない |
| 計算済み校正 | 本番永続チェックポイント `todayIntelligence.snapshots` | 1,024保存版。価格・信用残・VIX等の条件付き計算を実出力で確認 |
| 計算済み類似局面 | 同 `marketReplay.contexts` / `contextHistory` | 現行12コンテキスト、1,024参照記録。類似局面・将来ラベル・分布・校正結果。全期間特徴量索引の独立成果物とは別 |
| 旧計算成果 | 2026-08-10のcheckpoint-v2世代 `a3e6d8e510ad4212a0e0892b386cf57a` | manifestにmarketReplay 6,668,921 bytes、todayIntelligence 4,664,971 bytes。現在の状態へ上書き復元していない |
| 仕様・監査のみ | `artifacts/round2-research-coverage-v1.json` | DATA_GATED。計算済み10年成果そのものではない |
| レジストリ監査 | `artifacts/round2-jp-market-engine-registry-coverage-v1.json` | ルール登録と被覆の監査。UNVALIDATEDを維持 |
| オフライン計算コード | `argus_research_compute.py` / `scripts/run_round2_research.py` | ローカル入力のハッシュを検査する既存計算器。対応する本番用全指標manifest/resultは今回の探索で未特定 |
| 過去の一般校正 | ledgerブランチ `ledger/calibration_v1/summary.json` / `predictions.jsonl` | 実ファイルの存在・Git blobを確認。今回の日本株研究とは分離し、未精査の値を転用しない |

## 実出力の被覆と検証状態

14:25〜14:27 UTCに計算され、永続保存された出力を読み取り確認した。

- 日経平均（N225）: 2024-09-17〜2026-09-15、487営業日。
  保存ID `today-56b1cd63bb8ef92e63238240`、価格データ識別
  `bc4467872fc0c698fc4d1874533a4b4c`。
- 日経平均連動ETF（1321）: 2016-09-27〜2026-09-15、2,435営業日。
  保存ID `today-5a689d0f87701166da0c87c3`、価格データ識別
  `d20cae9d95465c7bcc8f38304b726a90`。
  現在の条件は信用倍率、信用売残、VIX水準・変化。日米相対力の入力はno_rows。
  5営業日先: 有効標本37、model Brier 0.6686、baseline 0.6552、skill -0.0203。
  1・20営業日先もskillは負。校正処理の整合性PASSを予測力PASSと解釈しない。
- TOPIX連動ETF（1306）も同期間2,435営業日。ETFの履歴を指数現物の10年履歴とは呼ばない。
- 1321の5営業日類似局面ID `replay-ecae7852ac467c23b1c37435f5bf1517`、
  手法 `market-context-replay-v3-pit-bound`。現在の校正手法は
  `today-replay-calibration-v3-market-conditioned` / `market-conditioned-knn-v1`。

10年間すべての信用評価損益率、1570信用残、海外投資家フロー、指数EPS/PER等が
そろっているとの証拠はない。独立した未使用期間での有効性受入も未完了。

## 探索範囲と未解決

現行mainと長期エンジン開発時のGitツリー、研究コード・出力監査、ローカル研究資料、
本番 `/var/data` と関連一時出力の深さ3までのファイル索引615件、GitHub Releases一覧、
Actions成果物の直近100件を探索。Actions全10,040件を調べたわけではない。
正式研究benchmarkはLLM品質検査であり、数値研究パッケージと混同しない。

非公開の既存保存先はツリー `a483ead7ada8b9c4205172931d3a51fc95cdd676` の
3,124パス（非切詰め）を名前で探索し、既存の説明・対話・保有保存manifestを確認。
独立した数値研究manifestは名前検索では未特定。全暗号化本文を研究資料として展開していない。
公開ledgerはツリー `1ec054dcdc8f9aa7674c810e77ea459fcf51123e` の855パスを確認。

現行の重い計算結果は保存されているが、毎回の新しい背景計算で特徴量・校正を作り直す
部分が残る。画面GETがキャッシュを読むことと、背景処理の増分化は別の受入項目。
古い詳細コンテキストは最新枠と上限付き参照記録へ集約されるため、過去すべての
全詳細出力が残っているとは主張しない。現在から版を固定して保存し、既存バックアップも
保全する。重い再構築が必要な範囲・処理量の見積もりは、追加索引の実在確認後に行う。
