import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AppShell } from './components/AppShell';
import { NavRail, type RouteKey } from './components/NavRail';
import {
  PRIMARY_NAVIGATION, assetDetailHash, pageDirection, parseLocationHash,
  primaryRouteIndex, routeHash, routeLabel, type ParsedLocation, type SettingsSection,
} from './navigation';
import { CommandCenter } from './routes/CommandCenter';
import { Watchlist } from './routes/Watchlist';
import { NotificationsPage } from './routes/NotificationsPage';
import { Settings } from './routes/Settings';
import { startCloudSync } from './lib/vault';
import { useMarketLedger } from './hooks/useMarketLedger';
import { resolveSessionJst } from './domain/sessionBrief';
import type { PlanningSessionAuthority } from './domain/positionPlan';
import type { AssetFocusIntent } from './components/assetDesk/AssetDeskList';

const initialLocation = (): ParsedLocation =>
  parseLocationHash(window.location.hash) ?? { route: 'command' };
const readHistoryIndex = (): number | null => {
  const value = Number((history.state as { argusNavigationIndex?: unknown } | null)?.argusNavigationIndex);
  return Number.isInteger(value) && value >= 0 ? value : null;
};
const currentHistoryState = () => history.state && typeof history.state === 'object'
  ? history.state as Record<string, unknown> : {};

