import React from 'react';
import type { DeskCardData } from './types';
import { DOM_TONE } from '../../domain/scenario';

// V12.2.12 — SCENARIOS(§7-8)。旧Todayの条件付き分岐(scenario engine・帯のみ)
// +旧Watchlistのルールシナリオ確率を併記。単一予測なし・%断定なし(不変)。

export const AssetScenarioPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const scn = d.scn;
  return (
    <>
      {scn && (
        <div style={{ marginBottom: 4 }}>
          <p className="uac-next" style={{ marginBottom: 2 }}>
            <b style={{ color: DOM_TONE[scn.dominant] }}>{scn.dominantJa}</b>
            <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{scn.summaryJa}</span>
          </p>
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>分岐と無効化条件を見る</summary>
            {scn.cases.map((cs) => (
              <p key={cs.label} className="uac-next" style={{ margin: '3px 0 0', fontSize: 11 }}>
                <b>{cs.titleJa}</b>
                <span style={{ marginLeft: 5, fontSize: 9.5, color: 'var(--text-faint)',
                               border: '1px solid var(--line)', borderRadius: 999, padding: '0 5px' }}>
                  {cs.bandJa}
                </span>
                <span style={{ marginLeft: 5, fontSize: 9.5, color: 'var(--text-faint)' }}>{cs.actionJa}</span>
                <br />
                <span style={{ color: 'var(--text-sub)' }}>{cs.narrativeJa}</span>
              </p>
            ))}
            <p className="uac-next" style={{ margin: '4px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              無効化条件: {scn.invalidationJa.join(' / ')}
            </p>
            <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              次の確認: {scn.nextChecksJa.join(' / ')}
            </p>
            <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              何が変われば: {scn.whatWouldChangeJa.join(' / ')}
            </p>
          </details>
        </div>
      )}
      {d.strat.scenarios.length > 0 && (
        <div className="asset-scen">
          <div className="asset-scen__head">Scenario probabilities · {d.strat.scenarioHorizonJa}</div>
          {d.strat.scenarios.map((s) => (
            <div className="asset-scen__row" key={s.label}>
              <span className="asset-scen__label">{s.labelJa}</span>
              <span className="asset-scen__bar"><span style={{ width: `${s.probability}%` }} /></span>
              <span className="asset-scen__pct">{s.probability}%</span>
              <span className="asset-scen__why">{s.rationaleJa}</span>
            </div>
          ))}
          <div className="asset-scen__disc">{d.strat.scenarioDisclaimerJa}</div>
        </div>
      )}
      {!scn && d.strat.scenarios.length === 0 && (
        <p className="uac-next" style={{ margin: 0, color: 'var(--text-faint)' }}>シナリオ合成に必要なデータが未取得です。</p>
      )}
    </>
  );
};
