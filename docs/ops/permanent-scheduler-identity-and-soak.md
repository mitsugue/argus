# Permanent scheduler identity and formal Soak closure

This runbook describes prepared code only. It does not authorize a merge,
deployment, Render restart, EC2 restart, manual workflow, or manual tick.

## Read-only repository audit

| Concern | Current path | Data flow before this change |
| --- | --- | --- |
| Render deploy scope | `render.yaml`, `scripts/deploy_scope.py` | A path allowlist decides whether Render should deploy. `render.yaml` is an explicit backend exception. |
| Render skip enforcement | `scripts/render_deploy_guard.py`, `.github/workflows/release-gate.yml` | A frontend-only merge must contain `[skip render]`; a backend-sensitive merge must not. |
| CI release candidate manifest | `scripts/release_gate.sh` | Generates an artifact for the exact CI SHA. It is eligibility evidence, not deployed-production identity. |
| Pages release | `.github/workflows/deploy-pages.yml` | Builds Pages and separately waits for backend readiness only when the merge scope is backend-sensitive. |
| Workflow backend identity | `scripts/resolve_backend_identity.py`, `.github/workflows/caos-scan.yml` | Previously walked first-parent `main` history for the newest backend-sensitive commit. This was still coupled to repository classification and deployment timing. |
| EC2 backend identity | `scripts/argus_build_identity.py`, `ops/systemd/argus-mission-tick.service` | `ExecStartPre` previously trusted GitHub `main`; `/healthz` was observed. A frontend-only main advance therefore produced a false transition. |
| EC2 mission request | `scripts/argus_mission_tick.py` | Reads the preflight decision, derives the natural 30-minute window, then sends one bounded idempotent mission POST. |
| EC2 installation | `scripts/install_argus_mission_timer.sh`, `ops/systemd/*` | Previously copied files and immediately ran daemon-reload plus enable/start, which could mutate the running scheduler during evidence collection. |
| Backend health/ready | `scanner.py` `/healthz`, `/readyz` | Health exposes a short Render SHA and backend version; readiness exposes restored runtime state. Neither is an authoritative deployment declaration. |
| Soak start/restore | `argus_runtime.py`, `scanner.py` `_SOAK`, `_osint_restore_once`, mission tick | A new build does not inherit another build's clock, but any non-manual scheduled source could start a Soak and `startedAt` used observed runtime time. |
| Checkpoint/WAL/cursor/receipt | `argus_persistent_storage.py`, `argus_tick_durability.py`, `scanner.py` `_osint_persist_locked` | WAL transitions are fsynced, sealed checkpoints are atomically replaced, and compaction is allowed only through a matching verified receipt sequence. |
| Remote Journal publication | `.github/workflows/caos-scan.yml`, `.github/workflows/caos-watchtower.yml`, `scripts/prepare_remote_journal_publish.py` | A compact proof is committed to `ledger`; the workflow records the exact commit SHA and posts it to the backend. |
| Remote Journal read-back | `scanner.py` `_remote_readback_ack`, `argus_remote_journal.py` | The backend previously retained the exact commit SHA but fetched the moving `ledger` branch. A concurrent ledger writer could therefore produce `commit_receipt_stale`. |
| Soak acceptance | `argus_runtime.py` `build_soak_state`/`build_soak` | Duration, evidence gaps, SHA, health/ready, integrity, Journal status, delay, and interruptions are aggregated, but the compatibility status and formal state require explicit separation. |

## New authoritative identity flow

1. A backend-sensitive commit reaches `main` and existing CI gates complete.
2. Render performs its normal deploy independently. This repository workflow
   never calls Render and never restarts a service.
3. `.github/workflows/publish-production-release-manifest.yml` polls public
   `GET /healthz` and `GET /readyz` for the exact full candidate SHA and version.
4. Only after both checks pass, `scripts/production_release_manifest.py`
   creates the validated public-safe manifest.
5. The exact bytes are committed to the separate `production-release` branch
   at `production/argus-backend.json`. Frontend-only commits and failed deploys
   do not change that branch.
6. EC2 and GitHub backup workflows compare the manifest SHA (trusted) with the
   backend health SHA (observed). The source label is
   `production_release_manifest`.
7. A matching manifest clears transition state and advances
   `lastVerifiedSha`. A new manifest that is not live yet produces a bounded
   `deployment_transition` skip. Expiry fails closed.
8. During manifest outage, only a matching `lastVerifiedSha` may continue in
   observable degraded mode. A static SHA is first-install/emergency bootstrap
   only and cannot override verified state.

The manifest requires:

- schema `argus-production-release-manifest-v1`
- service `argus-backend`
- environment `production`
- full 40-character `buildSha`
- semantic `version`
- timezone-qualified `deployedAt`
- public-safe `deploymentId`
- `verifiedHealth: true`
- `verifiedReady: true`

Short SHA, malformed JSON, wrong service/environment, missing verification,
future timestamps, cached timestamp regression, and secret-shaped keys fail
closed. A rollback is valid when it has a newer `deployedAt` and its older SHA
matches the actually restored production build.

## Staged EC2 installation

Run only after owner approval:

```sh
bash scripts/install_argus_mission_timer.sh --dry-run
sudo bash scripts/install_argus_mission_timer.sh --apply
```

The installer:

- has an explicit file list;
- validates source SHA256 and Python syntax;
- validates systemd units when `systemd-analyze` is available;
- creates a timestamped backup and rollback manifest;
- preserves existing owner, group, and mode;
- verifies each installed file by SHA256 read-back;
- never runs daemon-reload, enable, start, restart, POST, tick, or heartbeat.

After the copy, review the reported backup ID. `systemctl daemon-reload` and
any service action remain separate owner-approved production mutations.

Rollback preparation:

```sh
sudo bash scripts/install_argus_mission_timer.sh \
  --rollback YYYYMMDDTHHMMSSZ
```

Rollback also performs no daemon-reload or service action.

## Temporary pin removal gate

Do not remove `ARGUS_TRUSTED_BUILD_REF_URL` or
`ARGUS_EXPECTED_BUILD_SHA` until all of these are true:

1. the external manifest exists and passes local validation;
2. its full SHA matches public health and readiness;
3. the staged resolver is installed with verified SHA256;
4. one read-only resolver preflight records `lastVerifiedSha`;
5. owner approves the environment cleanup;
6. cleanup is performed without a tick, heartbeat, or restart in the same
   operation.

The old interrupted Soak remains historical evidence. A new formal Soak may be
created only by the separately reviewed backend/Soak change and the first
eligible natural EC2 mission window after deployment.
