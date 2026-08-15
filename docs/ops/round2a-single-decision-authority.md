# Round 2A: inactive single-decision contract

Status: **IMPLEMENTED AS AN INACTIVE CONTRACT ONLY**

Base integration: `9d23f719ec365eb5d4e9f6e98dc4c111dc9fdba0`

This round adds a bounded, content-addressed `DecisionEvidenceBundle` contract
and an isolated `SingleDecisionAuthority` interface. It does not install a
decision authority. Its sole runtime result is:

```json
{
  "schemaVersion": "single-decision-authority-v1",
  "status": "INACTIVE",
  "primaryAction": null,
  "decisionId": null,
  "evidenceBundleId": null,
  "authorityPolicyId": null,
  "supportingFactIds": [],
  "blockingReasonCodes": ["authority_inactive"]
}
```

No input, environment variable, feature flag, caller boolean, caller action,
vote, trusted constructor, route, or stored record can change that result.
`WAIT` is a real decision and is therefore not used as the inactive fallback.

## Placement and privacy boundary

The backend currently owns public/cached market evidence. Holdings, quantity,
cost basis, price paid, return and P/L remain device-local. A future authority
that can truthfully distinguish `BUY`, `HOLD`, `WAIT`, `REDUCE`, and `EXIT`
therefore cannot run on the current public backend payload alone.

The only valid future boundary is after the private join in
`web/src/hooks/useAssetIntel.ts`, or an equivalent device-local pure function.
The public bundle and the local `OwnerDecisionContext` remain separate until
that point. The owner context is closed and coarse:

- `positionState`: `HELD | NOT_HELD | UNKNOWN`
- `positionRiskBand`: `LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN`
- `concentrationBand`: `LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN`
- `addPermission`: `ALLOWED | BLOCKED | UNKNOWN`

It contains no owner identifiers or position values and must never be uploaded.
`HOLD`, `REDUCE`, and `EXIT` are not truthful without `HELD`. An unknown owner
state must fail closed to a future evaluated `WAIT`; that rule is documented but
not implemented in Round 2A. Existing position-agnostic `HOLD` values do not
prove that an asset is held.

Version 1 deliberately permits only an `ASSET` subject across `JP`, `US`,
`CRYPTO`, and `FUND`. A market or portfolio command cannot be mapped truthfully
onto the five asset actions without a separate approved subject contract.

## Existing action-emitter classification

The classifications below describe how each existing output may relate to a
future single authority. They do not change current runtime behavior.

| Existing module / seam | Current behavior | Classification | Future integration rule |
|---|---|---|---|
| `argus_evidence_pack.py::build_pack` and `scanner.py::_build_evidence_pack` | Public-safe, cached evidence projection | `EVIDENCE_ONLY` | Adapt bounded scalar facts or a source reference; never promote `allowedUse` booleans into an action. |
| `argus_signal.py::resolve_signal` and `web/src/domain/actionLevel.ts::resolveSignal` | Maps legacy strings into a seven-level permission signal | `EVIDENCE_ONLY` | Its code/permissions may be provenance facts. `EXIT`, `DEFEND`, or `ENTER` cannot directly become the new action. |
| `argus_action_priority.py` and `web/src/domain/actionPriority.ts` | Ranks attention; explicitly not an order | `EVIDENCE_ONLY` | Rank/reason codes may support urgency only. Rank cannot select the action. |
| `scanner.py::get_action_labels` | Produces legacy action strings, confidence and references; provider-capable internally, cache-only on the public route | `EVIDENCE_ONLY` | A future background adapter may project facts. Do not accept its raw `action` as authority. |
| `argus_scenario.py`, `argus_trade_plan.py`, `argus_position_exposure.py`, `argus_portfolio_strategy.py`, and `argus_session_brief.py` | Scenario, plan, exposure and session constraints | `EVIDENCE_ONLY` | Only bounded observations and policy constraints may enter the bundle. No plan string can set the primary action. |
| Decision Value / Decision Quality / forecast and outcome ledgers | Shadow/research scoring and historical feedback | `EVIDENCE_ONLY` | Provenance or calibration facts only. History may not create production authority. The inactive authority writes no ledger row; the separate canonical Prediction Ledger records evidence, never a final action. |
| `argus_primary_stance.py::resolve_primary_stance` and `web/src/domain/primaryStance.ts::resolvePrimaryStance` | A duplicated Python/TypeScript "single stance" policy | `DUPLICATE` | Keep unchanged now. Before a future cutover, convert to evidence or remove it from primary-action selection; do not run two authorities. |
| `scanner.py::_arbitrate_ai`, `web/src/domain/assetDecision.ts::mergeAiPrimary`, and `resolveAssetDecision` | Selects/merges AI and rule judgments | `DUPLICATE` | AI and rule outputs become challenge/provenance facts. Voting, freshness, or a raw model action cannot set the new action. |
| `scanner.py::get_action_alerts`, daily-digest action synthesis, and `web/src/lib/todayCall.ts` | Additional action-like aggregation | `DUPLICATE` | Current outputs remain untouched. They cannot be normalized or majority-voted into the new authority. |
| `web/src/domain/argusEngine.ts::synthesizeArgusDecision` and `web/src/domain/argusTodayView.ts::buildArgusTodayView` | Market-level `BUY | WAIT | SELL` display decision | `DUPLICATE` | Out of the v1 asset subject. `SELL` is ambiguous and must never be guessed as `REDUCE` or `EXIT`. The Today surface remains unchanged in this round. |
| `web/src/domain/assetDesk.ts::buildDecisionFirstView`, `web/src/domain/decisionView.ts`, `web/src/domain/commandSummary.ts`, and Asset Desk components | Builds and displays current/owner/entry commands | `PRESENTATION_ONLY` | Current synthesis stays unchanged while inactive. At a separately approved cutover it may display one authority result but must not choose or rewrite it. |
| `web/src/types/action.ts`, `web/src/domain/actions.ts`, and action badges | Legacy label catalog and presentation copy | `PRESENTATION_ONLY` | Do not expand or reinterpret the new five-action type through these catalogs in Round 2A. |
| Notifications and judgment-log UI | Diff/noise control and owner-visible history | `PRESENTATION_ONLY` | No notification or log write is caused by the inactive interface. Later notification policy requires a separate gate. |

