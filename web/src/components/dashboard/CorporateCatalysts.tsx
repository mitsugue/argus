import React from 'react';
import { useCatalysts } from '../../hooks/useCatalysts';
import type { CatalystItem } from '../../types/catalysts';

// Compact, calm panel of company-specific catalysts (earnings / filings / news /
// disclosures). Only surfaces medium/high catalyst-risk names to avoid clutter.
// No long article bodies — headline + source/URL only.

const RISK_COLOR: Record<string, string> = {
  high: 'var(--red)', medium: 'var(--amber)', low: 'var(--text-muted)',
};
const SRC_DOT: Record<string, string> = {
  live: 'var(--green)', partial: 'var(--amber)', unavailable: 'var(--text-muted)',
  error: 'var(--red)', pending_addon: 'var(--text-muted)',
};

function line(it: CatalystItem): string {
  const bits: string[] = [];
  if (it.earnings?.date) bits.push(`決算 ${it.earnings.date} (D-${it.earnings.daysUntil})`);
  if (it.filings?.length) bits.push(`${it.filings[0].form} ${it.filings[0].filingDate} ·filings ${it.filings.length}`);
  if (it.news?.length) bits.push(`news ${it.news.length}`);
  const liveDisc = it.disclosures?.filter((d) => d.status === 'live') ?? [];
  if (liveDisc.length) bits.push(`開示 ${liveDisc[0].date ?? ''}`);
  return bits.join(' · ');
}

export const CorporateCatalysts: React.FC = () => {
  const { data, phase } = useCatalysts();
  if (!data || phase === 'mock') return null;

  const notable = data.items.filter((i) => i.catalystRisk === 'high' || i.catalystRisk === 'medium');

  return (
    <section className="catalysts">
      <div className="catalysts__head">
        <span className="catalysts__title">Corporate Catalysts</span>
        <span className={`watch-status watch-status--${phase}`}>{phase}</span>
        <span className="catalysts__sources">
          {data.sources.map((s) => (
            <span className="catalysts__src" key={s.name}>
              <span className="catalysts__dot" style={{ background: SRC_DOT[s.status] ?? 'var(--text-muted)' }} />
              {s.name.replace(' Add-on', '')} <span className="catalysts__srcst">{s.status}</span>
            </span>
          ))}
        </span>
      </div>
      {notable.length === 0 ? (
        <div className="catalysts__empty">目立つ銘柄固有の触媒はありません(全銘柄 low)。</div>
      ) : (
        <div className="catalysts__list">
          {notable.map((it) => (
            <div className="catalysts__item" key={it.symbol}>
              <span className="catalysts__sym">{it.name ? `${it.name}(${it.symbol})` : it.symbol}</span>
              <span className="catalysts__risk" style={{ color: RISK_COLOR[it.catalystRisk] }}>{it.catalystRisk}</span>
              <span className="catalysts__data">{line(it)}</span>
              <span className="catalysts__reason">{it.summaryJa}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};
