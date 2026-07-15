# ARGUS v12.2.9 Qualification Outcome(soak中断・リモートジャーナル喪失の記録)

判定日: 2026-07-15(v12.2.10是正準備時・本番無変更の文書化のみ)

## QualificationOutcome

```
status: invalidated_by_remote_journal_loss
buildSha: 211bc9c
infrastructureStabilityObserved: true
buildScopedSoakWorked: true
startupRestoreWorked: true
forwardLiveLocalProofWorked: true
remoteJournalDurabilityFailed: true
completed72Hours: false
notProfessionalRcEvidence: true
```

## 観測事実(2026-07-15 read-only診断)

正しく動作した(v12.2.9の成果):
- build-scoped soak(新SHA非継承・同一SHA再起動を中断として記録)
- 起動即時復元+/readyz(restored/ready・cron非依存)
- FFL noBackdate(epoch比較)— 候補4件が全チェック通過・locally_proven
- プライバシー/US-only/JPフォールバック/スケジューラ回収

失敗が確定した:
- **リモートflush経路(caos-scan→memory-snapshot→ledger)のペイロードに
  opsJournal/opsJournalMeta/soakLastPersistAtが含まれず、運用ジャーナルは
  一度もリモート永続されなかった**(WAL 146件がプロセス再起動で消失・
  歴代カウントも喪失)。
- ack=復元時刻プロキシのため remote committed/pending 表示が両方向に不正確。
- soak中断のgap検証不能(soakLastPersistAt未同乗)→ soak=interrupted
  (unverified)となり operationally_verified に到達不能。

## 帰結

- v12.2.9の稼働はインフラ安定性の観測記録としては有効だが、
  **72時間Professional RC証拠としては無効**。
- v12.2.10(argus-durable-v3=journal同乗+検証済みread-back ack+実測SLO)を
  PR経由で統合し、デプロイ後に**新規のbuild-scoped 72時間soak**を開始する。
- ロールバック先: 211bc9c(それ以前へ戻すとv12.2.9の是正も失われるため
  緊急時のみ)。
