# ARGUS product requirements

毎回の作業と報告では `~/argus-handoff/引き継ぎ_Codex_2026-10-04.md` の §1b「先回りして拾う」を読み、依頼の目的・波及影響・本番確認・期限・判断待ちを点検する。

Read `docs/JP_MARKET_ENGINE_REQUIREMENTS.md` before changing analysis, data,
UI, AI prompts, persistence, or release behavior. It is an owner requirement.

Use 日本株分析エンジン for the overall user-facing name and `jp_market_engine`
for the code name. Use functional names for its components. Do not introduce
personal names or identifiers derived from personal names into this engine.
The concrete retired-name policy and original source records belong outside
the product; never copy their terms into fixtures, comments or audit reports.
Run `scripts/product_naming_guard.py` with the external naming policy for both
source and built artifacts. A missing policy is an unperformed check, not PASS.

Preserve holdings, settings, prediction history and validation results during
schema changes. Record compatibility periods and removal conditions. Verify
formula, threshold and action parity independently from identity/hash changes.
Do not activate BUY or treat unvalidated frequencies as predictive probabilities.
Distinguish implemented, tested, production-observed and complete in reports.

## 現行要件の優先順位（2026-10-05）

現在の開発対象は13.8。まず `docs/V13_8_REQUIREMENTS.md` を読む。
同じ事項の指示が食い違う場合は、オーナーの最新の直接指示、13.8要件、
`docs/V13_7_SHAPEUP_REQUIREMENTS.md` の機能整理、
`docs/JP_MARKET_ENGINE_REQUIREMENTS.md` の共通要件の順で解決する。
本ファイルは作業の入口、設計書は製品仕様、受入台帳は検証状態を扱う。
仕様の記載だけで実装済み・本番確認済みとは判断しない。

13.5〜13.7の資料は、現在も有効な未完了項目と履歴の参照に使う。
「13.6を終えてから13.7へ進む」等の旧版の段階順を13.8の開始条件にしない。
退役した対話・保有管理・FIRE・売買記録・外部AI相談・個別リアルタイム監視・
引け直前の予測を、旧資料に残っているだけの理由で復活させない。
未完了項目は実コードと既存の証跡に照合し、現在必要な修復・検証を行う。
無関係な残課題で独立した改善を止めず、完了の水増しもしない。
既存の出来事・根拠・予測・履歴の保存経路を再利用し、並立する基盤を作らない。

## 承認の扱い

オーナーがこの会話で明示した承認は、対象の作業・公開先・内容の範囲で継続する。
同じ範囲の承認を毎回取り直さない。引き継ぎ書の「承認済み」は経緯の記録であり、
自動承認審査を上書きする規則ではない。拒否時は実際の理由と対象を確認し、
設計書の禁止事項・検査失敗・権限審査を混同しない。
公開コード・文書・検査結果の提出承認を、認証情報・所有者の記録・本番応答本文を
公開する承認に拡張しない。拒否を避けるために検査や保護を削除しない。

## Release merge shape

The Pages release binds the exact pre-merge certificate to the second parent
of a two-parent merge commit, with identical candidate and merge trees. Use
`gh pr merge --merge --match-head-commit <verified-head>`; squash, rebase and
fast-forward merges cannot enter this release path. For frontend-only changes,
set the merge commit subject explicitly to include `[skip render]`, as well as
the PR title. Verify the existing required checks and exact admission proofs;
do not relax the tree or certificate checks to repair a failed deployment.

## Patch release identity

For each user-visible production correction, advance the patch version and
keep product/frontend/backend identity manifests and exact release expectations
consistent. Do not keep a patch number fixed solely because 13.6 acceptance is
unfinished. A patch increment is not a declaration that all 13.5 or 13.6 work
is complete. Preserve the executing build identifier and the existing update,
cache, holdings, and history protection mechanisms.

## 13.8の製品方針

統合AIをTodayの先頭に置き、蓄積したニュースと出来事の記憶から市場の現在位置を
把握して各機能の根拠を読む。結論を先に示し、根拠の詳細へつなぐ。
欠測・遅延・古さは各機能の取得経路で確認し、推測で補わない。
予測として示す新しい材料は過去データで評価し、成績と件数を併記する。
費用は実測して無駄を減らすが、総額上限を理由に必要な解析を止める旧方針は適用しない。
同時実行数・再試行間隔・入出力長など、障害や重複実行を防ぐ制限は維持する。
