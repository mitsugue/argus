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
  const lastUpdated = new Date(todayJudgment.updatedAt);

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
      onClick: () => {
        exitReview();
        setRoute('events');
      },
    };
  }, []);

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
          todayCall={{ action: todayJudgment.overall, risk: todayJudgment.risk }}
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
