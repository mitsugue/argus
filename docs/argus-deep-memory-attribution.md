# ARGUS deep memory attribution contract

This change is diagnostic only. It does not trim the allocator, collect the
Python heap, modify checkpoint payloads, alter Stage 1, or start work. The
production answer remains unknown until the diagnostic is separately approved
and deployed.

## Static source-construction audit

The real legacy checkpoint path is `scanner._osint_persist_locked`. The source
boundaries are placed in that function, not in a synthetic wrapper. Version 3
also separates the previously broad mission-start-to-final-WAL interval into a
fixed prelude and M0-M23 mission path. These fixed phases store scalar
projections only.

| Boundary | Construction | Coexisting representations | Lifetime |
| --- | --- | --- | --- |
| S0 | Checkpoint source entry immediately before the final WAL read | Authoritative state, mission locals and the earlier route-level WAL representation | Until the mission route returns |
| S1 | Final valid WAL read and cursor projection | S0 owners plus a second bounded parsed WAL representation | Through verified checkpoint |
| S2 | Initial `blob` | One top-level blob; 1 direct reference, 11 shallow list slices, 5 shallow dictionary copies, 4 deliberate deep copies, 2 scalar/new projections | `blob` is retained until after T4 |
| S3 | Four bounded control normalizers | Authoritative controls + 4 normalized results retained in `blob` | Until after T4 |
| S4 | Market Ledger normalize + hash | Authoritative ledger + normalized ledger retained in `blob`; `state_hash` creates a second transient normalization and canonical JSON bytes | Normalized copy until after T4; hash copy/bytes until call returns |
| S5 | Chart Intelligence normalize + hash | Same three-representation peak pattern as S4 | Same as S4 |
| S6 | Today Intelligence and Market Replay normalize + hash | Each authoritative state + retained normalized state + transient hash normalization/canonical bytes | Retained copies until after T4 |
| S7V0-S7V7 | Verified snapshots: retained normalize start/complete, hash entry, internal renormalize, stable JSON tree, canonical string, UTF-8 bytes, hash return | Authoritative store + retained normalized store + transient normalized store + stable tree + string/bytes at their actual lifetimes | Hash temporaries end at S7V7; retained copy survives to T4 |
| S7A0-S7A7 | Asset chart reports: retained normalize start/complete, hash entry, internal renormalize, hash projection, canonical string, UTF-8 bytes, hash return | Authoritative store + retained normalized store + transient normalized store + projection + string/bytes | Hash temporaries end at S7A7; retained copy survives to T4 |
| S7 | Public-store aggregate boundary | Both retained normalized stores remain; all hash temporaries have returned | Retained copies until after T4 |
| S8 | Durability cursor and final source mapping | 10 retained normalized state/store results plus the S2 slices/copies in the complete source | Through seal and verified legacy write |

The exact source sizes are deliberately not calculated by recursively walking
production objects. Source phases instead report RSS, RssAnon, RssFile, PSS, allocator
arena/live/free/top-releasable, cgroup current/anon, and boundary deltas. Safe
cardinality metadata reports the number of records or top-level entries already
available in bounded stores.

### Exact broad-interval split

The old diagnostic reused the earlier T0 sample as S0. That meant S0-to-S1
contained the whole natural mission, provider/cache construction, mission and
outcome work, Remote Journal preparation and a second WAL read. It could not be
interpreted as a WAL delta. Version 3 makes S0 a fresh checkpoint-source sample
and adds these finite groups:

- P0-P4: route entry, authenticated body/lease construction, lease acquisition,
  checkpoint-lock acquisition, and the initial route-level WAL read;
- M0-M5: fresh mission entry, window/history, calendar, market-ledger,
  daily-short, and the three pre-view state hashes;
- M6-M10: each of the four fixed market-view publications followed by the
  post-view hashes/journal boundary (the exception path is recorded too);
- M11-M17: asset-chart work, mission generation, missed-incident processing,
  outcome resolution, mission execution, Soak/batch bookkeeping, and mission
  window finalization;
- M18-M23: Remote Journal receipt preparation start/complete, checkpoint
  adapter/lock entry, and the exact final WAL start/complete boundaries.

Every adjacent boundary includes a named operation and scalar delta. The
source S0-to-S1 interval is now only the final `read_valid_wal` operation.

### Materialization inventory (diagnostic branch)

Line numbers below identify the audited branch before the diagnostic commit;
function names are the stable reference.  "Unknown" means the value is not
available without adding a second traversal or serialization and is therefore
not guessed.

