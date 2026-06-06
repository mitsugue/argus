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
    >
      <Active onNavigate={setRoute} />
    </AppShell>
  );
};

export default App;
