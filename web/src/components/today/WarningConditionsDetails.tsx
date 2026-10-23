import type { MarketSignalsView } from '../../domain/marketSignals';

type WarningRow = MarketSignalsView['signals'][number];

/** Owner policy 2026-10-23: the record as counts only; no verdict sentence. */
export function warningPerformanceJa(row: WarningRow): string | null {
  const p = row.performance, five = p?.horizons?.['5'];
  if (row.ruleStatus === 'RULE_NOT_DEFINED') return null;
  if (!p || p.ruleId !== row.ruleId || !five || !Number.isInteger(five.evaluated)
    || five.evaluated < 0 || !Number.isInteger(five.falls) || five.falls < 0 || five.falls > five.evaluated
    || five.evaluated === 0) return null;
  const base = typeof five.baselineFallShare === 'number' && Number.isFinite(five.baselineFallShare)
    ? `（普段${Math.round(five.baselineFallShare * 100)}%）` : '';
  const source = p.availabilityBasis === 'RECONSTRUCTED_PUBLICATION_18JST_NOT_ARCHIVED_VINTAGE' ? '（復元データ）' : '';
  return `成立後5日${source}：${five.evaluated}件中${five.falls}件下落${base}${p.status === 'INSUFFICIENT_SAMPLE' ? '・件数不足' : ''}`;
}

export function warningCoverageJa(view: MarketSignalsView) {
  const measured = view.signals.filter(row => row.state === 'ACTIVE' || row.state === 'CLEAR');
  const undefinedRules = view.signals.filter(row => row.ruleStatus === 'RULE_NOT_DEFINED');
  const missing = view.signals.filter(row => !measured.includes(row) && !undefinedRules.includes(row));
  return { measured: measured.length,
    undefinedLabel: undefinedRules.map(row => Number(row.family.slice(-2))).join('・'),
    missing: missing.map(row => `${Number(row.family.slice(-2))} · ${row.nameJa}：${row.gateNoteJa || row.stateJa}`) };
}

/** The measured value only: the first sentence, without notes in brackets or when it became usable. */
export function warningFactJa(text?: string | null): string | null {
  if (!text) return null;
  const first = text.split('。')[0].replace(/（[^）]*）/g, '');
  const value = first.split('・').filter(part => !/(から利用|に入手|利用可能)$/.test(part.trim())).join('・').trim();
  return value || null;
}

export function warningStateJa(row: WarningRow): string {
  if (row.state === 'ACTIVE') return '成立';
  if (row.state === 'CLEAR') return '未成立';
  if (row.ruleStatus === 'RULE_NOT_DEFINED') return '基準未確定';
  return row.state === 'DATA_GATED' ? 'データ待ち' : row.stateJa;
}

/** One row per sign: name and state, the value (or the missing data), the condition, the record. */
export function WarningConditionsDetails({ view }: { view: MarketSignalsView }) {
  return <div className="at-seven-signals" data-argus-contract="warning-conditions-v2">
    {view.signals.map(row => {
      const measured = row.state === 'ACTIVE' || row.state === 'CLEAR';
      const undefinedRule = row.ruleStatus === 'RULE_NOT_DEFINED';
      const fact = measured ? warningFactJa(row.factNoteJa) : undefinedRule ? null : row.gateNoteJa;
      const performance = warningPerformanceJa(row);
      return <div className="at-seven-row" key={row.ruleId ?? row.id}>
        <i data-signal-id={row.id} data-signal-state={row.state}>
          <span className="at-seven-condition">{Number(row.id.slice(-2))} · {row.nameJa}</span>
          <b>{warningStateJa(row)}</b>
          {fact && <small className="at-seven-fact">{fact}</small>}
          {!undefinedRule && row.conditionRuleJa && <small className="at-seven-rule">条件：{row.conditionRuleJa}</small>}
          {performance && <small className="at-seven-performance">{performance}</small>}
        </i>
      </div>;
    })}
  </div>;
}
