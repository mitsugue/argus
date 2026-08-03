# Prediction-ledger membership recovery contract

## Incident evidence

- Natural scheduled run `30807089385` on main SHA
  `9c743f93b9e5bbadc79c8ba891959db3a4e6287c` reached the backend with HTTP 200
  and failed its first Layer 2B step as a business error.
- The non-sensitive sync-status endpoint reported
  `privateStoreConfigured=true`, `lastStatus=never_synced`, `symbolCount=0`
  and no `lastSyncAt`.
- No public prediction record/score, ledger commit, push or artifact was made by
  that failed run because the private pre-step stopped the entire job.
- The failure is not caused by AI inference. The AI step was an expected skip in
  deterministic mode.

The old response `no_membership_synced` collapsed four materially different
states: never synchronized, intentionally empty, malformed and temporarily
unavailable. The shell's `errexit` then blocked the public ledger before its
independent work began.

## Authoritative membership

`membership/latest.json` in the configured private Layer 2B repository is the
only authoritative server-side membership. It contains membership metadata,
not quantities, cost basis, P/L, allocation, notes or trades. The owner device
creates it through the authenticated, idempotent watchlist-sync endpoint.

The workflow must never reconstruct owner symbols from public pages, logs,
portfolio payloads or a fallback cohort. If the private snapshot does not
exist, the correct state is `never_synced` and the operator action is an
authenticated owner watchlist sync. A valid snapshot with zero enabled members
is `empty_by_design` and is an expected skip.

## State and workflow contract

- `private_store_not_configured`: expected skip; private calibration disabled.
- `never_synced`: blocking; owner sync required.
- `empty_by_design`: expected skip; authoritative empty membership verified.
- `membership_invalid`: blocking; schema/count/content-hash mismatch.
- `membership_store_unavailable`: blocking; do not relabel outage as empty.
- `synced`: revision, schema, member count and content hash verified; run the
  append-only private record/score path.

The Layer 2B step captures a blocked result without terminating the shell. The
public prediction ledger continues through record, score and ledger-branch
commit. A final contract step then fails the workflow if private membership was
blocked. This preserves public learning progress while ensuring the private
record/score never pretends success. Result summaries expose only state, count,
revision and action; symbols remain private.

## EC2 PAT and permission evidence (no mutation performed)

Read-only metadata captured on 2026-08-03:

- `/opt/argus/bridge/trigger_ledger.sh`: owner `ubuntu:ubuntu`, mode `775`.
- `/opt/argus/bridge/trigger_closepin.sh`: owner `ubuntu:ubuntu`, mode `664`.
- `/home/ubuntu/argus-trigger.env`: owner `ubuntu:ubuntu`, mode `600`.
- User cron invokes ledger at `5 7 * * 1-5` and close-pin at
  `30 5 * * 1-5`.
- `argus-mission-tick.timer` is active, enabled and waiting; its last service
  result is success with exit 0.
- Historical trigger logging reports ledger-dispatch failures and the provided
  GitHub notice says fine-grained token `argus-ledger-trigger` expires in seven
  days. The scheduled GitHub run above did not depend on this external PAT.
- Close-pin's repeated `Permission denied` is explained by mode `664`: the
  owner has no execute bit.

No token value or env content was read or printed.

### Minimum owner action plan

1. Replace/renew the fine-grained token before expiry, scoped only to repository
   `mitsugue/argus`, with repository **Actions: write** (workflow dispatch) and
   implied metadata read. It does not need contents write; the dispatched
   workflow uses its own `GITHUB_TOKEN` for the ledger branch.
2. Store the replacement only as `GH_WORKFLOW_PAT` in
   `/home/ubuntu/argus-trigger.env`, owned by `ubuntu:ubuntu`, mode `600`.
3. Make each cron script owner-executable with the smallest practical host
   permission (recommended `700`; `750` only if an explicit operator group must
   execute it). Do not broaden the env file.
4. Verify at the next natural cron only. Do not manual-dispatch or rerun during
   this incident review.

These are rollout instructions, not changes made by this PR.

## Natural recovery acceptance

After an owner-approved backend/workflow release and an authenticated owner
membership sync, the next natural scheduled run must show:

- verified membership state (`synced` or intentional `empty_by_design`),
- no symbol leakage in public logs or artifacts,
- append-only private record/score with duplicate same-day recording equal to
  zero,
- public ledger record/score/commit independent of private expected skips,
- a precise blocking failure if membership is missing, invalid or unavailable.
