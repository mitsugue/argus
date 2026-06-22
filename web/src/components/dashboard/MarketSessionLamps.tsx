import { useEventsActive } from '../../hooks/useEventsActive';
import './SystemHealthLamps.css';

// What is LIVE right now = which markets are trading. A green lamp lights while a
// market's cash session is open and goes dark when it closes. This replaces the
// cryptic "partial" freshness word with something concrete. (API/data-source
// health — rates, events, EDINET — lives in the A.R.G.U.S. logo popover instead.)
export function MarketSessionLamps() {
  const { status } = useEventsActive();
  const markets = [
    { key: 'jp', label: 'JP market', open: status?.sessionJp ?? null },
    { key: 'us', label: 'US market', open: status?.sessionUs ?? null },
    { key: 'crypto', label: 'Crypto', open: true }, // crypto trades 24/7
  ];
  return (
    <div className="msl">
      {markets.map((m) => (
        <span
          key={m.key}
          className={`msl-item ${m.open ? 'msl-item--open' : 'msl-item--closed'}`}
          title={m.open === null ? '接続中' : m.open ? 'open · live' : 'closed'}
        >
          <span className={`shl-dot ${m.open ? 'shl-dot--ok' : 'shl-dot--off'}`} />
          {m.label}
        </span>
      ))}
    </div>
  );
}
