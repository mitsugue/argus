# Render Persistent Mission Durability

This is the operational contract for the dashboard-managed `argus-backend`
service. `render.yaml` documents the intended configuration; the Render
Dashboard and runtime `/readyz` diagnostics are the live source of truth.
Do not convert the existing service to a Blueprint to apply this document.

## Required topology

- Manual scaling: exactly **1 instance**
- Autoscaling: **disabled**
- Persistent Disk: **5 GB**
- Mount path: `/var/data`
- WAL: `/var/data/argus_mission_tick.wal`
- Full checkpoint: `/var/data/argus_osint_memory.json`
- Lease: `/var/data/argus_mission_tick.lease`
- Cursor: `/var/data/argus_mission_tick.cursor.json`
- Receipt metadata: `/var/data/argus_mission_tick.receipt.json`
- Checkpoint temporary directory: `/var/data`

`flock` protects concurrent requests only on one host. It is not a distributed
lock. The service must not be horizontally scaled while this
topology is in use. Future multi-instance operation requires shared
Postgres/Key Value state and a distributed lease.

## Owner Dashboard action

In **Render Dashboard → argus-backend**:

1. Confirm manual scaling is exactly one instance.
2. Confirm autoscaling is disabled.
3. Add a Persistent Disk with mount path `/var/data` and size `5 GB`.
4. Confirm the path environment variables above. The application safely
   defaults production durability paths to `/var/data`, but explicit values
   make configuration drift visible.
5. Do not change the plan, custom domain, secrets, build command, or start
   command.
6. Allow the disk attachment deploy to finish. Brief downtime is expected for
   a disk-backed service.
7. Check `/readyz`: `ready=true`,
   `persistentStorage.runtimeVerified=true`, all exact paths under
   `/var/data`, and `sameFilesystem`, `atomicRename`, and `fsync` all true.
8. Record the new process boot time and the non-secret disk diagnostics.

The current Soak is already interrupted. Do not start a new Soak from this
infrastructure-only disk attachment deploy.

## Startup and recovery

Production fails closed when the root is absent, a path escapes `/var/data`,
the durability probe fails, or free capacity is insufficient. `/healthz` may
remain live, but `/readyz` returns 503 and admin mission ticks return
`persistent_storage_unavailable`; there is no `/tmp` fallback.

An empty new disk is bootstrapped only from the latest verified
`argus-durable-v3` Remote Journal snapshot. The manifest is validated before a
sealed local checkpoint is written, fsynced, read back, and atomically
published. If no verified remote snapshot exists, readiness stays false and
the empty disk is preserved.

Malformed local checkpoints are quarantined beside the original file and the
verified remote snapshot remains authoritative. WAL records after the saved
cursor are replayed idempotently. WAL compaction is deferred until a Remote
Journal receipt explicitly covers the checkpoint sequence; a stale receipt is
never treated as verified.

## Capacity and backup limits

The startup check reserves capacity dynamically for the current checkpoint,
its temporary replacement, WAL growth, and a safety margin. Monitor the
reported safety ratio and increase the disk before it becomes critical.
Render Disks cannot be scaled down. Daily Render disk snapshots are useful
infrastructure protection but do not replace Remote Journal read-back
verification.

## Release after runtime proof

Only after the owner confirms the attached disk and `/readyz` proves the
runtime contract:

1. Merge PR #94.
2. Deploy the exact merge SHA and verify backend version `13.3.1`.
3. Verify checkpoint/WAL restore and all 12 market snapshots.
4. Wait for the first valid scheduled mission heartbeat to start the new Soak.
5. Verify two consecutive scheduled `caos-scan` runs, `ai-rejudge`, zero
   Render restarts, bounded checkpoints, and Remote Journal pending trend.

Manual acceptance ticks do not start the Soak.
