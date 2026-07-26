import React from 'react';
import type { DeskCardData } from './types';
import { probabilityDisplay } from '../../domain/decisionView';

// V12.2.12 — SCENARIOS(§7-8)。旧Todayの条件付き分岐(scenario engine・帯のみ)
// +旧Watchlistのルールシナリオ確率を併記。単一予測なし・%断定なし(不変)。

export const AssetScenarioPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const scn = d.scn;
  return (
    <div data-scenario-role="decision-conditions">
      {scn && (
        <div className="ad-scenario-conditions">
          {scn.cases.map((cs) => (
            <p key={cs.label} className="uac-next">
              <b>{cs.titleJa}</b>
              <span>{cs.bandJa}</span>
              <small>{cs.conditionsJa.slice(0, 2).join(' / ')}</small>
            </p>
          ))}
          <p className="uac-next"><b>無効化</b><small>{scn.invalidationJa.slice(0, 2).join(' / ')}</small></p>
          <p className="uac-next"><b>次の確認</b><small>{scn.nextChecksJa.slice(0, 2).join(' / ')}</small></p>
        </div>
      )}
      {!scn && d.strat.scenarios.length > 0 && (
        <div className="asset-scen">
          <div className="asset-scen__head">判断条件 · {d.strat.scenarioHorizonJa}</div>
          {d.strat.scenarios.map((s) => {
            const display = probabilityDisplay(s.probability, s.probabilityProvenance);
            return (
              <div className="asset-scen__row" key={s.label}>
                <span className="asset-scen__label">{s.labelJa}</span>
                <span className="asset-scen__band">
                  {display.qualitative}
                  {display.showPercent && <small>{display.percentText}</small>}
                </span>
                <span className="asset-scen__why">{s.rationaleJa}</span>
              </div>
            );
          })}
        </div>
      )}
      {!scn && d.strat.scenarios.length === 0 && (
        <p className="uac-next" style={{ margin: 0, color: 'var(--text-faint)' }}>条件データ未取得</p>
      )}
    </div>
  );
};
