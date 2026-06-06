import React, { useState } from 'react';
import { HudFrame } from './components/HudFrame';
import { NavRail, type RouteKey } from './components/NavRail';
import { CommandCenter } from './routes/CommandCenter';
import { ActionAlerts } from './routes/ActionAlerts';
import { MarketRegime } from './routes/MarketRegime';
import { EventRadar } from './routes/EventRadar';
import { Watchlist } from './routes/Watchlist';
import { CorePortfolio } from './routes/CorePortfolio';
import './styles/layout.css';

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
  return (
    <HudFrame>
      <Active />
      <NavRail active={route} onSelect={setRoute} />
    </HudFrame>
  );
};

export default App;
