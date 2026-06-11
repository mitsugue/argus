import React, { useEffect, useMemo, useState } from 'react';
import { AppShell } from './components/AppShell';
import { NavRail, type RouteKey } from './components/NavRail';
import { CommandCenter } from './routes/CommandCenter';
import { ActionAlerts } from './routes/ActionAlerts';
import { MarketRegime } from './routes/MarketRegime';
import { EventRadar } from './routes/EventRadar';
import { Watchlist } from './routes/Watchlist';
import { CorePortfolio } from './routes/CorePortfolio';
import { Guide } from './routes/Guide';
import { AIReview } from './routes/AIReview';
import { useActionLabels } from './hooks/useActionLabels';
import { useEventRadar } from './hooks/useEventRadar';
import { postureToCall, shortKind } from './lib/todayCall';
import { maybeAutoBackup } from './lib/backup';
import { startCloudSync } from './lib/vault';

interface RouteProps {
  onNavigate: (key: RouteKey) => void;
}

const ROUTES: Record<RouteKey, React.FC<RouteProps>> = {
  command:   CommandCenter,
  alerts:    ActionAlerts as React.FC<RouteProps>,
  regime:    MarketRegime as React.FC<RouteProps>,
  events:    EventRadar as React.FC<RouteProps>,
  watchlist: Watchlist as React.FC<RouteProps>,
  core:      CorePortfolio as React.FC<RouteProps>,
  guide:     Guide as React.FC<RouteProps>,
};

const App: React.FC = () => {
  const [route, setRoute] = useState<RouteKey>('command');
  // The AI review sheet lives outside the main 6 routes — accessible only
  // via #review in the URL hash so it can be shared without polluting the
  // nav. Reviewers paste the URL into ChatGPT (or click "Copy markdown").
  const [isReview, setIsReview] = useState(() => window.location.hash === '#review');

  useEffect(() => {
    const onHash = () => setIsReview(window.location.hash === '#review');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Weekly device-data auto-backup (v10.3.3): on app open, if 7+ days since
  // the last one, silently download argus-backup-<date>-auto.json. The only
  // device-local state is the watchlist/holdings + judgment log — this makes
  // an SSD failure or a Mac replacement cost at most a week of edits.
  // startCloudSync (sync-v1, v10.10) also runs the 20h cloud heartbeat and,
  // when cloud backup is enabled, keeps devices with the same passphrase in
  // sync (debounced push on edit + 90s pull while visible).
  useEffect(() => { maybeAutoBackup(); startCloudSync(); }, []);

  const exitReview = () => {
    if (window.location.hash === '#review') {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    setIsReview(false);
  };

  const enterReview = () => {
    if (window.location.hash !== '#review') {
      history.pushState(null, '', '#review');
    }
    setIsReview(true);
  };

  const Active = ROUTES[route];

  // Live "Today's call" pill + header chip + freshness — composed from the
  // action-labels posture and the live event calendar (mock-safe defaults
  // while connecting; never a hand-written judgment).
  const al = useActionLabels();
  const ev = useEventRadar();
  const todayCall = useMemo(
    () => postureToCall(al.data?.marketPosture?.label),
    [al.data],
  );
  const lastUpdated = useMemo(() => new Date(), [al.data]);

  const nextEvent = useMemo(() => {
    const next = (ev.data?.events ?? [])
      .filter((e) => e.impact === 'high' && e.daysUntil >= 0)
      .slice()
      .sort((a, b) => a.daysUntil - b.daysUntil)[0];
    if (!next) return undefined;
    return {
      title: next.title,
      kind: shortKind(next.title),
      daysAway: next.daysUntil,
      impact: 'high' as const,
      onClick: () => {
        exitReview();
        setRoute('events');
      },
    };
    // exitReview is stable in practice (defined per render but only mutates state)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ev.data]);

  const handleNavSelect = (key: RouteKey) => {
    exitReview();
    setRoute(key);
  };

  return (
    <AppShell
      sidebar={
        <NavRail
          active={isReview ? null : route}
          onSelect={handleNavSelect}
          todayCall={todayCall}
          onReviewLink={enterReview}
          isReview={isReview}
        />
      }
      lastUpdated={lastUpdated}
      nextEvent={nextEvent}
    >
      {isReview ? <AIReview /> : <Active onNavigate={handleNavSelect} />}
    </AppShell>
  );
};

export default App;
