# Recovery Phase A — State Registry and Measurement Foundation

Status: shadow-only implementation at baseline
`6caa1fb5aa1ef437d0300641e8b6598731900746`.

This slice makes recovery inventory and sizing claims machine-readable. It does
not change checkpoint selection, current WAL behavior, Remote Journal authority,
encryption configuration, Stage1/V2, Soak, readiness, or deployment.

## Authoritative State Registry v1

[`argus_recovery_registry.py`](../../argus_recovery_registry.py) is the single
typed registry for recovery state and mutation classes. Importing it performs no
I/O. Rows are explicitly sorted by stable identifier and serialize
deterministically.

State classifications are:

- A — authoritative, non-reacquirable.
- B — authoritative source facts or receipts.
- C — deterministic/recomputable only after a hash-equal rebuild proof over
  exact versioned inputs.
- D — reacquirable only after an accepted provider, entitlement, revision and
  point-in-time contract.
- E — cache/ephemeral.
- F — unresolved; owner semantics are required.

F is not disposable. Every F row is `mustPreserveNow=true`. C and D rows also
remain preserve-now until their explicit proof/contract flag is accepted. An E
row cannot be marked `FULL_PLUS_WAL` without a recorded reason. Private, client
or secret rows cannot be telemetry-exportable.

Registry v1 contains 61 state definitions: A 30, B 13, C 5, D 1, E 2 and F 10.
The ten unresolved states are asset reports, legacy scan state, buy candidates,
sweep/cooldown state, legacy `predictions.jsonl`, TDnet timing evidence, and the
four explicit client gaps (risk lines, replay drawings, pasted research and
dismissed gaps). All ten are preserve-now.

The registry explicitly keeps the client boundary separate. Holdings, trades,
research, judgment, snapshots, audit, FIRE and tombstones remain client-owned;
vault ciphertext remains an opaque external object. None becomes server
FullGeneration plaintext in this phase. Recovery root keys are also an external
secret reference and may never enter a checkpoint or telemetry.

Unknown state discovery uses `unregistered_state_ids()` and registry validation
fails tests loudly. It does not fail production startup because the inventory is
still shadow infrastructure.

## Mutation Class Registry v1

The same module declares 27 stable mutation classes. Each class identifies its
target state IDs, criticality, source family, reducer expectation, current
persistence route, current WAL coverage, proposed future WAL/external-reference
treatment, sync-durability candidacy and payload telemetry policy.

Current coverage is deliberately conservative:

| Current coverage | Classes |
| --- | ---: |
| COMPLETE | 0 |
| PARTIAL | 6 |
| INDEPENDENT_DURABLE_SOURCE | 4 |
| NOT_DURABLE_FOR_EXACT_REPLAY | 12 |
| UNKNOWN | 5 |

`INDEPENDENT_DURABLE_SOURCE` describes already successful immutable/public or
private Git writes, not the legacy mission WAL. It does not claim that separate
objects form one atomic recovery generation.

The current local mission WAL remains unchanged. It covers selected journal,
mission and cursor payloads but is neither a complete authoritative mutation
gateway nor a future authenticated remote WAL.

## Privacy-safe measurement

[`argus_recovery_metrics.py`](../../argus_recovery_metrics.py) accepts only:

- stable mutation class and telemetry-eligible target IDs;
- timestamp, success/failure, transition/record count and latency;
- canonical plaintext byte-count estimates;
- optional local scalar sequence;
- checkpoint section byte counts and existing timing/cursor metadata.

There is intentionally no payload argument. The persisted artifact has no field
for prompts, URLs, source text, model output, private research, holdings, secret
material, WAL payloads or recovery plaintext. Targets whose state registry row
forbids telemetry are replaced by a count, not an identifier. The legacy
prediction ledger is streamed only to count non-empty records and file bytes;
rows are never parsed or retained.

The mode-`0600` local diagnostic may retain a stable private mutation class as
allowed metadata, but the public data-quality projection combines classes whose
payload policy is `FORBIDDEN` into `private.redacted`. It never publishes their
class name or target IDs.

Measurements aggregate into aligned 5-minute buckets. 15- and 30-minute totals
and p50/p95/p99/max interval distributions are derived from those buckets.
Per-mutation plaintext sizes use bounded histograms; reported quantiles are the
histogram bucket upper bounds. Candidate record/segment values are explicitly
named `*PlaintextBytesEstimate`. No encrypted WAL byte claim is made because a
WAL v2 envelope does not yet exist.

