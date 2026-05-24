import React from 'react';
import { HudFrame } from './components/HudFrame';
import { SectorNetwork } from './components/SectorNetwork';
import { PredictionTracker } from './components/PredictionTracker';
import { StickyNotes } from './components/StickyNotes';
import { TickerStrip } from './components/TickerStrip';
import { EventTicker } from './components/EventTicker';
import { NewsStream } from './components/NewsStream';
import { HotspotRanking } from './components/HotspotRanking';
import { CalibrationTracker } from './components/CalibrationTracker';
import { usePillars } from './hooks/usePillars';
import { useNewsStream } from './hooks/useNewsStream';
import './styles/layout.css';

const App: React.FC = () => {
  // pillars + news are still mock-driven and feed the side panels. The
  // sector network (center) is its own data world for now — the bridge
  // between "sectors → today's stock picks" lands in Phase 2.
  const { pillars, selectedId, select } = usePillars();
  const { events } = useNewsStream(pillars);

  return (
    <HudFrame top={<TickerStrip />} bottom={<EventTicker />}>
      <div className="hud-grid">
        <div className="hud-grid__left">
          <HotspotRanking
            pillars={pillars}
            selectedId={selectedId}
            onSelect={select}
          />
          <PredictionTracker />
        </div>

        <div className="hud-grid__center">
          <SectorNetwork />
        </div>

        <div className="hud-grid__right">
          <NewsStream
            events={events}
            selectedPillarId={selectedId}
            onSelect={select}
          />
          <CalibrationTracker />
        </div>
      </div>

      <StickyNotes />
    </HudFrame>
  );
};

export default App;
