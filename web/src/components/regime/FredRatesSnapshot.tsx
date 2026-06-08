import React from 'react';
import {
  useRatesSnapshot,
  type FredSeriesPoint,
  type RatesPressureLabel,
  type RiskVolatilityLabel,
} from '../../hooks/useRatesSnapshot';
import './FredRatesSnapshot.css';

// ── helpers ──────────────────────────────────────────────────────────

function pctFmt(v: number, digits = 2): string {
  return `${v.toFixed(digits)}%`;
}

// Rates (DGS*) values are percentage points → format as "%". VIX is a
// vol index → format as a bare decimal.
function valueFmt(p: FredSeriesPoint): string {
  if (p.seriesId === 'VIXCLS') return p.latestValue.toFixed(1);
  return pctFmt(p.latestValue);
}

function changeFmt(p: FredSeriesPoint): string {
  if (p.seriesId === 'VIXCLS') {
    // VIX move expressed as raw delta with sign.
    const sign = p.change > 0 ? '+' : p.change < 0 ? '−' : '';
    return `${sign}${Math.abs(p.change).toFixed(1)}`;
  }
  // Rates: bps with sign.
  const bps = p.changeBp;
  const sign = bps > 0 ? '+' : bps < 0 ? '−' : '';
  return `${sign}${Math.abs(bps).toFixed(0)} bp`;
}

function changeClass(change: number): string {
  if (change > 0.005) return 'fred__cell-change fred__cell-change--up';
  if (change < -0.005) return 'fred__cell-change fred__cell-change--down';
  return 'fred__cell-change fred__cell-change--flat';
}

// Cell with label + value + change row.
const Cell: React.FC<{ label: string; point: FredSeriesPoint }> = ({ label, point }) => (
  <div className="fred__cell">
    <span className="fred__cell-label">{label}</span>
    <span className="fred__cell-value">{valueFmt(point)}</span>
    <span className={changeClass(point.change)}>{changeFmt(point)}</span>
  </div>
);

// Color mapping for the signal dots — same palette as risk/action tokens.
const PRESSURE_COLOR: Record<RatesPressureLabel, string> = {
  High:    'var(--red)',
  Medium:  'var(--amber)',
  Neutral: 'var(--text-muted)',
  Relief:  'var(--green)',
};

const VOL_COLOR: Record<RiskVolatilityLabel, string> = {
  High:   'var(--red)',
  Medium: 'var(--amber)',
  Low:    'var(--green)',
};

// ── component ────────────────────────────────────────────────────────

export const FredRatesSnapshot: React.FC = () => {
  const { data, loading } = useRatesSnapshot();
  if (loading || !data) {
    return (
      <div className="card fred">
        <header className="fred__head">
          <span className="fred__title">FRED Rates Snapshot</span>
          <span className="fred__status fred__status--mock">loading</span>
        </header>
      </div>
    );
  }
  const statusClass = data.status === 'live' ? 'fred__status--live' : 'fred__status--mock';
  const pressureColor = PRESSURE_COLOR[data.ratesPressure];
  const volColor = VOL_COLOR[data.riskVolatility];

  return (
    <div className="card fred">
      <header className="fred__head">
        <span className="fred__title">FRED Rates Snapshot</span>
        <span className={`fred__status ${statusClass}`}>{data.status}</span>
      </header>

      <div className="fred__grid">
        <Cell label="US 10Y"    point={data.us10y} />
        <Cell label="US 2Y"     point={data.us2y} />
        <Cell label="Real 10Y"  point={data.usReal10y} />
        <Cell label="VIX"       point={data.vix} />
      </div>

      <div className="fred__signals">
        <div className="fred__signal">
          <span className="fred__signal-label">Rates Pressure</span>
          <span
            className="fred__signal-value"
            style={{ ['--sig-color' as string]: pressureColor }}
          >
            {data.ratesPressure}
          </span>
        </div>
        <div className="fred__signal">
          <span className="fred__signal-label">Volatility Risk</span>
          <span
            className="fred__signal-value"
            style={{ ['--sig-color' as string]: volColor }}
          >
            {data.riskVolatility}
          </span>
        </div>
      </div>

      <div className="fred__footer">
        <span>Source: FRED · St. Louis Fed</span>
        <span>Last updated {data.us10y.latestDate}</span>
      </div>
    </div>
  );
};
