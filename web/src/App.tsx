import React from 'react';
import { HudFrame } from './components/HudFrame';
import { GlobeMonitor } from './components/GlobeMonitor';
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
  const { pillars, selected, selectedId, select } = usePillars();
  const { events, pulses } = useNewsStream(pillars);

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
          <GlobeMonitor
            pillars={pillars}
            selected={selected}
            onSelect={select}
            pulses={pulses}
          />
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
