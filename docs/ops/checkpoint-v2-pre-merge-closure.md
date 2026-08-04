# Checkpoint V2 pre-merge closure

This is a review artifact for Draft PR #133. It does not authorize merge,
deployment, a Render/EC2 change, a manual workflow/tick/heartbeat, or a formal
Soak. PR #132 is outside this change.

## Stage 1 formal-Soak control

`ARGUS_CHECKPOINT_V2_STAGE1=1` selects
`checkpointMode=dual_write_validation`. A new build SHA starts with
`formalSoakArmed=false` and `formalSoakState=not_started`. Ordinary
`ec2_systemd` mission ticks still write the authoritative legacy checkpoint and
WAL and additionally produce V2 validation generations. Manual, diagnostic,
and workflow-dispatch generations do not count.

The existing new-SHA automatic Soak path is suppressed while Stage 1 is
enabled. A formal Soak is possible only after three unique verified natural
generations, reviewed memory and disk evidence, isolated read-only restore
verification, recorded owner restore-authority approval, and a one-time arm.
The accept and arm requests persist control state but create neither a Soak nor
a heartbeat. Only the following qualified natural `ec2_systemd` window may
consume the arm. Consumption is one-time; subsequent natural ticks cannot
create a duplicate clock. Historical interrupted Soaks are never edited.

V2 remains validation-only throughout Stage 1. The legacy checkpoint is the
only production restore authority. Recording approval is not itself a restore
cutover.

## Memory measurement reconciliation

The two previously reported results are not combined:

| Run | Dataset | Topology | Source | Temperature / phase | Page cache | Allocator high-water |
|---|---|---|---|---|---|---|
| local exact public snapshot | public production-shaped JSON; 129,771,010 source bytes; 127,497,217 canonical bytes; DB 156,069,888 bytes | one local Python process per measured phase | process current RSS plus `ru_maxrss` | cold parse, write, and isolated restore | not in process RSS | yes in `ru_maxrss` |
| prior Linux gate | synthetic section-size fixture (59/26/16/9/6/3 MiB plus 120 missions, 240 windows, 400 journal, 40 compacted); not the exact public snapshot | orchestrator plus isolated write/restore children in one 4 GiB cgroup | child `ru_maxrss`; cgroup max was verified but old report did not capture `memory.current/peak` | cold children, synthetic write/restore, then warm reduced cycles | not in `ru_maxrss`; old cgroup peak not recorded | yes in child `ru_maxrss` |
| exact Linux gate capture | later public production-shaped JSON; 129,806,517 source bytes; DB 156,098,560 bytes | isolated write, restore, WAL and repeated-cycle children in one exact 4 GiB cgroup | cgroup `memory.current/peak`, process current RSS and child `ru_maxrss` | cold exact write/restore, then WAL and 50 warm reduced cycles | included in cgroup peak | yes in child `ru_maxrss` |

The local exact run measured write peak 974,635,008 bytes and write delta
169,115,648; isolated restore peak 490,864,640 and restore delta 473,972,736.
The earlier synthetic Linux gate measured maximum child RSS 173,039,616 and
maximum delta 145,076,224. They are different datasets and measurement scopes.

The exact Linux capture measured cgroup peak 753,143,808 bytes, write-process
peak 626,937,856, isolated-restore peak 387,080,192, WAL replay peak
27,623,424, and 3,608,576 bytes of retained growth after 50 reduced cycles.
It ended with zero pending generations and four retained generations. Its
first job result was incorrectly failed by a retired 512 MiB process-delta
threshold even though the comparable absolute cgroup peak was safe. Process
delta remains recorded for diagnosis but is not combined with an absolute
cgroup peak for acceptance.

The gate now performs an additional read-only public GET of the exact snapshot
and runs exact write, read-only restore, an observed-size 631,910-byte WAL
replay fixture, and repeated cycles inside an exact 4,294,967,296-byte Linux
cgroup. Its V2 evidence records:

- source file bytes and bounded item counts;
- cgroup `memory.current` before/after and `memory.peak`;
- process current RSS before/after and process `ru_maxrss` peak;
- SQLite generation bytes, restore peak, WAL bytes/replay peak, and exit;
- isolated-child topology, page-cache scope, allocator scope, and cold/warm
  execution labels.

The conservative acceptance value is the maximum of exact-run cgroup
`memory.peak` (includes children and page cache) and the exact child
`ru_maxrss`. The automated ceiling is 3 GiB, retaining at least 1 GiB of
headroom inside the exact 4 GiB cgroup. A delta-only or synthetic measurement
cannot override that result. Across the two exact captures, the most
conservative observed peak is 974,635,008 bytes, leaving 3,320,332,288 bytes
to the 4 GiB limit.

## Persistent disk budget

The contract treats Render's 5 GB as 5,000,000,000 bytes, not 5 GiB.

| Allocation | Worst case bytes |
|---|---:|
| retained incident evidence (observed aggregate) | 1,099,859,035 |
| current legacy checkpoint | 136,314,880 |
| legacy previous/backup | 136,314,880 |
| WAL hard planning allowance | 134,217,728 |
| Remote Journal local data | 67,108,864 |
| four retained V2 generations | 1,073,741,824 |
| one V2 in-progress generation | 268,435,456 |
| V2 manifests, lock and metadata | 1,048,576 |
| migration metadata | 16,777,216 |
| same-filesystem installer backups | 268,435,456 |
| operational reserve | 1,073,741,824 |
| filesystem overhead (5% of 5 GB) | 250,000,000 |
| **worst-case total** | **4,525,995,739** |
| **remaining beyond included reserve** | **474,004,261** |

