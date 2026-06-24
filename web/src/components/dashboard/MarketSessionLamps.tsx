import { useEventsActive } from '../../hooks/useEventsActive';
import './SystemHealthLamps.css';

// What is LIVE right now = which markets are trading. A green lamp lights while a
// market's cash session is open and goes dark when it closes. This replaces the
// cryptic "partial" freshness word with something concrete. (API/data-source
// health — rates, events, EDINET — lives in the A.R.G.U.S. logo popover instead.)
export function MarketSessionLamps() {
  const { status } = useEventsActive();
  // Status, NOT tabs (v10.120): explicit OPEN/CLOSED/24H + a heading so this row
  // is never mistaken for a market filter.
  const markets = [
    { key: 'jp', label: 'JP', state: status?.sessionJp == null ? null : (status.sessionJp ? 'OPEN' : 'CLOSED') },
    { key: 'us', label: 'US', state: status?.sessionUs == null ? null : (status.sessionUs ? 'OPEN' : 'CLOSED') },
    { key: 'crypto', label: 'Crypto', state: '24H' },
  ];
  return (
    <div className="msl" role="status" aria-label="Market status">
      <span className="msl-head">MARKET STATUS</span>
      {markets.map((m) => {
        const open = m.state === 'OPEN' || m.state === '24H';
        return (
          <span key={m.key} className={`msl-item ${open ? 'msl-item--open' : 'msl-item--closed'}`}>
            <span className={`shl-dot ${open ? 'shl-dot--ok' : 'shl-dot--off'}`} />
            {m.label} {m.state ?? '…'}
          </span>
        );
      })}
    </div>
  );
}
