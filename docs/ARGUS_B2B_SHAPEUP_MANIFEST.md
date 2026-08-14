# ARGUS B2b Shape-Up Manifest

Deterministic scope record for `codex/recovery-phase-a-shapeup-route-polling`.
The classification is the action taken in B2b, not a request to delete the
underlying domain engine or authority.

| Original surface | Class | New destination | Consumer migration | Reason | Rollback |
|---|---|---|---|---|---|
| `GET /api/argus/data-quality` | DELETE | `GET /api/argus/data-quality/status` | smoke/static/backend consumers use `/status`; B2a browser consumers already used it | byte-identical compatibility alias had no remaining required consumer | restore only the thin alias to the same closed DTO |
| selected Action Label/AI/integration/calibration/Decision Value/event/source/provider/depth/visibility/runtime/Learning Memory public family | MERGE | same public routes, cache-only DTO builders | sixteen status/aggregate browser consumers are pinned in `PUBLIC_CACHE_ONLY_CONSUMERS`; Event Ledger and persisted AI-view restore move to the existing process-bootstrap phase | these selected unauthenticated GETs must not perform provider, VWAP, private-Git, or ledger-restore work | keep DTO shape and restore live work only behind authenticated/background callers |
| JP/US watchlist browser reads | MERGE | same public routes, read-only provider-cache/bridge DTOs | both quote hooks are pinned in `PUBLIC_CACHE_ONLY_CONSUMERS`; provider acquisition remains in internal/background judgment and ledger paths; dynamic EC2 JP membership remains the existing authenticated OWNER_SYNC → private Layer-2B → admin bridge-code path | browser cadence must not spend J-Quants/Twelve Data/Finnhub quota or anonymously change the EC2 push target set | revert the explicit provider/state gates without changing quote DTOs |
| Evidence Pack and Decision Spine status | KEEP_PUBLIC | same public routes with stale-evidence rejection | no B2a default-mounted consumer; smoke/contract consumers remain | retain existing proof/product contracts while preventing ledger/private/provider refresh and current-time restamping from public reads | restore the prior builders only with an explicit authenticated refresh authority |
| standalone Rates, Event Radar, Important Events, Market Regime, calibration posture/ops and other rich product acquisition GETs | DEFER | unchanged product bodies | no migration in B2b | converting these contracts would require cold-start producer ordering or workflow migration; do not silently replace product acquisition with empty cache DTOs | later route-by-route authority review |
| `GET /api/argus/admin/provider-diagnostics` and internal capability builders | KEEP_BACKGROUND | unchanged authenticated/internal paths | no browser migration | preserve explicit live probe and cache-warming authority | revert cache-only projections without changing auth |
| `GET /api/argus/calibration/ops` and other unmounted rich operator/product bodies | DEFER | unchanged | B2a unmounted the operator panel; no active browser acquisition remains | response semantics and refresh authority differ from the selected status DTOs; do not silently turn a rich body into a status alias | later auth/route review with an explicit consumer migration |
| action-priority/flow/supply/session/scenario/position-plan status twins | DEFER | unchanged | none | response semantics are not proven identical | reconsider only with an exact consumer/response equivalence proof |
| remaining route delete candidates | DEFER | unchanged | none | workflow, operator, or historical consumers are not yet fully disproven | later deletion-only route review |
| Important Events recurring acquisition | MERGE | one module singleton | all hook consumers subscribe through `useSyncExternalStore` | 3 acquisition lifecycles duplicated the same query | restore hook-local lifecycle |
| Market Ledger recurring acquisition | MERGE | one module singleton | all hook consumers share the existing cache/in-flight request | 3 schedulers duplicated one stale-gated query | restore hook-local scheduler while retaining cache |
| Action Labels recurring acquisition | MERGE | keyed singleton by canonical JP/US symbol lists | identical consumers share a key | 2 identical lifecycles polled the same URL | restore per-hook lifecycle |
| JP/US quote recurring acquisition | MERGE | one keyed JP plus one keyed US lifecycle for identical asset sets | duplicate `useAssetIntel` consumers share keys | 4 identical lifecycles reduced to 2 without merging different symbol contracts | restore per-hook lifecycles |
| PWA update/version checks | MERGE | one bounded 60-second scheduler | service-worker update and deployed-version reconciliation serialize through single-flight promises | 2 timers could overlap the same update cycle | restore separate timers |
| server mission scheduler, GitHub schedules, WAL/checkpoint/Remote Journal recovery | KEEP_BACKGROUND | unchanged | none | outside B2b browser/public-read scope | not applicable |

Measured boundary:

- Catalogued HTTP contracts: `245 -> 244` (one compatibility alias removed).
- Browser recurring acquisition lifecycles: Important Events `3 -> 1`, Market
  Ledger `3 -> 1`, Action Labels `2 -> 1`, identical JP/US quote consumers
  `4 -> 2`, PWA timers `2 -> 1`.
- Route deletions: `1`; status-twin merges beyond that alias: `0`.
- Cache-only browser-consumer contracts: `18` (the sixteen selected aggregate/status
  routes plus the two quote routes above).
- Workflow, server-scheduler, authority, WAL/checkpoint/Remote Journal recovery,
  and storage-schema changes: `0`. Event snapshot and persisted AI-view product
  cache restore timing moves from incidental browser GETs to the existing
  process-bootstrap phase; this does not change recovery authority.
