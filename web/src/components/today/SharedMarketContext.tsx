import React from 'react';
import { useDecisionEvidence } from '../../hooks/useDecisionEvidence';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { selectMarketInternals } from '../../lib/marketInternals';
import { MarketInternalsCard } from './MarketInternalsCard';
import './ArgusToday.css';

/** Display only. Both pages share the existing pollers and exact frozen inputs. */
export function SharedMarketContext({horizon,focusSymbol}:{horizon:number;focusSymbol?:string}) {
  const evidence=useDecisionEvidence();
  const {brief}=useMarketBrief();
  const frame=selectMarketInternals(brief,evidence.marketView?.internals,horizon);
  return <div className="at-shared-context" data-analysis-binding={frame.binding}>
    <p className="at-shared-context__status">{frame.binding==='AI_SNAPSHOT'
      ? 'この比較は、表示中の統合AIが説明に使った時点の根拠です。'
      : frame.binding==='LATEST_SEPARATE'
        ? 'この比較は取得済みの最新データです。表示中のAI説明と同じ時点の根拠はまだ確認できません。'
        : '取得済みデータの比較です。統合AIの説明との接続は確認待ちです。'}</p>
    {evidence.error&&<p role="status" className="at-shared-context__status">最新データの更新に失敗しました。利用できる取得済みの情報を表示しています。</p>}
    <MarketInternalsCard document={frame.document} horizon={horizon} focusSymbol={focusSymbol}/>
  </div>;
}
