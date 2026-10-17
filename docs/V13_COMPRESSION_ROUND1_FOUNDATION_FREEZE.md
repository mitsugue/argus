# V13 Compression — Round 1 Cut / Foundation Freeze

Status: non-production Draft convergence. This document records the Round 1
contract; it does not authorize a merge, deployment, production configuration
change, recovery-authority change, or the start of an acceptance clock.

## Foundation

Round 1 is based on the accepted Registry/Measurement and Proof foundations,
merged in that order without rewriting either accepted head:

- PR C accepted head: `5845bb59eea83a3a6d7af9014260fdcb669e707e`
- PR C integration merge: `c11572c830f34b90b8a14b0307437993916f84e8`
- PR D accepted head: `a9ba2427ace965c09392925e4c91608ca4c2bdbd`
- final C+D integration base: `99d711319e2a5a24239009247b842d49918775d8`
- final C+D integration tree: `99e72cc1f97cf3c2b42ae4ddc76b483f69d35610`

The formal roadmap position remains **1 / 18 — Recovery storage / durability
redesign**. Round 2 and Round 3 are outside this change.

## Product foundation freeze

The primary product surface is exactly Today, Holdings/Watchlist,
Notifications, and Settings. Asset Detail is contextual. There is no
independent Market, Replay, AI Review, Prediction, Calibration, FIRE, Trade
Journal, Diagnostics, Research, or What-if page.

Removing a page does not remove its background intelligence. Prediction and
calibration engines, replay/history, FIRE computation, AI judgment, scenarios,
position and exposure logic, event and catalyst analysis, research/OSINT,
scheduled acquisition, provenance, and embedded decision behavior remain
available to the existing runtime. Round 1 does not consolidate them into a
new decision authority.

The protected local stores and active recovery-durability implementation remain
in place. Browser cloud upload, retry, and push behavior is not introduced.

## Runtime contraction

The frozen structural targets are:

- frontend TypeScript/TSX modules: 261 to 159
- TSX modules: 122 to 56
- CSS files: 55 to 20
- direct runtime dependencies: 14 to 5
- independent engine pages: 1 to 0
- event-status reads per refresh: 2 to 1
- persistent AppShell health timer: 1 to 0
- Flask route catalog: 244 to 158
- workflows: 25 to 24

The 158-route trust split is 62 `PUBLIC`, 87 `AUTH_OPERATIONAL`, 6
`OWNER_SYNC`, and 3 `RECOVERY_PROOF`. The approved obsolete public GET surface
is removed. Authenticated/operator siblings and all six owner-sync contracts
remain. Product health fields use the canonical data-quality response, and
event-backbone product fields use the canonical active-events response.

The two morning-digest schedules and their job live in the market-alerts
workflow with explicit schedule/manual discrimination. `osint-check.yml`
remains.

## Recovery Phase A integration law

The runtime adapter is optional shadow instrumentation. Its exact feature flag
is `ARGUS_RECOVERY_PHASE_A_MEASUREMENT_ENABLED`; only the literal value `1`
enables it, and this change does not enable it in any environment. Its only
artifact path is
`/var/data/diagnostics/recovery-measurement/measurement-v1.json`.

The five instrumented mutation classes are:

1. `core.ops_journal_transition`
2. `core.mission_transition`
3. `core.batch_cursor`
4. `durability.receipt_ack`
5. `startup.restore_transition`

All other Registry mutation classes remain explicitly uninstrumented. Bounded
scalar observations cross the adapter after successful authority actions. The
sole transient non-scalar handoff is the already-sealed checkpoint mapping for
streaming accounting; it is neither copied nor retained. Measurement failures
cannot change readiness, health, journal, WAL, checkpoint, compaction, restore,
Remote Journal, or investment-decision outcomes.

Detailed checkpoint accounting is limited by the Measurement Core policy to
successful JP/US post-session boundaries, the first checkpoint after identity
change, or a future owner-authorized exact request. Normal session sampling is
bounded to two detailed samples per day. Measurement persistence happens only
after authoritative checkpoint completion and after the durable checkpoint
lock is released.

Registry policy, exact producer build SHA, Measurement schema, and the adapter
instrumentation digest determine the generation identity. Missing or malformed
exact build identity disables measurement for that boot. Identity drift starts
a new shadow generation; old observations are not reinterpreted.

Measurement truth remains `SHADOW`, `INCOMPLETE`, non-authoritative,
`NOT_PROVEN`, and `acceptanceClockStarted=false`. The proof seam is a null
verifier. Public exact cold recovery remains `NOT_PROVEN` and
`hardRpoClaimPermitted=false`. Remote Journal health, a measurement artifact,
or Stage1/V2 flags are not proof evidence.

Stage1 remains disabled, V2 authority remains false, and Soak remains unarmed.
Legacy checkpoint, WAL, Remote Journal, restore, backup, and nonce authority are
not changed by this product contraction.

## Superseded work

- PR #152: `FULLY_SUPERSEDED`; administratively close as no longer needed.
  Do not merge, rebase, cherry-pick, or revive it.
- PR #154: `SUPERSEDED_ARCHITECTURE_AND_SOURCE`; administratively close without
  porting its old implementation.

Keep both branches/worktrees as audit and rollback references until the one
independent Round 1 macro review passes. Their later administrative closure is
not authority to delete recovery data or production resources.

## Deferred owner gates

Only evidence-dependent work is deferred: external access-log confirmation for
authenticated/operator route retirement, production observation and burn-in,
recovery authority generations and cutover, production configuration or
capacity changes, and the separately authorized Round 2/3 product work.

The Round 1 Draft must remain unmerged and undeployed until independent macro
review and explicit owner sequencing.
