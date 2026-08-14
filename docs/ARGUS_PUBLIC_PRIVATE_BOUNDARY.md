# ARGUS Public / Operational Boundary

Recovery Phase A PR B replaces the historical, convention-based public-route
list with the machine-readable catalog in `argus_route_catalog.py`. The catalog
is compared exactly with Flask `app.url_map`; adding, deleting, or changing a
rule is therefore a trust-boundary change that must update the catalog.

The current catalog contains four trust domains:

- `PUBLIC`: unauthenticated product data, static assets, and the fixed
  liveness/readiness/PublicDiagnostics DTOs.
- `AUTH_OPERATIONAL`: existing `X-ARGUS-ADMIN-TOKEN` server/operator routes.
  Responses are still allowlisted and may not include credentials, prompts,
  model output, unrestricted owner content, or raw exceptions.
- `OWNER_SYNC`: the existing owner-sync/admin capability; PR B adds no browser
  authentication and no new credential.
- `RECOVERY_PROOF`: legacy proof transport recorded explicitly for later PR D.
  PR B does not promote or redesign recovery authority.

## Public diagnostics

`GET /api/argus/data-quality` and
`GET /api/argus/data-quality/status` are compatibility aliases returning the
same closed `argus-public-diagnostics-v1` DTO. `/healthz` and `/readyz` return
separate minimal fixed DTOs. The public contract contains service identity,
coarse freshness counts, and conservative recovery claims only:

- `mode=LEGACY_ONLY`
- `measurement=SHADOW_INCOMPLETE`
- `exactColdRecovery=NOT_PROVEN`
- `hardRpoClaimPermitted=false`

No runtime dictionary is copied into these DTOs. Unknown future fields are
dropped by construction. Public builder failure returns a fixed content-free
fallback. Public responses are capped at 8 KiB.

The cached OSINT investigation and research-mission status APIs remain public
product routes, but no longer copy their internal records. The former exposes
an explicit verified-source/research-status projection and suppresses owner
terms, unverified agent claims, raw model payloads, and private-mode detail.
The latter exposes trigger/status scalars only and suppresses synthesis and
owner relevance. A bounded hostile test requests every catalogued public GET
and rejects any of eleven private-domain sentinel classes.

## Operational diagnostics

`GET /api/argus/admin/diagnostics/operational` requires the existing admin
token and is intended only for server-side/operator consumers. Its
`argus-operational-diagnostics-v1` response is reconstructed from reviewed
scalars, capped at 512 KiB, served with `no-store`, and is not CORS-enabled for
browser origins. Builder failure returns a fixed authenticated 503 code without
an exception string.

## State-changing routes

The following eight formerly unauthenticated POSTs now require the existing
admin token:

- `/api/argus/caos/investigate-now`
- `/api/argus/news/translation-request`
- `/api/argus/osint/deep-dive`
- `/api/argus/osint/terms`
- `/api/argus/osint/verify-gaps`
- `/api/argus/osint/url-verify`
- `/api/argus/mover-causes/explain-request`
- `/api/argus/vault-push`

The static frontend does not receive or embed that token. The affected browser
actions intentionally degrade to local no-ops until the later Security Gate
provides an owner-authenticated UX. Existing server-side Watchtower and
breadth-freshness consumers use the authenticated operational route. The EC2
Remote Journal re-arm keeps only its existing least-privilege workflow PAT:
it checks public liveness/readiness, dispatches Watchtower, and Watchtower uses
its existing admin secret to verify operational truth before acting.

Historical Guide entries describe the behavior of their named releases; this
document and the route catalog are authoritative for the current boundary.

## Non-authority guarantee

This boundary changes serializers, consumers, and authentication only. It does
not change WAL, checkpoint persistence, compaction, recovery keys/encryption,
Remote Journal authority, Stage1/V2 authority, Soak, or investment decisions.
