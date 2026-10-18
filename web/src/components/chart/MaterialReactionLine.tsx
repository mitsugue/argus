import React from 'react';
import { validMaterialReactionResearch } from '../../lib/japanMarketComparison';
import type { MaterialReactionResearch } from '../../types/japanMarketComparison';

// 2026-10-18 (owner): one plain line, shown under the default chart as well.
// The figures are from the period the decision did not see.
export function MaterialReactionLine({ research }: { research: unknown }) {
  if (!validMaterialReactionResearch(research)) return null;
  const r = research as MaterialReactionResearch;
  const pct = (n: number | null) => n === null ? '—' : `${(n * 100).toFixed(0)}%`;
  // Not used: the rates the decision compared. Used: the period the decision
  // did not see, as the independent check.
  const [without, withIt] = r.adopted ? [r.heldOutWithout, r.heldOutWith] : [r.decisionWithout, r.decisionWith];
  const change = `${pct(without.hitRate)} → ${pct(withIt.hitRate)}`;
  return <p className="jmc-material-reaction" data-material-reaction={r.adopted ? 'adopted' : 'not-adopted'}>
    経済指標の発表反応：{r.adopted
      ? `使用中（入れると5営業日後の方向の一致率 ${change}・検証${withIt.directionalEvaluations ?? 0}件）`
      : `不使用（入れても5営業日後の方向の一致率 ${change} で、差が偶然の範囲のため）`}
  </p>;
}

// 2026-10-19 (owner): when no past window is close enough, one line says why.
export function noAnalogText(document: unknown): string | null {
  const e = document && typeof document === 'object' ? (document as Record<string, unknown>).noAnalogExplanation : null;
  const text = e && typeof e === 'object' ? (e as Record<string, unknown>).textJa : null;
  return typeof text === 'string' && text.length > 0 && text.length <= 200 ? text : null;
}

export function NoAnalogLine({ document }: { document: unknown }) {
  const text = noAnalogText(document);
  return text ? <p className="jmc-no-analog" role="status">{text}</p> : null;
}

// 2026-10-19 (owner): the recent-years yardstick for the Japan 10-year yield,
// adopted only when it forecasts better. One line in the details.
const rate = (v: unknown) => v && typeof v === 'object' && ((v as Record<string, unknown>).hitRate === null
  || (typeof (v as Record<string, unknown>).hitRate === 'number' && Number.isFinite((v as Record<string, unknown>).hitRate as number)))
  ? (v as { hitRate: number | null }).hitRate : undefined;
export function YardstickLine({ research }: { research: unknown }) {
  if (!research || typeof research !== 'object') return null;
  const r = research as Record<string, unknown>;
  if (typeof r.adopted !== 'boolean') return null;
  const [without, withIt] = r.adopted ? [rate(r.heldOutWithout), rate(r.heldOutWith)] : [rate(r.decisionWithout), rate(r.decisionWith)];
  if (without === undefined || withIt === undefined) return null;
  const pct = (n: number | null) => n === null ? '—' : `${(n * 100).toFixed(0)}%`;
  return <p className="jmc-yardstick" data-yardstick={r.adopted ? 'adopted' : 'not-adopted'}>
    日本10年金利の物差し（直近3年で測る見直し）：{r.adopted
      ? `採用（5営業日後の方向の一致率 ${pct(without)} → ${pct(withIt)}）`
      : `不採用（一致率 ${pct(without)} → ${pct(withIt)} で、良くなると言えないため）`}
  </p>;
}

