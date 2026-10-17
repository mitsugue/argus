# Owner acceptance artifact protection

This change protects the complete warm profile and seed, consumer and mobile
browser evidence when owner authentication is enabled. The existing password
and session scan still runs before publication. Encryption does not replace
that scan or any profile, snapshot, mobile or release admission check.

## Configuration and release order

Use a dedicated cryptographically random 32-byte key, encoded as 64 lowercase
hex characters, in the repository secret `ARGUS_OWNER_ARTIFACT_KEY`. Never use
an owner password, password hash, administrative token or signing key. Do not
place it in chat, shell arguments, source, artifacts or logs. Restrict access
to trusted workflows and retain a private recovery copy through the owner's
existing secret management process. This document does not create or install
that key, choose a backup destination, or enable production authentication.

Deploy this transport and verify both modes with synthetic content first.
Configure the dedicated key and existing owner login settings through their
normal private configuration interfaces, then accept server/build/reader mode
consistency and the owner's device migration. Keep owner mode OFF until those
steps and private recovery access are accepted. Invalid modes and missing keys
fail before reading owner content. There is no plaintext fallback for mode ON.

OFF preserves the existing raw profile transport and all acceptance criteria.
ON seals the entire sanitized profile; the consumer authenticates and restores
it before invoking the unchanged complete profile verifier and browser checks.
Same-run and explicit Pages-run consumers bind to the producer run ID. Consumer
and mobile evidence bind to their own run. Authentication failures do not cause
an anonymous retry, skipped test, or successful acceptance result.

## Envelope and bounds

Node's built-in AES-256-GCM encrypts each file with a fresh 96-bit random nonce
and a 128-bit tag. A separately encrypted manifest enumerates every file,
directory, file length and owner permission. Associated data binds repository,
candidate SHA, producer run ID, artifact purpose and record index/path. The
manifest uses a separate purpose. File names and original content are encrypted;
file count and encrypted lengths remain visible. This is confidentiality and
integrity for transport, not concealment of artifact existence or a substitute
for GitHub permissions. No new service or package dependency is introduced.

The envelope rejects extra/missing records, bad tags, another context/key,
absolute paths, traversal, duplicate paths, links and special files. Maximum
10,000 entries, 512 MiB total file bytes, 4 MiB manifest. File encryption and
decryption stream in bounded chunks; plaintext is held only in a private
staging directory until every record authenticates. The destination must not
exist and is published by rename only after validation. A failed operation
removes its own staging directory and leaves source and prior outputs alone.
A killed runner can leave private staging data; only explicit sealed artifact
directories are uploaded. Use ephemeral trusted runners, whose workspace is
removed after the job. This does not encrypt a runner's filesystem or backup.

Seed profiles retain the existing one-day artifact lifetime; seed, consumer
and mobile evidence retain 30 days. Other release evidence is unchanged and
contains its existing bounded result/identity metadata. This change does not
retroactively protect or delete old public artifacts, logs or offline clients.

## Recovery and key rotation

Keep the key available for the full lifetime of artifacts that must be read.
A manual consumer must use the same key and producer run ID as its source
profile. Downloaded ciphertext alone never authorizes a result. To inspect
retained evidence privately, run the same `unseal` CLI with the exact repository,
SHA, source run and purpose, passing the key only via protected environment;
use a new private destination. Do not publish the decrypted folder.

Do not rotate the key midway between profile production and consumption.
Coordinate a new seed/consumer generation after rotation, retain the prior
key privately for retained evidence, and distinguish failed old-key reads from
missing data. The implementation does not try multiple keys or downgrade.

A rollback to a version without this protection must not run owner mode ON.
Keep the protected version in place while recovering a missing configuration
or transport failure. Turning authentication OFF exposes ordinary anonymous
content and is a separate owner decision, not an automatic rollback step.
Existing profile/market/history/authentication stores are neither converted
nor deleted by this transport.

## Acceptance status

Local synthetic round trips and abnormal cases are required, including actual
profile contract validation after transport, wrong context/key, tampering,
partial envelopes and an existing destination. All original browser assertions,
12-snapshot checks, 15 Today checks, timing limits and release proofs remain.
Actual production key placement, encrypted Actions transport, owner iPhone
registration and production acceptance are separate pending steps.
