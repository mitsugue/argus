import React, { useEffect, useRef, useState } from 'react';
import type { RiskLevel } from '../types/action';
import './AppShell.css';

// Overscroll-to-next (v10.15.1, user request): at the page bottom, one strong
// extra pull (touch) or wheel burst advances to the next nav page. Deliberate
// thresholds + a visible indicator prevent accidental jumps.
// Higher tension (v10.28): a deliberate, firm pull is required so a normal
// scroll never trips a page change by accident.
const PULL_THRESHOLD_PX = 150;    // touch: extra drag past the edge to flip
const WHEEL_THRESHOLD = 600;      // desktop: accumulated deltaY at the edge

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
  /** When set, a strong overscroll at the page top returns to this page. */
  overscrollPrev?: { label: string; go: () => void };
  /** Changes whenever the visible page changes — drives the enter animation. */
  pageKey?: string;
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
export const AppShell: React.FC<Props> = ({ sidebar, children, lastUpdated, nextEvent, overscrollNext, overscrollPrev, pageKey }) => {
  const mainRef = useRef<HTMLElement>(null);
  // Signed pull: + = toward NEXT (bottom), − = toward PREV (top). 0..±1.
  const [pull, setPull] = useState(0);
  const pullRef = useRef(0);
  const setPullBoth = (v: number) => { pullRef.current = v; setPull(v); };
  // Page-enter animation: re-keyed whenever the visible page changes.
  const [animTick, setAnimTick] = useState(0);
  const [animDir, setAnimDir] = useState<1 | -1>(1);
  const prevPageKey = useRef(pageKey);
  useEffect(() => {
    if (pageKey !== prevPageKey.current) {
      prevPageKey.current = pageKey;
      setAnimTick((t) => t + 1);
    }
  }, [pageKey]);

  useEffect(() => {
    const el = mainRef.current;
    if (!el || (!overscrollNext && !overscrollPrev)) return;
    const atBottom = () => el.scrollHeight - el.scrollTop - el.clientHeight < 2;
    const atTop = () => el.scrollTop < 2;
    // Cooldown: one deliberate gesture = one page (short next page that is
    // already "at bottom" must not chain).
    let lastGo = 0;
    const coolingDown = () => Date.now() - lastGo < 900;
    const go = (dir: 1 | -1) => {
      const target = dir > 0 ? overscrollNext : overscrollPrev;
      if (!target) { setPullBoth(0); return; }
      lastGo = Date.now();
      setPullBoth(0);
      setAnimDir(dir);
      target.go();
      el.scrollTop = dir > 0 ? 0 : el.scrollHeight;   // land at the sensible edge
    };

    let startY: number | null = null;
    let dir: 0 | 1 | -1 = 0;
    const onTouchStart = (e: TouchEvent) => { startY = e.touches[0].clientY; dir = 0; };
    const onTouchMove = (e: TouchEvent) => {
      if (startY == null || coolingDown()) return;
      const dy = startY - e.touches[0].clientY;   // +dy = dragging up
      if (dy > 0 && atBottom() && overscrollNext) {
        dir = 1; setPullBoth(Math.min(dy / PULL_THRESHOLD_PX, 1));
      } else if (dy < 0 && atTop() && overscrollPrev) {
        dir = -1; setPullBoth(-Math.min(-dy / PULL_THRESHOLD_PX, 1));
      } else if (dir) { dir = 0; setPullBoth(0); }
    };
    const onTouchEnd = () => {
      if (dir && Math.abs(pullRef.current) >= 1) go(dir);
      else setPullBoth(0);
      startY = null; dir = 0;
    };

    // Wheel: accumulate at the matching edge.
    let acc = 0;
    let idleTimer: number | undefined;
    const onWheel = (e: WheelEvent) => {
      if (coolingDown()) { acc = 0; if (pullRef.current) setPullBoth(0); return; }
      const down = e.deltaY > 0, up = e.deltaY < 0;
      if (down && atBottom() && overscrollNext) {
        acc = Math.max(0, acc) + e.deltaY; setPullBoth(Math.min(acc / WHEEL_THRESHOLD, 1));
        if (acc >= WHEEL_THRESHOLD) { acc = 0; go(1); }
      } else if (up && atTop() && overscrollPrev) {
        acc = Math.min(0, acc) + e.deltaY; setPullBoth(-Math.min(-acc / WHEEL_THRESHOLD, 1));
        if (-acc >= WHEEL_THRESHOLD) { acc = 0; go(-1); }
      } else { acc = 0; if (pullRef.current) setPullBoth(0); return; }
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => { acc = 0; setPullBoth(0); }, 600);
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
  }, [overscrollNext, overscrollPrev]);

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
          {/* Prev-page indicator (pull DOWN at the top). */}
          {overscrollPrev && pull < -0.05 && (
            <div className={`shell__pullnav shell__pullnav--top${pull <= -1 ? ' shell__pullnav--armed' : ''}`}
                 style={{ opacity: 0.35 + -pull * 0.65 }}>
              {pull <= -1 ? `↑ 離すと移動: ${overscrollPrev.label}` : `↑ さらに引っ張って ${overscrollPrev.label} へ`}
            </div>
          )}
          <div key={animTick} className={`shell__page shell__page--${animDir > 0 ? 'next' : 'prev'}`}>
            {children}
          </div>
          {/* Next-page indicator (pull UP at the bottom). */}
          {overscrollNext && pull > 0.05 && (
            <div className={`shell__pullnav shell__pullnav--bottom${pull >= 1 ? ' shell__pullnav--armed' : ''}`}
                 style={{ opacity: 0.35 + pull * 0.65 }}>
              {pull >= 1 ? `↓ 離すと移動: ${overscrollNext.label}` : `↓ さらに引っ張って ${overscrollNext.label} へ`}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
