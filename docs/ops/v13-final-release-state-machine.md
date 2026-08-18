# ARGUS V13 final release state machine

This is the finite release-control contract for completing V13. It changes no
product semantics, provider authority, credentials, runtime configuration, or
Recovery acceptance. Tachibana remains `UNKNOWN`, configuration `false`,
credentials/data `unavailable`, and `DATA_GATED`; that absence is not a V13
release blocker.

## V13.5 immutable acceptance runtime

V13.5 keeps the accepted product and decision semantics unchanged and replaces
only the failed browser provisioning boundary. Browser acceptance runs in the
digest-pinned Playwright 1.55.0 Noble image declared by
`release/v13-acceptance-runtime.json`. The image already contains Chromium
140.0.7339.16 and its OS libraries. Release jobs set
`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`; no acceptance job provisions a browser or
operating-system package.

Two independent pull-request jobs launch that exact runtime and each execute a
genuine 0-of-12 full release simulation. Their runtime identities, shared seed
digest, exact candidate SHA/tree, CURRENT_REQUIRED results, and canonical
1321/5D same-snapshot proof are sealed in a detached certificate. On main
merge, `acceptance-runtime-admission` retrieves the certificate by the exact
second-parent candidate SHA, proves the merge tree is identical, and launches
the same runtime before backend readiness or Pages deployment may begin. Seed
and final public acceptance repeat the same runtime admission.

The manual `restore-safe-pages.yml` path remains deliberately browser-free: it
builds and restores a previously accepted frontend artifact and polls its exact
public identity. It never seeds, creates business snapshots, or changes
`/var/data`.

## Exact causal states

The executable authority is `web/scripts/release-state-machine.mjs`.

| State | Meaning and admission evidence |
|---|---|
| R0 | Safe production and rollback identity pinned. |
| R1 | Candidate constructed. |
| R2 | Candidate unit/integration/build gates passed. |
| R3 | Candidate browser E2E passed. |
| R4 | Required CI and detached proof certificate passed for one SHA/tree. |
| R5 | Protected normal-history merge to main. |
| R6 | Exact backend deploying. |
| R7 | Backend infrastructure ready: health, ready, exact identity, stable process, storage/restore contract. Business snapshots may still be 0/12. |
| R8 | Exact frontend deploying. |
| R9 | Public frontend identity converged. |
| R10 | Public backend identity converged. |
| R11 | Today product selection is interactable. |
| R12 | Semantic 1321 control selected. |
| R13 | Semantic 5D control selected. |
| R14 | Exact market/1321/5D/verified request observed after selection. |
| R15 | Verified HTTP 200 snapshot received with zero automatic AI calls. |
| R16 | UI semantic snapshot ID equals the HTTP response snapshot ID. |
| R17 | Service Worker, IndexedDB, candidate identity, and warm profile sealed. |
| R18 | Exact trigger-bound, fresh business snapshot set accepted (12/12; no missing, extra, duplicate, wrong-build, or wrong-trigger member). |
| R19 | Independent profile reopen plus public/mobile product acceptance passed. |
| R20 | V13 live. |

Every state depends on its immediate predecessor. R5 through R19 have one
fail-closed rollback transition to R0. No caller may promote a state using a
screenshot, stale cache, receipt timing, an unacknowledged producer request, or
an `expected_skip`/busy response.

## Snapshot readiness contract

`release/v13-snapshot-readiness-contract.json` enumerates all twelve exact
identities: 1321, 1306, SPY, and QQQ across 1D, 5D, and 20D. All twelve are
`SEED_REQUIRED`; none is `INFRA_REQUIRED`. Therefore R7 must pass at a genuine
cold 0/12 when infrastructure is healthy, while R18 requires exact set equality.

The sole release producer trigger is an authenticated POST to
`/api/argus/admin/missions/tick` with `releaseSnapshotSeed=true`, the exact
backend SHA, and a unique producer trigger ID. The backend serializes the four
real producer calls, publishes all three horizons for each, reads each pointer
back, persists the checkpoint, and returns `completed` only for durable 12/12.
Each snapshot ID includes `expectedBuildSha`, `producerTriggerId`, and
`triggeredAt`; historical non-release snapshot IDs remain unchanged.

The production order is deliberately asymmetric:

1. Backend infrastructure reaches R7 without requiring any business snapshot.
2. Pages deploys and both public identities converge at R9/R10.
3. The dedicated producer trigger creates and durably acknowledges 12/12.
4. The UI selects 1321 then 5D, observes the verified response, and seals the
   warm profile through R17.
5. The shared engine re-reads and accepts exactly the trigger-bound set at R18.
6. Independent public acceptance advances R19/R20.

The previous production attempt inverted steps 1 and 3: its pre-deploy
`backend-readiness` job ran the business gate while the cold set was 0/12, then
skipped deploy, identity, and producer jobs. Classification:
`PREMATURE_BUSINESS_GATE`; it was not an infrastructure failure.

## Failure injection A–T

`web/scripts/release-state-machine.test.mjs` freezes A–T: cold 0/12; unhealthy
infrastructure; stale/wrong frontend or backend identity; deploy-before-seed
ordering; Today/1321/5D trigger order; HTTP 400 and bounded/exhausted 429;
verified/unverified response; response/UI equality; Service Worker; IndexedDB;
profile integrity; wrong-build snapshot; duplicate; missing seed-required
snapshot; and identity changes during acceptance. The exact success scenario is
also frozen.

## Two full simulations and proof

The PR workflow runs `web/scripts/full-release-simulation.mjs` twice on separate
fresh runners. Each run starts a new empty backend fixture, proves R7 at 0/12,
serves an exact candidate dist, executes the dedicated 12-snapshot producer,
uses the real canonical browser selector, seals and reopens a fresh profile,
and accepts the exact 12 set and four public surfaces.

After both jobs pass, `scripts/v13_release_certificate.py` generates a detached
content-addressed certificate bound to the exact commit SHA and tree, readiness
contract, accepted-fix manifest, shared engine, both simulation artifacts, and
their CI results. A detached artifact avoids the impossible self-reference of a
commit containing its own final SHA/tree digest. CI immediately verifies the
certificate before the protected merge can occur.

## Rollback and stop boundary

On any post-merge acceptance failure, preserve evidence, restore the pinned
safe frontend/backend release through normal repository history, verify its
identity/readiness, and stop. Do not make a second production attempt, rewrite
ledgers or owner-local state, start V14, begin Recovery acceptance, configure
Tachibana, or change credentials/authority without a new owner instruction.
