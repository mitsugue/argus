# WAL cursor and mission report lifetimes

Backup bookkeeping needs the WAL's validated count, maximum sequence and byte
count. Retaining every decoded transition for those scalar reads overlaps
full WAL owners with the checkpoint and report temporaries.

`read_valid_wal_cursor` uses the full reader's exact record decoder and checks
every line. It retains one parsed row at a time and returns only `recordCount`,
`corruptCount`, `maximumSequence` and `bytes`. It does not write, truncate or
compact the WAL. Replay, compaction, record ordering, hash validation, corruption
handling and the existing full reader's returned records keep their contracts.

The runtime consumers are limited to mission-entry bookkeeping, the final
checkpoint cursor and deferred-compaction reporting. A verified remote receipt
still controls actual compaction. The reader is not a new recovery source.

`mission_report_scalars` preserves the `reportId` and `status` values consumed
by mission bookkeeping. Producers and public readers continue returning complete
owned reports. The mission releases each full report after retaining those two
fields; this does not omit a calculation or change a dataset or report hash.

The existing tracked collection may retain three closed completion observations
for owner diagnostics. Each observation is sampled at an actual terminal event,
with its collection bounds, native memory, process identity and startup restore
state. Old starts, duplicate windows and unrelated later research do not become
successful completions. This extends the existing bounded in-process record;
it adds no timer, collection, provider request, AI call or persistent store.

Controlled comparisons use unchanged synthetic files, full original validation
and fresh native allocators without explicit collection or trimming. Component
measurements do not replace same-process production memory and restore acceptance.
