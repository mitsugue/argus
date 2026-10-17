# ARGUS v13.5.4 Causal Event Memory

## Architecture decision

v13.5.4 adds a bounded canonical Causal Event Ledger rather than enlarging the
News Intelligence mail-audit buffer. The ledger is linked to the current
authorities:

- News Intelligence authenticates and normalizes trusted mail.
- Market Data Truth supplies point-in-time observations and source references.
- Prediction Ledger owns issued decisions and decision outcome scoring.
- Learning Memory consumes one stable observation per independent episode.
- SDA remains the sole final decision authority.

Event Memory is a non-authoritative evidence system. It cannot change a live
severity, forecast, position, or SDA weight.

## Durable ledger and privacy

Production records use the approved persistent root at
`/var/data/argus_causal_event_memory.jsonl`. The ledger is append-only,
hash-chained, sequence-checked, file-locked, fsynced, and fail-closed on a bad
record or corrupt chain. It is bounded to 100,000 records and 256 MiB; records
are individually bounded to 96 KiB. The public UI receives compact projections,
never the archive.

This evidence ledger is intentionally outside Recovery authority. Adding it to
Recovery's authoritative restore contract would be an authority change and is
not part of v13.5.4. The approved persistent disk provides durability while the
existing Recovery state machine remains unchanged.

Raw article/mail bodies, licensed excerpts, holdings, cost basis, quantities,
PnL, and owner portfolio fields are forbidden by validation.

## Point-in-time and revision contract

Each event revision freezes `firstSeenAt`, `knownAt`,
`eventDecisionCutoff`, source receive/publish times, normalized facts,
provenance references, market observations, and the regime known at that
cutoff. Future source or market observations fail validation. Initial severity
and initial causal hypotheses are immutable. Later source revisions,
assessments, outcomes, and reviews append new records; they never rewrite the
original claim.

The explicit policy identities are:

- schema: `argus-causal-event-memory-v1`
- event policy: `causal-event-policy-v1`
- causal policy: `causal-assessment-policy-v1`
- analog policy: `structured-regime-analog-v1`
- calibration generation: `event-calibration-shadow-v1`

## Causal lifecycle

Deterministic hypothesis templates describe the causal path, expected
directions, required intermediate variables, confirmation requirements, and
invalidation conditions. Status progresses through `OPEN`, `WATCHING`,
`PARTIALLY_CONFIRMED`, `CONFIRMED`, `WEAKENED`, `INVALIDATED`, `RESOLVED`,
`UNSCORABLE`, or `DATA_GATED`.

Assessments use only `CONSISTENT_WITH` causal language. Confirmation requires
the intermediate chain, not just a later asset move. Attribution is explicitly
`SINGLE_CAUSAL`, `MULTI_CAUSAL`, or `ATTRIBUTION_UNCERTAIN`. An old flag can be
recovered only after 24 hours and sufficient required evidence. A later
de-escalation can weaken or invalidate the thesis; unrelated fiscal yield
moves cannot recover an inflation flag.

Outcome records cover `1H`, `SESSION_CLOSE`, `1D`, `5D`, `20D`, and `60D`.
They link observed Market Data Truth metrics or preserve an explicit
`UNSCORABLE`/`DATA_GATED` result. They do not duplicate Prediction Ledger
scoring math and have no policy influence.

Scheduled BLS, Federal Reserve, and BOJ records explicitly distinguish an
`EXPECTED_EVENT` from verified `SURPRISE_INFORMATION`. A surprise exists only
when both actual and consensus values carry point-in-time evidence; a missing
consensus never becomes a fabricated beat/miss.

## Episodes, analogs, and learning

Related events are clustered by structured family, themes, entities, countries,
causal path, and a bounded time window. Headlines and future outcomes are not
clustering or retrieval inputs. Analog retrieval applies a deterministic
structured filter and regime match, examines at most 2,000 candidates, returns
at most 12 results, and counts one result per independent episode. It reports
cohort definition, origin counts, sample size, independence, missingness,
regime similarity, and confidence. It never turns a small historical hit rate
into a calibrated probability.

Stable analog work is cached by event version, analog-policy version, ledger
outcome generation, and exact point-in-time cutoff. Cache cost and hit metrics
are exposed in Event Memory health. Outcome distributions are grouped by
origin, horizon, instrument, and metric so replay and forward-live evidence are
never silently pooled.

`FORWARD_LIVE`, `HISTORICAL_REPLAY`, `BACKFILL`, and `SHADOW` are isolated.
Only one `FORWARD_LIVE` observation per independent episode can enter Learning
Memory maturity. Prediction Ledger receives bounded event/hypothesis evidence
references on newly issued decisions; old sealed decisions are not mutated.
Missed-material-event and false-alert reviews append auditable findings and
optional regression fixture references.

## Calibration safety and future gate

Production starts with Event Memory `ACTIVE` and Event Calibration `SHADOW`.
Automatic calibration is disabled. The displayed maturity is explicit and is
`INSUFFICIENT` until forward-live evidence qualifies.

The defined future `CALIBRATION_ELIGIBLE` gate requires at least 100 independent
forward-live episodes, 60 resolved independent episodes, a 120 trading-day
span, stable policy generation, replay/backfill exclusion, duplicate control,
walk-forward proof, holdout proof, statistically meaningful effect, an
auditable rollback path, and explicit owner approval. v13.5.4 does not grant
that authority.
