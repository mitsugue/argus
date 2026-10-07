import React from 'react';
import type { DeskCardData } from './types';
import { uniqueDetailText } from './detailReading';

/** カード先頭の価格・目標・需給を繰り返さず、見立ての理由と次の確認を読む。 */
export const AssetDecisionDetails: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const view = d.decisionFirst;
  const seen: string[] = [];
  const rows = [
    ['理由', view.whyJa],
    ['次に確認すること', view.nextJa],
    ['判断が変わる条件', view.whatChangesJa],
  ].filter(([, text]) => {
    if (!uniqueDetailText([text], seen).length) return false;
    seen.push(text);
    return true;
  });
  return (
    <div className="ad-overview" data-decision-overview={view.symbol}>
      <details className="ad-legacy-conditions"><summary>参考条件・見直しの根拠</summary><dl className="ad-overview__facts">
        {rows.map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}
      </dl></details>
      <p className="ad-detail-note">登録銘柄の分析です。保有状況を扱わないため、旧売買判断の待機は取得待ちを意味しません。</p>
      {view.dataStatus !== 'LIVE' && view.dataStatus !== 'live' && (
        <p className="ad-overview__warning">{view.dataStatus} · データの不足・古さは「記録・データ」で確認できます。</p>
      )}
    </div>
  );
};
