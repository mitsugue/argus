import React from 'react';

// V12.2.12 — TECHNICAL & ENTRY(Entry Scout)。旧AssetStrategySection行から移設。
// オンデマンドのみ: ボタンを押した時だけ /api/argus/entry-scout を1回叩く。
// 表示のためにAI runを新規起動することはない(バックエンドの既存純計算のみ)。

export interface ScoutData {
  status: string;
  lastClose?: number; lastDate?: string;
  metrics?: { rsi14: number; ma25DiffPct: number | null; ret5: number | null; ret20: number | null; consecDown: number; volRatio5v20: number | null };
  flow?: { bigNetRatio: number | null; ageMin: number | null };
  nisshokin?: { ratio: number | null; loan: number; short: number } | null;
  shortDisclosed?: { ratioPct: number; reporters: number } | null;
  flowInference?: {
    classification: string;
    probabilities: { newLongAccumulation: number; shortCovering: number; distribution: number; retailNoise: number; unconfirmed: number };
    confidence: string; reasonsJa: string[]; nextConditionJa: string;
  };
  assessment?: { stance: string; score: number; reasonsJa: string[] };
  catalystContext?: { items: { kind: string; level?: string; labelJa?: string; count?: number; headline?: string | null; noteJa?: string }[]; noteJa: string };
  scoreTrackRecord?: { n: number; upRate: number | null; avgRetPct: number | null } | null;
  // v3 (v10.30): one-line call + moat-grounded story + calibration the LLM lacks.
  callJa?: string; narrativeJa?: string;
  engineCalibration?: { n: number; hitRate: number | null; days?: number } | null;
  postureCalibration?: { posture: string; n: number; hitRate: number | null } | null;
  dataGapsJa?: string[]; noteJa?: string;
}

export type ScoutState = null | 'loading' | 'error' | ScoutData;

