# Recovery Phase A Measurement Core

Status: private, internal, non-authoritative, shadow only.

This library is intentionally not imported by `scanner.py` or any durability,
recovery, readiness, health, route, or frontend path. Runtime producer wiring is
deferred to PR E.

## Artifact contract

`argus-recovery-measurement-shadow-v1` is a recursively closed JSON schema. It
binds the measurement generation, producer build, instrumentation coverage,
measurement schema digest, and the live Registry Core policy digest. A policy
digest mismatch invalidates the old artifact; identifiers are never
reinterpreted under a newer policy.

The persisted document contains metadata only: five-minute aggregate buckets,
bounded daily distributions, bounded recent mutation metadata, bounded
checkpoint samples, coverage timestamps/classification, and aggregate counters.
It contains no payload, owner content, source text, URL, prompt/model output,
credential, token, arbitrary exception, or public serializer.

The fixed state remains `SHADOW / INCOMPLETE / NOT_PROVEN`; the acceptance clock
cannot be started by this schema.

## Bounds

- Artifact: 12 MiB maximum.
- Five-minute buckets: 8,928; 4 MiB category budget.
- Daily distributions: 32; 1.5 MiB category budget.
- Checkpoint samples: 2,048; 5 MiB category budget.
- Recent mutation rows: 256; 1 MiB category budget.
- Mutation classes: 27.
- Histogram bins: 25.
- Detailed checkpoint section keys: 48.
- Fixed shell: 64 KiB; reserve: 448 KiB.

Retention planning validates once, encodes each candidate row once for category
accounting, bulk-removes an oldest prefix, validates/canonicalizes the final
document once, and performs one atomic write. It has no repeated whole-document
serialization/deletion loop.

## Path and persistence contract

The future canonical location is:

`/var/data/diagnostics/recovery-measurement/measurement-v1.json`

The resolver is pure/configurable and does not read runtime environment. It
allows only a direct JSON child of the dedicated namespace, rejects authority
ancestor/descendant/prefix collisions, and rejects traversal, outside paths,
symlinks, hardlinks, non-regular files, and temp/lock names.
The explicit authority inventory includes the current `argus_checkpoint_v2`
subtree, `checkpoint-v2-manifest.json`, its atomic-write/global locks and
temporary prefix, pending/immutable generation prefixes, and isolated-job
prefix. The older reserved `checkpoint-v2` family remains protected as well.

The storage adapter uses no-follow directory/file descriptors, a same-directory
0600 temporary, file fsync, pre-replace destination revalidation, atomic replace,
and parent-directory fsync. Before any filesystem mutation it independently
derives the exact canonical encoding of the validated plan artifact and rejects
any precomputed-byte mismatch. A deterministic hidden recovery link keeps the
prior measurement inode recoverable until commit durability or durable rollback;
failed rollback never triggers generic recovery cleanup. A later load/persist
validates and restores a leftover recovery artifact before using it. The temp
and recovery names cannot be selected as destinations, and authority paths are
never opened for writing.

## Checkpoint accounting and sampling

The pure detailed-sample policy requests metadata accounting only for JP/US
session-boundary signals, schema/build accounting changes, or an owner-authorized
request. Normal session requests are capped at two per day. It does not import a
market clock and does not choose FullGeneration cadence.

Streaming canonical accounting visits each top-level value once, returns exact
total and registered-section byte counts, emits no full-size buffer, and caps any
future output chunk at 1 MiB.

## Reproducible benchmarks

```sh
python3 scripts/recovery_measurement_benchmark.py --target-mib 145 --samples 5
python3 scripts/recovery_measurement_retention_benchmark.py --samples 5 --hot-samples 200
```

The first constructs unique nested registered-section-like state and enforces
the 130–160 MiB accounting, time, ratio, RSS, and zero-full-buffer gates. The
second constructs a valid 13–14 MiB adversarial artifact and enforces linear
pass/encode counts, planning p95, max-state hot-path p95/max, and the 12 MiB
persisted result.
