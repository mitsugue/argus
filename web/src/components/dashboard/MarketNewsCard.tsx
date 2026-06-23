import React from 'react';
import { useMarketNews } from '../../hooks/useMarketNews';

// Market News on Today (restored v10.88) — the headlines behind the moves, so the
// HOLD/WAIT posture has visible context. Finnhub general feed, market-moving items
// flagged "major". Tap to open the source. Overflow-safe (headlines wrap).
function hhmm(ts: number | null): string {
  if (!ts) return '';
  try {
    return new Date(ts * 1000).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

export const MarketNewsCard: React.FC = () => {
  const { data, loading } = useMarketNews();
  const items = (data?.items ?? []).slice(0, 8);

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">Market News</span>
        <span className="section-head__count" style={{ color: data?.status === 'live' ? 'var(--green, #34d399)' : 'var(--text-muted)' }}>
          {data?.status === 'live' ? `LIVE · ${items.length}` : data?.status ?? (loading ? '…' : 'off')}
        </span>
      </div>
      <div className="card" style={{ minWidth: 0 }}>
        {data?.status === 'missing_key' ? (
          <p style={{ fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.7 }}>
            ニュースは Finnhub の無料APIキーが必要です(Render に <code>FINNHUB_API_KEY</code>)。
          </p>
        ) : items.length === 0 ? (
          <p style={{ fontSize: 13, color: 'var(--text-sub)' }}>{loading ? 'ニュース取得中…' : '直近のニュースはありません。'}</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
            {items.map((it, i) => (
              <a key={i} href={it.url} target="_blank" rel="noopener noreferrer"
                 style={{ textDecoration: 'none', color: 'inherit', minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', minWidth: 0 }}>
                  {it.major && <span style={{ flex: 'none', width: 6, height: 6, borderRadius: '50%', background: 'var(--amber, #fbbf24)', alignSelf: 'center' }} />}
                  <span style={{ flex: 'none', fontSize: 10.5, color: 'var(--text-faint, #5f6b78)', whiteSpace: 'nowrap' }}>{hhmm(it.datetime)}</span>
                  <span style={{ flex: 'none', fontSize: 10.5, color: 'var(--text-faint, #5f6b78)', whiteSpace: 'nowrap', maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.source}</span>
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.5, color: it.major ? 'var(--text-main)' : 'var(--text-sub, #8b98a7)', overflowWrap: 'anywhere', fontWeight: it.major ? 600 : 400 }}>
                  {it.headlineJa || it.headline}
                </div>
              </a>
            ))}
            <div style={{ fontSize: 10.5, color: 'var(--text-faint)', marginTop: 2 }}>
              一般市場ニュース(Finnhub)。●=市場を動かしうる材料。参考情報で、事実検証はしていません。
            </div>
          </div>
        )}
      </div>
    </section>
  );
};