`EVIDENCE_ONLY` means a closed scalar projection may be considered, not that an
existing conclusion is trusted. `DUPLICATE` means the code is an action chooser
today and cannot remain a rival chooser after any future cutover.
`PRESENTATION_ONLY` means it may render a result but must not manufacture one.

## DecisionEvidenceBundle v1

`argus_decision_evidence_bundle.py` is a pure stdlib producer/validator.
`web/src/domain/singleDecisionAuthority.ts` mirrors its structural validation
and canonical body encoding. Neither file imports runtime application code.

The bundle contains exactly:

- `schemaVersion = decision-evidence-bundle-v1`
- `bundleId = deb-<sha256(canonical body)>`
- `privacyClass = PUBLIC_EVIDENCE`
- `subject = {kind: ASSET, instrumentId, market}`
- one closed `horizon`
- exact UTC `asOf` and `informationCutoffAt`, at whole-second precision
- exact producer build, evidence-policy hash, policy ID and generation ID
- at most 32 scalar facts
- at most 12 sorted missing-reason codes
- at most 12 sorted conflict-reason codes

The canonical body is at most 65,536 bytes. The producer build is a full,
lowercase 40-hex SHA. When scanner integration is separately approved, its
source must be `scanner.py::_backend_exact_sha()`, which accepts only the full
40-hex `RENDER_GIT_COMMIT`; a short or unknown SHA cannot produce a bundle.

Facts are sorted and duplicate-free by `factId`. Each fact has exactly:

- a bounded ID, closed kind and closed role;
- one tagged scalar: boolean, JavaScript-safe integer, canonical decimal,
  bounded enum, or exact UTC timestamp;
- a closed unit, observed time, freshness and evidence quality;
- a bounded source identifier, not a URL, headline, prompt or raw payload.

Decimals use a canonical string with at most eight fractional digits. JSON
floats, exponent notation, NaN, infinity, negative zero and trailing fractional
zeroes are rejected. This removes cross-language float rendering drift from
the content address.

No arbitrary dict, nested supporting payload, prose explanation, provider
response, exception text, secret, owner field, quantity, cost/P&L, prompt, model
output, price target, order, size, broker instruction, activation control, or
`SHO` state is part of the contract.

Supporting evidence in a future result is reference-only and capped at eight
fact IDs. Facts are not copied into the result. Round 2A returns no supporting
references because no decision exists.

## Authority semantics that are not active

The only declared primary-action vocabulary is:

```text
BUY | HOLD | WAIT | REDUCE | EXIT
```

There is no `SELL`, `TRIM`, `ADD`, `BUY_DIP`, `ENTER`, model-action, order side,
or arbitrary string fallback. There is no mapping implementation in this round.

Any later evaluated implementation requires all of the following rules to be
pinned before it can replace an existing chooser:

1. one validated bundle, one exact policy identity and one local owner context
   produce exactly one primary action;
2. a caller-provided action, boolean, confidence, vote or proof can never select
   the result;
3. missing build/policy/schema/generation identity, stale required evidence,
   unresolved conflicts or unknown owner state fail closed to evaluated `WAIT`;
