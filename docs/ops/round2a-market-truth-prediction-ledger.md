# Round 2A — Market Data Truth and Prediction Ledger

Status: non-production Draft integration. This document describes contracts in
this branch; it does not activate a final decision authority, SHO, Stage 1, V2
authority, Recovery Proof, or a production acceptance clock.

Foundation: `9d23f719ec365eb5d4e9f6e98dc4c111dc9fdba0` (the frozen Round 1
integration). Round 1 Recovery and public-boundary invariants remain controlling.

## Authority inventory and convergence

| Existing path | Round 2A classification | Treatment |
|---|---|---|
| moomoo bridge, J-Quants, Twelve Data, Finnhub, Yahoo, FRED, CoinGecko, Coinbase, and Toushin provider responses | `CANONICAL_SOURCE` candidates, never truth merely because transport succeeded | Scanner adapters validate values, timestamps, coverage, and provider status before constructing canonical observations. |
| `_PUSHED_QUOTES`, quote/history/provider caches, and ledger-branch read caches | `CACHE` | Cache age and per-row source age stay separate. A fresh cache may contain delayed evidence; a refreshed partial response may not rejuvenate an absent row. |
| `argus_market_data_truth.py` | `CANONICAL_SOURCE` selection contract | Provider-neutral observations, point-in-time filtering, explicit policy selection, dissent, and bounded decision snapshots. |
| `argus_market_clock.py` | `CANONICAL_SOURCE` for calendar/session identity | Reused for JP, US, and continuous-market maturity. No second market-open authority is introduced. |
| `argus_market_ledger.py` | `DERIVED_EVIDENCE` / point-in-time source concepts | Its append-only `availableFrom` ideas are retained; it is not a competing quote selector or Prediction Ledger. |
| `argus_today_intelligence.py`, chart intelligence, replay features, indicators, regime, supply/demand, event context | `DERIVED_EVIDENCE` | They must consume cutoff-filtered inputs. They cannot upgrade source freshness or select the final user action. |
| provider-specific legacy row status and browser `liveQuote` projections | `PRESENTATION_ONLY` compatibility | They decay after refresh failure and are not a canonical authority. |
| `argus_decision_ledger.py` sealed v2 records and `scripts/run_prediction_ledger.py` | `CANONICAL_SOURCE` Prediction Ledger | One immutable IssuedDecision + append-only OutcomeResolution/Evaluation family. |
| `argus_ledger.py`, old `data/predictions.jsonl`, `ledger/days`, `ledger/scores`, and `ledger/summary.json` | `LEGACY_DUPLICATE` / `unknown_legacy` | Historical data stays readable and is never upgraded to `forward_live`. New compatibility events are append-only and calibration-ineligible. |
| removed `argus_ledger_v4.py` / `argus_v4_dryrun.py` and their overwrite-oriented workflow | `DELETE_DEAD` | Their pure Brier/RPS math converged on `argus_calibration.py`; current/latest-price outcome substitution is removed. |
| rule labels, signals, AI judgment, stance, plans, and digest posture | `EVIDENCE_ONLY`, `DUPLICATE`, or `PRESENTATION_ONLY` | Exact emitter classification is in `round2a-single-decision-authority.md`. None is promoted by this round. |

## Canonical Market Data Truth

`argus_market_data_truth.py` is pure, provider-neutral, bounded, and contains no
credentials or network calls. An observation binds:

- instrument, symbol, market, asset type, fact type, currency, and values;
- `observedAt`, `receivedAt`, `knownAt`, optional `freshUntil`, and revision;
- provider key, adapter identity, source reference, dataset/provenance identity;
- independent freshness (`FRESH`, `DELAYED`, `STALE`, `UNAVAILABLE`) and
  completeness (`COMPLETE`, `PARTIAL`, `MISSING`);
- canonical session from `argus_market_clock`;
- observation schema, quality policy, authority policy, and content identity.

Unknown keys, non-finite or inconsistent market values, timestamp inversion,
future-known rows, unbounded provenance, and false COMPLETE/MISSING shapes fail
closed. Freshness is recomputed at the requested as-of time. Cache lifetime is
not substituted for source age.

Selection preserves the selected observation, bounded alternates, rejected
candidates, quality at the cutoff, disagreement evidence, and the exact
`repo-market-provider-priority-v1` policy identity. Adapter registration alone
never grants authority.

## Repository provider policy

Current priorities are based on implemented repository behavior, not a future
provider assumption:

| Scope | Explicit order |
|---|---|
| JP quote / index proxy | moomoo, then J-Quants |
| JP OHLCV | J-Quants |
| JP fund NAV | Toushin Library |
| US quote / index proxy | moomoo, Twelve Data, Finnhub |
| US OHLCV | Twelve Data, Finnhub |
| FX quote/rate | Yahoo, FRED |
| Crypto quote | CoinGecko, Coinbase |

