import React, { useEffect, useMemo, useState } from 'react';
import { AppShell } from './components/AppShell';
import { NavRail, type RouteKey } from './components/NavRail';
import { CommandCenter } from './routes/CommandCenter';
import { MarketRegime } from './routes/MarketRegime';
import { Watchlist } from './routes/Watchlist';
import { CorePortfolio } from './routes/CorePortfolio';
import { Guide } from './routes/Guide';
import { AIReview } from './routes/AIReview';
import { useActionLabels } from './hooks/useActionLabels';
import { useEventRadar } from './hooks/useEventRadar';
import { shortKind } from './lib/todayCall';
import { startCloudSync } from './lib/vault';

interface RouteProps {
  onNavigate: (key: RouteKey) => void;
}

const ROUTES: Record<RouteKey, React.FC<RouteProps>> = {
  command:   CommandCenter,
  regime:    MarketRegime as React.FC<RouteProps>,
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

  // Cloud sync (sync-v1, v10.10): 20h cloud heartbeat + same-passphrase device
  // sync (debounced push on edit + 90s pull while visible). v10.32: the weekly
  // auto-DOWNLOAD was removed — it popped a file-save dialog on app open, which
  // the user disliked. Cloud sync already protects the device-local state, and
  // a manual "DL backup" button lives in AI Review for an explicit local copy.
  useEffect(() => { startCloudSync(); }, []);

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
        // Navigation only (v10.138): jump to the single Important Events source on
        // Today and focus it — no second countdown/explanation lives in the chip.
        exitReview();
        setRoute('command');
        setTimeout(() => {
          const el = document.getElementById('important-events');
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            el.querySelector('details')?.setAttribute('open', '');
          }
        }, 140);
      },
    };
    // exitReview is stable in practice (defined per render but only mutates state)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ev.data]);

  const handleNavSelect = (key: RouteKey) => {
    exitReview();
    setRoute(key);
  };

  // Overscroll-to-next (v10.15.1): nav order for the bottom-pull page advance.
  // Keep in sync with NavRail's NAV order (1=全体把握 2=個別 3+=その他情報).
  const NAV_ORDER: RouteKey[] = ['command', 'watchlist', 'regime', 'core', 'guide'];
  const NAV_LABEL: Record<RouteKey, string> = {
    command: 'Today', regime: 'Market Context',
    watchlist: 'Watchlist', core: 'Core Portfolio', guide: 'Guide',
  };
  const curIdx = NAV_ORDER.indexOf(route);
  const overscrollNext = (!isReview && curIdx >= 0 && curIdx + 1 < NAV_ORDER.length)
    ? { label: NAV_LABEL[NAV_ORDER[curIdx + 1]], go: () => handleNavSelect(NAV_ORDER[curIdx + 1]) }
    : undefined;
  // Up-pull at the top → previous page (v10.28). On the FIRST page (Today) there is
  // no previous page, so an up-pull RELOADS instead (v10.153, owner request) — same
  // gesture + threshold + indicator, label "再読み込み".
  const overscrollPrev = (!isReview && curIdx > 0)
    ? { label: NAV_LABEL[NAV_ORDER[curIdx - 1]], go: () => handleNavSelect(NAV_ORDER[curIdx - 1]) }
    : (!isReview && curIdx === 0)
      ? { label: '再読み込み', go: () => window.location.reload() }
      : undefined;

  return (
    <AppShell
      sidebar={
        <NavRail
          active={isReview ? null : route}
          onSelect={handleNavSelect}
          onReviewLink={enterReview}
          isReview={isReview}
        />
      }
      lastUpdated={lastUpdated}
      nextEvent={nextEvent}
      overscrollNext={overscrollNext}
      overscrollPrev={overscrollPrev}
      pageKey={isReview ? 'review' : route}
    >
      {isReview ? <AIReview /> : <Active onNavigate={handleNavSelect} />}
    </AppShell>
  );
};

export default App;
