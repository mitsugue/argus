import type { MarketSignalsView } from '../../domain/marketSignals';
import { warningDistanceJa } from '../../domain/sevenSignReading';

export function WarningConditionsDetails({ view }: { view: MarketSignalsView }) {
  return <div className="at-seven-signals" data-argus-contract="warning-conditions-v2">
    {view.signals.map(row => <div className="at-seven-row" key={row.ruleId ?? row.id}>
      <i data-signal-id={row.id} data-signal-state={row.state}>
        <span className="at-seven-condition">{Number(row.id.slice(-2))} · {row.nameJa}</span>
        <b>{row.state === 'ACTIVE' ? '成立' : row.state === 'CLEAR' ? '未成立' : row.ruleStatus === 'RULE_NOT_DEFINED' ? '基準未確定' : row.stateJa}</b>
        <span className="at-seven-direction" data-direction="warning">{row.ruleStatus === 'RULE_NOT_DEFINED'
          ? '警戒の判定基準は未定義' : row.lineage === 'ARGUS_CANDIDATE' ? '警戒条件・ARGUSの計算候補' : '警戒条件'}</span>
        {row.conditionRuleJa && <small className="at-seven-rule">{row.conditionRuleJa}</small>}
        {row.factNoteJa && <small className="at-seven-fact">{row.factNoteJa}</small>}
        {warningDistanceJa(row) && <strong className="at-seven-distance">{warningDistanceJa(row)}</strong>}
        {row.gateNoteJa && row.gateNoteJa !== row.conditionRuleJa && <small className="at-seven-gate-note">{row.gateNoteJa}</small>}
        {row.knowledgeTime && <small>{row.sourcePeriodEnd ? `${row.sourcePeriodEnd}の値・` : ''}記録された利用可能日時：{new Date(row.knowledgeTime).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}</small>}
        <small className="at-seven-performance">この警戒規則の成績：未検証</small>
      </i>
    </div>)}
    <details><summary>「成績：未検証」の意味</summary>
      <p>条件の計算が動くことと、下落を予測できることは別です。判定基準を固定し、当時利用できたデータで過去の下落を測り、普段の下落割合との比較と件数を確認します。基準を上回らない場合もあり、時間がたつだけで検証済みにはなりません。</p>
    </details>
    <small>測定できる条件 {view.measurableCount ?? 0}件／全7条件。成立件数から暴落の確率は出しません。</small>
  </div>;
}
