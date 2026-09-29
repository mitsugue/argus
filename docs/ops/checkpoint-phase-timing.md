# Checkpoint timing diagnostics

The owner-only memory-attribution document retains additive scalar fields in each existing mission record's metadata. No route, credential, diagnostic file, extra provider request, or checkpoint format is introduced.

Each fixed phase has checkpointTiming_<phase>Micros, Count, and Failures. Time uses a monotonic clock and includes child phases; nested durations must not be added together. Repeated calls accumulate within the same mission. A missing field means unobserved, not zero or success.

Phases: seal, measurement, transaction, resolve_authority, mint_capability, consume_capability, checkpoint_write, sidecar_write, sidecar_verify, generation_install. Ten fixed names yield at most thirty scalar fields. Only the thread that began the mission may record them. Counters saturate at the maximum exactly representable JSON integer. The existing bounded mission history controls retention.

The transaction includes existing authority resolution, capability checks, checkpoint writing, encrypted sidecar handling, pair checks, authority switch, and cleanup. It is not equivalent to the sum of child phases. The seal and optional measurement phases occur before that transaction. Existing T2/T3 timestamps remain the outer observation.

Function return objects and exceptions are unchanged. Timing failures are ignored; validation failures continue to propagate. No argument, result, exception text, checkpoint content, key, or environment value enters the diagnostics. Signature, WAL, nonce, recovery authority, readback, and rollback checks remain unchanged.

This instrumentation does not establish faster production saves, safe 4GB operation, or the formal 72-hour acceptance. The latter starts only after all v13.7 implementation and individual acceptance are complete.

## 2026-09-29: verified-view hash and artifact write stream instead of copy

Production attribution (build 88e9f49d, 05:10Z) put one `checkpoint_persist`
at +429 MiB RSS while the verified-view store (47 MiB JSON, 12 snapshots) was
attached, against +41 MiB for a persist with it detached (05:47Z). The persist
held, at once, the normalized copy, the whole stable tree, the whole canonical
string and its UTF-8 bytes for hashing, then a second canonical encoding for
the artifact payload digest, and finally a full parse of the written file for
read-back.

Changes, all digest-preserving:

- `argus_verified_snapshot.state_hash` / `state_hash_normalized` stream the
  canonical text one snapshot at a time into SHA-256 (the same scheme the asset
  chart cache already used). The observer phases keep their order; the counts
  are accumulated totals and `stable_tree_ready` reports `stableTreeAlive: False`.
- `argus_market_artifact_store.payload_sha256` streams two container levels.
- `write_if_changed` reads the installed file back by byte digest against the
  writer's digest instead of parsing the document into objects again.

Expected effect: the attached-store persist drops from about four whole-store
representations to the normalized copy plus one snapshot in flight. The next
slice removes the whole-store attach from verified-view generation itself.
