# ARGUS Public/Private Boundary — Route Audit (v12.2.0 Phase 9)

Baseline: 218 routes (22 admin-gated `_require_admin`). 分類:

## 公開(無認証)— redacted設計・オーナー固有ペイロードなし
- health/status系: `/healthz`, `/api/argus/system-health`, `/api/argus/data-quality`(redacted console), `/api/argus/bridge/status`(redact済み), runtime-manifest
- 市場データ(watchlist水準・保有/数量/口座情報は構造的に不在): japan/us-watchlist, supply-demand, dashboard-events, price-history(cached-only), cause-attribution, osint/investigation(redacted設計), osint/canary, osint/memory-snapshot(public-safe), learning-memory
- 公開POST(enqueue/決定論のみ・外部AI/任意URL fetch不可): osint/deep-dive(決定論+キュー), osint/terms(語のみ・本文不受理), osint/verify-gaps(決定論のみ), osint/url-verify(enqueueのみ・SSRF防御), 調査/翻訳キュー(enqueueのみ)
- 恒久ガード: `test_argus_v12_rc.py` PUBLIC_GETS横断(contains_sensitive+秘密語+執行語+確率断定+JP稼働主張) + 自己漏洩検査(contains_sensitiveでcritical化)

## cron/機械経路(トークン/署名前提)
- quote-push(bridge HMAC), market-scan/crypto-scan/movers-push系(GitHub Actions), institutional-intelligence/collect(admin token)

## admin限定(`_require_admin` 22本)
- osint/agents-run, osint/canary-run, osint/benchmark-run(v12.1.7), provider診断, missed詳細, api-state full, 復元系

## オーナー領域(サーバー非保持=端末ローカル)
- 保有数量/取得単価/投信/FIRE/判断監査/通知本文はlocalStorage+暗号化vaultのみ。サーバーAPIに存在しない(構造的漏洩不可)。

## v12.2.0判断
- フルオーナー認証(全公開GETのトークン化)は**今スプリントでは見送り**(PWA/homescreen起動の互換リスク)。
  - 根拠: 公開面はwatchlist水準+redacted設計+横断テスト固定で、オーナー固有ペイロードが構造的に不在。
  - 実施済みの追加防御: 最高リスク経路(スカウト起動/ベンチ/復元/full state)はadmin施錠済み。
  - 将来フラグ: `ARGUS_OWNER_AUTH=1` でオーナー認証ミドルウェアを有効化できる素地(未実装機能はフラグOFFのまま)。
- 残る公開ルートは本書と PUBLIC_GETS が正典。新規ルートはどちらかに分類しテストに追加すること。
