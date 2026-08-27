# Recovery Phase A integration contract

Status: adapter and scanner wiring implemented; feature default-disabled.
Roadmap position: **1 / 18 — Recovery storage / durability redesign**.

This integration connects Registry Core, Measurement Core, diagnostic storage,
and Recovery Proof Core without changing recovery authority. It does not make
Remote Journal health, a successful legacy checkpoint, or measurement coverage
an exact-cold-recovery proof.

## Fixed public and authority boundary

The adapter is optional, shadow-only, and non-authoritative. Every persisted
measurement artifact remains:

- `mode = SHADOW`
- `coverageStatus = INCOMPLETE`
- `proofStatus = NOT_PROVEN`
- `authoritative = false`
- `acceptanceClockStarted = false`

No adapter result may participate in readiness, liveness, checkpoint/WAL
success, compaction, restore selection, Remote Journal state, or investment
decisions. The public exact-cold-recovery result remains exactly
`{"status":"NOT_PROVEN","hardRpoClaimPermitted":false}`.

`null_recovery_proof_document()` is the complete Phase A proof adapter. Scanner
obtains that no-input result at both existing public and operational DTO
builders and reapplies only the two already-defined conservative fields; it
does not add a route, key, or response shape. It passes no evidence to Proof
Core, accepts no boolean, never calls the private trusted-verifier constructor,
checks Proof Core's result is the exact null result, and falls back to the same
null result on any exception. Measurement artifacts are diagnostics, not proof
evidence.

## Configuration, identity, and startup

There is one opt-in flag:

`ARGUS_RECOVERY_PHASE_A_MEASUREMENT_ENABLED=1`

Only the exact string `1` enables the adapter. Missing, empty, alternate, or
non-string values leave it disabled. No production environment change belongs
in this integration change.

The adapter calls `resolve_measurement_path()` with no arguments. Runtime code
has no path override. The only artifact location is:

`/var/data/diagnostics/recovery-measurement/measurement-v1.json`

Scanner constructs the adapter once during `_startup_bootstrap` with
`_backend_exact_sha()`. That source
accepts only the normalized full lower-case 40-hex `RENDER_GIT_COMMIT`. It must
not use `_backend_sha()`, a seven-character value, `unknown`, or a local Git
fallback. A missing/malformed exact build disables measurement startup only;
application startup continues with its existing behavior.

Measurement generation identity is deterministic over these four exact
inputs:

1. Registry Core policy SHA-256
2. producer build SHA
3. Measurement Core schema SHA-256
4. the adapter's instrumentation-coverage SHA-256

The adapter validates the Registry as exactly 27 mutation declarations with
the six instrumented declarations present. It checks all four identities and
the derived generation ID at load and again at mutation/checkpoint boundaries.
Build, schema, instrumentation, or generation drift rotates to a fresh empty
artifact with the core's generic `artifact_invalid` code. Registry policy drift
uses `registry_policy_mismatch`. The next successfully persisted detailed
checkpoint carries `ACCOUNTING_SCHEMA_OR_BUILD_CHANGE`; failed accounting or
persistence leaves that request pending for a later checkpoint.

All adapter state is guarded by one in-process `threading.RLock`, matching the
deployed one-worker/eight-thread topology. This is diagnostics serialization,
not a cross-process authority lock.

## Exact producer seams

Scanner calls `record_mutation_after_authority(...)` only at these
six success boundaries:

| Registry mutation | Scanner seam | Exact success boundary | Measurement coverage |
|---|---|---|---|
| `core.ops_journal_transition` | `_journal` | journal append plus its required tick-WAL or non-tick verified checkpoint has completed | `OBSERVED_UNDURABLE` |
| `market.ledger_update` | `_investor_types_autorefresh` | the D05 investor-types import has succeeded and its existing legacy checkpoint has returned `verified == true` | `OBSERVED_UNDURABLE` |
| `core.mission_transition` | `_append_tick_wal` | `kind == "mission_transition"`, after WAL append/fsync returns | `OBSERVED_UNDURABLE` |
| `core.batch_cursor` | `_append_tick_wal` | `kind == "batch_cursor"`, after WAL append/fsync returns | `OBSERVED_UNDURABLE` |
| `durability.receipt_ack` | `_persist_with_remote_receipt_drain` | `_complete_remote_receipt_drain` returns `status == "verified"` | `OBSERVED_DURABLE` |
| `startup.restore_transition` | `_startup_bootstrap` | once, after terminal `ready` or `ready_degraded`; never `failed_safe` | `UNKNOWN` |

The other 21 Registry mutation classes remain uninstrumented. Wording must not
suggest their observation, durability, or replay completeness.

