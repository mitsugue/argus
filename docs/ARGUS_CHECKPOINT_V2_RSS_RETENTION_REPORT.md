# ARGUS Checkpoint V2 RSS Retention Report

Status: v13.4.3 Draft release candidate. This document does not authorize a
merge, deployment, restart, authority promotion, or Formal Soak.

## Production evidence (read-only)

- Version / SHA: `13.4.2` / `45977125f9fc45cd5c99fb4633e506422fbddd33`
- Boot: `2026-08-05T18:37:14.485989+09:00`
- Health / ready: HTTP 200 / HTTP 200
- Restart count: 0
- Restore authority: legacy (`persistent_local`); V2 authority: false
- Formal Soak: not armed, not started
- Persistent V2 generations: four or fewer; pending generations: zero
- The separate Remote Journal backlog was observed read-only and was not
  flushed, retried, deleted, or otherwise changed.

The three accepted natural Stage 1 generation windows recorded these process
RSS-after values:

| Natural window | RSS after | cgroup peak |
| --- | ---: | ---: |
| 1 | 1,122,643,968 B | 1,462,845,440 B |
| 2 | 1,252,290,560 B | 1,758,191,616 B |
| 3 | 1,411,465,216 B | 2,197,975,040 B |
| Optional natural window 4 | 1,450,196,992 B | 2,200,928,256 B |

The first-to-third RSS increase is 288,821,248 bytes. Window 4 confirms the
unfixed production allocator continues to rise, but its incremental increase
from window 3 is 38,731,776 bytes and the per-call RSS delta is only 12,288
bytes; current peak remains below 3 GiB and restart count remains zero. The separate
manual-classified physical generation is recorded as evidence but generation
source classification is intentionally unchanged in this PR.

A safe read-only `/proc` sample of the same production process showed:

- process RSS: approximately 1.31 GiB; PSS: approximately 1.30 GiB
- anonymous PSS / private dirty: approximately 1.27 GiB / 1.27 GiB
- file PSS / private clean: approximately 30.7 MiB / 27.6 MiB
- swap: zero; threads: 17; file descriptors: 6
- open SQLite generation descriptors: zero; deleted descriptors: zero
- mapped V2 SQLite or pending-generation files: zero
- child processes: one small Python multiprocessing resource tracker

The final cgroup sample was 2,022,367,232 bytes current and 2,326,851,584
bytes lifetime peak, with 1,420,648,448 bytes anonymous and 558,399,488 bytes
file memory. Final process RSS was 1,450,254,336 bytes, PSS was 1,439,352,832
bytes, and restart count remained zero. File cache is not
being treated as process RSS.

At final read-only observation Remote Journal reported 10 pending events; the
oldest of the trailing pending set was approximately 2,949 seconds old. Exact
WAL receipt read-back remained verified at sequence 3401. This independent
backlog is not changed here.

## Root cause

The retained resource is unused anonymous allocator memory after the
generation-sized Python source graph and transient JSON/SQLite row buffers
have become unreachable. The long-lived process allocator owns those pages;
no application collection, history, database handle, mapping, thread, future,
or descriptor owns a generation-sized live object.

The expected lifetime ends after legacy promotion, V2 section encoding,
manifest promotion, and validation. Before this fix, two full normalized
checkpoint owners (`blob` and `sealed_blob`) remained alive through the whole
V2 call, and glibc retained the freed high-water arenas after function return.
The owner after Python reference release was therefore the process allocator,
not a reachable Python container.

Evidence connecting this mechanism to the production slope:

1. Production PSS is dominated by anonymous private memory, with no open or
   mapped generation database and no descriptor/thread growth.
2. The V2 SQLite connection is closed in `finally`; row payload bytes are
   deleted in the encoding loop; the manifest keeps scalar metadata only and
   is bounded to four entries.
3. An eight-cycle pre-fix reproduction reached approximately 314 MiB RSS while
   `tracemalloc` retained only about 109 KiB. SQLite connections/cursors were
   zero, threads remained one, pending generations remained zero, and disk
   generations remained bounded to four.
4. The approximately 140 MiB per production interval is consistent with one
   generation-shaped allocator high-water increment and the observed
   288,821,248-byte first-to-third increase.

Relevant paths are `scanner._osint_persist_locked`,
`scanner._checkpoint_v2_dual_write`, and
`argus_checkpoint_v2.write_generation`.

This is allocator high-water retention, not a proven live-object memory leak.

## Narrow fix

- `scanner._osint_persist_locked` releases the redundant unsealed normalized
  source immediately after the authoritative legacy checkpoint verifies.
- The Stage 1 caller explicitly transfers ownership of the sealed throwaway
  mapping to `write_generation(..., consume_snapshot=True)`.
- The writer removes each successfully encoded top-level section, clears the
  remaining mapping on every success/failure path, and drops the last loop
  reference before measuring RSS.
- For generation-sized consumed sources only, Linux invokes `malloc_trim(0)`
  after the final Python owner is gone. Unsupported allocators fail safe and
  remain visible to the unchanged resource gate.
