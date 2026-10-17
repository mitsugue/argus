# ARGUS Write-Through Operational Journal (v12.2.7)
- 実装: argus_state_journal(純) — OperationalStateEvent(整合hash/冪等キー/単調sequence/private拒否)。
- **正直な耐久保証**: クリティカル遷移(forecast_issued/outcome_resolved等)で即時にローカルWAL(/tmp persist)へ書き込み(プロセス再起動の損失≈0)。リモート(ledgerブランチ)へは30分毎cronがflush — **リモート最大損失窓≦30分。厳密write-throughとは主張しない(buffered write-through)**。
- 復元: load_valid()が壊れイベントを検知・除外(corruptCount計上)し、有効イベントからlast-known-goodを再構成。30分snapshotはバックアップ/復元加速であり唯一の真実ではない。
- 私的データ(数量/単価/PnL等)はイベントpayloadで構造的に拒否。
