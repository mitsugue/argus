# Recovery Phase A — Recovery Proof Core

Status: isolated, private/internal, non-authoritative proof library for PR D.

Recovery Proof Core answers one question for one explicitly pinned evidence
package: is exact cold recovery `PROVEN` or `NOT_PROVEN`? It does not select an
authority, fetch an object, decrypt data, replay state, restore production, or
change current recovery behavior. Current production remains `NOT_PROVEN`.

The module is `argus_recovery_proof.py`. It has no dependency on PR C and no
scanner, route, frontend, checkpoint, WAL, compaction, Remote Journal, Stage1,
V2, Soak, storage, environment, or network integration.

## Trust boundary

The evaluator accepts only the exact `VerifiedRecoveryEvidence` class. That
class is frozen and deliberately has no public value-taking constructor. A raw
mapping such as `{"tagVerified": true}` cannot enter the evaluator as trusted
evidence, and a raw string such as `"FULL_PLUS_WAL"` cannot stand in for its
typed enum.

A later trusted verifier adapter may use the module-private
`_trusted_evidence_from_verifier` boundary only after it has:

1. fetched the pinned immutable objects;
2. performed the configured cryptographic verification and readback;
3. executed the isolated restore externally;
4. produced the exact typed observations and receipt.

The core verifies metadata/transcript consistency. It does not implement
cryptography and it cannot prove that a dishonest in-process caller actually
performed external verification. Python private names are an accidental-use
boundary, not a security token. PR E must keep raw request/caller data outside
this boundary and supply an audited verifier adapter.

Verification fields use identities, expected/observed digests, immutable
locator digests, state roots, exact sequence ranges, and verifier receipt
digests. They do not use `tagVerified`, truthiness, health, readiness, Stage1,
V2 status, overlay existence, timestamps alone, or Legacy Remote Journal
health.

## Exact evidence model

`argus-recovery-proof-evidence-v1` binds:

- authority epoch;
- pinned AuthorityManifest identity, digest, observed digest and pointer;
- initial and final manifest readback identities;
- FullGeneration identity, expected/observed digest and compatibility;
- baseline WAL sequence `T` and remote covered high-water `H`;
- state roots at `T` and `H`;
- ordered WAL segment identities, ranges, predecessors, roots and receipts;
- Registry Core policy digest obtained through
  `registry_policy_sha256()`;
- reducer, state-schema, producer-build and verifier-build identities;
- all must-preserve state coverage;
- all declared mutation coverage;
- declared immutable external references and verification observations;
- isolated restore root and receipt;
- explicit verification timestamps, clock evidence and verifier receipt.

Dataclasses are accepted only as their exact class with their exact complete
instance field set. Subclasses, missing fields, injected fields, wrong
containers, raw enum strings and implicit conversions are denied. Integers
must be exact non-negative integers within the JavaScript-safe range; booleans
are not integers. Digests are lowercase SHA-256 hex, build identities are
40-character lowercase Git SHAs, identities use fixed bounded ASCII patterns,
and timestamps are canonical whole-second UTC values.

## `PROVEN` contract

`PROVEN` requires every checked predicate:

1. evidence cardinality is within policy and absolute bounds;
2. the exact evidence schema is supported;
3. all types and enums are exact and supported;
4. mode is `FULL_PLUS_WAL`;
5. the initial manifest identity/digest is pinned;
6. the initial readback exactly matches the manifest;
7. the final pointer/identity/digest matches the initial observation;
8. FullGeneration identity and generation match the manifest;
9. FullGeneration expected, observed and manifest digests match;
10. FullGeneration reducer/schema/build/key identities are compatible;
11. FullGeneration covers exactly `T` and has `stateRootAtT`;
12. the WAL tail covers exactly `T+1..H`, or satisfies the explicit empty rule
    with identical state roots at `T` and `H`;
13. there is no WAL gap;
14. there is no duplicate segment, digest or range;
15. there is no overlap;
16. there is no fork;
17. ranges and high-water do not regress;
18. every predecessor identity/digest is exact;
19. manifest/object/segment authenticity evidence and root chaining agree;
20. reducer, schema, producer build and verifier build are policy-supported;
21. evidence and policy match the current Registry Core policy digest;
22. every Registry Core `mustPreserveNow` state is exactly covered through `H`;
23. every declared mutation class is exactly covered through `H` with no gap;
24. every manifest-declared immutable external reference verifies exactly;
25. the isolated restore generation/sequence/root equals `stateRootAtH`;
26. the verifier receipt binds the full canonical evidence transcript;
27. one explicit verification window orders the initial read, object
    observations, stable final reread, trusted clock observation, receipt and
    explicit `now`, with each required freshness bound satisfied.

Any failure makes the status `NOT_PROVEN`.

## `NOT_PROVEN` default

The public canonical result contains only:

```json
{"status":"NOT_PROVEN","hardRpoClaimPermitted":false}
```

Invalid values, malformed objects, unsupported policy, evaluator containment,
and absent evidence all produce that result. The internal bounded transcript
contains only fixed predicate IDs, fixed outcome codes, policy versions and
non-secret evidence identities/digests. Raw exceptions, decrypted state,
owner content and arbitrary caller fields are never returned.

