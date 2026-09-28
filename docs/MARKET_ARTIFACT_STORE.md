# Derived market artifacts outside the sealed checkpoint

Status: implemented and unit/integration tested; production effect is to be
observed through the normal release path. This document does not claim a
production measurement.

## What changed

The six large market-state sections — `marketLedger` and the derived
`chartIntelligence`, `todayIntelligence`, `marketReplay`,
`verifiedViewSnapshots`, `assetChartReports` — were 146 MB of a 147 MB
checkpoint in the 2026-09-28 production projection; control state (missions,
journal, forecasts, outcomes, soak, cost policy) was under 1 MB. The derived
five are deterministic outputs of the ledger and provider history; the ledger
holds owner-imported observations that cannot be re-fetched.

Each artifact now lives in its own file under
`<persistent root>/argus_market_artifacts/<name>.json`
(`argus_market_artifact_store.py`). The file is an envelope with schema,
artifact name, the module state hash, a SHA-256 of the canonical payload,
write time, method version and build SHA. A file is rewritten only when the
state hash recorded at the previous checkpoint differs; every write goes
through the existing fsync+rename writer and is read back and compared.

The sealed checkpoint keeps `<name>StateHash` for every artifact plus a
public-safe `marketArtifacts` status projection (hash, bytes, timestamps,
outcome). It no longer embeds any of the six payloads. The encrypted
recovery sidecar carries hashes only, as before. The Remote Journal
projection (`/api/argus/osint/memory-snapshot`) drops the five derived
payloads but **keeps `marketLedger`** so owner-imported observations remain
recoverable off-disk; that is the only artifact in `REMOTE_PROJECTED`.

## Restore

`_osint_restore_once` first applies whatever a checkpoint or remote
projection still carries inline (legacy checkpoints), then merges every
readable artifact file. All merges are the existing monotonic or append-only
merges, so order does not matter and newer local state is never rolled back.
A missing, oversized, symlinked or corrupt artifact file is recorded in the
status row and logged; it never blocks boot. The artifact regenerates from
the ledger on the next mission tick. The analysis-name migration that the
checkpoint restore applies is applied to artifact payloads as well.

## What did not change

Checkpoint seal, WAL ordering and compaction, nonce authority, capability
minting, sidecar encryption and verification, generation installation,
checkpoint v2, and every route contract (`chart-intelligence?snapshot=
verified` ETag/304, `today-headline`, `index-chart`) are untouched. The
in-memory stores and the mission-tick generators are unchanged; this change
is only about what the 30-minute save serializes, seals and verifies.

## Compatibility and rollback

Old checkpoints restore as before (inline payloads are still merged). A
build without this change ignores the artifact directory and would resume
embedding payloads in the checkpoint; nothing is deleted or migrated in
place. Rollback is the normal release path.

## Residency (v13.7.58): the two largest stores leave RAM between saves

After the allocator fix the web process held about 1 GB between mission
ticks, and the sampled resident inventory named the largest containers:
`verifiedViewSnapshots` (47 MiB of JSON) and `assetChartReports` (23 MiB),
about a third of the resident Python objects. Both are read by public GETs
one item at a time, so they need not be resident.

`argus_market_artifact_items.py` writes, next to each whole-artifact file,
one file per item (`argus_market_artifacts/<name>/<key>.json`) plus an
`index.json` carrying the artifact state hash and `{key: id}`. The writer is
hash-gated per item (`snapshotId` / record key) and prunes keys that left the
store.

`scanner.py` keeps a residency row per store. After a checkpoint whose
artifact file **and** item index both carry the current state hash, the
in-memory store is emptied ("detached"). While detached:

- `_verified_market_snapshot`, `today-headline`, `index-chart` closes and the
  asset-report route read the single item from disk through a small
  byte-level LRU validated by file size + mtime, then run the unchanged
  verifiers (`verify_snapshot`, `argus_asset_chart_cache.current`);
- the checkpoint carries the artifact hash from the residency row and neither
  normalizes nor rewrites the store (an empty store is never written); the
  public projection and the Remote Journal read-back compare the same hash;
- every generator (`_precompute_verified_market_view`,
  `_publish_verified_market_views`, `_precompute_asset_chart_tick`, the
  release seed, the mission tick) re-attaches first, i.e. reloads the
  whole-artifact file into the store, so nothing is ever published on top
  of an empty store;
- boot restore leaves the store detached when the item index matches the
  artifact, and merges as before otherwise (legacy inline checkpoints,
  missing or stale item files).

The daily public market report cache holds a pointer to the verified 5D
snapshot instead of a deep copy. Residency scalars ride the owner-only
`memory-attribution` route (`marketStoreResidency`). A detach that cannot
prove its item files current (`items_not_current`, `index_invalid`) simply
keeps the store resident until the next healthy save.

## Follow-ups

- Hash-gate the `marketLedger` section of the Remote Journal projection as
  well, so the watchtower does not re-commit 34 MB every 30 minutes when the
  ledger has not changed.
- Extend residency to `chartIntelligence`, `todayIntelligence`,
  `marketReplay` and `marketLedger` (their readers are the generators and a
  few summary routes), then run the generators in a scheduled worker process.
- The recovery registry now declares the five artifact states as
  `LOCAL_SIDECAR` / `LOCAL_ONLY` and adds `market.artifact_status` for the
  checkpoint status row. `market.today_source` (short-selling source rows
  inside `todayIntelligence`) therefore moved from the sealed checkpoint to
  a disk file as well; those rows are re-acquirable from the provider and
  remain durable across restarts, but are no longer in the Remote Journal.
