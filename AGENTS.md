# ARGUS product requirements

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

Read `docs/V13_6_REQUIREMENTS.md` for the current scope and acceptance criteria.
Finish the active 13.6 production repairs and relevant acceptance first, then
continue into 13.7 under `docs/V13_7_REQUIREMENTS.md`. The owner's explicit
2026-09-15 instruction supersedes the earlier 13.7 hold. Keep 13.6 repairs and
13.7 improvements in separate change units. Reuse completed evidence; do not
start another broad prerequisite audit or rebuild the platform. Unrelated
remaining limitations are documented, not silently completed or used to block
independent improvements. Preserve auth, release proofs, histories and risk
constraints. No automated trading, orders or brokerage-account operations.

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
