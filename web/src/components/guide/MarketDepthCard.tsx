import '../dashboard/Dashboard.css';
import React from 'react';
import { useMarketDepth, type DepthCapability } from '../../hooks/useMarketDepth';

// Market Depth Status (v10.196) — what depth ARGUS actually has, per capability.
// Feeds the Visibility Risk Guard. Honest: 'live' only on venue-timestamp proof.
const STATUS: Record<string, { ja: string; tone: string }> = {
  live: { ja: 'LIVE', tone: 'var(--value-positive, #34d399)' },
  partial: { ja: '遅延/終値', tone: 'var(--amber, #fbbf24)' },
  testing: { ja: '検証中', tone: 'var(--blue, #60a5fa)' },
  requires_contract: { ja: '要契約', tone: 'var(--text-muted)' },
  unavailable: { ja: '未接続', tone: 'var(--text-muted)' },
};

export const MarketDepthCard: React.FC = () => {
  const d = useMarketDepth();
  if (!d) return null;
  const entries = Object.entries(d.capabilities) as [string, DepthCapability][];
  return (
    <section className="mdepth">
      <div className="section-head">
        <span className="section-head__title">Market Depth Status</span>
        <span className="section-head__count">{d.summary?.live ?? 0}/{d.summary?.total ?? entries.length} live</span>
      </div>
      <div className="card mdepth__card">
        <p className="mdepth__lead">
          ARGUSが実際に持っている市場の深さ。<b>「LIVE」は取引所タイムスタンプ等で実証できたものだけ</b>(配信頻度≠鮮度)。
          未接続/未検証は誇張しません。可視性ガードの入力です。
        </p>
        <div className="mdepth__grid">
          {entries.map(([key, c]) => {
            const s = STATUS[c.status] ?? STATUS.unavailable;
            return (
              <div className="mdepth__row" key={key} title={c.limitations || ''}>
                <span className="mdepth__label">{c.labelJa ?? key}{c.affectsActionLevel ? ' ·判断に影響' : ''}</span>
                <span className="mdepth__status" style={{ color: s.tone }}>{s.ja}</span>
              </div>
            );
          })}
        </div>
        <p className="mdepth__note">未接続の深さ(PTS/板/歩み値/VWAP/時間外…)は「検知していない=安全」ではありません。</p>
      </div>
    </section>
  );
};
