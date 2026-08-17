# Round 2 macro convergence

This document is the operational contract for the Round 2 decision pipeline:

`MarketTruth -> PIT evidence -> SHO-JP -> Risk constraints -> Single Decision Authority -> Seven Sign -> Prediction Ledger`

The implementation authority is the supplied Canonical SHO RFC, SHA-256
`69a631ebc549b3bede6356cabf338e38d9418fc3683821198ef9a3c1eb440d51`.
The RFC is not reconstructed from comments, prompts, or legacy heuristic names.

## Authority invariant

There is one action vocabulary and one reducer: `BUY`, `HOLD`, `WAIT`,
`REDUCE`, or `EXIT`.  SHO, Turtle, scenarios, AI, legacy labels, Entry Scout,
market posture, and risk models generate evidence.  They do not vote and they
cannot override the reducer.  Correlated evidence is deduplicated by primitive
factor identity before risk constraints or support references are produced.

Owner position context is joined only on the device.  The bounded context says
only whether the asset is held and coarse risk/concentration/add-permission
bands.  Quantity, cost basis, price paid, P/L, returns, holdings lists, and owner
identity are not accepted by the public evidence or authority contracts.
`REDUCE` and `EXIT` are impossible unless the local position state is `HELD`.
Missing or unknown owner context fails to `WAIT`; it is never inferred from a
backend downside incident or a server watchlist.

Legacy scanner actions, majority labels, TOP3, dynamic exit, digest calls,
Primary Stance, AI-primary merge, old ActionLevel, and Entry Scout calls are
compatibility evidence only.  They cannot notify an action, append a canonical
prediction, or become the displayed Primary Action.  Old ActionLevel level 5
(`HOLD_ONLY`) is not Seven Sign level 5 (conditional BUY-favoured); the schemas,
identities, and labels remain separate.

## SHO evidence law

The sealed proposition registry preserves four lineages:
`SHO_ORIGINAL`, `ARGUS_CANDIDATE`, `TURTLE_REFERENCE`, and
`SEVEN_SIGN_CANDIDATE`.  Registry records are immutable, versioned,
content-addressed data.  No expression evaluation, generated execution, or
automatic promotion is supported.

The seven original families retain their exact meaning:

| ID | Canonical evidence | Current lawful repository coverage |
|---|---|---|
| D01 | Two-market total short margin balance below JPY 800bn | Official JPX weekly archive, 2002-08-02 through 2026-07-10; proposition evaluation is supported, but direct index outcome calibration remains data-gated. |
| D02 | 1570 margin ratio greater than or equal to 1 | `MISSING`; no committed point-in-time 1570 ratio/reverse-fee history. The obsolete below-1 heuristic is not SHO authority. |
| D03 | Japan relative strength | Direct Nikkei 225/TOPIX history is `DATA_GATED`; any 1321/1306 proxy is explicitly a proxy candidate and never relabelled as an index. |
| D04 | Nikkei EPS times PER at 17/18/19/20/21 | `LICENSE_BLOCKED`; the committed Nikkei valuation file is a template only. Values are never applied to ETF 1321. |
| D05 | Publication-gated foreign investor flow | `MISSING`; the ledger seam exists but no committed observation archive exists. |
| D06 | VIX MACD transition with level, velocity, percentile, regime | Durable VIX history and source-confirmed original MACD parameters are absent. Original parameters remain `UNKNOWN`; any 12/26/9 calculation is an `ARGUS_CANDIDATE`. |
| D07 | Earnings quality multiplied by market reaction | `MISSING` for broad validation; transient catalyst facts are not synthetic earnings quality. |

Every unavailable field remains `MISSING`, `UNVALIDATED`, `LICENSE_BLOCKED`,
or `UNKNOWN`.  Missing evidence can reduce confidence or force `WAIT`; it is
never zero-filled, inferred from receipt time, or silently treated as false.

## Research plane

Research is a deterministic offline process.  It must not import `scanner`,
provider clients, `requests`, credentials, live caches, owner state, or an
implicit clock.  A run binds dataset versions and hashes, the PIT policy,
registry/parameter versions, exact build SHA, calendar and adjustment policy,
cost/slippage assumptions, and any seed.  Equal identities must produce equal
canonical bytes.  Conflicting bytes under one frozen identity fail closed.
Lifecycle state is identity-bearing: freeze, recorded holdout, Golden access,
and retune lineage change the research identity.  Golden opening is additionally
bound to the predeclared research-data identity, so dataset/version/hash changes
must reseal rather than silently replacing the reserved case.

