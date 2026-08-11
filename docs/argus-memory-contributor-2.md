# ARGUS memory contributor #2: bounded Remote Journal read-back

The v13.4.13 candidate removes a recurring whole-state over-fetch from the
Remote Journal Watchtower. It does not change the durable full snapshot, boot
restore, legacy checkpoint, WAL, receipt acknowledgement, Stage1, V2 restore
authority, or Formal Soak controls.

## Proven allocation mechanism

The existing public memory snapshot assembles every restore store, computes
state hashes, serializes one large Flask JSON response, and retains the final
UTF-8 response buffer until the request completes. The production-shaped
local fixture produced a 41,890,036-byte response. In one long-lived process,
32 full requests had a maximum single RSS increase of 145,096,704 bytes and a
cycle-one tracemalloc peak of 215,852,328 bytes. A separate allocator sample
after the response body was released measured 71,303,168 more reserved bytes
but only 165,888 more live bytes.

The production operation showed the same shape: RSS +176,283,648 bytes,
allocator arena +33,976,320 bytes, and retained-free +33,793,808 bytes. A
current exact-source snapshot was 131,352,744 bytes while its deterministic
Remote Journal receipt was 699,148 bytes.

The final comparison fixture preserves that production composition instead of
matching only the aggregate byte count: Market Ledger 62,168,679 bytes,
verified views 27,025,423 bytes, asset reports 14,859,501 bytes, chart
intelligence 10,996,745 bytes, replay 6,696,436 bytes, today intelligence
4,971,964 bytes, 400 signed journal events, and 10 outcomes. In separate
long-lived local workers, 32 compact and 32 full requests produced identical
verified receipts 32/32. The compact response was 698,509 bytes versus
127,423,887 bytes, process peak RSS was 805,175,296 versus 1,377,435,648
bytes, and p50 request duration was 261.587 versus 3,587.681 ms. Linux-only
allocator, cgroup, and OOM gates remain fail-closed and are proven only by the
exact 4 GiB CI job.

## Narrow compatibility boundary

`/api/argus/osint/memory-snapshot` remains byte/schema compatible and remains
the boot-restore source used by `caos-scan`. The new public-safe
`/api/argus/osint/remote-readback` route directly constructs the existing
`argus-remote-readback-v1` receipt from the signed journal projection,
outcomes, durability scalars, and four existing state hashes. It does not
construct verified snapshots, asset reports, research stores, or the other
full restore bodies.

Watchtower uses the compact proof for its bounded publish decision. A skip or
receipt-only recovery never requests the full endpoint. A publish action still
fetches the full boot artifact, derives a fresh receipt from that same full
response, brackets the fetch with exact build/ready/process-boot identity, and
uses only the fresh pair for stale-writer validation, commit verification, and
the existing asynchronous receipt intent.

## Explicit exclusions

- No `malloc_trim`, forced garbage collection, restart, or RAM workaround.
- No change to normalized-hash semantics or golden digests.
- No change to Remote Journal acknowledgement or retry ownership.
- No change to checkpoint mode, Stage1, V2 authority, or Formal Soak.
- No production merge or deployment is part of this candidate.
