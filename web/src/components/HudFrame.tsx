import React, { useEffect, useState } from 'react';

const formatClock = (d: Date) =>
  d.toLocaleTimeString('en-GB', { hour12: false }) +
  '.' +
  String(d.getMilliseconds()).padStart(3, '0').slice(0, 2);

export const HudFrame: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 73);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="hud-frame">
      <header className="hud-frame__header">
        <div className="hud-frame__brand">
          <span className="hud-frame__logo">◈ stockscanner</span>
          <span className="hud-frame__ver">v3.0.0</span>
        </div>
        <div className="hud-frame__meta">
          <span className="hud-frame__pill">
            <i className="hud-blink" />
            LIVE — MOCK
          </span>
          <span className="hud-frame__clock">{formatClock(now)}</span>
        </div>
      </header>
      <div className="hud-frame__crosshair hud-frame__crosshair--tl" />
      <div className="hud-frame__crosshair hud-frame__crosshair--tr" />
      <div className="hud-frame__crosshair hud-frame__crosshair--bl" />
      <div className="hud-frame__crosshair hud-frame__crosshair--br" />
      <main className="hud-frame__main">{children}</main>
      <footer className="hud-frame__footer">
        <span>ORB-NET // PACIFIC GRID</span>
        <span>OPS NOMINAL</span>
        <span>SEC.LVL: ALPHA</span>
        <span>EOD //{now.toISOString().slice(0, 10)}</span>
      </footer>
    </div>
  );
};
