# Rollback (v12.2.0)
- モデル: ARGUS_OPENAI_MODEL_ROLLBACK に旧IDを常時保持。Render envで各roleを戻す→再デプロイ不要(env再読込はデプロイ)。
- コード: git revert + main push(Render自動)。OSINTストアは非永続=再走必要。
- 基準: エポックが変わるため旧エポックの校正と混ぜない(filter_runs_to_epoch)。
- 学習昇格: LearningProposal.rollbackId で旧設定に復帰(champion保持)。
