# Read-only verified-snapshot persistence

Published snapshot envelopes own their payloads. Publication creates and verifies
a serialized copy, then replaces current pointers; public readers return owned
copies. A writer can pin those existing envelopes in a new local mapping without
copying every payload. Replacing a publication pointer cannot change that mapping.

The private persistence hash revalidates every snapshot with the existing shared
normalizer and uses the existing canonical digest. The projection is a plain
mapping and receives no trusted normalized-store marker. It must only be hashed
or serialized by the worker, never mutated or returned to public requests.

The permitted integration is the checkpoint artifact writer and the mission's
before/after comparisons of its private published store. The comparisons keep
the raw `state_hash` entry point, with a private literal allocation hint; all raw
snapshot checks still run. The default mode, remote/readback, public memory
snapshot and owned-normalization paths stay unchanged. A JSON field cannot
select the allocation hint.

Restoration uses a read-only lookup before the existing `publish_atomic` call.
Each destination pointer still passes serialized readback, identity, age and
quality checks and owns its data independently from the restored input. Only
the unnecessary intermediate whole-store copy is removed.
Snapshot validation, invalid-record filtering, numeric normalization, order,
history retention, source state and serialized bytes remain unchanged. This
functional copy repair does not revise the historical normalized-hash
counterfactual or start a resource/Soak acceptance clock.

Acceptance requires independent legacy digest and full artifact-byte equality,
unchanged owned APIs and provenance rejection, pointer replacement during a
write, all exact release gates, and actual production resource/restore evidence.
An isolated allocation comparison is not production memory-plan acceptance.
