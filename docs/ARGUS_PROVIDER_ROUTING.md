# Provider Routing (v12.2.0)
- Role別モデル: ARGUS_OPENAI_MODEL_{EXTRACT,STANDARD,WAR_ROOM,REFEREE,ROLLBACK}(既定=現行_OPENAI_MODEL)。
- GPT-5.6は仮定しない — /admin/ai/capability-probe(実測)で確認後にのみ設定。
- シャドウ: ARGUS_OPENAI_SHADOW_ENABLED=1 + SAMPLE_RATE(決定論ハッシュ・オーナー判断に不使用)。既定OFF。
- 昇格ゲート: 可用性実測/スキーマ成功/privacy無回帰/コスト無違反/ホールドアウト非劣後/ロールバック保持。
