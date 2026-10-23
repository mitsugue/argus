import React from 'react';
import { useDecisionEvidence } from '../../hooks/useDecisionEvidence';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { selectMarketInternals } from '../../lib/marketInternals';
import { MarketInternalsCard } from './MarketInternalsCard';
import './ArgusToday.css';
import { SectorHeatmap } from './SectorHeatmap';

/** Display only. Both pages share the existing pollers and exact frozen inputs. */
export function SharedMarketContext({horizon,focusSymbol}:{horizon:number;focusSymbol?:string}) {
  const evidence=useDecisionEvidence();
  const {brief}=useMarketBrief();
  const frame=selectMarketInternals(brief,evidence.marketView?.internals,horizon);
  return <div className="at-shared-context" data-analysis-binding={frame.binding}>
    {!focusSymbol&&<SectorHeatmap internals={evidence.marketView?.internals}/>}
    {evidence.error&&<p role="status" className="at-shared-context__status">更新失敗・保存分</p>}
    <MarketInternalsCard document={frame.document} horizon={horizon} focusSymbol={focusSymbol}/>
  </div>;
}
