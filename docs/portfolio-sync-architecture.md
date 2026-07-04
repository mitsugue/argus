# ARGUS Portfolio Sync / Snapshot Architecture (v11.9.0)

オーナーの方針: 「Mac/iPhone/iPadの自動同期は諦めない。保有データと判断履歴は
恒久保存して、後から検証・学習に使う。」この文書はその土台の現在地と将来経路を
正直に記録する。

## 3層アーキテクチャ

### A. ローカル層(稼働中・従来どおり)
- `localStorage`(`argus.assets.v1` = 銘柄+保有数量+取得単価)。
- オフラインで動作、サーバー依存なし。UIは常にここを読む。

### B. 私的クラウド同期層(稼働中 — クライアント暗号化方式)
- **既存のパスフレーズvault**(`web/src/lib/vault.ts`)がこの層の実体。
  端末上でAES-GCM(PBKDF2 200k)暗号化 → バックエンド中継 → ledgerブランチに
  **暗号文のみ**保存。パスフレーズを知る端末だけが復元・マージ(sync-v2:
  銘柄単位マージ+tombstone+deviceId)。
- つまり **Mac/iPhone/iPad の保有自動同期は今日この方式で動いている**。
  encryptionStatus = `client_encrypted`。サーバーは平文を一度も見ない。
- サーバー側に**平文**の保有を置く方式(Supabase/私的DB等)はモデル定義のみで
  **無効**(`scanner._PORTFOLIO_SERVER_SYNC_ENABLED = False`・環境変数では
  有効化できない設計)。エンドポイントはadmin認証後でも `403 disabled` を返す。

### C. スナップショット/監査層(v11.9.0で新設)
- `argus.portfolio.snapshots.v1` — 1日1件の追記スナップショット(上限60件):
  保有サマリ・テーマ/通貨露出・リスク信号・レジーム所感・買い増し余地・
  使用価格・鮮度フラグ・欠損・アプリ/エンジン版数・整合ハッシュ。
- `argus.decision.audit.v1` — 銘柄ごとの判断監査(readiness=decisionContext、
  当時価格、flowClass、futureReturn1d/3d/5d/20d は将来のバックテスト用placeholder)。
- 両キーは `BACKUP_KEYS` に追加済み → **既存の暗号化vaultに同乗**して恒久保存+
  端末間同期される(クラウドは暗号文のみ)。

## 公開面の保証
- 公開エンドポイントが返すのは `/api/argus/portfolio-sync/status`(層の状態のみ)。
  機微キー(quantity/averageCost/costBasis/marketValue/unrealizedPnl/accountType/
  portfolioTotal/positions/ownerNote…)は `argus_portfolio_sync.contains_sensitive`
  のトリップワイヤでpytest+smokeの両方が監視。

## 真の「サーバー側」自動同期に足りないもの(意図的に未実装)
1. オーナー認証/オーナーロック(現状adminトークンのみ・ユーザー概念なし)
2. 私的バックエンドテーブル or 暗号化オブジェクトストレージ
3. 競合解決UI(conflictStatus=conflict の手動マージ画面)
4. 端末登録/デバイスラベル管理(deviceIdは既存・表示名管理が未)
5. その経路のクライアント側暗号化(vault方式の踏襲を推奨)
6. リカバリキー(パスフレーズ喪失=復元不能、の緩和)
7. 保持ポリシー(スナップショット無限蓄積の整理方針)

推奨: 認証を入れる時も**クライアント暗号化を維持**(vault方式の拡張)。
平文をサーバーに置く必然性は現状ない。
