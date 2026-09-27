# Recovery save materialization

This staged change keeps the existing recovery formats, canonical bytes, hashes,
AES-GCM/HKDF, nonce authority, WAL ordering, size limits, independent readbacks,
and crash boundaries. It reduces temporary encoding and copies inside one call.

The envelope length and body digest consume the ASCII ciphertext in bounded
chunks. Sidecar length counts that same ASCII string without building another
whole JSON byte buffer. Values outside the exact built-in fast path use the
existing canonical encoder. No verification result is cached across calls or I/O.

Freshly built or JSON-decoded payloads can retain their exclusively owned
targets after validation. Public validation still returns detached copies, and
build inputs are copied before becoming owned. Decryption reuses bytes from its
own validation only; an unusual copy-time text change uses the original decode
path again. The scanner releases checkpoint/journal and payload locals after
their last use, before the next large allocation. It does not force garbage
collection or skip reads.

## Compatibility and rollback

There is no data migration, rewrite, cleanup, new secret, or new dependency.
Existing sidecars/checkpoints and historical records remain readable. Old and
new producers/readers retain the same wire/storage contract throughout rollout.
No legacy reader is removed by this change. Rollback restores the previous
implementation through the normal release path without deleting or regenerating
saved results, nonce state, journals, or history.

## Validation and production acceptance

Canonical size/hash parity, exact limits, malformed input, copy-time mutation,
detached ownership, and actual encrypted save reference lifetime are covered by
the added tests. Existing publication, restore, nonce, producer, and crash tests
remain mandatory. Both Product and Recovery admission proofs are required for
the exact release candidate; prior candidates' certificates are insufficient.

External synthetic Mac measurements for the complete two-file candidate used
three fresh processes per variant, eight cycles each, in alternating order.
All 48 save/readback/nonce/WAL cycles succeeded. Median time was
23.175455 to 15.751614 seconds; median peak RSS was 672956416 to 567820288 bytes.
These are synthetic observations, not production improvements or 4 GiB/2 GiB
capacity acceptance. Production's last saved observation remains 330.436129
seconds and lifetime cgroup peak 5466861568 bytes.

After normal release, use authorized natural-run observations to assess save
duration, cgroup memory, legacy/readback success, nonce/WAL state, and failures.
Do not infer constant-resident memory reduction from temporary lifetime alone.
Do not lower capacity or start the final 72-hour acceptance from these tests.

