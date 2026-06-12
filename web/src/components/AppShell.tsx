import React, { useEffect, useRef, useState } from 'react';
import type { RiskLevel } from '../types/action';
import './AppShell.css';

// Overscroll-to-next (v10.15.1, user request): at the page bottom, one strong
// extra pull (touch) or wheel burst advances to the next nav page. Deliberate
// thresholds + a visible indicator prevent accidental jumps.
const PULL_THRESHOLD_PX = 90;     // touch: extra upward drag past the bottom
const WHEEL_THRESHOLD = 350;      // desktop: accumulated deltaY while pinned at bottom

interface NextEvent {
  title: string;       // short event title
  kind: string;        // CPI / FOMC / BOJ ...
  daysAway: number;    // 0 = today, 1 = tomorrow
  impact: RiskLevel;
  onClick?: () => void;
}

interface Props {
  sidebar: React.ReactNode;
  children: React.ReactNode;
  lastUpdated: Date;
  nextEvent?: NextEvent;
  /** When set, a strong overscroll at the page bottom advances to this page. */
  overscrollNext?: { label: string; go: () => void };
}

const IMPACT_COLOR: Record<RiskLevel, string> = {
  low:     'var(--risk-low)',
  med:     'var(--risk-med)',
  high:    'var(--risk-high)',
  extreme: 'var(--risk-extreme)',
};

function formatLastUpdated(d: Date): string {
  const now = new Date();
  const diff = Math.max(0, now.getTime() - d.getTime());
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatDaysAway(days: number): string {
  if (days === 0) return 'today';
  if (days === 1) return 'in 1d';
  if (days < 0) return `${-days}d ago`;
  return `in ${days}d`;
}

// Slim header (brand + next event + status + last-updated) on top,
// sidebar + main below. No clock, no UPLINK MOCK, no crosshairs.
export const AppShell: React.FC<Props> = ({ sidebar, children, lastUpdated, nextEvent, overscrollNext }) => {
  const mainRef = useRef<HTMLElement>(null);
  const [pull, setPull] = useState(0);          // 0..1 progress toward the jump
  const pullRef = useRef(0);
  const setPullBoth = (v: number) => { pullRef.current = v; setPull(v); };

  useEffect(() => {
    const el = mainRef.current;
    if (!el || !overscrollNext) return;
    const atBottom = () => el.scrollHeight - el.scrollTop - el.clientHeight < 2;
    // Cooldown: right after a jump the next page may still be SHORT (data
    // loading → already "at bottom"), and a continuing gesture would chain
    // through multiple pages. One deliberate gesture = one page.
    let lastGo = 0;
    const coolingDown = () => Date.now() - lastGo < 800;
    const go = () => {
      lastGo = Date.now();
      setPullBoth(0);
      overscrollNext.go();
      el.scrollTop = 0;   // land at the top of the next page
    };

    // Touch: extra upward drag while already pinned at the bottom.
    let startY: number | null = null;
    let pulling = false;
    const onTouchStart = (e: TouchEvent) => { startY = e.touches[0].clientY; pulling = false; };
    const onTouchMove = (e: TouchEvent) => {
      if (startY == null || coolingDown()) return;
      const dy = startY - e.touches[0].clientY;
      if (dy > 0 && atBottom()) { pulling = true; setPullBoth(Math.min(dy / PULL_THRESHOLD_PX, 1)); }
      else if (pulling) { pulling = false; setPullBoth(0); }
    };
    const onTouchEnd = () => {
      if (pulling && pullRef.current >= 1) go();
      else setPullBoth(0);
      startY = null; pulling = false;
    };

    // Wheel: accumulated downward delta while pinned at the bottom.
    let acc = 0;
    let idleTimer: number | undefined;
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY <= 0 || !atBottom() || coolingDown()) { acc = 0; if (pullRef.current) setPullBoth(0); return; }
      acc += e.deltaY;
      setPullBoth(Math.min(acc / WHEEL_THRESHOLD, 1));
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => { acc = 0; setPullBoth(0); }, 600);
      if (acc >= WHEEL_THRESHOLD) { acc = 0; go(); }
    };

    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: true });
    el.addEventListener('touchend', onTouchEnd, { passive: true });
    el.addEventListener('wheel', onWheel, { passive: true });
    return () => {
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
      el.removeEventListener('wheel', onWheel);
      window.clearTimeout(idleTimer);
    };
  }, [overscrollNext]);

  return (
    <div className="shell">
      <header className="shell__header">
        <div className="shell__brand">
          <span className="shell__brand-name">A.R.G.U.S.</span>
          <span className="shell__brand-version">v{__APP_VERSION__}</span>
          <span className="shell__brand-tag">
            Autonomous Risk and Global Uncertainty Scanner
          </span>
        </div>
        <div className="shell__meta">
          {nextEvent && (
            <button
              className="shell__next-event"
              onClick={nextEvent.onClick}
              style={{ ['--ne-fg' as string]: IMPACT_COLOR[nextEvent.impact] }}
              aria-label={`Next event: ${nextEvent.title}, ${formatDaysAway(nextEvent.daysAway)}`}
            >
              <span className="shell__next-event-dot" />
              <span className="shell__next-event-label">Next</span>
              {nextEvent.kind}
              <span className="shell__next-event-when">· {formatDaysAway(nextEvent.daysAway)}</span>
            </button>
          )}
          <span className="shell__status">Market Open</span>
          <span className="shell__updated">
            <span className="shell__updated-label">Updated</span>
            {formatLastUpdated(lastUpdated)}
          </span>
        </div>
      </header>
      <div className="shell__body">
        {sidebar}
        <main className="shell__main" ref={mainRef}>
          {children}
          {overscrollNext && pull > 0.05 && (
            <div className={`shell__pullnext${pull >= 1 ? ' shell__pullnext--armed' : ''}`}
                 style={{ opacity: 0.35 + pull * 0.65 }}>
              {pull >= 1 ? `↓ 離すと移動: ${overscrollNext.label}` : `↓ さらに引っ張って ${overscrollNext.label} へ`}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
