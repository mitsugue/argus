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
- Encrypted recovery sidecar: `/var/data/argus_remote_recovery.json`
- Recovery nonce authority: private `argus_remote_recovery_nonce_*` files
  under `/var/data`
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

For the one-time 13.3.0 migration, the stable raw checkpoint may be accepted
only when `/var/data/argus_osint_memory.json.legacy-seal.json` binds that exact
path, byte length, SHA-256, durable schema, and its own canonical record hash.
The original `/tmp` source is retained. An unsealed file without that receipt,
or any path/hash mismatch, still fails closed. The first normal 13.3.1
checkpoint rewrites the state with the embedded local integrity seal.

Malformed local checkpoints are quarantined beside the original file and the
verified remote snapshot remains authoritative. WAL records after the saved
cursor are replayed idempotently. WAL compaction is deferred until a Remote
Journal receipt explicitly covers the checkpoint sequence; a stale receipt is
never treated as verified.

## Encrypted Remote Journal recovery (v13.4.13)

The compact read-back remains public-safe. State that can contain owner context
or `full_private` values is never written to the public ledger in plaintext.
When recovery encryption is configured, every verified checkpoint produces a
fixed-size AES-256-GCM encrypted sidecar before WAL compaction. The configured
32-byte value is a root key, never the direct AES key. Every envelope receives
a fresh 256-bit CSPRNG salt and uses HKDF-SHA-256 to derive its own 256-bit AES
data key. HKDF `info` is domain-separated and binds the complete semantic
public header, including the schema, key ID, opaque checkpoint identity,
ledger base, and WAL boundary. The same fields and salt are also authenticated
as AES-GCM AAD. Cold restore and Remote Journal ACK both require the exact
read-back/sidecar pair at one immutable ledger commit and fail closed on a
missing sidecar, KDF/header/tag failure, stale checkpoint, wrong key ID, or
ancestry mismatch. There is no plaintext fallback.

The runtime contract uses four secret-manager values. Key IDs are non-secret
identifiers; key values are URL-safe base64 encodings of exactly 32 random
root-key bytes and must never be stored in this repository, GitHub Actions,
artifacts, logs, or the public ledger. The public sidecar contains only the key
ID, KDF algorithm, 256-bit salt, nonce, authenticated metadata, and fixed-size
ciphertext; neither root keys nor derived data keys are persisted or emitted.

```text
ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID=<opaque-id>
ARGUS_REMOTE_RECOVERY_CURRENT_KEY=<redacted-32-byte-key>
ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID=<opaque-id>       # rotation only
ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY=<redacted-32-byte-key>
```

Key configuration, generation, and rotation are separate owner-approved
production changes; this code release does not perform them. With no current
key configured, sidecar creation reports `not_configured` and preserves the
legacy checkpoint path. After an encrypted generation has been marked,
removing the required key or sidecar intentionally stops recovery rather than
downgrading to plaintext or accepting a stale full snapshot.

The first key activation requires a maintenance fence. Under a separate,
explicit owner approval, disable the `caos-watchtower` and `caos-scan`
workflow schedules and the EC2 re-arm timer, cancel or drain every queued and
in-progress run, and verify that no ledger writer remains active *before*
changing the Render key configuration or restarting the backend. Do not
re-enable a writer until the restarted backend reports encrypted recovery
mode and has produced a current-key sidecar. This fence is required because a
workflow that selected legacy mode before activation could otherwise finish a
legacy ledger push after the security boundary changed.

For rotation, install a new current key while retaining the old current key as
the single previous key. New encryption always uses only the current key;
previous is decrypt-only. Keep both until a new-current-key pair has been
published, ACKed at its immutable ledger commit, and cold-restore tested. Only
then may a separately approved change retire the previous key. A rollback must
restore the matching key IDs and values together. An ID-only rename is allowed
only for one transition window with the old ID in the previous (decrypt-only)
slot; both IDs share the same private material-domain counter and therefore
cannot restart its nonce sequence. Removing nonce-authority files is invalid.
The v1 authority has a lifetime ceiling of 16 distinct 32-byte key materials
(the initial key plus at most 15 material-changing rotations). An ID-only
rename does not consume another slot. Before every material-changing rotation,
verify capacity under a separately approved preflight; attempting a 17th
material fails checkpoints closed and must not be used as a production
rotation procedure. Expanding or migrating this bound requires a new
versioned, rollback-safe authority design—never delete an old floor to make
space.

Per-envelope key separation is a computational guarantee, not a mathematical
claim that random values can never collide. A whole-volume rollback may repeat
a local nonce counter, but a newly generated 256-bit salt derives a different
AES data key except with cryptographically negligible salt-collision
probability. The implementation therefore never intentionally reuses one
derived-data-key/nonce pair, and the private monotonic nonce authority remains
an independent defense for normal crashes, partial loss, published rollback,
and operator error. This is the approved availability/security boundary; a
literal external monotonic guarantee would require a separately authorized
pre-encryption reservation service.

Nonce reservations are serialized and persisted as private mode-0600 history,
head, cache, and anchor records. On keyed boot, local floors are reconciled
with the latest authenticated immutable Remote Journal pair before local state
becomes authoritative; missing, ambiguous, undecryptable, or regressing proof
fails closed. The encrypted payload carries forward the bounded per-key-
material floor map so a permitted current/previous-key rollback cannot forget
an older key's published high-water mark. The anchor rolls atomically to a
versioned successor epoch before its 64 MiB per-epoch limit; each successor
retains the absolute generation, all key-material-domain counters, and the
prior epoch's terminal digest. A crash before replacement leaves the old
epoch authoritative, while a crash after replacement leaves the fully fsynced
successor authoritative. Key rotation neither resets nor compacts these
counters. Do not delete, replace, roll back, or compact these files manually.

## Capacity and backup limits

The startup check reserves capacity dynamically for the current checkpoint,
its temporary replacement, WAL growth, and a safety margin. Monitor the
reported safety ratio and increase the disk before it becomes critical.
Render Disks cannot be scaled down. Daily Render disk snapshots are useful
infrastructure protection but do not replace Remote Journal read-back
verification.

## Future production activation (separate approval required)

This code/Draft-PR/CI scope does **not** authorize merge, deploy, restart,
Render environment changes, production-key generation or registration,
Stage1, V2 authority changes, or Soak. Before any future production key
activation, obtain a new explicit owner approval and apply the maintenance
fence above. Then verify the exact deployed SHA and backend version `13.4.13`,
the current-key checkpoint/sidecar pair, immutable ledger publication and ACK,
and a cold restore before retiring a previous key. Re-enable scheduled writers
only after their keyed-mode probes pass. A Soak may begin only under its own
separate approval and from a valid natural scheduled heartbeat.
