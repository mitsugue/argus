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
Finish the active naming migration and 13.5 production verification, then
implement 13.6 from that accepted baseline. Stop after 13.6 production acceptance.
Do not investigate, prototype, implement, open PRs, or deploy 13.7 until the owner
explicitly resumes it next week or later. A date change or 13.6 completion is not
permission. Existing budget/restoration/collection bug fixes remain in 13.5.