const App: React.FC = () => {
  const initial = useMemo(initialLocation, []);
  const [location, setLocation] = useState<ParsedLocation>(initial);
  const routeRef = useRef<RouteKey>(initial.route);
  const historyIndexRef = useRef(readHistoryIndex() ?? 0);
  const historyHashRef = useRef(window.location.hash);
  const [pageEnterDirection, setPageEnterDirection] = useState<1 | -1>(1);
  const [assetFocus, setAssetFocus] = useState<AssetFocusIntent | null>(() =>
    initial.asset ? { ...initial.asset, nonce: Date.now() } : null);
  useEffect(() => {
    if (!(history.state && typeof history.state === 'object'
      && Number.isInteger((history.state as { argusNavigationIndex?: unknown }).argusNavigationIndex))) {
      history.replaceState({ ...currentHistoryState(),
        argusNavigationIndex: historyIndexRef.current }, '', window.location.href);
    }
    const onLocation = () => {
      const target = parseLocationHash(window.location.hash);
      if (!target) return;
      let nextHistoryIndex = readHistoryIndex();
      // Native anchors and integrations can change the hash without going
      // through commitLocation. Stamp that new entry so subsequent Back/
      // Forward transitions retain the same direction contract.
      if (nextHistoryIndex == null
        || (nextHistoryIndex === historyIndexRef.current
          && window.location.hash !== historyHashRef.current)) {
        nextHistoryIndex = historyIndexRef.current + 1;
        history.replaceState({ ...currentHistoryState(),
          argusNavigationIndex: nextHistoryIndex }, '', window.location.href);
      }
      if (nextHistoryIndex !== historyIndexRef.current) {
        setPageEnterDirection(nextHistoryIndex < historyIndexRef.current ? -1 : 1);
      } else if (target.route !== routeRef.current) {
        setPageEnterDirection(pageDirection(routeRef.current, target.route));
      }
      historyIndexRef.current = nextHistoryIndex;
      historyHashRef.current = window.location.hash;
      routeRef.current = target.route;
      setLocation(target);
      setAssetFocus(target.asset ? { ...target.asset, nonce: Date.now() } : null);
    };
    window.addEventListener('hashchange', onLocation);
    window.addEventListener('popstate', onLocation);
    return () => {
      window.removeEventListener('hashchange', onLocation);
      window.removeEventListener('popstate', onLocation);
    };
  }, []);

  // Recovery remains device-driven. The unavailable push path is disabled in
  // vault.ts; startup/visibility pulls still restore readable encrypted state.
  useEffect(() => { startCloudSync(); }, []);

  const marketLedger = useMarketLedger();
  const lastUpdated = useMemo(() => {
    const parsed = Date.parse(marketLedger.ledger?.asOf ?? '');
    return Number.isFinite(parsed) ? new Date(parsed) : new Date();
  }, [marketLedger.ledger?.asOf]);
  const canonicalSessionAuthority = useMemo<PlanningSessionAuthority>(() => ({
    calendar: marketLedger.ledger?.phase3?.calendar ?? null,
    serverAsOf: marketLedger.ledger?.phase3?.asOf
      ?? marketLedger.ledger?.asOf ?? null,
    receivedAtMs: marketLedger.fetchedAtMs,
    availability: marketLedger.error ? 'refresh_failed'
      : marketLedger.loading ? 'loading'
        : marketLedger.sessionExpired ? 'expired' : 'available',
  }), [marketLedger.ledger, marketLedger.fetchedAtMs, marketLedger.error,
    marketLedger.loading, marketLedger.sessionExpired]);
  const marketStatusLabel = useMemo(() => resolveSessionJst(
    canonicalSessionAuthority).marketStatusJa, [canonicalSessionAuthority]);

  const commitLocation = (target: ParsedLocation, hash: string) => {
    setPageEnterDirection(pageDirection(routeRef.current, target.route));
    routeRef.current = target.route;
    setLocation(target);
    setAssetFocus(target.asset ? { ...target.asset, nonce: Date.now() } : null);
    if (window.location.hash !== hash) {
      const nextHistoryIndex = historyIndexRef.current + 1;
      history.pushState({ ...currentHistoryState(), argusNavigationIndex: nextHistoryIndex }, '',
        `${window.location.pathname}${window.location.search}${hash}`);
      historyIndexRef.current = nextHistoryIndex;
      historyHashRef.current = hash;
    }
  };

  const handleNavSelect = (route: RouteKey) => {
    commitLocation({ route }, routeHash(route));
  };

  const navigateToAsset = (symbol: string, section?: string) => {
    const asset = { symbol: symbol.toUpperCase(), section };
    commitLocation({ route: 'watchlist', asset }, assetDetailHash(symbol, section));
  };

  const navigateToSettings = (settingsSection: SettingsSection) => {
    commitLocation({ route: 'settings', settingsSection }, `#settings/${settingsSection}`);
  };

  const route = location.route;
  const contextual = !!location.asset;
  const curIdx = !contextual ? primaryRouteIndex(route) : -1;
  const overscrollNext = curIdx >= 0 && curIdx + 1 < PRIMARY_NAVIGATION.length
    ? { label: routeLabel(PRIMARY_NAVIGATION[curIdx + 1].route),
      go: () => handleNavSelect(PRIMARY_NAVIGATION[curIdx + 1].route) }
    : undefined;
  const overscrollPrev = curIdx > 0
    ? { label: routeLabel(PRIMARY_NAVIGATION[curIdx - 1].route),
      go: () => handleNavSelect(PRIMARY_NAVIGATION[curIdx - 1].route) }
    : curIdx === 0
      ? { label: '再読み込み', go: () => window.location.reload() }
      : undefined;

  const content = route === 'command' ? (
      <CommandCenter onNavigate={handleNavSelect} onNavigateToAsset={navigateToAsset}
        onNavigateToSettings={navigateToSettings} />
    ) : route === 'watchlist' ? (
      <Watchlist
        assetFocus={assetFocus}
        assetDetail={!!location.asset}
        initialPortfolioOpen={!!location.portfolioOpen}
        onNavigateToAsset={navigateToAsset}
        onBackToHoldings={() => handleNavSelect('watchlist')}
      />
    ) : route === 'notifications' ? (
      <NotificationsPage />
    ) : <Settings settingsSection={location.settingsSection} />;

  return (
    <AppShell
      sidebar={<NavRail active={route} onSelect={handleNavSelect} />}
      lastUpdated={lastUpdated}
      overscrollNext={overscrollNext}
      overscrollPrev={overscrollPrev}
      pageKey={location.asset
        ? `asset:${location.asset.symbol}:${location.asset.section ?? ''}` : route}
      pageDirection={pageEnterDirection}
      marketStatusLabel={marketStatusLabel}
    >
      {content}
    </AppShell>
  );
};

export default App;