| Function | Input -> output | Expected size evidence | Copy/coexistence | Owner and release boundary |
| --- | --- | --- | --- | --- |
| `scanner.py:16423 _osint_persist_locked` S1 | WAL file -> parsed bounded WAL mapping | Production WAL is 387,396 bytes at the read-only baseline | New parsed records coexist with authoritative state | local `wal_state`; function return |
| `scanner.py:16423 _osint_persist_locked` S2 | authoritative globals -> top-level source mapping | 23 top-level materializations: 1 reference, 11 slices, 5 shallow dictionaries, 4 deep copies, 2 scalar/projection values | All slices/copies coexist with the authoritative globals | local `blob`; after verified write/read-back |
| `argus_research_benchmark.py:254`, `argus_research_benchmark_v2.py:269`, `argus_foundation_jobs.py:231`, `argus_cost_policy.py:28` | authoritative control state -> normalized dictionaries | bounded by each module's schema; byte size unknown without another serialization | four normalized dictionaries coexist with originals | entries retained by `blob`; after read-back |
| `argus_market_ledger.py:94/183` | ledger -> normalized ledger, then transient normalized hash input and canonical JSON bytes | per-object byte size unknown; included in the 129,693,651-byte production checkpoint | original + retained normalized result + transient second normalization/JSON can overlap | retained result in `blob`; hash temporaries end at `state_hash` return |
| `argus_chart_intelligence.py:779/830` | chart state -> normalized chart state plus transient hash representation | unknown without another traversal | same three-representation peak pattern | same boundaries as Market Ledger |
| `argus_today_intelligence.py:757/828` and `argus_market_replay.py:612/698` | decision/replay states -> two retained normalizations plus two transient hash representations | unknown without another traversal | each original can overlap its retained and transient normalized forms | retained in `blob`; hash temporaries end per call |
| `argus_verified_snapshot.py:319/339` and `argus_asset_chart_cache.py:59/227` | bounded stores -> retained normalized stores plus transient hash representations | record counts are captured at S7; exact bytes are not re-serialized | each original can overlap its retained and transient normalized forms | retained in `blob`; hash temporaries end per call |
| `argus_persistent_storage.py:123 seal_checkpoint` | source mapping -> shallow top-level sealed mapping | production checkpoint baseline 129,693,651 bytes | unsealed mapping + sealed top-level mapping coexist; nested values remain shared | caller locals through verified write/read-back |
| `argus_persistent_storage.py:59 _canonical_chunks` | sealed mapping -> bounded canonical JSON byte chunks | total canonical stream approximates checkpoint size; individual strings remain one existing validator-bounded token | iterator chunks coexist only while hashing/writing | generator/call stack; released per chunk/call |
| `argus_persistent_storage.py:675 write_checkpoint` | sealed mapping -> atomic temporary file then checkpoint file | production checkpoint baseline 129,693,651 bytes; local structural probe 1,563,161 bytes | no second whole response body; streamed encoding and filesystem buffers coexist transiently | writer call; temp atomically renamed, Python buffers released on return |

The public `/api/argus/osint/memory-snapshot` route is a separate large-state
projection, not the checkpoint writer itself.  Its static path repeats the six
normalize/hash pairs and assembles a response mapping for Flask JSON encoding.
The diagnostic does not call it during passive production collection.

### Seal and write lifetime

`argus_persistent_storage.seal_checkpoint` makes a shallow top-level mapping and
streams the canonical hash. Nested state is not deep-copied by the seal. The
unsealed `blob` and sealed top-level mapping coexist through T4. The unsealed
mapping is then released before the disabled-V2 adapter, and the sealed mapping
is released before that adapter is called. Atomic checkpoint encoding is
streamed in bounded chunks, but every JSON string remains one bounded token by
the existing persistent-storage validator.

### Static duplication finding

Six hash calls currently normalize the same authoritative object again after a
normalized form has already been retained in the checkpoint source:

- Market Ledger
- Chart Intelligence
- Today Intelligence
- Market Replay
- verified view snapshots
- asset chart reports

This proves a construction pattern with temporary duplicate object graphs. It
does **not** by itself prove that any one graph explains production RSS
retention. The diagnostic records each normalize and hash call separately so a
Linux production observation can attribute arena, live, free, anonymous RSS,
and cgroup changes without payload capture.

## Inter-mission operation contract

The latest-32 ring remains useful for individual examples, but is no longer
the attribution authority. Every observed operation, including sub-threshold
events, updates three independent bounded top-16 summaries:

- cumulative positive allocator-arena bytes (Space-Saving estimate and error
  upper bound);
- maximum single positive arena delta;
- cumulative positive RSS bytes (Space-Saving estimate and error upper bound).

Up to 64 known finite operation names also receive exact scalar aggregates.
The ring still retains the latest 32 qualifying operations: a known operation
is always retained; an unknown operation is retained only when an observed
scalar delta reaches 1 MiB. Each retained or aggregate row contains only:

- normalized operation type and route/task name;
- start/end/delta memory scalars;
- duration;
- whitelisted scalar result metadata.

Operations register in a hard-capped active set (at most 256 tracked tokens)
before sampling. Overflow is retained only as scalar counts and those spans
complete as `UNKNOWN`; unmatched or hung operations cannot grow a diagnostic
map without bound. Each result is
classified `EXCLUSIVE`, `OVERLAPPED`, or `UNKNOWN`, with active counts and an
overlap epoch. Same-thread nesting and cross-thread overlap are published as
separate scalar flags while conservatively retaining the required three-class
causality vocabulary. The published scope is explicitly
`instrumented_operations_only`; EXCLUSIVE is not a claim that unrelated native
threads were absent.

