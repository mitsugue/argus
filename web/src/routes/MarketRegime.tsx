import React, { useEffect, useMemo } from 'react';
import { PageShell } from './PageShell';
import { CapitalRotationBoard } from '../components/regime/CapitalRotationBoard';
import { RegimeMatrix } from '../components/regime/RegimeMatrix';
import { FredRatesSnapshot } from '../components/regime/FredRatesSnapshot';
import { useMarketRegime } from '../hooks/useMarketRegime';
import type {
  CapitalRotationRow, FlowLabel, FlowStrength, RegimeMatrixState,
} from '../types/regime';
import type { MarketRegimeSnapshot, RotationGroup } from '../types/marketRegime';
import '../components/dashboard/Dashboard.css';

// Regime tag keys stay English (UI vocabulary); gloss is JP — intentional
// bilingual split, not a transition mistake.
const REGIME_GLOSSARY: { tag: string; gloss: string }[] = [
  { tag: 'Risk On',               gloss: '株式・ハイベータが牽引、ディフェンシブは遅れる。' },
  { tag: 'Risk Off',              gloss: 'ディフェンシブが先導、株式・クレジットが弱含み。' },
  { tag: 'Event Wait',            gloss: 'ウィンドウ内に主要触媒。新規エントリーを抑制。' },
  { tag: 'Cautious',              gloss: '方向感は限定的、金利・VIX・イベントのリスクがくすぶる。' },
  { tag: 'Mixed',                 gloss: '明確な主導役がなく、資金の方向感は限定的。' },
  { tag: 'Rates Pressure',        gloss: '金利上昇 — デュレーション資産とグロース倍率が圧縮。' },
  { tag: 'Credit Stress',         gloss: 'ハイイールド・スプレッド拡大、リスク回避の兆候。' },
  { tag: 'Gold Hedge',            gloss: 'マクロ不安または実質利回り反転で金が先行。' },
];

const REGIME_LABEL_JA: Record<string, string> = {
  RISK_ON: 'Risk On', RISK_OFF: 'Risk Off', CAUTIOUS: 'Cautious',
  EVENT_WAIT: 'Event Wait', MIXED: 'Mixed',
};

const PHASE_COLOR: Record<string, string> = {
  live: 'var(--green)', partial: 'var(--amber)', mock: 'var(--text-muted)', connecting: 'var(--text-muted)',
};

const POSTURE_COLOR: Record<string, string> = {
  supportive: 'var(--green)', neutral: 'var(--text-sub)', tightening: 'var(--amber)', stress: 'var(--red)',
};

function flowLabel(score: number): FlowLabel {
  if (score >= 0.4) return 'Inflow';
  if (score >= 0.15) return 'Slight Inflow';
  if (score <= -0.4) return 'Outflow';
  if (score <= -0.15) return 'Slight Outflow';
  return 'Neutral';
}
function flowStrength(score: number): FlowStrength {
  const a = Math.abs(score);
  if (a >= 0.5) return 'High';
  if (a >= 0.2) return 'Medium';
  return 'Low';
}

function toRotationRows(groups: RotationGroup[]): CapitalRotationRow[] {
  return groups
    .filter((g) => g.available)
    .slice()
    .sort((a, b) => b.score - a.score)
    .map((g) => ({
      assetClass: g.label,
      flow: flowLabel(g.score),
      flowValue: Math.round(g.score * 100),
      strength: flowStrength(g.score),
      role: g.role,
    }));
}

function toMatrixState(data: MarketRegimeSnapshot): RegimeMatrixState {
  const labelEn = REGIME_LABEL_JA[data.regime.label] ?? data.regime.label;
  return {
    x: data.matrix.x,
    y: data.matrix.y,
    quadrantLabel: labelEn,
    primaryRegime: labelEn,
    secondaryRegime: `Rates: ${data.ratesBackdrop.posture}`,
    posture: data.regime.summaryJa || data.matrix.rationaleJa,
    assets: data.matrix.points,
  };
}

