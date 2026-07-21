# ARGUS Operational State Durability Map (v12.7.13)

| ストア | 分類 | 生存経路 |
|---|---|---|
| Gemini基準run(_OSINT_BASELINE_RUNS) | write-through+snapshot | persist毎+30分ledger |
| ARGUS RQ履歴(_OSINT_RPS_HISTORY・epochId付) | write-through+snapshot | 同上(DQ測定復元の源) |
| エポック(model/prompt/rubric/source) | 決定論再計算 | コードから再導出(安全rebuildable) |
| 学習語(_OSINT_TERM_OVERLAY)/検証済みメタ(_OSINT_MEMORY) | snapshot | 30分ledger+毎時watchtower |
| ミッション台帳(_MISSIONS)/soak(_SOAK) | snapshot | 30分ledger(redeploy非リセット) |
| 予測(_FORECAST_LEDGER)/成果(_OUTCOME_LEDGER)/インシデント | snapshot | 30分ledger |
| Foundation jobs/checkpoint/breadth backtest | write-through+snapshot | admin job batch commit+30分ledger |
| ポストモーテム/週次月次/challenger | process-memory→snapshot(部分) | 有界・rebuildable |
| OSINT調査本文(_OSINT_STORE) | process-memory | 意図的揮発(warmupで再構築・測定は履歴から復元) |
| 私的データ(保有/数量/単価/PnL/FIRE) | local/vault only | サーバ非保存(構造保証) |

- schemaVersion=argus-durable-v3・整合性=_DURABLE_STATE・corrupt=corrupt_ignored(last known good維持)。
- 私的フィールドはpublic-safe耐久状態に一切入らない(横断漏洩テスト固定)。
- J-Quants licensed raw rows/API secretsは耐久状態へ保存しない。保存対象は集計値、
  checkpoint、source observation hash、remote receiptのみ。
- Breadthのproduction coreは最新確定営業日から直近5年。契約上利用可能な旧期間は
  append-onlyで保持しつつ`archiveBackfillStatus=deferred`、`coreRequired=false`とする。
  追加メタデータは後方互換なoptional fieldのためdurable-v3／Market Ledger v1の
  schema versionは変更しない。
