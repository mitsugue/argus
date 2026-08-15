# B2a deferred UI cleanup manifest — Round 1 completion ledger

## Round 1 deletion completed

The V13 Round 1 coordinated cut physically removed the historical candidate
tree after its route-policy and test-only references were migrated. Repository
truth at the cut head is:

- 66 TSX modules removed (the 62 deferred modules below plus Market,
  Market Context Replay, global AI Review, and WhatIf surfaces)
- 36 orphan TS modules removed
- 35 dead CSS files removed
- `countries.geojson` and its PWA include removed
- 159 TS/TSX modules remain, including 56 TSX and 20 CSS files
- four route keys and zero retired hash aliases remain

The protected stores and background engines remain. This ledger does not
authorize deletion of acquisition, replay/calibration, FIRE, recovery,
OWNER_SYNC, storage-schema, or server authority code.

## Removed baseline UI modules (47)

- `web/src/components/AlertSystem.tsx`
- `web/src/components/CalibrationTracker.tsx`
- `web/src/components/EventTicker.tsx`
- `web/src/components/GlobeMonitor.tsx`
- `web/src/components/HotspotRanking.tsx`
- `web/src/components/HudFrame.tsx`
- `web/src/components/NewsStream.tsx`
- `web/src/components/OverlayPanel.tsx`
- `web/src/components/PredictionTracker.tsx`
- `web/src/components/SectorBlob.tsx`
- `web/src/components/SectorBubbles.tsx`
- `web/src/components/SectorNetwork.tsx`
- `web/src/components/TabRail.tsx`
- `web/src/components/TickerStrip.tsx`
- `web/src/components/action/CommandSummaryCard.tsx`
- `web/src/components/action/SignalGauge.tsx`
- `web/src/components/dashboard/ActionPrioritySection.tsx`
- `web/src/components/dashboard/BuyCandidates.tsx`
- `web/src/components/dashboard/CaosEvents.tsx`
- `web/src/components/dashboard/CaosHub.tsx`
- `web/src/components/dashboard/CauseStackCard.tsx`
- `web/src/components/dashboard/EventRow.tsx`
- `web/src/components/dashboard/FlowAttributionSection.tsx`
- `web/src/components/dashboard/FxMacroSection.tsx`
- `web/src/components/dashboard/HeroCard.tsx`
- `web/src/components/dashboard/LiveEventRow.tsx`
- `web/src/components/dashboard/MarketSessionLamps.tsx`
- `web/src/components/dashboard/PositionPlanSection.tsx`
- `web/src/components/dashboard/PositionRiskSection.tsx`
- `web/src/components/dashboard/RiskIndicator.tsx`
- `web/src/components/dashboard/SessionBriefSection.tsx`
- `web/src/components/dashboard/SupplyDemandSection.tsx`
- `web/src/components/regime/CapitalRotationBoard.tsx`
- `web/src/components/regime/LedgerHistory.tsx`
- `web/src/components/regime/MarketEventsSections.tsx`
- `web/src/components/regime/MarketLedgerPanel.tsx`
- `web/src/components/regime/RegimeMatrix.tsx`
- `web/src/components/regime/TopRotations.tsx`
- `web/src/components/system/DataQualityIncidents.tsx`
- `web/src/components/today/NextCheckCard.tsx`
- `web/src/components/today/OvernightChangesCard.tsx`
- `web/src/components/today/TodayActionQueue.tsx`
- `web/src/components/today/TodayAssetExceptions.tsx`
- `web/src/components/today/TodayAttention.tsx`
- `web/src/components/today/TodayDetails.tsx`
- `web/src/components/today/TodayStanceCard.tsx`
- `web/src/components/today/YourExposureCard.tsx`

## Additional modules removed after route cuts (15)

Removing the standalone Guide and AI Review routes also made these
operator/support modules unreachable from `main.tsx`; Round 1 removed them
after their test-only imports and owner-capability dependencies were migrated.

- `web/src/components/guide/ArgusProAboutCard.tsx`
- `web/src/components/guide/ArgusProStatusCard.tsx`
- `web/src/components/guide/CalibrationCard.tsx`
- `web/src/components/guide/CalibrationOpsCard.tsx`
- `web/src/components/guide/DecisionSpineCard.tsx`
- `web/src/components/guide/DecisionValueOpsCard.tsx`
- `web/src/components/guide/EventCardsPanel.tsx`
- `web/src/components/guide/IntegrationsPanel.tsx`
- `web/src/components/guide/LedgerHealthCard.tsx`
- `web/src/components/guide/MarketDepthCard.tsx`
- `web/src/components/guide/PaidSourceStatusCard.tsx`
- `web/src/components/guide/SourceRegistryCard.tsx`
- `web/src/components/guide/SourceUniverseCard.tsx`
- `web/src/routes/Guide.tsx`
- `web/src/routes/AIReview.tsx`

B2a originally made `web/src/components/guide/Layer2BSyncCard.tsx` unreachable.
B2b reactivated that existing OWNER_SYNC control only inside the conditionally
mounted Holdings / Watchlist Supporting tools disclosure, replacing anonymous
JP-interest registration with an explicit owner-authorized path.

The 62 entries above are the approved deferred manifest inventory that Round 1
physically removed. Their names remain here as an auditable deletion ledger,
not as live source paths and not as authorization to delete their background
engines or server-side producers.

## Completed gates

1. Static module graph re-run from `web/src/main.tsx`.
2. Market ledger and verified market acceptance migrated to Today.
3. Route-policy consumer sentinels migrated without weakening cache-only policy.
4. Dead CSS, asset, dependency, and import graphs reconciled.
5. Protected data keys and all six OWNER_SYNC contracts retained.
