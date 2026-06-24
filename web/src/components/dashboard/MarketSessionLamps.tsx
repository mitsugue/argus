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
  const markets = [
    { key: 'jp', label: 'JP', state: status?.sessionJp == null ? null : (status.sessionJp ? 'OPEN' : 'CLOSED'), open: !!status?.sessionJp },
    { key: 'us', label: 'US', state: status?.sessionUs == null ? null : (status.sessionUs ? 'OPEN' : 'CLOSED'), open: !!status?.sessionUs },
    { key: 'crypto', label: 'Crypto', state: '24H', open: true },
  ];
  return (
    <div className="msl" role="status" aria-label="Market status">
      {markets.map((m) => (
        <span key={m.key} className={`msl-item ${m.open ? 'msl-item--open' : 'msl-item--closed'}`}>
          <span className={`shl-dot ${m.open ? 'shl-dot--ok' : 'shl-dot--off'}`} />
          {m.label} {m.state ?? '…'}
        </span>
      ))}
    </div>
  );
}