4. `HOLD`, `REDUCE`, and `EXIT` require `positionState=HELD`;
5. `BUY` requires a policy-defined eligible non-held/add context and cannot be
   inferred from an existing `ENTER`, `ADD`, or AI string;
6. `SELL` cannot be inferred as `REDUCE` or `EXIT`;
7. the authority remains pure: no order, size, target, broker, notification,
   persistence, health/readiness, or recovery side effect.

These rules describe a later review gate. The current TypeScript result union
contains only `INACTIVE` and `primaryAction: null`; no active constructor exists.

## Exact inactive-interface slice file scope

This scope describes only the future Single Decision Authority interface slice,
not the surrounding Market Data Truth and Prediction Ledger work in the Round
2A macro branch.

Added:

- `argus_decision_evidence_bundle.py`
- `test_argus_decision_evidence_bundle.py`
- `web/src/domain/singleDecisionAuthority.ts`
- `web/scripts/single-decision-authority.test.cjs`
- `docs/ops/round2a-single-decision-authority.md`

Changed:

- `web/package.json`, only to register the focused structural test in `lint`

Not changed or imported by this inactive-interface slice:

- `scanner.py`
- any Flask route or route catalog entry
- `web/src/hooks/useAssetIntel.ts`
- any component, route or navigation item
- checkpoint, WAL, Remote Journal, Registry or Recovery Proof code
- any localStorage, IndexedDB, vault, backup or sync code
- any workflow, deployment or production flag

## Exact later integration surface (separate approval)

The smallest future cutover would modify only the seams below. This list is not
authorization to change them.

1. `scanner.py`
   - project already-collected cached evidence after producer success;
   - use `_backend_exact_sha()` and an exact evidence policy/generation identity;
   - attach bundles only to an existing cached response or existing background
     snapshot; do not add a route, provider fetch, mutation or checkpoint key.
2. `web/src/types/actionLabels.ts`
   - accept an optional public bundle field without changing legacy payloads.
3. `web/src/hooks/useAssetIntel.ts`
   - perform the device-local owner-context join and make the sole authority call.
4. `web/src/domain/assetDecision.ts`
   - retain AI/rule provenance for review, but stop selecting the primary action.
5. `web/src/domain/assetDesk.ts` and `web/src/domain/decisionView.ts`
   - become presentation adapters for the one result; do not synthesize a rival
     current/owner/entry action.
6. Focused tests: `test_argus_decision_spine.py`,
   `test_argus_public_operational_boundary.py`,
   `web/scripts/asset-desk.test.cjs`,
   `web/scripts/product-integrity.test.cjs`, and a new scanner adapter test.

The market-level `argusEngine`/Today action remains out of scope until an owner
chooses whether the authority is asset-only or receives a separately designed
market subject. No automatic market-to-asset mapping is acceptable.

## Storage and index requirements

The inactive Single Decision Authority interface stores nothing. It adds no
checkpoint state, Registry row, mutation, WAL record, localStorage key,
IndexedDB database/version, cache, pointer, audit row, forecast, outcome, or
notification. The canonical Prediction Ledger implemented elsewhere in the
Round 2A macro has its own append-only storage contract. This interface slice
must not create a second store.

If public bundle retention is later approved, it must use a separate bounded
IndexedDB object store rather than whole-array localStorage or the monolithic
backend checkpoint:

- immutable records keyed by `bundleId`;
- one current-pointer store with a unique compound key
  `(instrumentId, horizon, evidencePolicyId)`;
- indexes on `(instrumentId, horizon, asOf)` and `generationId`;
- canonical hash and schema/policy/generation checks before write;
- transaction commit plus canonical read-back verification before current
  pointer replacement;
- rejection of older `asOf` and identity drift, never silent reinterpretation;
- fixed record, byte, per-key history and global-history caps approved by the
  owner before the store exists;
- cursor/batch garbage collection, not `getAll()` of all payloads;
- private context and decision audit only inside the existing device-local,
  export/vault boundary; no private server index.

Provisional engineering ceilings for the future store are one canonical bundle
at 64 KiB, at most eight retained generations per current key, at most 256
history records and at most 8 MiB total. They are benchmark inputs, not a
production retention promise, and require explicit owner approval.

Server durability would be a different design. It would require a new Registry
state/mutation declaration, policy-digest and generation rotation, checkpoint
mapping, restore/reducer proof, resource attribution, and explicit updates to
the Recovery Phase A adapter. It must not be disguised as one of the five
instrumented mutation classes. The current Registry has 27 mutations and the
adapter pins that exact count.

## Benchmark requirements before any stored or active path

The inactive pure contract needs deterministic/hash parity and typecheck gates,
not a production burn-in. A future storage or evaluated path must add a focused
benchmark that measures:

- build, strict validation and SHA-256 latency for empty, typical and exact
  32-fact/64-KiB boundary cases;