Every bar and event carries its own exact session decision cutoff.  Revisions
must carry `knownAt`, share the original session cutoff, and be visible by that
cutoff; a later global evaluation cutoff cannot backdate a historical trigger.
Close-derived signals execute only at the next session open.  Same-close fills
without an independently proven pre-close issuance time are rejected.

Partitions are mutually exclusive `DEVELOPMENT`, `HOLDOUT`, `GOLDEN`, and
`EMBARGO`.  The embargo covers the largest preregistered horizon.  A failed
holdout cannot be retuned under the same identity.  The late-July/August 2026
JP reversal is reserved as `GOLDEN` and cannot be opened before the registry,
rule, parameter, and partition identities are frozen.  In this repository the
raw direct-index Golden input is absent, so the Golden result remains
`DATA_GATED`, not fabricated from an audit summary or ETF proxy.
The manifest precommits separate non-Golden and Golden dataset hashes without
reading the sealed Golden files.  Opening requires the exact expected event and
instrument, a validated-reversal marker, complete required horizons, an
evaluated counterfactual, and content-addressed Risk Kernel and SHO-reversal
references already sealed in that event.  Compact acceptance checks separately
record whether Risk-Off was reached before the reversal, whether Band Walk
ending was detected, the VIX-DC/SAR/MACD/25DMA trigger observations, and the
WAIT missed-opportunity measurement.  False or absent observations remain
honest false results; they are never converted into a successful Golden claim.
Declared embargo width is checked both as calendar span and against actual bar
sessions.  Walk-forward outcomes crossing a stage boundary are unscorable.
Recording a holdout requires the exact verified sealed artifact; its compact
proof binds the input commitment, per-event metrics, counterfactuals, every
required horizon, and lifecycle timestamps.  Empty or unscorable holdouts
cannot be marked passed or open Golden.

Required outcomes are 1, 5, 10, and 20 sessions.  Forty sessions is accepted
only when preregistered.  Unavailable outcomes and probability metrics are
null/unscorable.  False-positive, false-rally, and false-reversal metrics remain
distinct.  Counterfactuals share one PIT path and one execution/cost
policy: BUY_NOW, SHO reversal, VIX dead cross, SAR flip, MACD golden cross,
25DMA reclaim, Turtle confirmation, and WAIT.  WAIT missing a validated
reversal is recorded as missed opportunity, never as realised owner P/L.

The Turtle shadow contains only versioned 20/55-day breakouts, 10/20-day exits,
and ATR/N.  Unsupplied historical details stay `UNVALIDATED`; Turtle is not a
hard veto on a validated early SHO reversal.

Only compact, bounded, content-addressed summaries and proofs may be consumed
outside the research process.  Bulk/raw/licensed bars never enter the live
backend, browser bundle, or Git history.
The authoritative builder accepts exact raw dataset bytes, rechecks every
declared SHA-256, and constructs the input receipt internally.  An unbound
in-memory artifact or caller-authored receipt cannot be verified or used to
record a holdout result.  Retained detail is partition-aware so Golden and
holdout evidence cannot be displaced by an earlier development tail.

## Production calibration gates

The architecture is complete without purchasing data, but production claims
remain gated until the following evidence is lawfully available and passes the
listed acceptance tests.