Mutation hooks accept only the Registry ID and bounded scalar byte/count/
latency/sequence metadata. They do not accept payloads, dictionaries, raw
exceptions, caller success booleans, remote-health booleans, or proof state.
For `_append_tick_wal`, scanner can measure elapsed microseconds and the
nonnegative WAL file-size delta around the successful append. For `_journal`,
use byte estimate `0`, record count `1`, measured elapsed time, and its local
sequence because the adapter must not serialize the event payload. Receipt and
startup hooks likewise use already-available scalar facts only.

The WAL and journal pre-authority probes are lock-free scalar gates. They read
only the cached adapter pointer, exact raw flag, exact build identity, per-tick
WAL-byte cursor, and monotonic clock; they call no adapter method and perform no
pre-append filesystem I/O. Immediately when `append_wal` returns, scanner
freezes the completion time and post-append file size. Existing context
bookkeeping and lease heartbeat happen afterward, and a non-masking `finally`
submits the frozen observation even if that legacy bookkeeping raises. The
existing `walAppendMs` duration is also frozen at append return, so optional
file-size measurement and adapter work cannot inflate legacy telemetry.
The byte cursor is sequence-pinned: if an uninstrumented WAL record intervenes,
the next instrumented row reports a truthful byte estimate of `0` rather than
claiming the intervening bytes, then advances the cursor to the new sequence.

## Checkpoint handoff and sampling

Checkpoint accounting has a split boundary so diagnostic I/O cannot become
checkpoint authority:

1. `_osint_persist_locked` builds and seals the authoritative checkpoint.
2. While the exact `sealed_blob` mapping still exists, scanner obtains a
   sampling decision. JP/US flags may be true only after a corresponding
   `post_session_snapshot` mission has successfully persisted. The empty-OSINT
   `warmup_queued` branch is not a post-session boundary. Owner sampling
   requires the existing exact-build authenticated owner operation and creates
   no route.
3. Only when detail is requested, scanner passes that same mapping object to
   `account_checkpoint`. The adapter immediately passes the object by identity
   to `streaming_checkpoint_accounting`. It does not copy, retain, persist, or
   return the mapping. The only returned data is bounded scalar accounting,
   represented as immutable section-name/byte-count tuples. Core evidence must
   report `full_size_buffers == 0`.
4. Scanner stores only the sampling token, scalar accounting, seal timing, and
   pre-read WAL byte/count/high-water scalars in a thread-local handoff. No
   checkpoint object is retained or copied there. All three sampling-reason
   flags are consumed at preparation and reset again at tick entry and exit, so
   an aborted tick cannot leak a reason into a later checkpoint.
5. `_osint_persist_locked` completes existing authority work and returns. A
   non-tick `_osint_persist` finalizes only after its lock scope exits. A mission
   tick holds an outer recursive lock, so it defers finalization until the
   route's outer `finally` releases that lock. Both paths call
   `record_checkpoint_after_authority` only if `result["verified"]` is true;
   otherwise they call `abandon_checkpoint`.
6. The adapter records the sample, applies Measurement Core retention, and
   atomically writes the optional diagnostics artifact. It never fsyncs per
   mutation.

The sealed mapping is the sole transient exception to the scalar-only adapter
boundary. It is required because section accounting cannot be derived after
`sealed_blob` is deleted, and re-reading or reserializing the checkpoint would
create the prohibited generation-sized duplicate.

Detailed sampling is limited to at most two normal JP/US session samples per
UTC day. The adapter rechecks the quota at commit under its `RLock`, so stale
parallel decisions cannot exceed it. The first sample after accounting/build
identity change and an owner-authorized diagnostic are separate exact reasons
and do not consume the normal session quota.

Use `snapshotBytes` as the successfully written streaming-canonical checkpoint
size; the authoritative writer adds no newline. Use existing post-authority
`walCompaction.bytes`, `remainingRecords`, and `receiptSequence` for WAL
size/count/high-water. When `walCompaction` is absent, use the bounded
`wal_state` byte/count/maximum-sequence scalars captured before sealing; do not
infer replacements from payloads. `write_seal_duration` must be measured around
`seal_checkpoint`. The runtime currently exposes no isolated serialization
duration and no isolated fsync-plus-readback duration; both fields must
therefore receive `UNOBSERVED_DURATION_MICROS` (`0`). In this Phase A contract,
zero means **not observed**, not “zero work”. `checkpointMs` includes
validation, write, fsync, readback, post-verification, and possibly WAL
compaction and must never be relabeled as either isolated duration.

`peak_rss_bytes` comes only from platform-normalized
`resource.getrusage(RUSAGE_SELF).ru_maxrss`: bytes on Darwin and KiB converted
to bytes on Linux. Current RSS is never relabeled as peak RSS. A verified
receipt observation carries the exact bounded `coalescedReceiptCount`,
including truthful zero, and a fresh aware timestamp captured after receipt
completion.

