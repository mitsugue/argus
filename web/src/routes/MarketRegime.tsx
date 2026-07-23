import React from 'react';
import { PageShell } from './PageShell';
import { MarketContextReplay } from '../components/marketReplay/MarketContextReplay';

/**
 * v13.2.0 Market owns one compact three-view replay surface.  The underlying
 * regime, Chart Intelligence, Ledger, Turning Point and Rule Card domains stay
 * intact; their previous long-form duplicate presentation is intentionally not
 * mounted below this surface.
 */
export const MarketRegime: React.FC = () => (
  <PageShell title="Market" subtitle={null}>
    <MarketContextReplay />
  </PageShell>
);
