import React from 'react';
import { HudFrame } from './components/HudFrame';
import { GlobeMonitor } from './components/GlobeMonitor';
import { PredictionTracker } from './components/PredictionTracker';
import { AlertSystem } from './components/AlertSystem';
import { StickyNotes } from './components/StickyNotes';
import { TickerStrip } from './components/TickerStrip';
import { EventTicker } from './components/EventTicker';
import { NewsFeed } from './components/NewsFeed';
import { HotspotRanking } from './components/HotspotRanking';
import { usePillars } from './hooks/usePillars';
import './styles/layout.css';

const App: React.FC = () => {
  const { pillars, selected, selectedId, select } = usePillars();

  return (
    <HudFrame
      top={<TickerStrip />}
      bottom={<EventTicker />}
    >
      <div className="hud-grid">
        <div className="hud-grid__left">
          <NewsFeed pillars={pillars} selectedId={selectedId} onSelect={select} />
        </div>

        <div className="hud-grid__center">
          <GlobeMonitor pillars={pillars} selected={selected} onSelect={select} />
        </div>

        <div className="hud-grid__right">
          <HotspotRanking
            pillars={pillars}
            selectedId={selectedId}
            onSelect={select}
          />
          <PredictionTracker />
        </div>
      </div>

      <AlertSystem />
      <StickyNotes />
    </HudFrame>
  );
};

export default App;
