import { useEventsActive } from '../../hooks/useEventsActive';
import { useLocale, t } from '../../i18n';
import './SystemHealthLamps.css';

// What is LIVE right now = which markets are trading. A green lamp lights while a
// market's cash session is open and goes dark when it closes. This replaces the
// cryptic "partial" freshness word with something concrete. (API/data-source
// health — rates, events, EDINET — lives in the A.R.G.U.S. logo popover instead.)
export function MarketSessionLamps() {
  const { status } = useEventsActive();
  useLocale();   // re-render on locale switch
  // Status, NOT tabs (v10.120): explicit OPEN/CLOSED/24H + a heading so this row
  // is never mistaken for a market filter.
  const OPEN = t('status.open'), CLOSED = t('status.closed'), H24 = t('status.h24');
  const markets = [
    { key: 'jp', label: 'JP', state: status?.sessionJp == null ? null : (status.sessionJp ? OPEN : CLOSED), open: !!status?.sessionJp },
    { key: 'us', label: 'US', state: status?.sessionUs == null ? null : (status.sessionUs ? OPEN : CLOSED), open: !!status?.sessionUs },
    { key: 'crypto', label: 'Crypto', state: H24, open: true },
  ];
  return (
    <div className="msl" role="status" aria-label="Market status">
      <span className="msl-head">{t('status.market')}</span>
      {markets.map((m) => (
        <span key={m.key} className={`msl-item ${m.open ? 'msl-item--open' : 'msl-item--closed'}`}>
          <span className={`shl-dot ${m.open ? 'shl-dot--ok' : 'shl-dot--off'}`} />
          {m.label} {m.state ?? '…'}
        </span>
      ))}
    </div>
  );
}
