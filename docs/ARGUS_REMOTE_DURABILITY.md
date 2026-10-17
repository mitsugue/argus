# ARGUS Remote Durability (v12.2.8準備)
- 状態: not_persisted/local_committed/remote_pending/remote_committed/remote_failed/recovered_*/integrity_failed。
- バックエンド: 既存GitHub ledger(cron 30分毎)=configured。サーバ自身はgit push不可 — **リモート実損失窓≦30分。60秒保証は主張しない(将来のDB/Storageアダプタ実測後)**。
- 照合(reconcile): 冪等キー+整合hashで一致/ローカル先行(再送)/リモート先行(再生)/競合を判定。**タイムスタンプ単独で上書きしない・競合は黙殺せずインシデント**。
- クリティカル承認: forecast/outcome/incident/soak/学習承認は「ローカル確定」と「リモート永続」を区別表示 — remote_pendingを完全永続と呼ばない。
- First Forward-Live Gate: 予測を**生成しない**検証専用(replay/mock/backdate/重複を拒否)。
