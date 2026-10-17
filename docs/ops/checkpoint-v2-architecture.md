# ARGUS Checkpoint V2 architecture closure

Status: **Draft / owner validation required**. This document does not approve a
merge, deployment, restart, or Soak. Production remained read-only during the
inventory. The retained approximately 1.10 GB incident temporary was neither
opened, hashed, renamed, copied, nor deleted.

## Production inventory

Read-only source: public `GET /api/argus/osint/memory-snapshot`, observed
2026-08-04 JST. The response was 129,771,010 bytes. Canonical top-level values
sum to 127,497,217 bytes; separators/envelope explain the difference. A
reference-aware `sys.getsizeof` traversal estimates 468,924,819 bytes, while an
isolated real JSON parse peaked at 805,519,360 bytes RSS. The incident prompt's
earlier valid checkpoint was 124,008,215 bytes.

| Section | JSON bytes | % | Items | Approx Python bytes |
|---|---:|---:|---:|---:|
| marketLedger | 62,033,974 | 48.6552 | 12 | 188,735,242 |
| verifiedViewSnapshots | 27,369,764 | 21.4670 | 4 | 123,725,162 |
| assetChartReports | 17,240,251 | 13.5221 | 5 | 71,670,299 |
| chartIntelligence | 9,404,551 | 7.3763 | 9 | 32,677,097 |
| marketReplay | 6,590,261 | 5.1689 | 5 | 33,637,903 |
| todayIntelligence | 3,404,899 | 2.6706 | 6 | 13,640,225 |
| formalResearchBenchmarkV2 | 270,427 | .2121 | 15 | 745,370 |
| outcomes | 255,581 | .2005 | 10 | 1,158,008 |
| opsJournal | 238,853 | .1873 | 400 | 727,841 |
| missionWindows | 182,825 | .1434 | 240 | 565,424 |
| foundationJobs | 153,532 | .1204 | 4 | 568,565 |
| missions | 85,766 | .0673 | 120 | 261,535 |
| integrityManifest | 61,968 | .0486 | 12 | 191,538 |
| soakHistory | 43,722 | .0343 | 1 | 143,044 |
| formalResearchBenchmark | 40,608 | .0319 | 13 | 143,567 |
| soak | 37,129 | .0291 | 17 | 122,658 |
| opsJournalCompacted | 15,736 | .0123 | 40 | 61,025 |
| benchmarkRuns | 15,548 | .0122 | 20 | 53,362 |
| urlCache | 11,803 | .0093 | 60 | 37,266 |
| memory | 8,004 | .0063 | 25 | 30,461 |
| forecasts | 7,549 | .0059 | 10 | 27,678 |
| rpsHistory | 6,441 | .0051 | 32 | 24,395 |
| incidents | 5,926 | .0046 | 20 | 19,162 |
| baselineRuns | 5,453 | .0043 | 24 | 19,859 |
| costPolicy | 2,506 | .0020 | 6 | 11,770 |
| canaryLast | 1,892 | .0015 | 2 | 8,065 |
| remoteJournalCycle | 708 | .0006 | 21 | 2,936 |
| termOverlay | 555 | .0004 | 2 | 2,779 |
| missionTickDurability | 318 | .0002 | 10 | 1,481 |
| noteJa | 88 | .0001 | 1 | 134 |
| soakControl | 78 | .0001 | 5 | 553 |
| verifiedViewSnapshotsStateHash | 66 | .0001 | 1 | 113 |
| durableState | 59 | <.0001 | 2 | 474 |
| buildIdentity | 44 | <.0001 | 2 | 459 |
| decisionLedger | 38 | <.0001 | 2 | 383 |
| chartIntelligenceStateHash | 34 | <.0001 | 1 | 81 |
| marketLedgerStateHash | 34 | <.0001 | 1 | 81 |
| marketReplayStateHash | 34 | <.0001 | 1 | 81 |
| todayIntelligenceStateHash | 34 | <.0001 | 1 | 81 |
| assetChartReportsStateHash | 26 | <.0001 | 1 | 73 |
| opsJournalMeta | 23 | <.0001 | 1 | 322 |
| asOf | 22 | <.0001 | 1 | 69 |
| generatedAt | 22 | <.0001 | 1 | 69 |
| soakLastPersistAt | 22 | <.0001 | 1 | 69 |
| schemaVersion | 18 | <.0001 | 1 | 65 |
| missionState | 13 | <.0001 | 1 | 314 |
| forecastStore | 12 | <.0001 | 1 | 314 |