- IndexedDB insert, read-back verification and pointer-swap p50/p95/p99;
- current-pointer lookup by the exact compound index;
- incremental GC at the exact record/byte caps;
- heap/RSS delta, stored bytes and canonical bytes without payload duplication;
- 50 repeated cycles and drift rejection across schema, build, policy and
  generation identities.

The Linux gate must use `--memory 4g --memory-swap 4g`, verify
`memory.max=4294967296` and `memory.swap.max=0`, capture `memory.current`,
`memory.peak` and before/after `memory.events`, require zero `oom` and
`oom_kill`, and upload artifacts named with the exact `${{ github.sha }}`.
Acceptance thresholds for latency and retained bytes must be owner-approved
before the benchmark can authorize runtime use; absence of a threshold is a
blocking gate, not a pass.

## Route and UI effects

The inactive authority interface adds no route, page, navigation item, or visible
feature. The wider Round 2A macro adapts existing quote/cache consumers to
preserve canonical freshness, but does not add a product surface:

- route catalog remains exactly 158: 62 `PUBLIC`, 87 `AUTH_OPERATIONAL`,
  6 `OWNER_SYNC`, and 3 `RECOVERY_PROOF`;
- public reads remain cached-only and cannot fetch a provider or mutate state;
- the product remains Today, Holdings/Watchlist, Notifications and Settings,
  with Asset Detail contextual;
- no new page, navigation item, card, badge, message, notification, action copy,
  public field, owner-sync call or browser upload exists;
- current action selection remains governed by its existing modules because the
  new authority is not imported; Round 2A does not activate a replacement.

## Round 1 recovery invariants

All Round 1 recovery truth is frozen and unaffected:

- Recovery Measurement remains default-disabled, optional, `SHADOW`,
  `INCOMPLETE`, non-authoritative and health/readiness-neutral;
- coverage remains exactly the five existing mutation classes; the other 22
  Registry mutations remain uninstrumented;
- public exact cold recovery remains `NOT_PROVEN` and hard-RPO claims remain
  false; the proof boundary remains the null verifier;
- `acceptanceClockStarted=false`, Stage1 remains disabled, V2 authority remains
  false and Soak remains unarmed;
- legacy checkpoint, WAL, Remote Journal, restore, backup, nonce and Registry
  authority do not change;
- measurement or evidence-contract failure cannot change an investment decision.

## Regression and release gates

Focused Round 2A gates:

1. Python contract tests: exact keys/actions/caps, deterministic ordering,
   cross-language fixed hash, deep-copy isolation, identity drift, strict scalar
   types, private-field rejection, temporal ordering, malformed/oversize cases,
   and absence of runtime imports.
2. TypeScript contract tests: the same fixed hash, async digest verification,
   structural/hash separation, owner-context privacy, immutable inactive result,
   hostile caller-action/boolean resistance, and no network/storage/flag seams.
3. `tsc -b --noEmit`.
4. Existing decision tests: decision spine, signal/action priority/stance,
   Asset Desk, product integrity and Argus engine.
5. Existing boundary tests: public/operational route catalog, lean surface,
   mobile Today, portfolio privacy and recovery durability.
6. Existing Recovery Core/Measurement/Proof/adapter suites.
7. Full `pytest`, web `lint`, web build, clean-tree check and exact-SHA release
   manifest before any merge.

No Round 2A test may claim action quality, production authority, storage
durability, cold recovery proof or burn-in. Those capabilities do not exist.

## Concrete risks and owner gates

1. **Authority placement:** backend placement would guess or leak owner truth.
   Owner must retain the device-local join.
2. **Rival choosers:** `primaryStance`, AI/rule merge, action-alert aggregation,
   Asset Desk synthesis and market `BUY/WAIT/SELL` can create contradictory
   commands if a future authority is merely added beside them. Cutover must
   replace selection and leave one chooser.
3. **Vocabulary ambiguity:** existing `SELL`, `TRIM`, `DEFEND`, `ENTER`, `ADD`
   and position-agnostic `HOLD` have no lossless mapping. Owner must approve an
   evidence projection, not an action mapping.
4. **Subject ambiguity:** asset semantics are defined; market and portfolio
   semantics are not. Expanding the subject is a new contract.
5. **Identity drift:** short/unknown build SHA or policy/schema/generation drift
   invalidates the bundle; it cannot fall back to a legacy action.
6. **Storage expansion:** any durable server state changes Registry and recovery
   identity. Any client store needs explicit caps, resource proof and privacy
   review before creation.
7. **False inactivity:** importing the interface from a hook, route or producer
   would create a runtime seam even with a null result. Round 2A forbids the
   import; a later change requires independent review.

Stop here. There is no authority, runtime integration, storage, deployment or
production acceptance clock in Round 2A.
