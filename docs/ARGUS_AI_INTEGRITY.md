# ARGUS AI Integrity (v12.2.0)
- 中央実行: `argus_ai_gate.ai_execution_result` — 全プロバイダ呼び出しの共通結果。
- store=False: 全OpenAI Responses呼び出しで強制(test_argus_v12_2_0がgrep固定)。
- usage: 同一応答オブジェクトから取得(共有グローバル不使用)。
- model_only/search_failed はLIVE調査に偽装不可・主因証拠不可・ベンチ不適格。
- Chat Completionsフォールバックはdegraded扱い(ベンチ/2x不適格)。
- Structured Outputs: 現行は頑健パーサ+検証(互換アダプタ・degradedマーク)。完全移行はP2。
- 未承認の直接呼び出しはAPPROVED_CALL_SITESテストで失敗する。
