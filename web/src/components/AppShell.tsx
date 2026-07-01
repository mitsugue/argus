import React, { useEffect, useRef, useState } from 'react';
import type { RiskLevel } from '../types/action';
import { useSystemHealth, type LampStatus } from '../hooks/useSystemHealth';
import { SystemHealthPopover } from './dashboard/SystemHealthPopover';
import { ArgusMark } from './ArgusMark';
import './AppShell.css';

const BRAND_DOT: Record<LampStatus, string> = {
  ok: 'shl-dot--ok', warning: 'shl-dot--warn', stopped: 'shl-dot--stop', off: 'shl-dot--off',
};

// Overscroll-to-next (v10.15.1, user request): at the page bottom, one strong
// extra pull (touch) or wheel burst advances to the next nav page. Deliberate
// thresholds + a visible indicator prevent accidental jumps.
// "Clear app" tension (v10.29, user request): the page content physically
// follows the finger but with heavy exponential damping — it yields less the
// harder you pull, so the gesture feels weighty and resistant. You must pull a
// long way to cross the trigger, and the next page oozes in with an overshoot.
// v10.153 (owner request): page flip ~30% lighter in BOTH directions (down=next,
// up=prev) — was 340 / 1700. Still deliberate enough to avoid accidental jumps.
const PULL_THRESHOLD_PX = 238;    // touch: extra drag past the edge to flip
const WHEEL_THRESHOLD = 1190;     // desktop: accumulated deltaY at the edge
const RESIST_MAX = 104;           // max px the page ever yields under the finger
const RESIST_K = 300;             // damping constant — bigger = heavier resistance

