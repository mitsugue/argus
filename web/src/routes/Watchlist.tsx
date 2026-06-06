import React from 'react';
import { PageShell, Placeholder } from './PageShell';

export const Watchlist: React.FC = () => (
  <PageShell
    title="Watchlist"
    subtitle="Tracked Japan and US individual stocks with their AI action label."
  >
    <Placeholder
      title="Not wired yet"
      note="JP rows show price · daily Δ · volume · VWAP Δ · margin / credit · JSF · earnings · news · action. US rows show price · pre/after-hours Δ · earnings · guidance · sector trend · rate sensitivity · news · action."
    />
  </PageShell>
);
