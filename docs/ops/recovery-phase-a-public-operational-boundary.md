# Recovery Phase A — Public / Operational Boundary

## Outcome

PR B established the contracted boundary. V13 Compression Round 1 now reduces
that inventory to 158 contracts while preserving every authenticated
operator, owner-sync, and recovery-proof route. It is an API/product-boundary
change, not a recovery-authority change.

## Deterministic route inventory

`argus_route_catalog.py` declares every Flask rule with:

- route and methods;
- endpoint;
- trust domain and authentication policy;
- semantic mutation flag;
- response DTO family;
- consumer category.

The catalog contract test compares exact `(route, methods, endpoint)` tuples
with `app.url_map` and pins the accepted split:

- `PUBLIC=62`
- `AUTH_OPERATIONAL=87`
- `OWNER_SYNC=6`
- `RECOVERY_PROOF=3`

## Consumer disposition

| Surface/consumer | Disposition | Current contract |
|---|---|---|
| `/healthz` | `KEEP_PUBLIC` | minimal liveness/build DTO |
| `/readyz` | `KEEP_PUBLIC` | minimal readiness/build DTO; 200/503 truth unchanged |
| `/api/argus/data-quality/status` | `PRODUCT_DTO` | canonical fixed public diagnostics plus closed `systemHealth`; `/data-quality` and `/system-health` aliases retired |
| `/api/argus/events-active` | `PRODUCT_DTO` | active event list plus product-facing backbone fields; `/event-backbone-status` retired |
| remaining Action Label/JP-US quote/AI/visibility/Learning Memory snapshot consumers | `PRODUCT_DTO` | public GET is state-free and provider/ledger-cache-only; process-bootstrap/authenticated/background paths retain refresh authority |
| cached OSINT investigation | `PRODUCT_DTO` | verified-source allowlist; owner terms/raw agent claims excluded |
| Watchtower | `MOVE_TO_AUTH_OPERATIONAL` | existing Actions admin secret |
| breadth freshness runner | `MOVE_TO_AUTH_OPERATIONAL` | existing workflow admin secret |
| EC2 re-arm | `KEEP_PUBLIC` trigger + authenticated workflow verification | no new EC2 credential |
| memory snapshot/readback proof transport | `DEFER_TO_RECOVERY_PROOF` | cataloged; unchanged in PR B |
| static Data Quality/Command Center | `PRODUCT_DTO` | public-safe summary; rich panel removed |
| browser investigation/translation/vault mutations | `REMOVE` pending Security Gate | local no-op; no browser secret |

## DTO contracts

`argus_diagnostics_contract.py` is the sole serializer for the new DTOs.
Builders construct literal allowlists from scalar inputs. They do not spread or
copy internal dictionaries.

PublicDiagnosticsDTO is capped at 8 KiB and exposes only:

- response timestamp;
- liveness/readiness/overall state;
- semantic backend version and exact build SHA when available;
- coarse freshness counts and expected-disabled count;
- closed, bounded system-health lamps (`key`, `labelJa`, `status`, `detailJa`);
- conservative, non-authoritative recovery labels.

OperationalDiagnosticsDTO is capped at 512 KiB and exposes reviewed scalar
service, freshness, storage, durability, Remote Journal, feature, scheduler,
registry, OSINT, and cost-policy metadata. It never includes credentials,
owner payloads, prompts/model outputs, target/state identifiers, raw exception
strings, or extension maps.

## Hostile-field and error behavior

Tests inject eleven distinctive private-domain sentinels into Remote Journal
cycle, durable state, incidents, OSINT, mission/report/challenger/postmortem
collections, model output, owner data, AI integrity, and checkpoint V2 state.
Every one of the catalogued unauthenticated GET routes is requested with
network access disabled; none may serialize a sentinel. The mixed OSINT
investigation surface uses an explicit nested allowlist so raw agent synthesis,
owner terms, and future fields are not part of the public contract. Future
nested diagnostic fields must leave the public DTO byte-equivalent when
response time is fixed.

Unauthenticated operational requests and moved POSTs return a fixed 401 (or a
fixed 503 when admin auth is unavailable). Diagnostic builder failures return
fixed safe fallbacks. New code does not log tokens or raw exceptions.

## Intentional product changes

The static Data Quality page and AppShell consume one shared public diagnostics
snapshot containing service, freshness, system-health, and recovery-claim
lamps; the persistent `/system-health` polling lifecycle is gone. Rich
unauthenticated operational details are intentionally unavailable. Browser
buttons that formerly mutated server queues are intentionally non-operational
until a separate owner-authenticated browser architecture exists; they do not
fall back to exposing a token.

## Explicit non-regression boundary

PR B must remain byte/behavior neutral for WAL append/replay/framing,
checkpoint write/readback, compaction, recovery authority and encryption,
Remote Journal promotion/receipt authority, Stage1/V2 authority, Soak, and
investment decisions. No production environment/configuration change,
deployment, restart, or key enablement is part of this PR.