## Failure behavior

- Disabled configuration performs no diagnostics filesystem I/O.
- Invalid build or Registry identity disables only the adapter.
- Path, namespace, load, accounting, serialization, retention, and persistence
  failures are caught at the adapter boundary and produce fixed scalar status
  codes. Raw exception text is never retained or returned.
- Mutation measurement failure does not change the completed mutation result.
- Checkpoint accounting failure downgrades that diagnostic sample to
  non-detailed; it does not fail the checkpoint.
- Diagnostic persistence runs after authority completion. Failure preserves
  the storage core's prior valid artifact and cannot revise the checkpoint
  result.
- A live identity change clears pending sampling tokens and starts a new
  generation. It never reinterprets old rows under the new policy.
- Remote Journal `verified`/healthy state is only a producer observation and
  cannot flow into the proof adapter.

## Runtime integration risks

1. The thread-local handoff must be cleared on every verified, unverified, and
   exceptional checkpoint path. A stale handoff could attribute scalars to the
   wrong checkpoint even though the adapter's generation/token checks contain
   most cases.
2. Sampling must inspect the sealed mapping before its existing deletion, but
   optional persistence must occur only after the durable lock is released.
   Reversing either boundary risks excess peak memory or authority coupling.
3. `post_session_snapshot` is a mission type, not proof of successful session
   completion. JP/US flags must be set only after that mission's authoritative
   persistence succeeds and must be consumed once.
4. `_journal` intentionally swallows some non-tick failures. Its measurement
   hook must sit inside the proven-success branch and must not turn the
   optional adapter status into a raised error.
5. WAL byte delta can be zero after a valid append on unusual filesystems or
   races; it remains an estimate. The adapter must never reconstruct the
   payload to improve that estimate.
6. Optional diagnostics persistence is synchronous after authority and may add
   response latency. Burn-in must measure it; it cannot be moved inside the
   authority lock or used to change readiness.
7. The current Registry has only six instrumented classes. Any Registry count
   or policy change deliberately disables/rotates measurement until the
   instrumentation manifest is reviewed.
8. Pre-authority observers must remain lock-free. Calling `adapter.status()` or
   another adapter method there can wait behind diagnostics persistence and
   couple optional work back into WAL/journal authority.

## Verification and deployment gates

Focused tests cover default-disable/no-I/O behavior, strict build identity,
canonical resolver use, the `RLock`, all six Registry-bound producers,
scanner success seams, no adapter call before WAL/journal authority, timer
exclusion, sequence-pinned WAL-byte estimates, heartbeat-failure observation,
both durable-lock release paths, scalar-only mutation APIs, transient
identity-preserving checkpoint accounting, WAL scalar fallback, peak-RSS
normalization, session-flag clearing, truthful receipt zero/timestamp behavior,
daily sampling limits, identity rotation, failure containment, runtime-bound
null proof, and eight-thread mutation contention. Core suites remain required:

```text
test_argus_recovery_registry.py
test_argus_recovery_measurement.py
test_argus_recovery_measurement_storage.py
test_argus_recovery_proof.py
test_argus_recovery_phase_a_adapter.py
```

The `linux-4gib-recovery-measurement` CI job must retain exact Docker limits
`--memory 4g --memory-swap 4g`, verify cgroup `memory.max == 4294967296` and
`memory.swap.max == 0`, run both measurement benchmarks, require zero `oom` and
`oom_kill` deltas, and upload artifacts named with `${{ github.sha }}`.

Merge and deployment order is: independently accept PR C, independently accept
PR D, merge C and then D without rebasing (already completed), land this
adapter and implemented scanner wiring after backend conflicts settle, rerun
core/adapter/scanner and exact-4-GiB gates, then deploy with the feature still
disabled. Owner approval is required before any environment enablement.

An eventual canary burn-in must verify no changes in readiness/liveness,
checkpoint/WAL/receipt outcomes, restore behavior, or memory bounds; observe JP
and US sampling, identity rotation, retention under 12 MiB, permissions and
atomic replacement, and optional-failure containment for at least the agreed
retention window. Burn-in does not start a proof acceptance clock and does not
upgrade public truth.

## Evidence still missing for any future `PROVEN`

Measurement cannot supply proof. A later trusted verifier must independently
authenticate and read back a pinned authority manifest, compatible full
generation, complete ordered WAL tail with no gap/fork/overlap/regression,
Registry-bound complete state and mutation coverage, reducer/state-schema/build
and key identities, immutable external references, start/end restore roots,
verification receipts, and trustworthy clock/freshness evidence. Until that
entire verifier boundary exists and passes owner review, production remains
`NOT_PROVEN` and hard-RPO claims remain forbidden.
