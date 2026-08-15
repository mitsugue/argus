# B2a deferred UI cleanup manifest

This manifest records modules that were unreachable from `web/src/main.tsx` at
the PR #156 public-boundary baseline. B2a changes the mounted product surface,
but deletion is deliberately deferred so the route/mount change can be reviewed
and rolled back independently from a broad mechanical removal.

No domain engine, polling hook, storage format, recovery authority, or server
workflow is authorized for deletion by this list.

## Unreachable UI modules (47)

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

## Newly unreachable after B2a, still deferred after B2b (15)

Removing the standalone Guide and AI Review routes also makes these operator/support modules
unreachable from `main.tsx`. They remain deferred for the same rollback and
test-import reasons as the baseline 47.

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
B2b reactivates that existing OWNER_SYNC control only inside the conditionally
mounted Holdings / Watchlist Supporting tools disclosure, replacing anonymous
JP-interest registration with an explicit owner-authorized path.

The current B2b static graph therefore has 62 unreachable component/route TSX
modules (47 baseline + 15 newly unreachable modules still deferred). This is an
audit result, not authorization to delete their engines or their server-side
producers.

## Preconditions for a later deletion-only PR

1. Re-run the static module graph from `web/src/main.tsx` after B2a merge.
2. Migrate `web/scripts/market-ledger.test.mjs`, which currently reads
   `MarketLedgerPanel.tsx` directly despite that panel being unreachable.
3. Confirm no CSS/assets are referenced only by one of the modules above.
4. Run `npm run build`, the complete frontend lint suite, and public acceptance.
