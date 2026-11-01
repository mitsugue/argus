# Allocator policy, bounded reclaim and resident inventory (v13.7.55)

## Current scalar coverage and retained builtin graph

The server preserves the interpreter's default Python allocator and any
explicit PYTHONMALLOC or interpreter flags. Startup records the actual native
allocator name without re-executing the interpreter. The glibc thresholds and
existing bounded reclaim remain unchanged. With an explicit malloc allocator,
pymalloc arena statistics are UNAVAILABLE rather than zero.

When comparison input content changes, the old sealed candidate generation
cannot serve that content key. The comparison now releases the cache and
local reference to that obsolete graph before constructing its replacement.
Identical keys still reuse their candidates across horizons. Completed studies
and saved reports remain available if a new build fails; no obsolete candidate
is admitted to the new input. Inputs, formulas, thresholds, episode hashes,
validation, retention bounds and restore authority are unchanged. No GC or
extra allocator reclaim is introduced.

The market ledger state hash encodes the same sorted canonical JSON one array
item at a time. This avoids retaining the full Unicode encoding and its UTF-8
copy together with the resident history. Normalization, every field, array
order, scalar encoding and the stored hash remain unchanged. Individual row
encodings are temporary; no archive, row, receipt or restore check is omitted.

Chart, Today and replay state hashes also use the existing artifact chunk
encoder, with each consumer explicitly retaining its legacy JSON options.
Chart state keeps its default string fallback; the other state codecs retain
their own prior behavior. Artifact writing and verification keep their strict
default codec. Normalization and array order are unchanged. The existing
private collection record additionally projects only the already reported
cgroup anon/file/kernel counters and startup RSS integers, without another
request, to distinguish file cache from process resident memory.

The existing event-ledger backup shares the complete line/sequence/hash-chain
validator with restoration. Restoration still receives every record; backup
verification retains only count, tail hash and status. Only the exact trusted
reader selects that streaming path. Injected readers keep their verification
behavior, with summaries derived from their records. Chunk boundaries, bytes,
limits and manifest encoding remain identical. All chunk descriptors and the
limit are checked before a remote write, then one outgoing piece is retained.
No record or validation step is removed and no authority is switched.

Only when the operation view is read, the existing bounded native reader
also supplies five Python arena reservation counters outside the recorder
lock. Event snapshots do not perform this read. The closed private projection
retains no native table, raw text, addresses or exception details. Unsupported,
missing or malformed results stay UNAVAILABLE with unknown counters, not zero.

The existing operation view samples current OS/allocator scalars once when
read, outside its lock, and carries an opaque process instance plus PID.
The instance changes across interpreter replacement and survives recorder
resets; PID distinguishes forked processes. The existing post-collection GET
projects these counters, the kernel RSS high-water mark, cgroup limit/events,
and the trusted startup build/allocator identity into the existing private
timing file. It adds no request, heap walk, timer or raw response storage.
Missing or malformed scalars remain unknown. This enables ordinary stored
collection records to verify a repair without repeating hot diagnostics.