In production the local file defaults to
`<persistent-root>/argus_recovery_measurement.json` (override:
`ARGUS_RECOVERY_MEASUREMENT_FILE`). Non-production execution leaves persistence
disabled unless that path is explicitly supplied, avoiding shared `/tmp` test
state. The artifact is:

- schema-versioned and marked `authoritative=false` /
  `coverage=SHADOW_INCOMPLETE`;
- atomically streamed, flushed/fsynced, hash-read back and replaced using the
  existing persistent-storage primitive;
- mode `0600`;
- bounded to 31 days, 8,928 five-minute buckets, 256 recent metadata samples,
  2,048 checkpoint samples and 12 MiB total;
- updated in memory on mutation and written only at the existing checkpoint
  boundary (plus explicit diagnostic/test flush), so the WAL hot path gains no
  measurement-only fsync;
- ignored safely if absent, malformed, partial, oversized or invalid.

The metrics file is not placed inside the authoritative checkpoint and is never
used for restore, WAL compaction, mutation acceptance, readiness or authority.
Failure to size a section or write the file is swallowed at the scanner boundary.

## Checkpoint and large-store accounting

At the existing checkpoint assembly boundary, the implementation makes one
streaming canonical-size pass over registered top-level sections. It records:

- final checkpoint serialized bytes;
- deterministic top-level section serialized bytes;
- explicit Market Ledger, verified-view, asset-report, chart-intelligence,
  market-replay and today-intelligence sizes;
- source assembly, section accounting and seal durations;
- the existing atomic writer's combined serialization/write/fsync/hash-readback
  duration (not a fabricated per-subphase split);
- peak process RSS when the platform exposes it;
- local WAL bytes, valid record count and high-water;
- `legacyRemoteAckSequence` and timestamp;
- legacy `predictions.jsonl` byte and non-empty-record counts.

This adds no checkpoint deep copy. Section sizes stream encoder chunks from the
already assembled snapshot. Per-mutation measurement canonicalizes only the
existing mutation-local record/proof, never the 130+ MiB checkpoint. Diagnostic
fsync is not performed per WAL record.

## Shadow RPO and exact recovery diagnostic

The public data-quality document adds three non-breaking fields:

- `authoritativeStateRegistry` — counts/validation status only;
- `recoveryMeasurement` — `status=SHADOW`, `coverage=INCOMPLETE`, approximate
  oldest observed mutation age, latest local observation, latest legacy ACK and
  legacy scalar lag;
- `exactColdRecovery` — `not_proven`, `shadow` or `proven`.

Legacy Remote Journal health and exact current cold recovery are separate:

```text
legacy compact readback / ACK healthy
    != complete immutable FullGeneration
    != contiguous authenticated remotely durable WAL tail
    != exact current cold recovery proven
```

At current `legacy_only` production, `exactColdRecovery.status` remains
`not_proven` even if `legacyRemoteHealth` is `verified_within_target`. The shadow
model sets `hardRpoClaimPermitted=false`; it cannot advertise “RPO <= 30m”. A
future `proven` result requires all four explicit inputs: complete authoritative
mutation coverage, verified exact FullGeneration, verified exact remote WAL tail
and verified exact AuthorityManifest. Phase A supplies none of those authorities.

## Thirty-day decision data

The collector can retain the inputs needed to compare one versus two daily
FullGenerations: mutation size/count distributions, 5/15/30-minute totals,
section composition, checkpoint timing/RSS, WAL-growth proxies and legacy lag.
It explicitly records `acceptanceClockStarted=false`.

The cadence decision still requires a later approved deployment and at least 30
consecutive production days spanning JP and US sessions, weekends and holidays.
No cadence decision is made in this PR.

## Later gated work (not implemented here)

After owner review of Phase A, the recommended next task is the Unified
Authority Transaction Gateway plus local shadow WAL v2. Subsequent independent
gates cover complete reducer/mutation coverage, FullGeneration/WALSegment object
formats, Candidate B object storage, small Git AuthorityManifest promotion,
hostile restore drills and only then an authority cutover. Production deployment,
keys, credentials, object-store provisioning, Stage1/V2/Soak and any cutover all
remain separate owner gates.
