# Recovery Phase A — Registry Core v1

Status: non-authoritative declaration library for the approved
`SPLIT_154` Phase A plan.

Baseline: `6caa1fb5aa1ef437d0300641e8b6598731900746`.

Registry Core has no scanner integration, durable I/O, route output, readiness
effect, or recovery-authority role. It declares the recovery inventory and
validates policy semantics for later Phase A PRs.

The earlier Draft PR #154 is architecturally superseded by the approved split:

1. PR A — Registry Core
2. PR B — Public / Operational Boundary
3. PR C — Measurement Core
4. PR D — Recovery Proof Boundary
5. PR E — Phase A Integration

PR A ports only the audited state/mutation inventory concepts. It does not port
PR #154 metrics, public serializers, checkpoint instrumentation, retention,
paths, or proof helpers. PR #154 remains unchanged and Draft while replacement
PRs are established.

## State declaration contract

`argus_recovery_registry.StateDeclaration` is frozen and declarative. Its
stable `stateId` identifies a logical recovery component; it does not contain
runtime state or payload bytes.

Classifications:

| Class | Meaning | v1 preserve rule | Intended future durability |
|---|---|---|---|
| A | Authoritative, non-reacquirable | `mustPreserveNow=true` | `FULL_PLUS_WAL` or `IMMUTABLE_EXTERNAL_REF` |
| B | Authoritative source fact/receipt | `mustPreserveNow=true` | `FULL_PLUS_WAL` or `IMMUTABLE_EXTERNAL_REF` |
| C | Deterministic only after exact rebuild proof | `mustPreserveNow=true` | `REBUILD_AFTER_PROOF` with exact inputs and reducer |
| D | Reacquirable only under accepted source contract | `mustPreserveNow=true` | `REACQUIRE_AFTER_CONTRACT` with explicit requirements |
| E | Cache/ephemeral | normally `mustPreserveNow=false` | `EPHEMERAL`; a retained cache requires `FULL_PLUS_WAL`, preserve-now and an explicit reason |
| F | Unknown/unresolved owner semantics | `mustPreserveNow=true` | `UNRESOLVED` only |

A, B, and F can never declare `EPHEMERAL`. C and D cannot be omitted in v1.
Registry Core contains no boolean that accepts a rebuild proof or reacquisition
contract. Such acceptance requires a later versioned evidence contract.

The current inventory is 61 states:

| Class | Count |
|---|---:|
| A | 30 |
| B | 13 |
| C | 5 |
| D | 1 |
| E | 2 |
| F | 10 |

F includes asset reports, legacy scan/buy/sweep/prediction/TDnet state, and four
explicit client recovery gaps. All ten remain preserve-now.

## Exact-type and total validation

`validate_registry()` accepts only exact declared forms:

- the state and mutation registries are exact tuples;
- every row is the exact frozen declaration dataclass, not a subclass;
- booleans require `type(value) is bool`;
- enums require the exact expected enum class;
- tuple fields are not converted from lists, generators, strings, or iterables;
- IDs and checkpoint keys use bounded ASCII patterns;
- descriptive text and tuple counts are bounded.

The declaration helpers perform no `bool()`, `str()`, tuple conversion, or enum
conversion. `allowedInTelemetry` defaults to the exact boolean `False`.
`mustPreserveNow` uses a private omitted-value sentinel: omitted E defaults
false; every other and every unknown classification defaults conservatively to
true. An explicitly supplied `None` remains invalid.

The validator treats its inputs as `Any`. Non-tuples, wrong rows, hostile
objects, raw enum strings, unhashable values and malformed nested fields return
stable sorted error codes. It does not call arbitrary `__str__`, `__iter__`,
`__hash__`, or truthiness hooks. Inputs beyond the fixed 512-row safety bound
are rejected before row iteration.

Exact declaration type is not treated as proof that the dataclass constructor
ran. The validator snapshots the exact instance dictionary, accepts only the
complete fixed field set, and reports a static `missing_field` or
`unexpected_instance_field` code for malformed exact instances. This includes
objects created with `object.__new__` and instances with a deleted field. It
never formats an invalid field value. A final static containment code protects
the total API from novel Python objects, while the supported malformed forms
retain their field-specific canonical errors.

## Privacy and telemetry

Telemetry permission is an affirmative policy capability, not evidence that
payload content is public.

Only exact `PUBLIC_METADATA` can set `allowedInTelemetry=true`, and only when:

- `containsSecret=false`;
- `containsOwnerPrivateData=false`.

These classes can never authorize literal public identifiers:

- `INTERNAL`
- `OWNER_PRIVATE`
- `SECURITY_SENSITIVE`
- `SECRET`
- `CLIENT_PRIVATE`
- `CLIENT_OPAQUE`

Unknown or malformed privacy is invalid and non-public. PR A exposes no public
API; the helper exists for PR B/C policy decisions.

Authorization is validity-bound: the state helper first applies the complete
declaration structural, exact-type, compatibility and privacy validator. A raw
string that happens to equal an enum value, an incomplete exact dataclass, or
any other validation-invalid declaration is denied even when its remaining
telemetry fields look permissive.