At T11 the recorder opens a bounded inter-mission interval and closes it at the
next pre-collected T0. Sixteen summaries are retained. Each has boundary
RSS/arena/free deltas, six fixed per-kind aggregate slots, concurrency counts,
top-four contributors, completed and still-active boundary-spanning counts,
and an unexplained residual. Only contained EXCLUSIVE signed deltas are
subtracted from the residual;
OVERLAPPED operations are kept as possible contributors to avoid double
counting process-wide movement.

Query strings, request bodies, symbols, provider payloads, tokens, UUIDs, long
hex identifiers, and unbounded exception messages are never recorded. HTTP
names come from Flask route templates rather than raw URLs. Dynamic identifiers
are replaced with `<id>`.

The following real task boundaries are instrumented:

- HTTP: health, readiness, state, system/ledger/research/admin memory and
  mission routes, market, prediction, OSINT, and checkpoint prefixes;
- scheduler: natural scheduler loop, full run, phase 5, and phase 5 rerun;
- background: legacy scan, OSINT agents, formal benchmark, foundation jobs,
  OSINT benchmark, and residency AI tick;
- journal: receipt preparation and completion;
- internal: checkpoint persistence plus each source normalizer/hash.

## Expensive GET audit

The static route audit identified these read paths as material candidates:

- `/api/argus/osint/memory-snapshot`: constructs the entire durable source and
  invokes all six normalize/hash pairs. This endpoint is intentionally excluded
  from passive production collection because it would create diagnostic noise.
- `/api/argus/admin/memory-attribution`: serializes the bounded 16-mission and
  32-operation histories. It is protected and is read once only after the
  natural collection window.
- `/api/argus/chart-intelligence`: can deep-copy the selected public chart
  projection but remains bounded by the chart store contract.
- `/api/state`, `/api/argus/data-quality/status`, `/healthz`, and `/readyz`: local
  state/health projections; representative GETs in the probe verify them.
- public quote/news/action endpoints: may call provider/cache helpers. The
  route recorder observes only the route boundary and never provider content.
- The former public learning/attribution history GETs are retired. The retained
  Learning Memory snapshot is cache-only and cannot initiate remote restore;
  authenticated/background paths retain acquisition authority.

## Local and CI proof

`scripts/deep_memory_attribution_probe.py` performs four isolated probes:

1. repeated S0-S8 construction using the real checkpoint function;
2. representative Flask GETs;
3. 32 complete legacy-only checkpoint lifecycles in a temporary directory;
4. scheduler/background bookkeeping boundaries plus privacy/bound events.

`scripts/memory_attribution_probe.py` additionally drives 10,001 operation
events with reusable scalar samples. It requires all top-K structures and the
history to remain bounded, the early heavy contributor to survive later noise,
RSS overhead to remain at or below 4 MiB when observable, and FD/thread counts
to remain stable. No forced GC or `malloc_trim` is used.

The GitHub workflow runs the probe in a Linux container with an exact 4 GiB
cgroup (`--memory 4g --memory-swap 4g`). It uploads the scalar JSON artifact.
No V2 generation is permitted, and all T6-T10 phases must be
`NOT_APPLICABLE`.

The closure branch was also exercised locally without forced GC/trim. On one
representative fixture, the current double-normalizing paths produced about
14.94 MiB RSS peak for asset-report hashing and 24.95 MiB for verified-snapshot
hashing; full S0-S8 source construction produced about 28.38 MiB and the full
legacy lifecycle about 30.33 MiB. A representative large read-only
verified-view route materialized about 1.11 GiB RSS and its largest Python
allocation site was JSON decoding. These are local causal measurements, not
claims about exact production magnitudes.

A deliberately uncommitted 32-cycle comparison hashed the already-normalized
representation. Hashes remained bit-for-bit identical in every cycle. Asset
tracemalloc peak fell from 18,000,507 to 13,399,797 bytes and verified-snapshot
peak from 24,909,814 to 18,219,521 bytes; median elapsed time fell from 380.95
to 232.87 ms and from 922.87 to 523.53 ms respectively. This experiment
defines a candidate narrow architectural correction but is intentionally not
part of the diagnostic PR.

The static ranking of other whole-state materializations is therefore:

1. representative verified-view response decoding/materialization;
2. retained normalized verified-snapshot store plus its transient stable JSON
   tree/canonical bytes;
3. retained asset-report normalization plus transient projection/canonical
   bytes;
4. the complete legacy checkpoint source/seal lifecycle;
5. the remaining market-ledger, chart, today-intelligence and replay
   normalize-plus-hash pairs.

## Interpretation limits

Local or CI evidence can prove that a named construction operation produces a
reproducible allocator/anonymous-memory pattern. Only a separately approved
production deployment can determine whether the same operation dominates the
accepted production T0-to-T1 and inter-mission growth. Until then the production
root cause remains unproven. This diagnostic change does not implement the
candidate "hash an already-normalized store" optimization; that remains a
separate, uncommitted experiment until causal and compatibility proof exists.