// Exponential rubber-band: raw finger travel → damped page offset. Approaches
// RESIST_MAX asymptotically, so pulling twice as far moves the page far less
// than twice as much. This is what makes it feel like it "耐える" (resists).
function rubberBand(rawPx: number): number {
  return RESIST_MAX * (1 - Math.exp(-Math.abs(rawPx) / RESIST_K));
}

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
  // System-health beacon on the brand: one poll shared by the dot + popover.
  const health = useSystemHealth();
  const [healthOpen, setHealthOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  // The drag is driven DIRECTLY through the DOM (refs), NOT React state — a
  // per-frame setState on touchmove re-renders the whole shell ~60×/s and
  // judders ("ガタガタ"). Refs keep it on the compositor: buttery. React state
  // is used ONLY for the page-change enter animation (once per gesture).
  const pageRef = useRef<HTMLDivElement>(null);
  const topNavRef = useRef<HTMLDivElement>(null);
  const botNavRef = useRef<HTMLDivElement>(null);
  const pullRef = useRef(0);   // signed armed-progress at release time
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

  // Stable labels for the indicators (set via textContent — no re-render).
  const nextLabel = overscrollNext?.label;
  const prevLabel = overscrollPrev?.label;
  useEffect(() => {
    const el = mainRef.current;
    if (!el || (!overscrollNext && !overscrollPrev)) return;
    const atBottom = () => el.scrollHeight - el.scrollTop - el.clientHeight < 2;
    const atTop = () => el.scrollTop < 2;

    // ── direct-DOM helpers (no setState) ──
    const paintPage = (px: number) => {
      const p = pageRef.current; if (!p) return;
      if (px === 0) { p.style.transform = ''; p.classList.remove('shell__page--dragging'); }
      else { p.classList.add('shell__page--dragging'); p.style.transform = `translateY(${px}px)`; }
    };
    const paintNav = (signed: number) => {
      pullRef.current = signed;
      const top = topNavRef.current, bot = botNavRef.current;
      if (bot) {
        if (signed > 0.05) {
          bot.style.opacity = String(0.35 + Math.min(signed, 1) * 0.65);
          bot.classList.toggle('shell__pullnav--armed', signed >= 1);
          bot.textContent = signed >= 1 ? `↓ 離すと移動: ${nextLabel}` : `↓ さらに引っ張って ${nextLabel} へ`;
        } else { bot.style.opacity = '0'; }
      }
      if (top) {
        if (signed < -0.05) {
          top.style.opacity = String(0.35 + Math.min(-signed, 1) * 0.65);
          top.classList.toggle('shell__pullnav--armed', signed <= -1);
          top.textContent = signed <= -1 ? `↑ 離すと移動: ${prevLabel}` : `↑ さらに引っ張って ${prevLabel} へ`;
        } else { top.style.opacity = '0'; }
      }
    };
    const release = () => { paintPage(0); paintNav(0); };

    let lastGo = 0;
    const coolingDown = () => Date.now() - lastGo < 900;
    const go = (dir: 1 | -1) => {
      const target = dir > 0 ? overscrollNext : overscrollPrev;
      if (!target) { release(); return; }
      lastGo = Date.now();
      release();
      setAnimDir(dir);
      target.go();
      el.scrollTop = dir > 0 ? 0 : el.scrollHeight;   // land at the sensible edge
    };

    let startY: number | null = null;
    let dir: 0 | 1 | -1 = 0;
    let raf = 0;
    // rAF-coalesce: many touchmove events per frame collapse into one paint.
    const schedule = (px: number, signed: number) => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; paintPage(px); paintNav(signed); });
    };
    const onTouchStart = (e: TouchEvent) => { startY = e.touches[0].clientY; dir = 0; };
    const onTouchMove = (e: TouchEvent) => {
      if (startY == null || coolingDown()) return;
      const dy = startY - e.touches[0].clientY;   // +dy = dragging up
      if (dy > 0 && atBottom() && overscrollNext) {
        dir = 1; schedule(-rubberBand(dy), Math.min(dy / PULL_THRESHOLD_PX, 1));
      } else if (dy < 0 && atTop() && overscrollPrev) {
        dir = -1; schedule(rubberBand(dy), -Math.min(-dy / PULL_THRESHOLD_PX, 1));
      } else if (dir) { dir = 0; if (raf) { cancelAnimationFrame(raf); raf = 0; } release(); }
    };
    const onTouchEnd = () => {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      if (dir && Math.abs(pullRef.current) >= 1) go(dir);
      else release();
      startY = null; dir = 0;
    };

    // Wheel/trackpad: accumulate at the matching edge for the threshold + a
    // SMALL capped page nudge (≤30px, not the growing rubber-band) so momentum
    // scrolling on desktop doesn't jitter ("ガタガタ"). rAF-coalesced like touch.
    let acc = 0;
    let idleTimer: number | undefined;
    const onWheel = (e: WheelEvent) => {
      if (coolingDown()) { acc = 0; if (pullRef.current) release(); return; }
      const down = e.deltaY > 0, up = e.deltaY < 0;
      let signed: number;
      if (down && atBottom() && overscrollNext) {
        acc = Math.max(0, acc) + e.deltaY;
        if (acc >= WHEEL_THRESHOLD) { acc = 0; go(1); return; }
        signed = Math.min(acc / WHEEL_THRESHOLD, 1);
      } else if (up && atTop() && overscrollPrev) {
        acc = Math.min(0, acc) + e.deltaY;
        if (-acc >= WHEEL_THRESHOLD) { acc = 0; go(-1); return; }
        signed = -Math.min(-acc / WHEEL_THRESHOLD, 1);
      } else { acc = 0; if (pullRef.current) release(); return; }
      schedule(-signed * 30, signed);   // gentle, jitter-free
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => { acc = 0; release(); }, 450);
    };

    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: true });
    el.addEventListener('touchend', onTouchEnd, { passive: true });
    el.addEventListener('wheel', onWheel, { passive: true });
    return () => {
      if (raf) cancelAnimationFrame(raf);
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
      el.removeEventListener('wheel', onWheel);
      window.clearTimeout(idleTimer);
    };
  }, [overscrollNext, overscrollPrev, nextLabel, prevLabel]);

  return (
    <div className="shell">
      <header className="shell__header">
        <button
          className="shell__brand"
          onClick={() => setHealthOpen((v) => !v)}
          aria-haspopup="dialog"
          aria-expanded={healthOpen}
          title="システム状態を表示"
        >
          <ArgusMark size={20} className="shell__brand-mark" />
          <span className={`shell__brand-beacon shl-dot ${BRAND_DOT[health?.overall ?? 'off']}`} />
          <span className="shell__brand-name">A.R.G.U.S.</span>
          <span className="shell__brand-version">v{__APP_VERSION__}</span>
          <span className="shell__brand-tag">
            Autonomous Risk and Global Uncertainty Scanner
          </span>
        </button>
        {healthOpen && <SystemHealthPopover health={health} onClose={() => setHealthOpen(false)} />}
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
          {/* Prev-page indicator (pull DOWN at the top). Driven via ref —
              opacity/text/armed set imperatively in the drag handler. */}
          {overscrollPrev && (
            <div ref={topNavRef} className="shell__pullnav shell__pullnav--top" style={{ opacity: 0 }} aria-hidden />
          )}
          <div
            key={animTick}
            ref={pageRef}
            className={`shell__page shell__page--${animDir > 0 ? 'next' : 'prev'}`}
          >
            {children}
          </div>
          {/* Next-page indicator (pull UP at the bottom). */}
          {overscrollNext && (
            <div ref={botNavRef} className="shell__pullnav shell__pullnav--bottom" style={{ opacity: 0 }} aria-hidden />
          )}
        </main>
      </div>
    </div>
  );
};
