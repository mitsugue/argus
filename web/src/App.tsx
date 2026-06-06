import React, { useState } from 'react';
import { AppShell } from './components/AppShell';
import { NavRail, type RouteKey } from './components/NavRail';
import { CommandCenter } from './routes/CommandCenter';
import { ActionAlerts } from './routes/ActionAlerts';
import { MarketRegime } from './routes/MarketRegime';
import { EventRadar } from './routes/EventRadar';
import { Watchlist } from './routes/Watchlist';
import { CorePortfolio } from './routes/CorePortfolio';
import { todayJudgment } from './mock/dashboard';

const ROUTES: Record<RouteKey, React.FC> = {
  command:   CommandCenter,
  alerts:    ActionAlerts,
  regime:    MarketRegime,
  events:    EventRadar,
  watchlist: Watchlist,
  core:      CorePortfolio,
};

const App: React.FC = () => {
  const [route, setRoute] = useState<RouteKey>('command');
  const Active = ROUTES[route];
  const lastUpdated = new Date(todayJudgment.updatedAt);
  return (
    <AppShell
      sidebar={<NavRail active={route} onSelect={setRoute} />}
      lastUpdated={lastUpdated}
    >
      <Active />
    </AppShell>
  );
};

export default App;