The current privacy counts are:

| Privacy | Count |
|---|---:|
| PUBLIC_METADATA | 11 |
| INTERNAL | 22 |
| OWNER_PRIVATE | 9 |
| SECURITY_SENSITIVE | 11 |
| SECRET | 1 |
| CLIENT_PRIVATE | 6 |
| CLIENT_OPAQUE | 1 |

Exactly 11 state identifiers are explicitly telemetry-safe. This permission is
still insufficient by itself to place any field in PublicDiagnosticsDTO v1.

## Mutation declaration contract

The 27 `MutationDeclaration` rows describe target states, criticality, current
persistence/WAL coverage, future treatment, reducer expectations, sync
durability candidacy, privacy and metadata policy. They do not intercept or
authorize production mutations.

A mutation identity is telemetry-safe only when all of these are true:

1. the complete mutation declaration is valid;
2. mutation privacy is exact `PUBLIC_METADATA`;
3. telemetry policy is exact `METADATA_ONLY`;
4. the target tuple is non-empty, exact, and contains no duplicate;
5. every target exists;
6. every target independently passes the state telemetry policy.

One private, internal, security, secret, client or unknown target denies the
whole mutation identity. Payloads are never authorized by this helper.

The optional raw state index boundary accepts only an exact `dict`. Before any
target lookup it iterates the raw entries without lookup, rejects every
non-exact-string key and incomplete/invalid value, proves each key equals the
validated declaration `stateId`, and builds a fresh canonical index. A custom
mapping, dict subclass, key mismatch, missing target, semantically duplicated
declaration or hostile object key is denied. Hostile key equality, hashing and
formatting are not invoked by authorization. Duplicate mutation targets are
malformed policy input and are never silently de-duplicated.

Current WAL-coverage inventory:

| Coverage | Mutation classes |
|---|---:|
| COMPLETE | 0 |
| PARTIAL | 6 |
| INDEPENDENT_DURABLE_SOURCE | 4 |
| NOT_DURABLE_FOR_EXACT_REPLAY | 12 |
| UNKNOWN | 5 |

No declaration claims complete current WAL coverage. Independent durable source
means a successful external write exists; it does not mean those objects form
one atomic recovery generation.

Exactly three mutation identities currently satisfy the literal-ID policy:

- `external.public_ledger_write`
- `market.asset_report_update`
- `market.verified_view_publish`

## Deterministic document and policy fingerprint

`registry_document()` returns declarations, a normative machine-readable
policy-semantics document, and a semantic golden vector evaluated through the
actual exported validation and authorization helpers. It contains no timestamp
or runtime payload. Every declaration field is explicitly serialized;
arbitrary object serialization is not used.

Canonical bytes use UTF-8 JSON with sorted keys, compact separators,
`allow_nan=false`, and no timestamp. `registryPolicySha256` binds:

- state and mutation schema versions;
- every declaration field;
- versioned exact-type and total-validator semantics;
- all A–F classification/durability compatibility rules;
- the complete state and mutation authorization rules;
- raw-index and duplicate-target denial semantics;
- an evaluated allow/deny/error-code golden vector covering public, private,
  malformed, mixed-target, unknown-target and representative durability cases.

The fingerprint is therefore not merely a declaration digest. Changing either
authorization helper's evaluated behavior changes the vector and digest even
when declarations are byte-identical. Changing a compatibility/type rule is
bound through its explicit rule version and normative document. Identical
policy produces byte-identical content and digest across processes and hash
seeds. PR C may later use it to reject measurement artifacts written under a
different policy; PR A persists nothing.

## Checkpoint inventory tripwire

The focused test parses the source AST for literal top-level keys assembled in
`scanner._osint_persist_locked` and compares them with registered checkpoint
keys. A new literal top-level checkpoint key fails deterministically until it is
classified.

`localCheckpointIntegrity` is registered separately because the sealing writer
adds it after the literal blob assembly.

Known limitations:

- dynamic/computed top-level keys are not discovered;
- nested-field additions are not discovered;
- in-memory, `/tmp`, client and external stores are not checkpoint keys;
- one checkpoint key may intentionally map to multiple logical source/derived
  declarations;
- the tripwire proves inventory coverage, not mutation coverage, durability,
  ordering, completeness, or recovery authority.

It is a test/discovery guard only. No runtime reflection or startup failure is
introduced.

## Non-authoritative boundary

Registry Core is not imported by `scanner.py` and is not wired into:

- WAL append, validation, replay or compaction;
- checkpoint assembly, seal or selection;
- restore or Remote Journal ACK;
- encryption, nonce authority or recovery keys;
- readiness or health;
- Stage1, V2 authority or Soak;
- public APIs or frontend behavior;
- investment decisions.

Future PR B may consume the privacy helpers for typed serializers. Future PR C
may bind the policy fingerprint to local shadow measurements. Future PR D may
bind the registry snapshot into exact-recovery evidence. Each remains a separate
owner and review gate.
