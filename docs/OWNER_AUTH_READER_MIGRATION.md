# Owner-authenticated release readers (local candidate)

This unit connects the business snapshot acceptance and producer readback to
owner sessions, and the two operational warmer groups to the existing admin
credential. It does not enable owner authentication or publish credentials.

## Deployment prerequisites

The owner-auth server candidate and this reader change require their own exact
admission, tests and two-parent merge before deployment. The current local
candidate is not an accepted public release. Do not reuse the parent candidate's
certificate after changing these files. Do not set production authentication on
until public browser, warm profile, mobile, machine inventory and iPhone
migration acceptance also pass.

For the business trigger and acceptance steps, set the repository variable
`ARGUS_ACCEPTANCE_OWNER_AUTH=1` together with the already reviewed frontend and
server activation. Set `ARGUS_ACCEPTANCE_OWNER_PASSWORD` as a protected Actions
secret through the owner's normal secret-entry process. It is an owner login
credential, never a browser admin token. The workflow fixes the owner origin to
`https://mitsugue.github.io`; a different approved deployment requires an explicit
origin change. No secret value is supplied by this change.

The default mode `0` preserves existing public readback for the staged rollout.
There is no automatic downgrade from mode `1`, and a backend 401 in mode `0`
cannot pass existing snapshot acceptance. No session is exported to an artifact
or browser profile. Each process checks anonymous rejection before login, uses
fresh server nonce echoes for reads, and confirms logout even after a data
failure. Rejection is terminal. A session near its expiry is proactively revoked
and replaced; the original data/reconciliation deadline remains unchanged.

Operational warmers require the existing `ARGUS_ADMIN_TOKEN`. They perform only
the fixed six runtime reads or twelve chart reads on the established backend,
reject redirects/non-200 responses, and log index/status/timing only. Missing
credentials now fail explicitly. They neither prove business content acceptance
nor rerun a mission. The existing producer mutation remains separately admin
protected. No new role, bypass or browser privilege is introduced.

## Failure and recovery

Keep all existing business artifacts and prior snapshots. Authentication failures
stop the invocation without data retries, fallback credentials or another
producer trigger. A logout transport failure also fails the invocation; the
server still imposes the original session expiry. Restore the validated matching
reader/server configuration before a new normal acceptance run. Do not disable
authentication merely to make a failed check green. There is no data/schema
migration or deletion in this unit. The compatibility mode remains until all
owner-protected consumers, the actual iPhone, and recovery are accepted; remove
it only in a separately reviewed change afterwards.

## Browser work still required

The existing mobile M13 asserts that an offline reload displays a saved
snapshot. Memory-only owner authentication deliberately loses the session at
reload. The correct protected acceptance must verify a locked offline screen,
preserved stored results, and the same snapshot ID after online reauthentication.
Do not skip M13 or inject a persisted/admin token to satisfy it. Public/warm
profile browser login, password/token-free artifacts, old PWA cache migration,
and actual iPhone Face ID/recovery are separate remaining acceptance work. Their
current gates are left intact by this unit.

## Local validation

`python3 -m pytest -q test_owner_auth_reader_contract.py test_warm_protected_reads.py`
runs synthetic transport failures and the actual Flask authentication boundary
from Node through the unchanged exact twelve-snapshot evaluator, including
separate admin trigger and authenticated readback, then verifies zero remaining
sessions. Run the existing release-state-machine tests as well. No live market
payloads, actual credentials, external requests, capacity changes or formal
72-hour acceptance are involved.
