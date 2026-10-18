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