The existing owner-only `?inventory=1` response also contains `memoryCoverage`.
Its before/after samples retain the current process and smaps totals, glibc
arena/in-use/free/**mmap** counters, and cgroup current/peak/max/events. Missing
kernel fields remain unknown. `uordblks` alone excludes mmap chunks. A process
RSS or a serialized-size estimate cannot replace these counters, and a cgroup
peak includes other processes and file cache in that cgroup.

The selected twelve largest inventory roots receive a separate builtin graph
observation. Object identity is deduplicated across roots and cycles. Bytes
are attributed to first discovery in that order, not exclusive ownership.
Only exact builtin containers and scalars are visited; no element values,
inner keys, addresses, paths, custom hooks or object representations are output.
The walk is non-atomic: concurrent changes can make its sum differ from any
single instant. It proves neither the current heap size nor a current heap
lower bound, and it cannot account for native buffers or all module roots.

The walk is capped at 131,072 unique objects, 32,768 per root, 524,288 edges,
depth 64 and two seconds, with explicit incomplete statuses. It skips active
collection/heavy work, unknown finite cgroup limits, headroom below 128 MiB,
and another concurrent walk. It never calls GC or trim, clears a cache, starts
collection or AI, or changes a timer. Before/after metrics expose its own
measurement effect. All observations use the existing private diagnostics
storage; the public workflow log contains no production memory values.

On 64-bit Linux CPython 3.12, the same coverage also reads the small-block
allocator's current/highwater/reclaimed arenas, allocated and available blocks,
unused pools and allocator overhead. The interpreter's existing native stats
reader runs with the GIL held and writes to an isolated temporary FILE; stderr
is never redirected. The FILE and its descriptors are closed before parsing.
At most 16 KiB is read. The parser admits only fixed counters and the 32 size
classes after reconciling class totals and all arena components. Unsupported
runtimes, a missing native entry point, disabled pymalloc, missing counters or
inconsistent totals yield UNAVAILABLE, never a zero-allocation observation.

These are allocator reservations, not resident pages, whole-process heap size
or application-owned live objects. Allocated blocks can include interpreter
free lists; available blocks and unused pools are not automatically resident.
Compare the timestamped before/after allocator readings with OS anonymous RSS,
glibc counters and cgroup file/kernel memory. Readings taken during other work
cannot measure the diagnostic's own effect or assign growth to one operation.

These observations do not accept a production memory plan. Check the actual
production limit, boot/build, lifetime peak, memory events and collection
coverage separately. The owner runbook's 70% peak criterion and the existing
resource/restore acceptance remain required; neither a 4 GiB CI run nor an
unlimited/larger cloud machine supplies production 2 GB acceptance.

## Evidence

Runtime diagnostics run 36279443457 (build 22478dce, 2026-09-27, 16 mission
ticks) measured the web process **between** ticks at RSS 3.69 GB, anonymous
RSS 3.64 GB, cgroup current 4.29 GB, lifetime cgroup peak 5.47 GB on the
8 GB instance. The glibc counters at the same instant were:

| counter | bytes |
|---|---:|
| arena (all arenas) | 2,031,611,904 |
| in use (`uordblks`) | 183,752,512 |
| free but not returned (`fordblks`) | 1,847,859,392 |
| releasable from the arena top (`keepcost`) | 21,102,656 |
| free chunks | 4,883 |

So 1.85 GB of the resident set was allocator free space, not live state.
The market stores that this morning's artifact split moved to files
(147 MB of JSON) are roughly 0.5 GB as Python objects, measured locally at
3.1–3.6 bytes per JSON byte; they cannot explain the balance.

## Cause

glibc raises its mmap threshold dynamically each time a mapped chunk is
freed (up to 32 MB). After the first checkpoint save frees a large mapped
string, every later multi-megabyte temporary (canonical JSON, normalized
store copies, response bodies) is carved from the brk heap. When those are
freed, the pages stay in the arena because live small objects sit above
them; `keepcost` (what a trim of the top can return) is tiny. Under the
Flask threaded server each request thread may also acquire its own arena.

## What changed

`argus_allocator_policy.py` (pure, secret-free, never raises):

- `startup_policy()` — from the server entry point only, on Linux, sets a
  fixed `M_MMAP_THRESHOLD` (1 MiB; `ARGUS_MALLOC_MMAP_THRESHOLD_BYTES`,
  `0` disables the policy), `M_TRIM_THRESHOLD` (8 MiB) and `M_ARENA_MAX`
  (4; `ARGUS_MALLOC_ARENA_MAX`). Module import does not touch the
  allocator, so probes and tests observe the untouched default.
- `reclaim_decision()` — reclaim only when the published allocator counters
  report at least 256 MiB free-but-unreturned, at most once per five
  minutes, never while a mission tick owns the process. After a checkpoint
  save outside the tick the interval is skipped and the floor is 128 MiB.
- `resident_inventory()` — sampled serialized-size estimate per
  module-level container: name, type, length, byte count, status. Containers
  longer than 256 items are sampled and scaled (`ESTIMATED`), shorter ones
  are fully visited (`MEASURED`), so a whole-process inventory of ~340
  containers takes well under a second instead of the 8 s the first
  streaming version needed for three (v13.7.56). Element values are never
  copied into the result; a concurrently mutated container is reported, not
  retried.

`scanner.py` wires these in: `_allocator_reclaim(reason)` calls the existing
`argus_checkpoint_v2._release_unused_allocator_memory` (the same
`malloc_trim(0)` path the isolated writer already uses) and records
before/after RSS and allocator counters in `_ALLOCATOR_RECLAIM_STATE`. It is
triggered from the five-minute scheduler boundary and after
`_osint_persist` outside a tick. The owner-only
`/api/argus/admin/memory-attribution` route always carries
`allocatorReclaim` and, with `?inventory=1`, `residentInventory`; the
`runtime-diagnostics` workflow requests both and prints them.

## What did not change

No route was added. Checkpoint seal, WAL, sidecar, capability, generation
install, the 4 GiB checkpoint-v2 gate and its probes, and the memory
attribution measurement contract (which still never trims inside a measured
phase) are untouched. `gc.collect()` is not called. Nothing is deleted,
reset or downgraded.

## How to read the effect

After deploy, dispatch `runtime-diagnostics`. First observation (v13.7.55,
run 36417719767, 8 minutes after boot, before the first mission tick): the
policy reported `APPLIED`, the free arena was 50 MB, so no reclaim was
due — the fixed mmap threshold keeps generation-sized temporaries out of
the arena in the first place. The meaningful reading is the one taken after
a mission tick: `allocatorReclaim.last` (`rssReleasedBytes`,
`allocatorBefore/After.freeBytes`) plus the tick's own RSS record. The next
reduction step (moving generation out of the web process and serving
verified snapshots from files) is sized from that inventory, not from
estimates.
