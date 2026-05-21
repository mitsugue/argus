import React, { useEffect, useState } from 'react';

const formatClock = (d: Date) =>
  d.toLocaleTimeString('en-GB', { hour12: false }) +
  '.' +
  String(d.getMilliseconds()).padStart(3, '0').slice(0, 2);

// Inline brand glyph — central iris + 4 cardinal "eyes of Argus".
// Uses currentColor for the cyan layer so it follows .hud-frame__logo.
const ArgusGlyph: React.FC<{ size?: number }> = ({ size = 20 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    aria-hidden="true"
    className="hud-frame__glyph"
  >
    <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1.4" />
    <circle cx="16" cy="16" r="8" fill="none" stroke="var(--hud-amber)" strokeWidth="1.1" />
    <circle cx="16" cy="16" r="2.2" fill="currentColor" />
    {/* Surrounding eyes */}
    <circle cx="16" cy="3" r="1.2" fill="var(--hud-amber)" />
    <circle cx="16" cy="29" r="1.2" fill="var(--hud-amber)" />
    <circle cx="3" cy="16" r="1.2" fill="var(--hud-amber)" />
    <circle cx="29" cy="16" r="1.2" fill="var(--hud-amber)" />
    {/* Diagonal cyan satellites */}
    <circle cx="25" cy="7" r="1" fill="currentColor" />
    <circle cx="7" cy="7" r="1" fill="currentColor" />
    <circle cx="25" cy="25" r="1" fill="currentColor" />
    <circle cx="7" cy="25" r="1" fill="currentColor" />
  </svg>
);

interface Props {
  children: React.ReactNode;
  top?: React.ReactNode;
  bottom?: React.ReactNode;
}

export const HudFrame: React.FC<Props> = ({ children, top, bottom }) => {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 73);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="hud-frame">
      <header className="hud-frame__header">
        <div className="hud-frame__brand">
          <span className="hud-frame__logo">
            <ArgusGlyph />
            A.R.G.U.S.
          </span>
          <span className="hud-frame__ver">v{__APP_VERSION__} · PANOPTES</span>
        </div>
        <div className="hud-frame__meta">
          <span className="hud-frame__pill">
            <i className="hud-blink" />
            UPLINK · MOCK
          </span>
          <span className="hud-frame__clock">{formatClock(now)}</span>
        </div>
      </header>

      {top && <div className="hud-frame__top">{top}</div>}

      <div className="hud-frame__crosshair hud-frame__crosshair--tl" />
      <div className="hud-frame__crosshair hud-frame__crosshair--tr" />
      <div className="hud-frame__crosshair hud-frame__crosshair--bl" />
      <div className="hud-frame__crosshair hud-frame__crosshair--br" />

      <main className="hud-frame__main">{children}</main>

      {bottom && <div className="hud-frame__bottom">{bottom}</div>}

      <footer className="hud-frame__footer">
        <span>ARGUS // PANOPTES NET</span>
        <span>OPS NOMINAL</span>
        <span>SEC.LVL: OMEGA</span>
        <span>EOD //{now.toISOString().slice(0, 10)}</span>
      </footer>
    </div>
  );
};