The six largest sections are 98.86% of serialized top-level data. No
substantial exact duplicate top-level graph exists. Only the three 22-byte
timestamps were exact duplicates. State hashes and the integrity manifest are
small verification metadata, not copied graphs.

### What grows and what is retained

`marketLedger` contains 45,063 observations across 32 series (maximum 2,441
records in a series), 4,617 turning points, 815 derived metrics and 214 import
receipts. Its inputs span the ten-year analysis window. `chartIntelligence`,
`todayIntelligence`, and `marketReplay` held append-only derived histories
without hard normalization limits. Those were the unbounded active
collections. V2 source normalization now enforces:

- market observations: 2,700 per series (maximum 90,000 overall), derived
  metrics 5,000, turning points 25,000, backtests 64, imports/rollbacks 1,000;
- chart: snapshots 512, zones 4,000, turning points 20,000, anomaly and
  relationship records 2,000 each, invalidations 4,000;
- Today: snapshots 1,024, short history 3,000, failed-rally outcomes 5,000;
- replay: current contexts 32 and compact receipts 1,024;
- missions 120, windows 240, forecasts/outcomes 200, incidents 20, journal
  events 400, compact journal batches 40, Remote Ack keys 800/400;
- view snapshots 24 current/48 receipts; asset reports 24 and 32 MiB in their
  existing cache contracts.

Records rotated from the active ten-year/bounded operational window are not
claimed to disappear: prior immutable Git/Remote Journal generations own the
historical evidence. V2 retains four local immutable generations for rollback.
No history is deleted during Stage 1.

### Growth model

The only directly observed gross delta is 5,762,795 bytes between the owner's
124,008,215-byte evidence and the 129,771,010-byte public snapshot. Treating it
conservatively as one day (it includes backfill and is not a stable daily rate)
gives the following **legacy unbounded** extrapolation:

| Horizon | Legacy extrapolation |
|---|---:|
| 7 days | 170,110,575 bytes |
| 30 days | 302,654,860 bytes |
| 90 days | 648,422,560 bytes |
| 365 days | 2,233,191,185 bytes |

V2 does not rely on that extrapolation: active count retention is finite,
individual rows are capped at 8 MiB, section byte limits are 8-120 MiB, and the
source plus SQLite file each have a 256 MiB hard ceiling enforced before
manifest promotion. Crossing any bound leaves the prior generation
authoritative and reports a classified failure. With the rolling windows in
normalization, the expected 7/30/90/365-day active snapshot plateaus rather
than accumulating; its absolute safety ceiling is 256 MiB at every horizon.

## Architecture decision

| Design | Write/restore memory | Atomicity/corruption | Growth | Decision |
|---|---|---|---|---|
| A. streamed monolithic JSON | bounded write, full `json.load` restore | one rename; one corruption domain | unbounded collections remain | reject |
| B. immutable files + manifest | bounded by segment | good, but transaction/index logic is custom | bounded only with extra policy | acceptable, not selected |
| C. immutable SQLite generation + manifest | bounded rows, section-at-a-time restore | FULL synchronous transaction, DB and row hashes, atomic manifest | hard count/byte ceilings | **selected** |
| D. external managed DB | potentially good | adds network/credentials/control plane | service-dependent | unnecessary for 4 GiB closure |

V2 writes `.v2-pending-<generation>/checkpoint.sqlite3` under a stable
cross-process lock. SQLite uses `journal_mode=DELETE`, `synchronous=FULL`, and
one transaction. Every row is canonical JSON no larger than 8 MiB with byte
count, SHA-256, row schema and generation ID. Every section records canonical
source bytes/SHA, schema and generation. After DB fsync and directory fsync,
the immutable generation is renamed, its complete file is stream-hashed, and
only then is the small manifest atomically promoted. A partial directory is
never authoritative. The prior manifest remains valid.

