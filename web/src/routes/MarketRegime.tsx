import React, { useEffect, useMemo } from 'react';
import { PageShell } from './PageShell';
import { CapitalRotationBoard } from '../components/regime/CapitalRotationBoard';
import { RegimeMatrix } from '../components/regime/RegimeMatrix';
import { MarketEventsSections } from '../components/regime/MarketEventsSections';
import { useMarketRegime } from '../hooks/useMarketRegime';
import type {
  CapitalRotationRow, FlowLabel, FlowStrength, RegimeMatrixState,
} from '../types/regime';
import type { MarketRegimeSnapshot, RotationGroup } from '../types/marketRegime';
import '../components/dashboard/Dashboard.css';

// Regime tag keys stay English (UI vocabulary); gloss is JP — intentional
// bilingual split, not a transition mistake.
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
      title="Market Context"
      subtitle="今の地合い(レジーム・資金ローテーション・金利)と、これから来る予定イベント・危機ニュースを1画面に。アクションラベルの裏付けであって、それ自体は売買シグナルではない。ETFローテーションは資金フローのproxy。"
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
        ) : data && (data.rotationGroups?.length ?? 0) > 0 ? (
          // Groups exist but ETF momentum is pending (Twelve Data free-tier cap) —
          // be honest about WHY rather than looking like a stuck "connecting".
          <div className="card"><p style={{ fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.7 }}>
            ETFモメンタムのデータ取得待ち(Twelve Data無料枠の上限)。取得でき次第、
            {data.rotationGroups.map((g) => g.label).join(' / ')} のローテーションがここに表示されます。
            (金利/VIX/レジーム判定は下に表示中)
          </p></div>
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

      {/* Forward-looking context: scheduled events + escalation + crisis news
          (merged from the old Event Radar page, v10.57). */}
      <MarketEventsSections />

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
    </PageShell>
  );
};
