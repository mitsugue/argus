import React, { useState } from 'react';
import { HudFrame } from './components/HudFrame';
import { SectorNetwork } from './components/SectorNetwork';
import { PredictionTracker } from './components/PredictionTracker';
import { StickyNotes } from './components/StickyNotes';
import { TickerStrip } from './components/TickerStrip';
import { EventTicker } from './components/EventTicker';
import { NewsStream } from './components/NewsStream';
import { HotspotRanking } from './components/HotspotRanking';
import { CalibrationTracker } from './components/CalibrationTracker';
import { TabRail, type TabKey } from './components/TabRail';
import { OverlayPanel } from './components/OverlayPanel';
import { usePillars } from './hooks/usePillars';
import { useNewsStream } from './hooks/useNewsStream';
import './styles/layout.css';

const App: React.FC = () => {
  // Mock pillar data still drives news + hotspots until backend lands.
  const { pillars, selectedId, select } = usePillars();
  const { events } = useNewsStream(pillars);

  // Which tab is open as an overlay (null = bubbles only).
  const [openTab, setOpenTab] = useState<TabKey | null>(null);
  const toggleTab = (key: TabKey) =>
    setOpenTab((prev) => (prev === key ? null : key));
  const closeTab = () => setOpenTab(null);

  return (
    <HudFrame top={<TickerStrip />} bottom={<EventTicker />}>
      {/* Bubbles fill the entire main area now. */}
      <SectorNetwork />

      <TabRail active={openTab} onToggle={toggleTab} />

      <OverlayPanel open={openTab === 'news'} onClose={closeTab}>
        <NewsStream
          events={events}
          selectedPillarId={selectedId}
          onSelect={select}
        />
      </OverlayPanel>

      <OverlayPanel open={openTab === 'calibration'} onClose={closeTab}>
        <CalibrationTracker />
      </OverlayPanel>

      <OverlayPanel open={openTab === 'hotspots'} onClose={closeTab}>
        <HotspotRanking
          pillars={pillars}
          selectedId={selectedId}
          onSelect={select}
        />
      </OverlayPanel>

      <OverlayPanel open={openTab === 'watch'} onClose={closeTab}>
        <PredictionTracker />
      </OverlayPanel>

      <StickyNotes />
    </HudFrame>
  );
};

export default App;