- Allocator evidence is published only as bounded scalar telemetry. There is
  no unconditional `gc.collect()`, restart schedule, plan increase, telemetry
  reset, generation deletion, cap reduction, or acceptance-gate relaxation.
- Default `write_generation` calls do not consume their input, preserving API
  compatibility for migration and tests.

Legacy restore authority, four immutable disk generations, one pending limit,
transactions, fsync/hash/read-back semantics, Remote Journal behavior,
historical Soak evidence, and all ten incident temp files remain unchanged.

## Deterministic reproduction and acceptance

The gate constructs 41 sections, 43,348 SQLite rows, and a
113,788,303-byte serialized source (144,056,320-byte SQLite generation). It
runs eight consecutive write and read-back cycles in one long-lived process,
under the existing exact 4 GiB Linux cgroup.

Per cycle it records current/peak RSS, Linux PSS anonymous/file, cgroup values,
tracemalloc current/peak and top traceback deltas, GC counts, live SQLite
connections/cursors, mappings, descriptors, threads, futures, disk reserve,
lock duration, generation metadata, retained generations, pending generations,
and ten incident-temp hashes.

The local Darwin diagnostic completed all eight generations with verified
read-back, four retained generations, zero pending generations, no live
connection/cursor/FD/thread growth, immutable incident temps, and a 6,471,680
byte cycles-3-through-8 RSS increase. Raw samples included an equal pair, so
steady-state RSS was not strictly monotonic. Peak RSS was 326,467,584 bytes;
final/peak traced Python allocations were 759,960 / 145,168,015 bytes.
Darwin's allocator reported zero bytes from pressure relief; the authoritative
`malloc_trim` plateau evidence remains the required Linux 4 GiB PR check.

The first natural Linux check exposed an observer effect in the probe itself:
the raw cycles-3-through-8 RSS samples rose by only 708,608 bytes while a live
cross-cycle `tracemalloc` snapshot was retained. Each cycle's identical
allocation trace now runs in an isolated
diagnostic child. A separate authoritative long-lived process performs eight
writes and read-backs with only the production lifecycle, GC release, allocator
pressure relief, and RSS sampling between cycles. Production does not enable
`tracemalloc`; process isolation keeps every traceback/current/peak allocation
record without measuring the diagnostic allocator as application retention.
With observer state removed, the integrated local authoritative window
retained 589,824 bytes and its last three RSS samples were equal, so the
then-current strict monotonic gate passed.

The final exact-state natural run then produced a strictly increasing
cycles-3-through-8 sequence with only 15,691,776 bytes of total growth. All
live-owner/resource deltas were zero, the cgroup peak was 2,654,576,640 bytes,
and the independent 32-cycle job proved a nonmonotonic bounded allocator band.
Strict monotonicity over only six steady samples is therefore retained as
diagnostic telemetry, not a failure by itself. The unchanged 128 MiB RSS
envelope and the precise 32-cycle mapping/allocator gates remain authoritative.

The Linux authoritative synthetic run recorded 28,672 bytes of
cycles-3-through-8 RSS growth and
`strictlyMonotonicSteadyState=false`. All eight cycles were verified and
consumed, pending generations remained zero, retained generations remained
four, and SQLite connection/cursor, mapping, descriptor, thread, and future
counts did not grow. Conservative cgroup peak was 1,588,060,160 bytes, below
the unchanged 3 GiB acceptance ceiling in the exact 4 GiB cgroup. The exact
public-state pass intentionally repeats all eight cycles; its job budget is
180 minutes so the evidence is not reduced merely to avoid a timeout.

The gate still fails when any of these occurs:

- cgroup is not exactly 4 GiB or peak reaches 3 GiB
- cycles 3–8 grow by 128 MiB or more
- generation shape, write, restore, consumption, disk reserve, retention,
  pending cleanup, incident-temp integrity, or resource counts differ

## Regression scope

New regression coverage includes opt-in/default compatibility, eight
sequential generations, four-generation retention, bounded metadata,
serialization/transaction/checksum/post-manifest faults, lock contention,
validation failure, connection/cursor/mapping/FD/thread closure, allocator
telemetry, legacy rollback authority, no Formal Soak creation, and ten-file
incident-temp immutability.

Remote Journal, Soak/history, release identity, frontend lint/TypeScript/tests,
frontend production build, AST, YAML, shell, privacy/secrets, and full pytest
remain part of required checks.

## Finite rollout and rollback plan

Owner approval is required before every mutable production step:

1. Merge the single v13.4.3 RSS-fix PR.
2. Allow one normal Render Auto-Deploy; do not manually restart.
3. Verify exact SHA, version, boot, manifest, legacy authority, and no Soak.
4. Observe three new distinct natural `ec2_systemd` Stage 1 windows.
5. Require stable post-generation RSS and every existing independent gate.
6. Stop before addressing Remote Journal backlog or source classification.

Rollback is the prior exact v13.4.2 SHA through the normal approved deployment
path. Because legacy remains authoritative and V2 is non-authoritative, no V2
restore, promotion, checkpoint mutation, queue edit, or WAL edit is part of
rollback.
