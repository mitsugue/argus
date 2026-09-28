# Allocator policy, bounded reclaim and resident inventory (v13.7.55)

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
- `resident_inventory()` — streaming serialized-size estimate per
  module-level container: name, type, length, byte count, status. Element
  values are never copied into the result. Per-object and total time budgets
  bound the walk; a concurrently mutated container is reported, not retried.

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

After deploy, dispatch `runtime-diagnostics`. Expect `allocatorReclaim.last`
to show `rssReleasedBytes` in the hundreds of MiB to about 1.8 GiB on the
first reclaim, `allocatorAfter.freeBytes` far below `allocatorBefore`, and
the resident inventory to name the remaining largest containers. The next
reduction step (moving generation out of the web process and serving
verified snapshots from files) is sized from that inventory, not from
estimates.
