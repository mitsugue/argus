# Acceptance failure evidence

The business readback command records a failed gate even when an HTTP 200
response cannot be read as JSON. Its evidence distinguishes request failure,
body abort, invalid JSON, an empty JSON value, unsuccessful HTTP status and
snapshot acceptance rejection. Only fixed reason codes, expected contract
identities, HTTP status and existing build/trigger metadata are recorded.
Response bodies, response-derived identities and arbitrary exception text are
not copied into failure artifacts or command output.

The existing twelve-snapshot acceptance, build/trigger binding, freshness,
request timeout and producer retry/deadline conditions remain unchanged.
Authentication rejection still stops the ordinary data-read path immediately.
The owner reader still closes its session; if both readback and logout fail,
the artifact retains the readback code and the owner reader's combined failure.
A failure remains a nonzero command exit. No fallback, new retry, acceptance
skip, production request or diagnostic workflow dispatch is introduced.

The existing local synthetic measurement benchmark also retains its stdout
JSON and stderr in a pytest failure when its child exits unsuccessfully. Its
arguments, check=True, sample count, resource thresholds and assertions remain
unchanged. This reporting is restricted to that synthetic benchmark; it is
not a generic mechanism for logging production commands or their output.

## Migration and recovery

Successful business gate artifacts retain their existing shape. Failed gate
artifacts now consistently have status=failed and a fixed reason. Readback
failures can include a readback object with fixed per-contract missing entries.
Consumers must continue requiring a successful gate and must not interpret
artifact existence as acceptance. These diagnostics do not repair unavailable
or malformed snapshots. Correct the underlying producer, network, or response
problem through the existing release process; preserve the original failed run.
A rollback loses these additional diagnostics without changing market data,
profiles, authentication, history or recovery formats.

## Validation limits

Synthetic tests run the actual CLI and owner reader with a fetch implementation
restricted to one fixture origin. They cover success in both owner modes,
request/body/JSON/HTTP failures, wrong build/trigger, stale, malformed, duplicate
and substituted identities, authentication rejection, and concurrent readback
and logout failures. Private marker strings must be absent from output.
Existing release, profile, mobile, authentication and measurement regressions
remain mandatory. This unit does not identify the historical production HTTP
200 body failure, prove a production memory reduction, or complete a soak test.
It changes operational diagnostics only; product identity remains v13.7.52.
