# Checkpoint V2 mapping attribution

The v13.4.3 acceptance gate uses mapping categories, allocator bytes, Python
reachability, RSS/PSS and cgroup limits. It intentionally does not fail on the
raw total number of `/proc/self/maps` records alone. Linux may split or coalesce
anonymous allocator mappings without changing application ownership.

## Exact 32-cycle evidence

The isolated natural CI run used one Python 3.12 process, a 4 GiB cgroup, the
exact public production-shaped snapshot (47 sections, 45,203 rows,
158,736,384 generation bytes), retention 4 and no process reset.

- all 32 writes and the final full restore verified;
- pending generations returned to 0 and retained generations stayed at 4;
- active/retained SQLite, V2 temp, deleted, incident and unknown mappings were
  0 after return;
- connection, cursor, future, generation-context, thread and descriptor growth
  was 0;
- raw-payload telemetry owners and reachable large tracked containers were 0;
- steady total mappings fluctuated from 275 to 308 and ended at 305;
- allocator-large anonymous mappings fluctuated from 38 to 71 and ended at 68;
- final allocator anonymous RSS was 199,614,464 bytes;
- cycles 27-32 stayed in a 9,445,376-byte RSS band and a 3-record mapping band;
- steady RSS/PSS growth was 120,922,112 bytes, below the existing 128 MiB gate;
- cgroup peak was 1,400,467,456 bytes and disk free was 92,691,406,848 bytes.

The surviving anonymous mappings are predominantly 1 MiB or merged multiples
of 1 MiB created by the Python process with `MAP_PRIVATE|MAP_ANONYMOUS`. This
matches CPython arena-sized allocator retention. `mallinfo2` remained bounded
(14,667,776 system bytes and 7,396,672 in-use bytes at cycle 32), while syscall
tracing recorded 1,791 mmap calls, 1,601 munmap calls and no generation-file
mapping survivor. This separates Python allocator arena retention from glibc
arena growth and from an application-owned generation leak.

## Controlled trim comparison

The four-cycle tracemalloc comparison used identical data and topology.

| Variant | final RSS | allocator system bytes | in-use bytes | final maps |
| --- | ---: | ---: | ---: | ---: |
| pre-fix, no trim | 810,917,888 | 713,650,176 | 13,668,880 | 271 |
| candidate, no trim | 643,084,288 | 546,111,488 | 13,781,888 | 274 |
| candidate, trim | 120,811,520 | 511,258,624 | 13,846,512 | 282 |

Application ownership is released before trim. Trim materially reduces
resident free pages, the 32-cycle invocation remains inside the resource
envelope, and live/in-use and Python reachability do not grow. Therefore trim
is retained; it is not used as evidence that live objects were released.

## Precise gate

The gate keeps exact zero checks for generation, temp, deleted, incident and
unknown mappings. It also checks reachability/resource growth, a 256 MiB
anonymous allocator ceiling, 4 glibc arena mappings, 96 allocator-large mapping
records, bounded mapping/category bands, a 32 MiB final-six-cycle plateau band,
the existing 128 MiB RSS/PSS envelope and cgroup peak below 3 GiB.

These limits include measured headroom over the 32-cycle maxima. Removing raw
map-count checks entirely would lose useful leak detection; using total map
count alone was over-broad because it could not distinguish allocator arena
reuse from a surviving generation-owned resource.
