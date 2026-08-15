# ARGUS B2b Shape-Up Manifest

Deterministic scope record for `codex/recovery-phase-a-shapeup-route-polling`.
The classification is the action taken in B2b, not a request to delete the
underlying domain engine or authority.

| Original surface | Class | New destination | Consumer migration | Reason | Rollback |
|---|---|---|---|---|---|
| `GET /api/argus/data-quality` | DELETE | `GET /api/argus/data-quality/status` | smoke/static/backend consumers use `/status`; B2a browser consumers already used it | byte-identical compatibility alias had no remaining required consumer | restore only the thin alias to the same closed DTO |
| approved obsolete public GET families | DELETE / MERGE | `/events-active` and `/data-quality/status` absorb the two surviving product status needs; all other approved GETs are removed | active browser consumers migrate atomically; eight retained cache-only surfaces are pinned in `PUBLIC_CACHE_ONLY_CONSUMERS` | eliminate dead product/API breadth without removing background engines or authority routes | restore only a reviewed thin adapter with an identified authority consumer |
| JP/US watchlist browser reads | MERGE | same public routes, read-only provider-cache/bridge DTOs | both quote hooks are pinned in `PUBLIC_CACHE_ONLY_CONSUMERS`; provider acquisition remains in internal/background judgment and ledger paths; the existing OWNER_SYNC card is reachable only after the owner opens Holdings / Watchlist → Supporting tools, and dynamic EC2 JP membership remains OWNER_SYNC → private Layer-2B → admin bridge-code | browser cadence must not spend J-Quants/Twelve Data/Finnhub quota or anonymously change the EC2 push target set; explicit owner sync preserves newly added/removed JP membership | revert the explicit provider/state gates without changing quote DTOs |
| Evidence Pack and Decision Spine status | DELETE | internal builders remain available to retained background/decision paths | obsolete browser/test consumers removed | no current authority consumer justified separate public read models | restore only after an explicit consumer and authority review |
| standalone Rates, Event Radar, Important Events, Market Regime and other retained rich product acquisition GETs | DEFER | unchanged product bodies | no Round 1 migration | converting these contracts would require cold-start producer ordering or workflow migration | later route-by-route authority review |
| `GET /api/argus/admin/provider-diagnostics` and internal capability builders | KEEP_BACKGROUND | unchanged authenticated/internal paths | no browser migration | preserve explicit live probe and cache-warming authority | revert cache-only projections without changing auth |
| action-priority/flow/supply/session/scenario/position-plan status twins | DELETE | none | obsolete consumers and tests removed atomically | repository truth found no authority/background consumer | restore only with concrete consumer evidence |
| authenticated/operator route candidates | DEFER | unchanged | none | external access-log confirmation is still unavailable | later deletion-only review with real access evidence |
| Important Events recurring acquisition | MERGE | one module singleton | all reachable hook consumers subscribe through `useSyncExternalStore` | up to 2 concurrently reachable acquisition lifecycles duplicated the same query | restore hook-local lifecycle |
| Market Ledger recurring acquisition | MERGE | one module singleton | all hook consumers share the existing cache/in-flight request | 3 schedulers duplicated one stale-gated query | restore hook-local scheduler while retaining cache |
| Action Labels recurring acquisition | MERGE | keyed singleton by canonical JP/US symbol lists | identical consumers share a key | 2 identical lifecycles polled the same URL | restore per-hook lifecycle |
| JP/US quote recurring acquisition | MERGE | one keyed JP plus one keyed US lifecycle for identical asset sets | duplicate `useAssetIntel` consumers share keys | 4 identical lifecycles reduced to 2 without merging different symbol contracts | restore per-hook lifecycles |
| PWA update/version checks | MERGE | one bounded 60-second scheduler | service-worker update and deployed-version reconciliation serialize through single-flight promises | 2 timers could overlap the same update cycle | restore separate timers |
| morning digest schedule | MERGE | `.github/workflows/market-alerts.yml` | both digest crons and the complete job move under schedule/manual-mode guards | remove duplicate workflow shell while preserving delay, stale-skip, ntfy, and alert-state behavior | split the two guarded jobs back into separate workflow files |
| server mission scheduler, WAL/checkpoint/Remote Journal recovery | KEEP_BACKGROUND | unchanged | none | outside Round 1 product compression | not applicable |

Measured boundary:

- Catalogued HTTP contracts: `245 -> 244 -> 158`.
- Trust split: `PUBLIC=62`, `AUTH_OPERATIONAL=87`, `OWNER_SYNC=6`,
  `RECOVERY_PROOF=3`.
- Browser recurring acquisition lifecycles: Important Events `2 -> 1`, Market
  Ledger `3 -> 1`, Action Labels `2 -> 1`, identical JP/US quote consumers
  `4 -> 2`, PWA timers `2 -> 1`.
- Round 1 route removals from the 244 baseline: `86` public GET contracts
  (`84` approved obsolete reads plus `/event-backbone-status` and
  `/system-health` after their field merges).
- Cache-only browser-consumer contracts: `7`.
- Dynamic JP bridge membership: public GET registration `1 -> 0`; the existing
  authenticated owner sync remains conditionally mounted under Holdings /
  Watchlist → Supporting tools and is the sole browser write authority.
- Workflow files: `25 -> 24`; `morning-digest.yml` is consolidated into
  `market-alerts.yml`. Authority, WAL/checkpoint/Remote Journal recovery, and
  storage schemas are unchanged. This does not change recovery authority.
