import React, { useEffect, useMemo, useState } from 'react';
import { AppShell } from './components/AppShell';
import { NavRail, type RouteKey } from './components/NavRail';
import { CommandCenter } from './routes/CommandCenter';
import { MarketRegime } from './routes/MarketRegime';
import { Watchlist } from './routes/Watchlist';
import { CorePortfolio } from './routes/CorePortfolio';
import { BackupPage } from './routes/BackupPage';
import { DataQualityPage } from './routes/DataQualityPage';
import { Guide } from './routes/Guide';
import { AIReview } from './routes/AIReview';
import { useActionLabels } from './hooks/useActionLabels';
import { useImportantEvents } from './hooks/useImportantEvents';
import { nextUpcomingEvent } from './lib/eventClock';
import { startCloudSync } from './lib/vault';

interface RouteProps {
  onNavigate: (key: RouteKey) => void;
}

const ROUTES: Record<RouteKey, React.FC<RouteProps>> = {
  command:   CommandCenter,
  regime:    MarketRegime as React.FC<RouteProps>,
  watchlist: Watchlist as React.FC<RouteProps>,
  core:      CorePortfolio as React.FC<RouteProps>,
  backup:    BackupPage as React.FC<RouteProps>,
  quality:   DataQualityPage as React.FC<RouteProps>,
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
  const lastUpdated = useMemo(() => new Date(), [al.data]);

  // v12.0.8追補: 「次のイベント」は単一のイベント時計(eventClock)から —
  // 発表済・日付不明は次に出さず、Important Events(公式日程)と必ず一致させる。
  const impEv = useImportantEvents();
  const nextEvent = useMemo(() => {
    const pick = nextUpcomingEvent(impEv.data?.events ?? [], Date.now(), { highImpactOnly: true });
    if (!pick) return undefined;
    return {
      title: pick.title,
      kind: `${pick.eventCode} ${pick.dateJa}`,
      daysAway: pick.daysUntil,
      impact: 'high' as const,
      onClick: () => {
        // Navigation only (v10.138): jump to the single Important Events source on
        // Today and focus it — no second countdown/explanation lives in the chip.
        // v12.2.11: 重要イベントはDETAILS/MARKET DETAILS内(lazy)のため、
        // まずグループを開くイベントを送ってから、要素の出現をリトライで待つ。
        exitReview();
        setRoute('command');
        // 開く指示(CustomEvent)は毎リトライで再送する — Today未マウントで
        // 最初の発火が失われても、マウント後のリトライが確実に届く(要素検索
        // だけのリトライにしない)。チップが出る時点でイベントfeedは取得済みの
        // ため、~4.5秒のリトライ窓でカードの出現まで十分カバーする。
        let tries = 0;
        const tryScroll = () => {
          window.dispatchEvent(new CustomEvent('argus:open-today-section', { detail: 'g-market' }));
          const el = document.getElementById('important-events');
          if (el) {
            // 即時スクロール(グループ内の遅延ロードで高さが変わるとsmoothは
            // 中断されるため)+700ms後に一度だけ位置を再固定(settle pass)。
            el.scrollIntoView({ block: 'start' });
            el.querySelector('details')?.setAttribute('open', '');
            setTimeout(() => {
              document.getElementById('important-events')
                ?.scrollIntoView({ block: 'start' });
            }, 700);
          } else if (tries++ < 30) {
            setTimeout(tryScroll, 150);
          }
        };
        setTimeout(tryScroll, 140);
      },
    };
    // exitReview is stable in practice (defined per render but only mutates state)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [impEv.data]);

  const handleNavSelect = (key: RouteKey) => {
    exitReview();
    setRoute(key);
  };

  // Overscroll-to-next (v10.15.1): nav order for the bottom-pull page advance.
  // Keep in sync with NavRail's NAV order (V12.2.11: Today → Positions & Risk →
  // Watchlist → Market Context; route keys unchanged).
  const NAV_ORDER: RouteKey[] = ['command', 'core', 'watchlist', 'regime', 'backup', 'quality', 'guide'];
  const NAV_LABEL: Record<RouteKey, string> = {
    command: 'Today', regime: 'Market Context',
    watchlist: 'Watchlist', core: 'Positions & Risk', backup: 'Backup',
    quality: 'Data Quality', guide: 'Guide',
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