## Empty WAL rule

An empty tail is valid only when both conditions are explicit:

- `T == H`; and
- the manifest enum is `EXPLICIT_EMPTY` with zero declared and observed WAL
  segments; and
- `stateRootAtT == stateRootAtH`.

Missing segment data never implies an empty tail. `SEGMENTS` requires `H > T`
and exact contiguous coverage of `T+1..H`.

## WAL chain contract

The first segment must name the FullGeneration identity/digest as predecessor.
Each later segment must name the immediately preceding segment identity/digest.
The first start root equals `stateRootAtT`; each next start root equals the
prior end root; the final end root equals `stateRootAtH`. Segment identities,
digests and ranges are unique. Segment order must match the manifest order.
Every segment matches the pinned generation, key identity, reducer, schema and
producer build.

Gap, duplicate, overlap, fork, reorder, predecessor mismatch, regression,
cross-generation data, wrong baseline and final-root mismatch all deny proof.

## Unified verification window and generation binding

The package carries an initial pinned readback and a final reread. The final
manifest identity, digest, pointer, authority epoch and generation must equal
the initial observation and the manifest. All object/reference/restore
verification timestamps must fall after the initial observation and before the
final reread. The final reread must be fresh relative to explicit `now`, and
the final-reread-to-receipt gap cannot exceed the typed receipt-age limit. The
trusted clock observation must be fresh, must not precede the initial read, and
must exist before or exactly when the receipt is issued. The receipt itself
must be fresh. Future observations are rejected according to the explicit
typed skew policy; no hidden clock is read. A fresh receipt therefore cannot
refresh stale authority or clock evidence.

Pointer movement or generation mixing is always `NOT_PROVEN`.

## Registry policy and coverage binding

`make_proof_policy()` obtains the Registry Core digest from the accepted
`registry_policy_sha256()` API; no digest is hardcoded. The evaluator checks
that the proof policy still matches that live deterministic API and that the
manifest carries the same digest. A policy drift denies proof.

State coverage must exactly contain every current `mustPreserveNow` state,
once, for the pinned generation through `H`. Mutation coverage must exactly
contain every Registry Core mutation declaration, once, through `H`, with
`EXACT_COMPLETE` coverage and `COMPLETE_NO_GAPS` instrumentation.

PR D does not consume Measurement Core. PR E may later translate independently
reviewed Measurement Core instrumentation into the trusted proof evidence
boundary; it must not weaken these exact coverage predicates.

## Hard RPO contract

`hardRpoClaimPermitted=true` requires `status=PROVEN` plus all of:

- exact accepted mutation coverage through `H`;
- complete instrumentation with no coverage gap;
- verified remote durable lag no greater than the policy target;
- trustworthy explicit clock evidence;
- fresh clock evidence and fresh verifier receipt.

The default policy target is 1,800 seconds. Receipt/clock freshness defaults to
300 seconds under `EXPLICIT_UTC_SECONDS_V1`. These are typed policy values, not
hidden current time. Tests pass canonical `explicitNow`; the evaluator never
reads a clock.

A valid recovery proof with lag above policy remains `PROVEN` but returns
`hardRpoClaimPermitted=false`. PR D does not activate or publish this result in
production.

## Determinism and transcript

Given identical evidence, policy and explicit `now`, the result and canonical
transcript bytes are identical. Evaluation performs no filesystem, network,
environment, randomness or clock access. Canonical JSON is UTF-8, key-sorted,
compact and rejects NaN. Hash-seed subprocess tests cover deterministic output.

The canonical transcript binds the complete typed evidence package by digest,
but replaces the receipt's transcript-digest field with a fixed zero digest
before hashing to avoid a circular hash. The receipt must contain that computed
digest.

## Performance and cardinality

The evaluator checks metadata only. It does not replay state or load a
FullGeneration payload. Work and memory are linear in the bounded evidence
descriptors. Absolute maxima are:

| Evidence collection | Maximum |
|---|---:|
| WAL segment descriptors | 4,096 |
| Immutable external references | 256 |
| State coverage entries | 512 |
| Mutation coverage entries | 512 |

Policy may lower any bound but cannot raise an absolute maximum. Over-limit
input fails closed. The focused suite evaluates the maximum 4,096-segment
metadata package within a conservative ten-second tripwire; ordinary packages
are much smaller.

## No authority selection or fallback

The evaluator receives exactly one pinned package. It does not decide which
Git commit or remote object is latest, choose a snapshot, fall back from a
broken generation, or determine whether production should restore.

Recovery from a previous generation requires explicit operator/owner selection
outside this core and a separate complete proof package for that generation.
There is no `latest broken -> previous PROVEN` path.

## Non-authoritative boundary and PR E

PR D changes no restore authority, WAL implementation, checkpoint, compaction,
encryption, keys, nonce semantics, object storage, Remote Journal, readiness,
Stage1, V2, Soak, public API, frontend or production configuration. It creates
no recovery objects and does not implement FullGeneration production or WAL
v2.

PR E may later provide audited verifier adapters and runtime integration only
after independent review of PR D and its prerequisites. Until then, current
production diagnostics and behavior remain `NOT_PROVEN` with hard-RPO claims
disabled.
