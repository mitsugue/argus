import type { MarketSignalsView } from '../../domain/marketSignals';
import { warningDistanceJa } from '../../domain/sevenSignReading';

export function WarningConditionsDetails({ view }: { view: MarketSignalsView }) {
  return <div className="at-seven-signals" data-argus-contract="warning-conditions-v2">
    {view.signals.map(row => <div className="at-seven-row" key={row.ruleId ?? row.id}>
      <i data-signal-id={row.id} data-signal-state={row.state}>
        <span className="at-seven-condition">{Number(row.id.slice(-2))} · {row.nameJa}</span>
        <b>{row.state === 'ACTIVE' ? '成立' : row.state === 'CLEAR' ? '未成立' : row.stateJa}</b>
        <span className="at-seven-direction" data-direction="warning">{row.ruleStatus === 'RULE_NOT_DEFINED'
          ? '警戒の判定基準は未定義' : row.lineage === 'ARGUS_CANDIDATE' ? '警戒条件・ARGUSの計算候補' : '警戒条件'}</span>
        {row.conditionRuleJa && <small className="at-seven-rule">{row.conditionRuleJa}</small>}
        {row.factNoteJa && <small className="at-seven-fact">{row.factNoteJa}</small>}
        {warningDistanceJa(row) && <strong className="at-seven-distance">{warningDistanceJa(row)}</strong>}
        {row.gateNoteJa && <small className="at-seven-gate-note">{row.gateNoteJa}</small>}
        {row.knowledgeTime && <small>{row.sourcePeriodEnd ? `${row.sourcePeriodEnd}の値・` : ''}記録された利用可能日時：{new Date(row.knowledgeTime).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}</small>}
        <small className="at-seven-performance">この警戒規則の成績：未検証</small>
      </i>
    </div>)}
    <small>測定できる条件 {view.measurableCount ?? 0}件／全7条件。成立件数から暴落の確率は出しません。</small>
  </div>;
}
