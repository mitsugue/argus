# ARGUS V13 final release state machine

This is the finite release-control contract for completing V13. It changes no
product semantics, provider authority, credentials, runtime configuration, or
recovery acceptance. Tachibana remains `UNKNOWN`, `UNCONFIGURED`,
`NON_AUTHORITATIVE`, and `DATA_GATED`; that absence does not block this release.

## States and triggers

| State | Meaning | Trigger required before any wait |
|---|---|---|
| R0 | Safe production | Last accepted frontend/backend remain available for rollback. |
| R1 | Candidate constructed | Exact branch and candidate tree exist. |
| R2 | Candidate tested | Local exact-tree gates pass. |
| R3 | Candidate browser E2E accepted | Five fresh profiles and independent copied-profile consumers pass. |
| R4 | Required CI accepted | `ci`, `release-gate`, exact 4 GiB, and release-control checks pass for one SHA. |
| R5 | Main merged | Protected normal-history merge completes. |
| R6 | Backend candidate deploying | Normal deploy trigger is observed. |
| R7 | Frontend candidate deploying | Normal Pages deploy trigger is observed. |
| R8 | Backend identity converged | Health, readiness, and manifest report the exact release SHA. |
| R9 | Frontend identity converged | Public bundle reports the exact release SHA/version. |
| R10 | Product selection ready | Today controls and evidence disclosure are interactable. |
| R11 | 1321 selected | The semantic 1321 control is activated. |
| R12 | 5D selected | The semantic 5D control is activated. |
| R13 | Canonical request observed | Exact market/1321/5D/verified GET is observed after R11/R12. |
| R14 | Verified snapshot received | HTTP 200, verified status, snapshot ID, and zero automatic AI calls. |
| R15 | Same snapshot projected | DOM contract equals the response snapshot ID and exact instrument/horizon. |
| R16 | Warm profile sealed | Service Worker, IndexedDB, identity, and manifest are sealed after R15. |
| R17 | Public product accepted | Independent reopen plus public/mobile/visual acceptance pass. |
| R18 | V13 live | External production manifest is published for the accepted exact SHA. |

The executable graph is `web/scripts/release-state-machine.mjs`. A state cannot
be entered twice or before every declared predecessor. The canonical selection
routine registers request/response observers, performs real selection actions,
then awaits request, response, and same-snapshot UI projection. If a reopened
profile is already on 1321 or 5D, it first moves to an alternate control so the
canonical selection remains a real trigger instead of a no-op wait.

## Failure injection A–P

`web/scripts/release-state-machine.test.mjs` freezes the following outcomes:

- A: default Today may be DATA_GATED; explicit 1321/5D selection can still pass.
- B–D: old/stale frontend or backend identity fails closed.
- E: exact candidate identity and same verified snapshot passes.
- F: HTTP 400 fails; G: bounded 429 then 200 passes; H: exhausted 429 fails.
- I: unverified response fails; J: response/UI snapshot mismatch fails; K: exact
  equality passes.
- L: missing Service Worker readiness fails; M: missing IndexedDB readiness
  fails until the action creates it; N: malformed profile fails.
- O–P: frontend or backend identity change during the sequence fails.

No scenario can promote a result by receipt time, stale cache, default
instrument state, a screenshot, or a caller assertion.

## Pre-production and production gates

Before R5, the PR workflow builds the exact candidate locally and serves that
dist without touching public Pages. Both seed/consumer pairs execute the same
shared production seed implementation against that exact build. The release
control paths trigger the Linux exact-4-GiB truth/ledger job. The candidate is
not deployable unless full backend tests, frontend lint/build, workflow syntax,
secret scans, release gate, state-machine matrix, resource proof, and five fresh
browser cycles all pass for the same SHA/tree.

After R5, only the repository's normal protected deploys are allowed. A failed
identity, readiness, canonical request, verified response, snapshot equality,
profile, mobile/public acceptance, or external manifest step stops progression.
There is no second production attempt in the same cycle.

## Rollback and stop boundary

On any post-merge acceptance failure, preserve evidence, restore the last safe
frontend/backend release using the existing controlled rollback, verify its
identity/readiness, and stop. Do not delete or rewrite ledgers, device-local
owner state, recovery evidence, or immutable manifests. Do not merge another
fix, deploy again, begin V14, start recovery acceptance, configure Tachibana,
or change credentials/authority without a new owner instruction.
