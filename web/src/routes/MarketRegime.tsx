import React, { useEffect, useMemo } from 'react';
import { PageShell } from './PageShell';
import { useLocale, t, tEn } from '../i18n';
import { SignedValue } from '../components/common/SignedValue';
import { CapitalRotationBoard } from '../components/regime/CapitalRotationBoard';
import { jpIntradayJa } from '../lib/regimeLabels';
import { RegimeMatrix } from '../components/regime/RegimeMatrix';
import { MarketEventsSections } from '../components/regime/MarketEventsSections';
import { LedgerHistory } from '../components/regime/LedgerHistory';
import { useMarketRegime } from '../hooks/useMarketRegime';
import { useMarketMovers } from '../hooks/useMarketMovers';
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
  useLocale();   // re-render on locale switch
  const { data, phase } = useMarketRegime();
  const movers = useMarketMovers();
  const jpMovers = useMarketMovers('/api/argus/jp-market-movers');

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
      title={tEn('nav.marketContext')}
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
        {data && (
          <div className="regime-head__status">
            {typeof data.heldOverMin === 'number' ? (
              <span className="regime-head__held">
                ⚠ 前回のフル評価を保持表示中(約{data.heldOverMin}分前)。今のRISK_ON/MIXEDは最新の確定ではありません。
              </span>
            ) : (
              <span className="regime-head__fresh">
                {data.status === 'live' ? 'ライブ(フル評価)' : data.status === 'partial' ? '部分データ(一部ソース欠損 — 確信度を割り引いて解釈)' : 'mock'}
              </span>
            )}
            {data.jpIntradayOverlay && data.jpIntradayOverlay.jpIntradayOverlay !== 'NORMAL' && (
              <span className="regime-head__overlay-tag">
                · JP intraday: {data.jpIntradayOverlay.jpIntradayOverlay}
              </span>
            )}
          </div>
        )}
        {data && <p className="regime-head__summary">{data.regime.summaryJa}</p>}
        {data?.jpIntradayOverlay && data.jpIntradayOverlay.jpIntradayOverlay !== 'NORMAL' && (
          <div className={`regime-jp-overlay regime-jp-overlay--${data.jpIntradayOverlay.jpIntradayOverlay === 'RISK_OFF_WATCH' ? 'red' : 'amber'}`}>
            <span className="regime-jp-overlay__tag">{data.jpIntradayOverlay.displayJa}</span>
            <p className="regime-jp-overlay__reason">{data.jpIntradayOverlay.reasonJa}</p>
          </div>
        )}
      </div>

      <section id="full-board" className="regime-anchor">
        <div className="section-head">
          <span className="section-head__title">Capital Rotation Board</span>
          <span className="section-head__count">{rows.length} groups</span>
        </div>
        {data && (() => {
          const ov = data.jpIntradayOverlay;
          const jpov = ov?.jpIntradayOverlay;
          const tone = !jpov ? 'muted' : jpov === 'RISK_OFF_WATCH' ? 'red' : jpov === 'NORMAL' ? 'green' : 'amber';
          return (
            <div className="regime-jp-row">
              <span className={`regime-jp-row__dot regime-jp-row__dot--${tone}`} />
              <span className="regime-jp-row__label">日本(ザラ場の地合い)</span>
              <span className="regime-jp-row__val">{jpov ? (ov.displayJa || jpIntradayJa(jpov)) : 'データ取得待ち'}</span>
              <span className="regime-jp-row__note">米ETF中心のローテーションに対するJPオーバーレイ</span>
            </div>
          );
        })()}
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

      {/* US whole-market movers (v10.62) — beyond the watchlist, via Alpha Vantage. */}
      <section>
        <div className="section-head">
          <span className="section-head__title">US Market Movers</span>
          <span className="section-head__count">
            {movers?.status === 'live' ? `as of ${movers.asOf ?? ''}` : movers?.status ?? '…'}
          </span>
        </div>
        <div className="card">
          {movers?.status === 'live' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', minWidth: 0 }}>
              {[...movers.gainers.slice(0, 5), ...movers.losers.slice(0, 5)]
                .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct)).slice(0, 8)
                .map((m) => (
                  <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13, minWidth: 0 }}>
                    <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <b>{m.symbol}</b> {(m as { name?: string }).name ?? ''}
                    </span>
                    <span style={{ flex: 'none', whiteSpace: 'nowrap' }}>
                      <SignedValue value={m.changePct} suffix="%" arrow={false} /> (${m.price})
                    </span>
                  </div>
                ))}
            </div>
          ) : movers?.status === 'missing_key' ? (
            <p style={{ fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.7 }}>
              ウォッチリスト外の米国全市場スキャンは <b>Alpha Vantage の無料APIキー</b> が必要です。
              取得して Render に <code>ALPHAVANTAGE_API_KEY</code> を設定すると、全市場の急騰/急落を検出し
              24/7イベント+通知に乗ります。
            </p>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--text-sub)' }}>connecting… 全市場ムーバーを取得中</p>
          )}
        </div>
      </section>

      {/* JP whole-market EOD movers (v10.64) — all listed stocks, via J-Quants. */}
      <section>
        <div className="section-head">
          <span className="section-head__title">JP Market Movers</span>
          <span className="section-head__count">
            {jpMovers?.status === 'live' ? (jpMovers.provider ?? `as of ${jpMovers.asOf ?? ''}`) : jpMovers?.status ?? '…'}
          </span>
        </div>
        <div className="card">
          {jpMovers?.status === 'live' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', minWidth: 0 }}>
              {[...jpMovers.gainers.slice(0, 5), ...jpMovers.losers.slice(0, 5)]
                .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct)).slice(0, 8)
                .map((m) => (
                  <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, gap: 8, minWidth: 0 }}>
                    <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <b>{m.symbol}</b> {(m as { name?: string }).name ?? ''}
                    </span>
                    <span style={{ flex: 'none', whiteSpace: 'nowrap' }}>
                      <SignedValue value={m.changePct} suffix="%" arrow={false} /> (¥{Math.round(m.price).toLocaleString('en-US')})
                    </span>
                  </div>
                ))}
              <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 4 }}>
                全上場銘柄から算出(引け後・前日比)。リアルタイムの寄り中急騰は別途。
              </div>
            </div>
          ) : jpMovers?.status === 'missing_key' ? (
            <p style={{ fontSize: 13, color: 'var(--text-sub)' }}>J-Quants APIキーが未設定です。</p>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--text-sub)' }}>引け後に全市場ムーバーを集計します(取得待ち)。</p>
          )}
        </div>
      </section>

      {/* Forward-looking context: scheduled events + escalation + crisis news
          (merged from the old Event Radar page, v10.57). */}
      <MarketEventsSections />

      {/* 履歴/台帳 read-back (v10.185): the daily ledgers (rotation Δ / downside / attribution)
          were accumulating with no UI — surfaced here. */}
      <LedgerHistory />

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
