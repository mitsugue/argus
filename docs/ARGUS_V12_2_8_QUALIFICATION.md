# ARGUS v12.2.8 Qualification Outcome(72時間soak早期終了の記録)

判定日: 2026-07-14(オーナー判断・v12.2.9是正リリース準備時)

## QualificationOutcome

```
status: invalidated_by_confirmed_defect
infrastructureStabilityObserved: true
completed72Hours: false
defects:
  - forward_live_timezone_comparison
  - soak_not_build_scoped
  - startup_restore_readiness_ordering
  - operational_journal_transition_wiring
notARegressionClaim: true
notProfessionalRcEvidence: true
```

**reasonJa**: 「本番観測で中核機能の確認済み欠陥を検出したため、既知の欠陥を含むbuildの
72時間完走を待たず、修正版v12.2.9へ移行する」

## v12.2.8(SHA 5651479)で観測できた事実 — 正直な整理

観測できた(インフラ安定性):
- クリティカルなクラッシュなし(missed=0 / failedSafe=0)
- 耐久復元(durable integrity=ok / restoreSource=ledger)の実働
- スケジューラ回収(incident open→resolved)の実働
- プライバシー/ブリッジガード(publicLeakSafe=true / US-only / JPフォールバック)の実働

観測により**確認された欠陥**(72h完走をProfessional RC証拠として無効化):
1. **forward_live_timezone_comparison** — FFLゲートのnoBackdateがJST発行時刻と
   UTC現在時刻を文字列比較。本番実測でliveForecasts=2が`candidate_ineligible`
   (`noBackdate:false`)になることを確認(JST09時以降は構造的に常時誤判定)。
2. **soak_not_build_scoped** — soak startedAt(23:23:24 JST)が実Deploy live
   (約23:33 JST)より早い。tick壁時計の無条件書込+復元時のbuildSha無検証継承。
3. **startup_restore_readiness_ordering** — 起動復元とsoak開始/readinessが
   構造的に順序付けられていない(復元が30分cron/特定GET依存)。
4. **operational_journal_transition_wiring** — incident/soak遷移がジャーナル
   未配線(incident解決済みでもevents=0)。

## 意味論

- これは**リグレッション主張ではない**(notARegressionClaim=true): 欠陥はv12.2.8で
  混入したのではなく、観測強化により可視化された既存の意味論的欠陥である。
- v12.2.8の稼働時間は**Professional RC証拠として扱わない**
  (notProfessionalRcEvidence=true)。インフラ安定性の観測記録としてのみ保持する。
- 本記録はAPIによる本番状態の変更を伴わない(読み取り観測+文書化のみ)。

## 帰結

- v12.2.9(是正リリース)をPR経由で統合し、デプロイ後に**新規のbuild-scoped
  72時間soak**を最初からやり直す。
- 旧v12.2.8 soakの時計はv12.2.9に継承されない(previousSoakとして履歴保存のみ)。
- ロールバック先: 5651479。