// Order: Subtitle → status/regime header → Capital Rotation Board (primary) →
// Regime Matrix (supporting) → Regime Summary → Rates backdrop → FRED snapshot
// → Data limitations → Glossary. The bubble / SectorBlob viz stays retired.
export const MarketRegime: React.FC = () => {
  const { data, phase } = useMarketRegime();

  useEffect(() => {
    let target: string | null = null;
    try { target = sessionStorage.getItem('argus.scrollTo'); } catch { /* ignore */ }
    if (target !== 'full-board') return;
    try { sessionStorage.removeItem('argus.scrollTo'); } catch { /* ignore */ }
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        document.getElementById('full-board')?.scrollIntoView({ block: 'start' });
      }),
    );
    return () => cancelAnimationFrame(id);
  }, []);

  const rows = useMemo(() => (data ? toRotationRows(data.rotationGroups) : []), [data]);
  const matrix = useMemo(() => (data ? toMatrixState(data) : null), [data]);

  const labelEn = data ? (REGIME_LABEL_JA[data.regime.label] ?? data.regime.label) : '—';
  const confPct = data ? Math.round(data.regime.confidence * 100) : 0;

  return (
    <PageShell
      title="Market Regime"
      subtitle="Current cross-asset environment and capital rotation. Visualizations support action labels; they are not trading signals by themselves. ETF rotation is a proxy for capital flow, not direct flow."
    >
      {/* Status + regime header */}
      <div className="card regime-head">
        <div className="regime-head__main">
          <span
            className="regime-head__pill"
            style={{ color: PHASE_COLOR[phase] ?? 'var(--text-muted)', borderColor: PHASE_COLOR[phase] ?? 'var(--line)' }}
          >
            {phase === 'connecting' ? 'connecting…' : phase}
          </span>
          <span className="regime-head__label">{labelEn}</span>
          <span className="regime-head__conf">confidence {confPct}%</span>
          {data?.asOf && <span className="regime-head__asof">asOf {data.asOf.slice(0, 16).replace('T', ' ')}Z</span>}
        </div>
        {data && <p className="regime-head__summary">{data.regime.summaryJa}</p>}
      </div>

      <section id="full-board" className="regime-anchor">
        <div className="section-head">
          <span className="section-head__title">Capital Rotation Board</span>
          <span className="section-head__count">{rows.length} groups</span>
        </div>
        {rows.length > 0 ? (
          <CapitalRotationBoard rows={rows} />
        ) : (
          <div className="card"><p style={{ fontSize: 13, color: 'var(--text-sub)' }}>
            connecting… 最新のローテーションを取得中
          </p></div>
        )}
      </section>

      {matrix && (
        <section>
          <div className="section-head">
            <span className="section-head__title">Regime Matrix</span>
            <span className="section-head__count">supporting view</span>
          </div>
          <RegimeMatrix
            state={matrix}
            compact
            axisLabels={{ xNeg: 'Defensive', xPos: 'Growth', yNeg: 'Duration', yPos: 'Risk' }}
          />
        </section>
      )}

      {data && (
        <section>
          <div className="section-head">
            <span className="section-head__title">Rates backdrop</span>
            <span
              className="section-head__count"
              style={{ color: POSTURE_COLOR[data.ratesBackdrop.posture] ?? 'var(--text-sub)' }}
            >
              {data.ratesBackdrop.posture}
            </span>
          </div>
          <div className="card">
            <div className="regime-backdrop">
              <span><b>US10Y</b> {data.ratesBackdrop.us10y}%</span>
              <span><b>US2Y</b> {data.ratesBackdrop.us2y}%</span>
              <span><b>Real10Y</b> {data.ratesBackdrop.real10y}%</span>
              <span><b>VIX</b> {data.ratesBackdrop.vix}</span>
              <span><b>HY OAS</b> {data.ratesBackdrop.hyOas}%</span>
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.7, marginTop: 10 }}>
              {data.ratesBackdrop.rationaleJa}
            </p>
            {data.supportingEvidence.length > 0 && (
              <ul className="regime-evidence">
                {data.supportingEvidence.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
          </div>
        </section>
      )}

      <section>
        <div className="section-head">
          <span className="section-head__title">FRED Rates Snapshot</span>
          <span className="section-head__count">live data source</span>
        </div>
        <FredRatesSnapshot />
      </section>

      {data && data.dataLimitations.length > 0 && (
        <section>
          <div className="section-head">
            <span className="section-head__title">Data limitations</span>
            <span className="section-head__count">honest scope</span>
          </div>
          <div className="card">
            <ul className="regime-limits">
              {data.dataLimitations.map((d, i) => <li key={i}>{d}</li>)}
            </ul>
          </div>
        </section>
      )}

      <section>
        <div className="section-head">
          <span className="section-head__title">Regime glossary</span>
          <span className="section-head__count">{REGIME_GLOSSARY.length} tags</span>
        </div>
        <div className="card" style={{ padding: 0 }}>
          <div className="core-list" style={{ padding: '4px 22px' }}>
            {REGIME_GLOSSARY.map((g) => (
              <div className="core-row" key={g.tag}>
                <div className="core-row__body">
                  <span className="core-row__top">{g.tag}</span>
                  <span className="core-row__reason">{g.gloss}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </PageShell>
  );
};
