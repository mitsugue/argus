import React from 'react';
import { useEventsActive } from '../../hooks/useEventsActive';
import './SystemHealthLamps.css';

// What is LIVE right now = which markets are trading. A green lamp lights while a
// market's cash session is open and goes dark when it closes. This replaces the
// cryptic "partial" freshness word with something concrete. (API/data-source
// health — rates, events, EDINET — lives in the A.R.G.U.S. logo popover instead.)
// Status labels stay English (JP OPEN / US CLOSED / 24H) — short status keywords,
// not prose (v10.132); the "MARKET STATUS" heading was redundant and is dropped.
export function MarketSessionLamps() {
  const { status } = useEventsActive();
  // v12.0.8追補: 「JP OPEN」は取引セッションの状態であり、JPリアルタイム価格の
  // 稼働ではない — moomooメンテ中はJP開場中に注記を出す(bridge/statusから自動判定。
  // 復旧してjpRealtimeStatus=okになれば自然に消える)。
  const [jpRtDown, setJpRtDown] = React.useState(false);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    fetch(`${backend.replace(/\/$/, '')}/api/argus/bridge/status`)
      .then((r) => r.json())
      .then((d) => { if (alive) setJpRtDown(String(d?.jpRealtimeStatus ?? '') !== 'ok'); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  const markets = [
    { key: 'jp', label: 'JP', state: status?.sessionJp == null ? null : (status.sessionJp ? 'OPEN' : 'CLOSED'), open: !!status?.sessionJp },
    { key: 'us', label: 'US', state: status?.sessionUs == null ? null : (status.sessionUs ? 'OPEN' : 'CLOSED'), open: !!status?.sessionUs },
    { key: 'crypto', label: 'Crypto', state: '24H', open: true },
  ];
  return (
    <div className="msl" role="status" aria-label="Market status">
      {markets.map((m) => (
        <span key={m.key} className={`msl-item ${m.open ? 'msl-item--open' : 'msl-item--closed'}`}
          title={m.key === 'jp' && m.open && jpRtDown ? 'JPリアルタイムAPIはメンテ中・代替データで判定' : undefined}>
          <span className={`shl-dot ${m.open ? 'shl-dot--ok' : 'shl-dot--off'}`} />
          {m.key === 'jp' ? `${m.label} MARKET ${m.state ?? '…'}` : `${m.label} ${m.state ?? '…'}`}
        </span>
      ))}
      {!!status?.sessionJp && jpRtDown && (
        <span style={{ fontSize: 9.5, color: 'var(--amber, #fbbf24)', display: 'block', width: '100%' }}>
          JPリアルタイムAPIはメンテ中・代替データで判定
        </span>
      )}
    </div>
  );
}