export async function fetchScout(symbol: string, market: string): Promise<ScoutState> {
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  if (!backend) return 'error';
  try {
    const mkt = market === 'US' ? '&market=US' : '';
    const r = await fetch(`${backend.replace(/\/$/, '')}/api/argus/entry-scout?symbol=${encodeURIComponent(symbol)}${mkt}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()) as ScoutData;
  } catch { return 'error'; }
}

const FLOW_LABEL: Record<string, string> = {
  NEW_LONG_ACCUMULATION: '新規買い主導', SHORT_COVERING: '買い戻し主導(踏み上げ)',
  DISTRIBUTION: '上値での分配(売り抜け疑い)', RETAIL_NOISE: '短期ノイズ', UNCONFIRMED: '判定不能(データ不足)',
};

export const AssetEntryScout: React.FC<{
  market: string;
  scout: ScoutState;
  onRun: () => void;
}> = ({ market, scout, onRun }) => {
  if (market !== 'JP' && market !== 'US') {
    return <p className="uac-next" style={{ margin: 0, color: 'var(--text-faint)' }}>エントリー診断はJP/US株のみ対応(この資産クラスは対象外)。</p>;
  }
  return (
    <>
      <p className="uac-next" style={{ margin: '0 0 4px' }}>
        <button className="asset-mini" onClick={onRun} disabled={scout === 'loading'}
                title="60日トレンド・過熱度・大口フロー・イベント接近を束ねた入りの瞬間診断(押した時だけ実行)">
          {scout === 'loading' ? '診断中…' : '⚡ エントリー診断'}
        </button>
        <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>オンデマンド実行 — 自動では走りません</span>
      </p>
      {scout === 'error' && (
        <div className="scout scout--note">⚡ 診断を取得できませんでした(時間をおいて再試行)。</div>
      )}
      {scout && scout !== 'loading' && scout !== 'error' && scout.status !== 'live' && (
        <div className="scout scout--note">⚡ {(scout as ScoutData & { noteJa?: string }).noteJa ?? '診断対象外です。'}</div>
      )}
      {scout && scout !== 'loading' && scout !== 'error' && scout.status === 'live' && scout.assessment && (
        <div className="scout">
          {scout.callJa && <div className="scout__call">⚡ {scout.callJa}</div>}
          {scout.narrativeJa && <div className="scout__story">{scout.narrativeJa}</div>}
          <div className="scout__stance">{scout.assessment.stance} <span className="scout__score">score {scout.assessment.score >= 0 ? '+' : ''}{scout.assessment.score}</span></div>
          {scout.scoreTrackRecord && scout.scoreTrackRecord.n >= 5 && (
            <div className="scout__track">
              📊 この水準の実績: 過去{scout.scoreTrackRecord.n}件中
              {scout.scoreTrackRecord.upRate != null && ` ${Math.round(scout.scoreTrackRecord.upRate * 100)}%が上昇`}
              {scout.scoreTrackRecord.avgRetPct != null && `(平均${scout.scoreTrackRecord.avgRetPct >= 0 ? '+' : ''}${scout.scoreTrackRecord.avgRetPct}%)`}
            </div>
          )}
          <ul className="scout__reasons">
            {scout.assessment.reasonsJa.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          {scout.flowInference && scout.flowInference.classification !== 'UNCONFIRMED' && (
            <div className="scout__flow">
              <div className="scout__flow-head">
                🐋 大口の正体: <b>{FLOW_LABEL[scout.flowInference.classification] ?? scout.flowInference.classification}</b>
                <span className="scout__flow-conf"> (確度 {scout.flowInference.confidence})</span>
              </div>
              <div className="scout__flow-bars">
                {([['新規買い', scout.flowInference.probabilities.newLongAccumulation],
                   ['買い戻し', scout.flowInference.probabilities.shortCovering],
                   ['分配', scout.flowInference.probabilities.distribution],
                   ['ノイズ', scout.flowInference.probabilities.retailNoise],
                   ['不明', scout.flowInference.probabilities.unconfirmed]] as [string, number][])
                  .filter(([, v]) => v > 0)
                  .map(([k, v]) => (
                    <span className="scout__flow-prob" key={k}>{k} {Math.round(v * 100)}%</span>
                  ))}
              </div>
              <div className="scout__flow-next">次の確認: {scout.flowInference.nextConditionJa}</div>
            </div>
          )}
          {scout.catalystContext && scout.catalystContext.items.length > 0 && (
            <div className="scout__cat">
              <div className="scout__cat-head">📰 材料(参考)</div>
              <ul className="scout__reasons">
                {scout.catalystContext.items.map((it, i) => (
                  <li key={i}>
                    {it.kind === 'news' && `ニュース: ${it.labelJa}が${it.level === 'high' ? '高水準' : '増加'}(${it.count}件)${it.headline ? ` 「${it.headline}」` : ''}`}
                    {it.kind === 'link' && `${it.labelJa}: ${it.noteJa}`}
                    {it.kind === 'regime' && `${it.labelJa}: ${it.noteJa}`}
                    {it.kind === 'event' && `${it.labelJa}: ${it.noteJa}`}
                    {it.kind === 'earnings' && `${it.labelJa}: ${it.noteJa}`}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {scout.metrics && (
            <div className="scout__metrics">
              RSI14 {scout.metrics.rsi14}・25日線乖離 {scout.metrics.ma25DiffPct ?? '—'}%・5日 {scout.metrics.ret5 ?? '—'}%・20日 {scout.metrics.ret20 ?? '—'}%
              {scout.flow?.bigNetRatio != null && <>・大口 {(scout.flow.bigNetRatio * 100).toFixed(0)}%{scout.flow.ageMin != null && scout.flow.ageMin > 30 ? `(${Math.round(scout.flow.ageMin / 60)}h前)` : ''}</>}
            </div>
          )}
          <div className="scout__gaps">
            未対応(正直表示): {(scout.dataGapsJa ?? []).join(' / ')}
          </div>
          <div className="scout__note">{scout.noteJa}</div>
        </div>
      )}
    </>
  );
};
