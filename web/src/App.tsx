import React, { useMemo, useState } from 'react';
import { AppShell } from './components/AppShell';
import { NavRail, type RouteKey } from './components/NavRail';
import { CommandCenter } from './routes/CommandCenter';
import { ActionAlerts } from './routes/ActionAlerts';
import { MarketRegime } from './routes/MarketRegime';
import { EventRadar } from './routes/EventRadar';
import { Watchlist } from './routes/Watchlist';
import { CorePortfolio } from './routes/CorePortfolio';
import { todayJudgment, upcomingEvents } from './mock/dashboard';

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
};

const App: React.FC = () => {
  const [route, setRoute] = useState<RouteKey>('command');
  const Active = ROUTES[route];
  const lastUpdated = new Date(todayJudgment.updatedAt);

  // Pick the nearest scheduled event as the header next-event chip. Sorted
  // by date — the first item not yet past is the "next" one.
  const nextEvent = useMemo(() => {
    const upcoming = upcomingEvents
      .slice()
      .filter((e) => e.at >= Date.now())
      .sort((a, b) => a.at - b.at);
    const ev = upcoming[0];
    if (!ev) return undefined;
    const daysAway = Math.max(0, Math.round((ev.at - Date.now()) / 86_400_000));
    return {
      title: ev.title,
      kind: ev.kind,
      daysAway,
      impact: ev.impact,
      onClick: () => setRoute('events'),
    };
  }, []);

  return (
    <AppShell
      sidebar={
        <NavRail
          active={route}
          onSelect={setRoute}
          todayCall={{ action: todayJudgment.overall, risk: todayJudgment.risk }}
        />
      }
      lastUpdated={lastUpdated}
      nextEvent={nextEvent}
    >
      <Active onNavigate={setRoute} />
    </AppShell>
  );
};

export default App;