Provider HTTP success does not imply FRESH or COMPLETE. Future or missing source
timestamps cannot be LIVE. Mock macro values remain UNAVAILABLE and cannot make
an aggregate LIVE/COMPLETE. Provider disagreement remains visible instead of
being overwritten. Index facts remain explicitly ETF proxies where that is what
the repository actually observes.

## Point-in-time fabric and no-look-ahead proof

`observations_as_of`, `select_history_as_of`, and `point_in_time_rows` admit only
facts whose `knownAt`/`availableFrom` and observation time are at or before the
cutoff. Among visible revisions, selection is deterministic and binds source,
dataset, revision, counts, admitted digest, exclusions, and proof digest.

Replay additionally binds the normalized dataset hash to that proof. Current
cache fallback and `latestValue` backdating are forbidden. Chart/calibration
auxiliary payloads require a content seal and knowledge time; nested history and
knowledge timestamps are mechanically audited, so a later bar cannot be hidden
inside an earlier outer receipt. Current event/cache payloads are usable only
with their real acquisition time. `noFutureLeakage=true` requires verification
of the row filter, revision selection, auxiliary temporal integrity, and ledger
publication-time evidence.

Historical imports without a trustworthy original first-known timestamp use the
actual ingestion/migration time and retain that limitation; a bar date is not
silently re-labelled as publication time.

## Canonical decision-time snapshot

`build_decision_snapshot` accepts at most 64 explicit requests and binds:

- exact decision cutoff and later generation time;
- strict 40-character producer build SHA;
- selected, alternate, rejected, and missing evidence per instrument;
- provider, source time, freshness, completeness, session, currency, revision;
- Market Truth schema and provider/quality/disagreement policy identities;
- bounded derived evidence and a deterministic snapshot ID/digest.

The maximum serialized snapshot is 256 KiB. The scanner deterministically caps
candidate records as well as unique instruments and reports omitted IDs/counts;
overflow never disappears inside a generic exception. A sealed prediction must
refer to the exact selected observation, not an arbitrary candidate.

## Canonical Prediction Ledger

`argus_decision_ledger.py` v2 is the storage-neutral record contract. Mode is
inside the sealed identity and is exactly one of:

- `historical_replay`
- `forward_live`
- `shadow`

Changing a mode, truth reference, target session, horizon, engine/build,
distribution, target ladder, policy, missing evidence, or dissent invalidates
the record. Legacy records without a sealed mode classify as `unknown_legacy`
and never silently become forward-live evidence.

An IssuedDecision binds the exact Market Truth snapshot/observation, issued time,
instrument, explicit horizon and independent session maturity contract, engine
and build identities, categorical probability distribution and class ordering,
threshold ladder, confidence, policy hash, evidence IDs, and explicit missing or
dissent facts. Round 2A records scenario predictions only; a legacy BUY/WAIT/etc.
string is not a canonical action because its causal inputs are not yet sealed.

OutcomeResolution and Evaluation records are new immutable events referencing
the IssuedDecision. They never edit it. Exact target-session OHLC evidence is
required; today's/latest price, wrong session, wrong target time, and a bare
numeric price are rejected. Missing or malformed truth creates `UNSCORABLE`, not
a zero return. Retry events carry sequence and previous-event identity.

Typed evaluation metrics include actual-path MFE, MAE, horizon end return,
target/invalidation touch and time, Brier/RPS score, and extensible opportunity
metrics. A same-bar target/invalidation collision is `AMBIGUOUS` without finer
evidence. WAIT metrics are explicit `avoided_mae` and `missed_mfe`, never P&L.
Only `forward_live` evaluation records are accepted for calibration aggregates.

## Append, indexes, and workflow

The canonical runner performs no network request. It consumes the bounded
`canonicalPredictionLedger` snapshot plus the immutable manifest-generation
journal, segment inventory, index, and aggregate. Every load/open/append
bounded-discovers the retained immutable segments, reconstructs the single
exact genesis-to-head chain, requires one matching immutable manifest
generation per committed segment, and replays retained authority before
accepting either derived projection. It writes:

- immutable, content-addressed, hash-chained run segments;
- an immutable, versioned, manifest-bound complete segment inventory and root;
- immutable versioned bounded pending-index and forward-live calibration
  projections, whose segment-ID filenames also witness a prepared generation;
- a contiguous immutable manifest-generation journal installed after its
  staged segment as the sole commit point;
- `commit-head.json` and `manifest.json` only as repairable projections.

