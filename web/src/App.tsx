import React from 'react';
import { HudFrame } from './components/HudFrame';
import { GlobeMonitor } from './components/GlobeMonitor';
import { PredictionTracker } from './components/PredictionTracker';
import { AlertSystem } from './components/AlertSystem';
import { StickyNotes } from './components/StickyNotes';
import { MarketReadout, PhasePanel, LogPanel } from './components/SidePanels';
import './styles/layout.css';

const App: React.FC = () => {
  return (
    <HudFrame>
      <div className="hud-col">
        <MarketReadout />
        <PhasePanel />
        <LogPanel />
      </div>

      <div className="hud-col hud-col--center">
        <GlobeMonitor />
      </div>

      <div className="hud-col">
        <PredictionTracker />
      </div>

      <AlertSystem />
      <StickyNotes />
    </HudFrame>
  );
};

export default App;