| Gate | Missing and why | Current fallback | Confidence / production effect | Future acceptance test |
|---|---|---|---|---|
| 1570 margin and reverse fee | No exact PIT archive | None; D02=`MISSING` | Lowers coverage; blocks D02 validation and production credit | Hash-bound import; exact publication/availableFrom; no future revisions; >=1 boundary; missing/malformed/future/stale hostile cases; holdout replay. |
| Direct Nikkei 225/TOPIX OHLCV | No lawful committed direct-index archive | Explicit 1321/1306 proxy candidate only | Blocks direct D03/outcome and Golden claims | Exact instrument identity; complete OHLCV; corporate/calendar policy; PIT proof; proxy cannot satisfy index request; development/holdout/Golden isolation. |
| Nikkei EPS/PER | Template only; licensed field | None; D04=`LICENSE_BLOCKED` | Blocks valuation ladder production use | Licence/right metadata; exact source/publication time; EPS/PER units; 17-21x ladder; no ETF-price mixing; retention/display rights test. |
| Foreign-flow archive | No committed observations | None; D05=`MISSING` | Lowers confidence; blocks D05 validation | Publication timestamp and revision cutoff; complete reporting periods; future revision rejection; regime and ablation report. |
| VIX history/original parameters | Runtime source is not a durable research dataset; original parameters not confirmed | ARGUS candidate only | Blocks SHO-original D06 and probability calibration | Hash-bound complete series; source-time proof; parameter source identity; original vs candidate separation; transition/false-cross holdout tests. |
| Earnings quality | No comprehensive point-in-time fundamentals history | Current catalyst facts remain context only | Blocks D07 validation | Exact filing/publication/revision times; deterministic quality definition; market-reaction join after availability; restatement/no-lookahead tests. |
| Sector/style/rotation history | No complete durable PIT archive | Missing factors | Reduces stock-lens coverage | Versioned constituents/classification; publication availability; survivorship-safe replay; sector/style ablation. |
| Tachibana live API | Credentials and real field behaviour unavailable | Existing seam reports `UNKNOWN` | No provider priority/authority change | See checklist below. |

## Tachibana live-acceptance checklist

Credentials/configuration are deliberately outside this task.  When access is
available, acceptance requires all of the following before any authority or
priority change:

1. Record the contracted API/product identity, licence, retention, display,
   redistribution, and derived-data rights.
2. Capture exact documented field names and types for symbol, venue, asset
   identity, source/exchange timestamp, receipt timestamp, session, currency,
   price, OHLCV, adjustment, depth, flow, and status.  Unprovided capability is
   `UNKNOWN`; no field is invented.
3. Prove timezone/DST/calendar interpretation and strict missing, malformed,
   future, stale, weekend, holiday, pre-open, in-session, and completed-EOD
   behaviour with recorded fixtures.
4. Prove per-observation source age; transport receipt cannot substitute for
   venue time and aggregate percentiles cannot hide one stale required row.
5. Reconcile duplicates/revisions and preserve provider disagreement and
   alternates through MarketTruth, snapshot, cache, handoff, and compact
   artifacts.
6. Demonstrate exact instrument identity (direct index versus ETF proxy),
   currency, corporate-action/adjustment semantics, lot/session rules, and
   complete OHLCV requirements.
7. Run shadow-only parity against current providers with no notifications,
   decisions, calibration, or owner data.  Record coverage, latency, error,
   freshness, disagreement, and failure-mode results.
8. Pass the provider hostile suite, PIT/no-lookahead replay, closed-schema
   checks, bounded cache expiry, exact 4 GiB gate, rights audit, and an explicit
   owner-reviewed authority-change proposal.  Credentials are never committed.

Until every item passes, Tachibana stays `UNKNOWN` and cannot affect SDA,
Seven Sign, Prediction Ledger, or provider selection.

## Ledger and deployment boundaries

The SDA adapter is append-only and content-addressed.  It binds issuance and
cutoff, exact truth/SHO/Risk/SDA/Seven identities, Primary Action, confidence,
targets, invalidation, missingness, conflicts, and dissent.  It does not mutate
existing prediction rows.  Owner-aware decisions remain device-local and are
not written to the public ledger.  The browser appends the canonical result and
its recomputed adapter to a device-local, idempotent bounded tail (128 records,
1 MiB); corrupt or unavailable storage fails without overwrite, the key is not
cloud-backup eligible, and quantity/cost/P&L/raw owner fields are rejected.
Public/non-owner forward-live records retain mode separation and append-only
outcome resolution.

Seven Sign is a distinct projection, never the old ActionLevel.  Its candidate
level may be shown only as shadow evidence.  The production-calibration
registry is deliberately empty: caller-supplied expectancy arrays or asserted
OOS/immutable flags cannot activate a production level.  A future activation
requires a separately verified artifact whose exact identity is pinned in the
closed registry under explicit owner review.

This branch does not merge, deploy, restart production, modify environment or
keys, activate Stage1/V2/Soak, configure Tachibana, place orders, or begin Round
3.  Today and Asset Desk may project the canonical result with minimal fields;
there is no new page or expanded card surface.