Same ID/same content is idempotent; same ID/different content is fatal. Pending
index overflow is fatal rather than eviction. The index and calibration
aggregate are verified derived projections: neither can survive a missing or
invalid canonical source segment. Complete verification bounded-enumerates at
most 8,192 files in each immutable segment, index, aggregate, inventory, and
manifest generation family; it does not discover unbounded provider/request
history. Their exact serialized bytes share a 1 GiB retained-authority cap that
is checked from file metadata before segment parsing. Restoring older mutable
projections cannot hide a surviving newer immutable generation witness.
Publication installs the derived versions and inventory, stages the immutable
segment, and installs its immutable manifest generation last as the commit
point. A direct load rejects every uncommitted prepared tail. Only a retry that
deterministically rebuilds the exact prepared segment ID (therefore the same
run ID, run time, input digest, producer/runner identities, predecessor, and
content) may finish it; another input or append may not adopt it. Missing,
tampered, reordered, disconnected, or truncated segments, projection
witnesses, inventories, and manifest generations fail closed. Diagnostics and
mutable compatibility projections do not become authority.

The workflow stages the runner and all canonical modules from the exact
triggering SHA before switching to the ledger branch, verifies checksums, and
serializes the ledger writer. Legacy `ledger/days`, `scores`, and `summary.json`
are read-only compatibility artifacts. Closepin/scout products in this workflow
are explicitly `shadow`, `SHADOW_DERIVED`, noncanonical, and
calibration-ineligible.

## Future Single Decision interface

`DecisionEvidenceBundle -> SingleDecisionAuthority -> PrimaryAction` is defined
but inactive. The five future actions are `BUY`, `HOLD`, `WAIT`, `REDUCE`, and
`EXIT`. The evaluator always returns `INACTIVE`, `primaryAction=null`, and
`authority_inactive`; it has no activation flag, route, hook, UI, storage write,
or side effect. Owner position/cost/P&L remains device-local. REDUCE, EXIT, and
owner-aware HOLD cannot be derived on the backend without that private join.

No SHO, Turtle, Seven Sign, order, size, target, or broker semantics are encoded.

## TACHIBANA_API_READINESS

- canonical adapter seam ready: **YES**. `ProviderAdapterRegistry` accepts a
  provider implementation, validates bounded typed outcomes, and does not grant
  it selection authority. A future Tachibana adapter is one provider adapter,
  never a second Market Data Truth system.
- fields currently blocked on the real API: exact instrument identifiers and
  coverage; quote/trade/order-book field names and units; exchange/source,
  receipt, and first-known timestamps; timestamp precision and timezone;
  auction, halt, session, holiday, and market-status semantics; entitlement and
  delayed-data indicators; partial-response and per-field error semantics;
  authentication/session expiry, rate limits, retries, and disconnect behavior;
  currency/lot/adjustment/corporate-action fields; field-level authority and
  fallback eligibility.
- tests runnable without the API: adapter registration grants no authority;
  adapter outcome shape/caps; provider-neutral observation validation;
  timestamp inversion/future/malformed rejection; fresh/partial/stale/missing
  fixtures; explicit current JP precedence; dissent/alternate preservation;
  point-in-time revision selection; decision snapshot determinism and bounds;
  replay no-look-ahead; neutral candidate benchmark.
- exact live acceptance when access arrives: capture and document actual schemas
  without committing credentials; map only observed supported fields; verify
  exchange/source/receipt/known time ordering and clock skew; exercise open,
  lunch break, closing auction, halt, holiday, and after-hours states; test full,
  partial, empty, malformed, entitlement, auth-expiry, rate-limit, timeout,
  reconnect, and duplicate/revision responses; compare per field against current
  J-Quants/moomoo sources and preserve disagreement; verify failover/failback and
  no false freshness; verify currency/lot/corporate-action behavior; run
  exact-SHA live shadow burn-in with zero authority effect before any owner
  approval to alter JP field priority.

No credential is requested or stored by Round 2A, and env/config is unchanged.

## Storage/performance and CI

The resource benchmark exercises bounded observations, snapshots, predictions,
outcomes, canonical hashes, and deterministic contract construction. Separate
runner tests exercise retained-chain deletion/tamper/reorder detection while
any local immutable generation witness remains, calibration-source replay,
immutable segments, bounded projections, exact prepared-tail recovery,
manifest-journal rollback/deletion detection, and deterministic replay. The
mandatory CI job runs
both in an exact 4
GiB/no-swap cgroup (`memory.max=4294967296`, `memory.swap.max=0`), requires zero
OOM/oom-kill deltas, pins the triggering head SHA, enforces the 256 KiB snapshot
cap, and uploads a scalar proof. Browser polling count is unchanged.

## Round 1 non-regression and stop gate

Round 2A does not change the public route count/trust split, four visible
surfaces, readiness/health authority, Registry policy, Recovery Measurement
authority, checkpoint/WAL authority, or public Recovery Proof. Measurement stays
SHADOW/INCOMPLETE and default-disabled. `exactColdRecovery` stays `NOT_PROVEN`,
`hardRpoClaimPermitted=false`, Stage 1 and V2 authority remain disabled, and soak
and acceptance clocks remain unarmed.

After the exact-head Draft PR gates pass, development stops at
`SHO_CANONICAL_SPEC_REQUIRED`. The latest owner-supplied Canonical SHO
Instruction is required before any SHO implementation.