The whole DB hash isolates any page-level corruption; row hashes localize a
malformed segment. Restore verifies the manifest, DB byte count/SHA, SQLite
integrity, generation/schema, row counts and hashes. It never reads the
retained incident temporary.

`verifiedViewSnapshots` and `assetChartReports` are rebuildable presentation
caches. Their immutable V2 segments remain verified archive evidence but are
not required for immediate authoritative boot. Skipping their eager Python
graphs removes 44,610,015 serialized bytes and about 195,395,461 estimated
Python bytes. They may be rebuilt naturally or read through a future bounded
cache path; they cannot determine ledger/WAL recovery.

The WAL remains authoritative after the promoted generation. V2 neither
rewrites nor compacts it. Existing receipt-gated compaction remains unchanged.
Stage 1 V2 failure cannot convert a verified legacy checkpoint into failure.

## Migration and rollback

`migrate_legacy_checkpoint` hashes and parses only the configured old
checkpoint, writes V2 separately, records `legacy-sha256:<hash>` as the source
generation, verifies V2, and confirms the source inode/size/mtime did not
change. A matching generation makes retries idempotent. An interruption before
promotion leaves the previous manifest valid. The old checkpoint and WAL are
not rewritten or deleted, so rollback is the old reader/writer plus feature
flag off. Production migration must run in an isolated 4 GiB-capped process.

## Resource evidence

Actual public production-shaped snapshot on macOS, isolated local processes:

- source response: 129,771,010 bytes; canonical sections 127,497,217 bytes;
- V2 SQLite generation: 156,069,888 bytes (below preferred 160 MiB target);
- write baseline before source parse 16,580,608; loaded-source peak
  805,519,360; write peak 974,635,008; checkpoint-induced delta 169,115,648;
- bounded active restore baseline 16,891,904; peak 490,864,640; delta
  473,972,736 (below 512 MiB).

Local structurally equivalent probe (3 full write/restore cycles, 50 reduced
cycles): maximum peak 275,513,344 bytes, maximum delta 257,474,560 bytes;
repeated process RSS 18,153,472 -> 66,633,728 (retained +48,480,256, below
128 MiB); zero pending generations and four retained immutable generations.
This local run is not called a Linux cgroup proof. The Draft PR has a dedicated
`checkpoint-v2-gate` that runs the same 3+50 probe in Docker with exactly 4 GiB
memory and swap capped to the same value. Its artifact is the authoritative
Linux result.

## Failure matrix

Deterministic tests cover interruption during a segment, after the transaction,
after DB fsync, and after generation rename; size/disk budget breach; fsync and
rename failures; DB checksum mismatch; malformed row; missing DB; unsupported
manifest schema; lock contention; idempotent/interrupted old migration; WAL
immutability and replay/compaction tests. Every pre-promotion failure keeps the
old manifest restorable and leaves no pending generation. Two simultaneous
writers reduce to the same nonblocking OS lock proof.

Remote Journal unavailability does not invalidate local checkpoint success.
The production contribution was exactly 255,297 bytes for `opsJournal`,
`opsJournalCompacted`, and `remoteJournalCycle` combined (0.20%); V2 stores it
once, so after-redesign contribution is also 255,297 bytes. Pending active
events are capped at 400 and compact batches at 40; Remote Ack lists at 800 and
400; retries are constant-size cycle metadata; poison/incident evidence is
isolated by the existing 20-record incident bound.

## Finite rollout

1. **Stage 1 / owner-approved V2 validation:** enable dual-write only. Legacy
   checkpoint and WAL remain restore authority. Observe three natural verified
   generations; capture before/peak/after RSS, isolated restore, generation and
   temp counts, Remote Journal counts. This is not the formal Soak.
2. **Stage 2 / separate owner approval:** review Stage 1, promote V2 active
   sections as restore authority, perform one genuinely necessary controlled
   restart, verify exact generation plus WAL replay, then begin one final
   formal 72-hour Soak.

No RAM increase is part of either stage. PR #131 is decision **C**: a tactical
writer hotfix, superseded by the v13.4.0 Checkpoint V2 Draft.
