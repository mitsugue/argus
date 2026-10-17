# ARGUS Dual-Plane Agent (v12.2.1)
- Research Plane(research_server): サーバ/cronで24x365。公開安全データのみ — 保有/数量/取得単価/PnL/FIRE/私的メモは構造的に到達不能(既存の非漏洩テスト+plane_may_access_private=False)。
- Private Decision Plane(private_client): 保有文脈の判断は端末PWAでアプリを開いた時に更新。private worker(オーナー管理)は未構成=client_only表示。
- 正直な文言: 「市場・ニュース調査は24時間稼働しています。保有情報を含む個人判断は、端末でARGUSを開いた時に更新されます。」— private worker検証まで「保有判断も24時間稼働」とは言わない(テスト固定)。
- スケジューラ: argus_scheduler(冪等生成/lease/見逃し検知/回収)。実行体は既存caos-scan cronの /admin/missions/tick。
- 予測発行/成果解決/ポストモーテムはミッション経由でforward_live origin刻印。解決サンプルゼロの日は「学習主張はしません」。
