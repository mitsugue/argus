# ARGUS deep memory attribution contract

This change is diagnostic only. It does not trim the allocator, collect the
Python heap, modify checkpoint payloads, alter Stage 1, or start work. The
production answer remains unknown until the diagnostic is separately approved
and deployed.

## Static source-construction audit

The real legacy checkpoint path is `scanner._osint_persist_locked`. The S0-S8
boundaries are placed in that function, not in a synthetic wrapper.

| Boundary | Construction | Coexisting representations | Lifetime |
| --- | --- | --- | --- |
| S0 | Mission T0 sample | Authoritative in-process state only | Service lifetime |
| S1 | Valid WAL read and cursor projection | Authoritative state + bounded parsed WAL records | Through verified checkpoint |
| S2 | Initial `blob` | One top-level blob; 1 direct reference, 11 shallow list slices, 5 shallow dictionary copies, 4 deliberate deep copies, 2 scalar/new projections | `blob` is retained until after T4 |
| S3 | Four bounded control normalizers | Authoritative controls + 4 normalized results retained in `blob` | Until after T4 |
| S4 | Market Ledger normalize + hash | Authoritative ledger + normalized ledger retained in `blob`; `state_hash` creates a second transient normalization and canonical JSON bytes | Normalized copy until after T4; hash copy/bytes until call returns |
| S5 | Chart Intelligence normalize + hash | Same three-representation peak pattern as S4 | Same as S4 |
| S6 | Today Intelligence and Market Replay normalize + hash | Each authoritative state + retained normalized state + transient hash normalization/canonical bytes | Retained copies until after T4 |
| S7 | Verified snapshots and asset chart reports normalize + hash | Each authoritative store + retained normalized store + transient hash normalization/canonical bytes | Retained copies until after T4 |
| S8 | Durability cursor and final source mapping | 10 retained normalized state/store results plus the S2 slices/copies in the complete source | Through seal and verified legacy write |

The exact source sizes are deliberately not calculated by recursively walking
production objects. S0-S8 instead report RSS, RssAnon, RssFile, PSS, allocator
arena/live/free/top-releasable, cgroup current/anon, and boundary deltas. Safe
cardinality metadata reports the number of records or top-level entries already
available in bounded stores.

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

The operation ring retains the latest 32 qualifying operations. A known
operation is always retained; an unknown operation is retained only when an
observed scalar delta reaches 1 MiB. Each row contains only:

- normalized operation type and route/task name;
- start/end/delta memory scalars;
- duration;
- whitelisted scalar result metadata.

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
- `/api/state`, `/api/argus/system-health`, `/healthz`, and `/readyz`: local
  state/health projections; representative GETs in the probe verify them.
- public quote/news/action endpoints: may call provider/cache helpers. The
  route recorder observes only the route boundary and never provider content.
- learning/attribution history GETs: perform bounded remote ledger reads; they
  are distinguishable from in-process source construction by route name and
  mission-active flag.

## Local and CI proof

`scripts/deep_memory_attribution_probe.py` performs four isolated probes:

1. repeated S0-S8 construction using the real checkpoint function;
2. representative Flask GETs;
3. 32 complete legacy-only checkpoint lifecycles in a temporary directory;
4. scheduler/background bookkeeping boundaries plus 250 privacy/bound events.

The GitHub workflow runs the probe in a Linux container with an exact 4 GiB
cgroup (`--memory 4g --memory-swap 4g`). It uploads the scalar JSON artifact.
No V2 generation is permitted, and all T6-T10 phases must be
`NOT_APPLICABLE`.

## Interpretation limits

Local or CI evidence can prove that a named construction operation produces a
reproducible allocator/anonymous-memory pattern. Only a separately approved
production deployment can determine whether the same operation dominates the
accepted production T0-to-T1 and inter-mission growth. Until then the production
root cause remains unproven.
