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
import { useInstitutionalSignals } from '../hooks/useInstitutionalSignals';
import { useFlowAttributionList, FLOW_TONE } from '../hooks/useFlowAttribution';
import { latestExposure } from '../lib/positionExposureShare';
import { jpDisplay } from '../lib/displayName';

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

// JP Regime Matrix state (v10.192) — same 2 axes as US, built from the JP sector
// matrix the backend derives from TOPIX flows. No JP regime label yet, so the
// quadrant/tags are read straight off the axes.
function toJpMatrixState(m: NonNullable<MarketRegimeSnapshot['jpMatrix']>): RegimeMatrixState {
  const risk = m.y >= 0.15 ? 'Risk On' : m.y <= -0.15 ? 'Risk Off' : 'Neutral';
  return {
    x: m.x,
    y: m.y,
    quadrantLabel: risk,
    primaryRegime: risk,
    secondaryRegime: `Growth ${m.x >= 0.1 ? '優位' : m.x <= -0.1 ? '劣位' : '中立'}`,
    posture: m.rationaleJa,
    assets: m.points,
  };
}

// Order: Subtitle → status/regime header → Capital Rotation Board (primary) →
// Regime Matrix (supporting) → Regime Summary → Rates backdrop → FRED snapshot
// → Data limitations → Glossary. The bubble / SectorBlob viz stays retired.
export const MarketRegime: React.FC = () => {
  useLocale();   // re-render on locale switch
  const { data, phase } = useMarketRegime();
  const movers = useMarketMovers();
  const { data: instData } = useInstitutionalSignals();   // v11.6.0 regime themes
  const { records: flowRecords } = useFlowAttributionList();  // v11.7.0 flow bias
  const instThemes = instData?.regimeThemes;
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
  const jpRows = useMemo(() => (data?.jpRotationGroups ? toRotationRows(data.jpRotationGroups) : []), [data]);
  const matrix = useMemo(() => (data ? toMatrixState(data) : null), [data]);
  const jpMatrix = useMemo(
    () => (data?.jpMatrix && data.jpMatrix.available !== false ? toJpMatrixState(data.jpMatrix) : null),
    [data],
  );

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

      {/* ── US block (v10.192): Regime Matrix (現在地) → Capital Rotation Board ── */}
      {matrix && (
        <section id="full-board" className="regime-anchor">
          <div className="section-head">
            <span className="section-head__title">US Regime Matrix</span>
            <span className="section-head__count">市場全体の現在地</span>
          </div>
          <RegimeMatrix
            state={matrix}
            compact
            axisLabels={{ xNeg: 'Defensive', xPos: 'Growth', yNeg: 'Duration', yPos: 'Risk' }}
          />
        </section>
      )}

      <section className={matrix ? undefined : 'regime-anchor'} id={matrix ? undefined : 'full-board'}>
        <div className="section-head">
          <span className="section-head__title">US Capital Rotation Board</span>
          <span className="section-head__count">US · {rows.length} groups</span>
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

      {/* ── JP block (v10.192): JP Regime Matrix → Japan Sector Rotation board ──
          Japan gets its OWN matrix (from TOPIX sector flows), same geometry as US. */}
      {jpMatrix && (
        <section>
          <div className="section-head">
            <span className="section-head__title">JP Regime Matrix</span>
            <span className="section-head__count">日本セクターの現在地</span>
          </div>
          <RegimeMatrix
            state={jpMatrix}
            compact
            axisLabels={{ xNeg: 'Defensive', xPos: 'Growth', yNeg: 'Duration', yPos: 'Risk' }}
          />
        </section>
      )}

      <section>
        <div className="section-head">
          <span className="section-head__title">Japan Sector Rotation</span>
          <span className="section-head__count">JP · {jpRows.length} sectors</span>
        </div>
        {data && (() => {
          const ov = data.jpIntradayOverlay;
          const jpov = ov?.jpIntradayOverlay;
          const tone = !jpov ? 'muted' : jpov === 'RISK_OFF_WATCH' ? 'red' : jpov === 'NORMAL' ? 'green' : 'amber';
          return (
            <div className="regime-jp-row">
              <span className={`regime-jp-row__dot regime-jp-row__dot--${tone}`} />
              <span className="regime-jp-row__label">ザラ場の地合い</span>
              <span className="regime-jp-row__val">{jpov ? jpIntradayJa(jpov) : 'データ取得待ち'}</span>
            </div>
          );
        })()}
        {jpRows.length > 0 ? (
          <CapitalRotationBoard rows={jpRows} />
        ) : (
          <div className="card"><p style={{ fontSize: 13, color: 'var(--text-sub)' }}>
            日本セクター(TOPIX-17 ETF)の資金フローを取得中…
          </p></div>
        )}
      </section>

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
                  <div key={m.symbol} style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13, minWidth: 0 }}>
                      <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <b>{m.symbol}</b> {(m as { name?: string }).name ?? ''}
                      </span>
                      <span style={{ flex: 'none', whiteSpace: 'nowrap' }}>
                        <SignedValue value={m.changePct} suffix="%" arrow={false} /> (${m.price})
                      </span>
                    </div>
                    {m.cause?.causeStatusJa && (
                      <div style={{ fontSize: 11, color: 'var(--text-sub)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <b>{m.cause.causeStatusJa}</b>{m.cause.bestLeadJa ? ` — ${m.cause.bestLeadJa}` : ''}
                      </div>
                    )}
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
            {jpMovers?.status === 'live'
              ? `${jpMovers.provider ?? 'JP'}${jpMovers.dataAsOf ? ` · データ ${jpMovers.dataAsOf.slice(11, 16)}Z時点` : ''}`
              : jpMovers?.status ?? '…'}
          </span>
        </div>
        <div className="card">
          {jpMovers?.status === 'live' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', minWidth: 0 }}>
              {[...jpMovers.gainers.slice(0, 5), ...jpMovers.losers.slice(0, 5)]
                .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct)).slice(0, 8)
                .map((m) => (
                  <div key={m.symbol} style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, gap: 8, minWidth: 0 }}>
                      <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <b>{m.symbol}</b> {(m as { name?: string }).name ?? ''}
                      </span>
                      <span style={{ flex: 'none', whiteSpace: 'nowrap' }}>
                        <SignedValue value={m.changePct} suffix="%" arrow={false} /> (¥{Math.round(m.price).toLocaleString('en-US')})
                      </span>
                    </div>
                    {m.cause?.causeStatusJa && (
                      <div style={{ fontSize: 11, color: 'var(--text-sub)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <b>{m.cause.causeStatusJa}</b>{m.cause.bestLeadJa ? ` — ${m.cause.bestLeadJa}` : ''}
                      </div>
                    )}
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

      {/* v11.6.0: institutional regime commentary — public signals grouped by theme */}
      {instThemes && Object.values(instThemes).some((t) => t.count > 0) && (
        <section className="card">
          <h2 style={{ margin: '0 0 6px', fontSize: 15 }}>INSTITUTIONAL REGIME SIGNALS</h2>
          <p style={{ margin: '0 0 8px', fontSize: 11.5, color: 'var(--text-faint)' }}>
            機関・メディアの公開コメントをテーマ別に集計(文脈情報・売買指示ではない)
          </p>
          {([
            ['risk_on', 'リスクオン論調'], ['risk_off', 'リスクオフ論調'],
            ['rate_cut', '利下げ観測'], ['rate_hike', '利上げ観測'],
            ['ai_capex', 'AI設備投資'], ['sector_rotation', 'ローテーション'],
            ['jp_flow', '日本株フロー'],
          ] as const).map(([key, label]) => {
            const t = instThemes[key];
            if (!t || t.count === 0) return null;
            return (
              <p key={key} style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-sub)' }}>
                <b>{label}</b> × {t.count}
                {t.example && <span style={{ color: 'var(--text-faint)', fontSize: 11 }}> — 例: {t.example}</span>}
              </p>
            );
          })}
        </section>
      )}

      {/* v11.8.0: 今日のレジーム × あなたのポートフォリオ(端末内計算・送信なし)。
          保有未入力/未計算なら未計算と正直に表示。 */}
      {(() => {
        const pe = latestExposure();
        return (
          <section className="card">
            <h2 style={{ margin: '0 0 6px', fontSize: 15 }}>PORTFOLIO SENSITIVITY</h2>
            {!pe || pe.noHoldings ? (
              <p style={{ margin: 0, fontSize: 12, color: 'var(--text-faint)' }}>
                {!pe
                  ? 'Todayページを一度開くと、保有構成と今日の地合いの突き合わせを表示します(端末内計算)。'
                  : '保有数量・取得単価が未入力のため、地合いとの突き合わせは暫定です(Watchlistで入力・端末内のみ)。'}
              </p>
            ) : (
              <>
                <p style={{ margin: 0, fontSize: 12.5, color: 'var(--text-sub)', lineHeight: 1.7 }}>
                  {pe.regimeSummaryJa}
                </p>
                {pe.headwinds.length > 0 && (
                  <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--value-negative)' }}>
                    向かい風: {pe.headwinds.join(' / ')}
                  </p>
                )}
                {pe.tailwinds.length > 0 && (
                  <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--value-positive)' }}>
                    追い風: {pe.tailwinds.join(' / ')}
                  </p>
                )}
                <p style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
                  端末内で計算(保有データは送信されません)。リスク点検であり売買指示ではありません。
                </p>
              </>
            )}
          </section>
        );
      })()}

      {/* v11.7.0: watchlist flow bias — inflow vs outflow classes, aggregated.
          推定の集計であり実測ではない(実測は米国ブリッジのみ)。 */}
      {flowRecords.length > 0 && (
        <section className="card">
          <h2 style={{ margin: '0 0 6px', fontSize: 15 }}>FLOW BIAS (推定)</h2>
          <p style={{ margin: '0 0 8px', fontSize: 11.5, color: 'var(--text-faint)' }}>
            本日の大きな動き{flowRecords.length}件の資金フロー推定の偏り(売買指示ではない)
          </p>
          {(() => {
            const inflow = flowRecords.filter((r) => r.direction === 'inflow');
            const outflow = flowRecords.filter((r) => r.direction === 'outflow');
            const other = flowRecords.length - inflow.length - outflow.length;
            return (
              <p style={{ margin: 0, fontSize: 12.5 }}>
                <span style={{ color: FLOW_TONE.inflow }}>流入型 {inflow.length}</span>
                <span style={{ margin: '0 8px', color: 'var(--text-faint)' }}>/</span>
                <span style={{ color: FLOW_TONE.outflow }}>流出型 {outflow.length}</span>
                {other > 0 && <span style={{ marginLeft: 8, color: 'var(--text-faint)' }}>混在・不明 {other}</span>}
              </p>
            );
          })()}
          {flowRecords.slice(0, 4).map((r) => (
            <p key={r.id + r.symbol} style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-sub)' }}>
              <b>{jpDisplay(r.symbol, r.name)}</b>
              <span style={{ marginLeft: 6, color: FLOW_TONE[r.direction] || 'var(--text-main)' }}>{r.flowClassJa}</span>
              <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>確度{Math.round(r.confidence * 100)}%</span>
            </p>
          ))}
        </section>
      )}
    </PageShell>
  );
};
