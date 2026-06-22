import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { AlertCard } from '../components/dashboard/AlertCard';
import { CoreRow } from '../components/dashboard/CoreRow';
import { useActionAlerts } from '../hooks/useActionAlerts';
import { useAssets } from '../hooks/useAssets';
import { coreActionFor } from '../lib/todayCall';
import { genreOf } from '../types/assetItem';
import type { CorePosition } from '../types/dashboard';
import '../components/dashboard/Dashboard.css';

const PHASE_COLOR: Record<string, string> = {
  live: 'var(--green)', partial: 'var(--amber)', mock: 'var(--text-muted)', connecting: 'var(--text-muted)',
};

// One LIVE judgment per asset class (alerts-v1): JP/US stock aggregates from
// the label engine, GLD/TLT/XLRE momentum, CoinGecko crypto, USD/JPY, cash.
export const ActionAlerts: React.FC = () => {
  const { cards, posture, phase } = useActionAlerts();
  const { assets } = useAssets();

  // Index funds = the USER's actual core funds + posture-aware core action.
  const funds: CorePosition[] = useMemo(() => {
    const act = coreActionFor(posture ?? undefined);
    return assets
      .filter((a) => genreOf(a) === 'funds')
      .slice()
      .sort((a, b) => a.sortOrder - b.sortOrder)
      .map((a) => ({
        symbol: a.symbol,
        name: a.displayNameJa || a.displayName,
        market: 'JP' as const,
        action: act.action,
        reason: act.reason,
      }));
  }, [assets, posture]);

  return (
    <PageShell
      title="Action Alerts"
      subtitle={
        <span>
          One judgment per asset class. Satellites first; index funds at the bottom.
          <span className="today-phase" style={{ color: PHASE_COLOR[phase] }}>
            {' '}- {phase === 'connecting' ? 'connecting...' : phase}
          </span>
        </span>
      }
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">Satellites</span>
          <span className="section-head__count">{cards.length} classes{posture ? ` - posture ${posture}` : ''}</span>
        </div>
        <div className="alert-grid">
          {cards.map((c) => (
            <AlertCard key={c.assetClass} card={c} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Index Funds</span>
          <span className="section-head__count">{funds.length} positions</span>
        </div>
        <div className="card core-list">
          {funds.map((p) => (
            <CoreRow key={p.symbol} position={p} />
          ))}
        </div>
      </section>
    </PageShell>
  );
};
