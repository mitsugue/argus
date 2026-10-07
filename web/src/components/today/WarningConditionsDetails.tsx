import type { MarketSignalsView } from '../../domain/marketSignals';
import { warningDistanceJa } from '../../domain/sevenSignReading';

export function warningPerformanceJa(row: MarketSignalsView['signals'][number]) {
  const p = row.performance, five = p?.horizons?.['5'];
  if (row.ruleStatus === 'RULE_NOT_DEFINED') return '成績：測定規則の確定後に検査します';
  if (!p || p.ruleId !== row.ruleId || !five || !Number.isInteger(five.evaluated)
    || five.evaluated < 0 || !Number.isInteger(five.falls) || five.falls < 0 || five.falls > five.evaluated)
    return '成績：まだ採点できる記録がありません';
  const grade = p.status === 'NOT_ABOVE_BASELINE' ? '通常時より予測が優れるとは確認できません'
    : p.status === 'INSUFFICIENT_SAMPLE' ? '件数不足' : '予測力は未検証';
  return `過去の成立後5営業日：${five.evaluated}件中${five.falls}件下落・${grade}`;
}

export function warningCoverageJa(view: MarketSignalsView) {
  const measured = view.signals.filter(row => row.state === 'ACTIVE' || row.state === 'CLEAR');
  const undefinedRules = view.signals.filter(row => row.ruleStatus === 'RULE_NOT_DEFINED');
  const missing = view.signals.filter(row => !measured.includes(row) && !undefinedRules.includes(row));
  return { measured: measured.length,
    undefinedLabel: undefinedRules.map(row => Number(row.family.slice(-2))).join('・'),
    missing: missing.map(row => `${Number(row.family.slice(-2))} · ${row.nameJa}：${row.gateNoteJa || row.stateJa}`) };
}

export function WarningConditionsDetails({ view }: { view: MarketSignalsView }) {
  const coverage = warningCoverageJa(view);
  return <div className="at-seven-signals" data-argus-contract="warning-conditions-v2">
    <div role="status" data-argus-contract="warning-coverage-v1">
      <p>7条件の判定状況：{coverage.measured}件を測定できています。</p>
      {coverage.undefinedLabel && <p>{coverage.undefinedLabel}番は判定基準の確定待ちです。データを取得し直すだけでは判定できません。</p>}
      {coverage.missing.length > 0 && <ul aria-label="7条件で確認が必要な入力">
        {coverage.missing.map(line => <li key={line}>{line}</li>)}
      </ul>}
    </div>
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
        <small className="at-seven-performance">{warningPerformanceJa(row)}</small>
      </i>
    </div>)}
    <details><summary>「成績：未検証」の意味</summary>
      <p>条件の計算が動くことと、下落を予測できることは別です。判定基準を固定し、当時利用できたデータで過去の下落を測り、普段の下落割合との比較と件数を確認します。基準を上回らない場合もあり、時間がたつだけで検証済みにはなりません。</p>
    </details>
    <small>測定できる条件 {coverage.measured}件／全7条件。成立件数から暴落の確率は出しません。</small>
  </div>;
}