V2 enforces four generations, 256 MiB per generation, 1 GiB retained V2
bytes, 256 MiB in-progress bytes, and a 1 GiB free-space reserve. Before a
pending directory is created it requires `free >= reserve + generation
budget`; an insufficiency is `checkpoint_v2_disk_reserve_insufficient`. A
refusal cannot modify the current manifest, legacy checkpoint, WAL, or
incident evidence. Only exact V2 directory names are measured or pruned.

The public runtime evidence gives 123,973,516 bytes for the valid checkpoint,
1,099,859,035 aggregate legacy temporary bytes, WAL 631,910 bytes and
3,953,586,176 free bytes. It does not expose the incident filename, device,
mount, filesystem, apparent size or allocated blocks. The authenticated Render
tab currently resolves to the login screen, so those values were not invented
and the actual evidence file was not accessed. Production disk acceptance must
remain false until a metadata-only `stat`/mount result records those fields.
The arm endpoint requires a reviewed disk-evidence ID, so this evidence gap
cannot silently start a Soak. Values from different filesystems must not be
added together.

## Dual-write failure isolation

A healthy legacy checkpoint/WAL remains a successful mission durability result
when V2 validation fails. V2 reports `state=validation_failed`, an exact stable
classification and bounded details; disarms Stage 1; leaves
`formalSoakState=not_started`; and blocks authority promotion. There is no V2
retry loop in the mission tick.

Covered classes are writer lock contention, source/section/count/row limits,
SQLite byte cap, disk reserve, transaction, fsync, generation/manifest rename,
checksum, malformed generation, and isolated restore failure. No V2-only
failure requires the whole mission tick to fail in Stage 1. A simultaneous
legacy/WAL failure still fails on its own legacy durability semantics; that is
not converted into a V2 failure.

## PR #131 → PR #133 supersession matrix

PR #133 contains PR #131 head `b9163a49e7e33b438ba3e14aff30b16858295c72`
as an ancestor, then adds incident-retention proof and V2. Therefore no PR #131
change needs a separate merge.

| Protection | Classification in PR #133 | Evidence / disposition |
|---|---|---|
| streaming serialization | fully superseded | inherited legacy streaming writer; V2 bounded rows |
| incremental SHA-256 | fully superseded | inherited legacy streaming hash; V2 row/section/file hashes |
| streaming byte limit | fully superseded | legacy 512 MiB; V2 section/row/DB/total caps |
| stable writer lock | fully superseded | inherited legacy lock plus V2 writer lock |
| PID/UUID temp ownership | fully superseded | inherited for legacy; V2 UUID pending directories |
| open-process detection | fully superseded | retained for ordinary legacy temps; incident evidence bypasses target open |
| abandoned temp handling | fully superseded | legacy reconciliation plus V2 pending reconciliation under writer lock |
| incident evidence retention | fully superseded | strengthened: pre-hotfix evidence target is never opened |
| atomic replace/promotion | fully superseded | legacy atomic replace; V2 immutable rename then manifest promotion |
| fsync ordering | fully superseded | DB/pending/root/manifest ordering plus inherited legacy ordering |
| WAL ordering | fully superseded | legacy WAL remains authority and is unchanged by V2 |
| receipt behavior | fully superseded | inherited without V2 coupling |
| Remote Journal separation | fully superseded | inherited; V2 has no remote publication authority |
| bounded pending queue | fully superseded | bounded legacy temps; max 16 exact V2 pending candidates and one writer |
| no full read-back buffer | fully superseded | inherited streaming verification; V2 file checksum streams |
| no second full parsed object graph | fully superseded | V2 partitions the live bounded snapshot; isolated restore is separate |
| startup handling of incomplete files | fully superseded | legacy exact-name reconciliation; V2 exact pending reconciliation; manifest ignores unpromoted generations |

Recommendation: retain PR #131 temporarily as an auditable reference until
owner acceptance of PR #133, then close it as superseded with links to PR #133
and this matrix. Do not merge it separately. No partial extraction is needed.

## Incident evidence no-read contract

Pre-v13.3.8 legacy temp evidence is discovered only through directory metadata.
The target inode is not opened, locked, read, hashed, copied, renamed, deleted,
or timestamp-mutated. Only aggregate public diagnostics are exposed. V2 uses
`.v2-pending-<uuid>` and `v2-generation-<uuid>/checkpoint.sqlite3`; a legacy
temp name cannot become a V2 candidate. Sparse-file tests patch `os.open` to
raise and verify inode, size, atime and mtime remain unchanged.

## Stage 1 production acceptance

Each of three unique generations must have ordinary `ec2_systemd` provenance,
a unique ID, committed transaction, all required sections, valid byte/count and
SHA-256 checks, promoted manifest, zero pending directories, legacy restore
authority, no manual source, no formal Soak, no restart since deployment,
reserve compliance and no oversized temp. Evidence must record RSS before,
peak and after, cgroup peak, generation bytes, duration, free disk before/after,
WAL sequence and Remote Journal state.

After generation three, an isolated read-only process must restore the matching
V2 generation without restarting production, compare active bounded sections
to the same legacy authority, and separately report intentionally archived
presentation sections. Only after reviewed resource/disk evidence and this
restore may owner approval and the one-time arm be recorded. Stage 1 itself
creates no formal Soak and begins no 72-hour clock.
