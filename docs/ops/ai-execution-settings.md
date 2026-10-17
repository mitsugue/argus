# AI 実行設定（2026-09-30 オーナー指示）

2026-09-21 の「日 $0.50・月 $10 の本番上限」は、9/21 以降に統合AIの生成が一度も走らない結果（見立て・重要ニュース・イベント分析が1週間更新されない）を招いた。
オーナー指示（2026-09-30）「まずきちんと動かした上で削る。上限撤廃して全て動くように」により、既定値を次のとおり変更した。

| 設定 | 既定 | 環境変数で戻す |
|---|---|---|
| 金銭上限による停止（日次・月次・回数） | **停止しない**（会計・表示は継続） | `ARGUS_AI_BUDGET_ENFORCED=1` |
| 主分析レーン（ai_judgment / entity_profiles / candidate_research / mover_explanation / osint_research / owner_dialogue） | **有効** | `ARGUS_AI_FULL_ANALYSIS=0` |
| イベント分析レーン（pre/post） | **有効** | `ARGUS_EVENT_AI_OPT_IN=0` |
| モード | SCHEDULED_AI（変更なし） | `ARGUS_COST_POLICY_MODE` |

残るもの: トークン上限（1リクエスト 65,536 推定トークン）、モード別の権限（手動系は確認必須）、使用量の記録、公開の支出表示、`market-brief` の `generationGate`（拒否が起きた場合の理由と再開時刻）。

13.8 では、この状態で計測した機能別の使用量から削る箇所を決める（推定でなく実測から削る）。
