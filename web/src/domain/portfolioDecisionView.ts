import type { PositionRisk } from './positionExposure';

export interface PortfolioDecisionInput {
  combinedJpy: number | null;
  combinedPlJpy: number | null;
  pricedCount: number;
  unpriced: string[];
  noHoldings: boolean;
  top1Symbol: string | null;
  top1Pct: number | null;
  topThemeJa: string | null;
  topThemePct: number | null;
  jpyPct: number | null;
  usdPct: number | null;
  risks: PositionRisk[];
  stressConditions?: string[];
  nextPortfolioChecks?: string[];
}

export interface PortfolioDecisionOverview {
  command: string;
  exposure: {
    valueJpy: number | null;
    plJpy: number | null;
    pricedCount: number;
    unpricedCount: number;
  };
  topRisks: Array<{ label: string; value: string; severity: string }>;
  actionQueue: Array<{ symbol: string; action: string; severity: string }>;
  stressConditions: string[];
  nextChecks: string[];
}

const severityRank = { critical: 0, high: 1, medium: 2, low: 3, unknown: 4 } as const;

export function buildPortfolioDecisionOverview(
  input: PortfolioDecisionInput,
): PortfolioDecisionOverview {
  const risks = input.risks.slice().sort((a, b) =>
    severityRank[a.riskLevel] - severityRank[b.riskLevel]
    || a.symbol.localeCompare(b.symbol));
  const urgent = risks.some((risk) => risk.riskLevel === 'critical' || risk.riskLevel === 'high');
  const command = input.noHoldings
    ? '保有数量と平均取得単価を入力し、リスク計算を有効化'
    : urgent
      ? '新規追加を止め、上位リスクの縮小条件を先に点検'
      : input.unpriced.length
        ? '未評価資産を確認してから配分を判断'
        : '現在配分を維持し、集中とイベント条件を監視';

  const topRisks: PortfolioDecisionOverview['topRisks'] = [];
  if (input.top1Symbol && input.top1Pct != null) {
    topRisks.push({
      label: '銘柄集中',
      value: `${input.top1Symbol} ${input.top1Pct.toFixed(0)}%`,
      severity: input.top1Pct >= 40 ? 'critical' : input.top1Pct >= 25 ? 'high'
        : input.top1Pct >= 15 ? 'medium' : 'low',
    });
  }
  if (input.topThemeJa && input.topThemePct != null) {
    topRisks.push({
      label: 'テーマ集中',
      value: `${input.topThemeJa} ${input.topThemePct.toFixed(0)}%`,
      severity: input.topThemePct >= 40 ? 'high' : input.topThemePct >= 25 ? 'medium' : 'low',
    });
  }
  if (input.jpyPct != null || input.usdPct != null) {
    topRisks.push({
      label: '通貨',
      value: `JPY ${input.jpyPct?.toFixed(0) ?? '未算出'}% / USD ${input.usdPct?.toFixed(0) ?? '未算出'}%`,
      severity: Math.max(input.jpyPct ?? 0, input.usdPct ?? 0) >= 80 ? 'medium' : 'low',
    });
  }
  if (input.unpriced.length) {
    topRisks.push({
      label: '未評価',
      value: `${input.unpriced.length}件`,
      severity: 'unknown',
    });
  }

  // A position may raise several risk types. The portfolio queue owns one compact
  // command per symbol; the full per-asset explanation remains in Asset Desk.
  const actionQueue: PortfolioDecisionOverview['actionQueue'] = [];
  const queuedSymbols = new Set<string>();
  for (const risk of risks) {
    const symbol = risk.symbol.toUpperCase();
    if (queuedSymbols.has(symbol)) continue;
    queuedSymbols.add(symbol);
    actionQueue.push({ symbol, action: risk.checkNextJa, severity: risk.riskLevel });
    if (actionQueue.length === 5) break;
  }
  const stressConditions = [...new Set(input.stressConditions ?? [])].slice(0, 2);
  if (stressConditions.length === 0) {
    stressConditions.push(input.noHoldings
      ? '保有データ未入力のため、条件付きdownsideは未算出'
      : input.top1Pct != null
        ? `最大保有が下落する局面（集中 ${input.top1Pct.toFixed(0)}%）`
        : '重大な条件付きdownsideは現在未検出');
  }
  const nextChecks = [...new Set([
    ...risks.map((risk) => risk.checkNextJa),
    ...(input.nextPortfolioChecks ?? []),
    input.unpriced.length ? `未評価 ${input.unpriced.slice(0, 2).join(' / ')} の価格更新` : null,
  ].filter((value): value is string => !!value))].slice(0, 2);

  return {
    command,
    exposure: {
      valueJpy: input.combinedJpy,
      plJpy: input.combinedPlJpy,
      pricedCount: input.pricedCount,
      unpricedCount: input.unpriced.length,
    },
    topRisks: topRisks.slice(0, 4),
    actionQueue,
    stressConditions,
    nextChecks: nextChecks.length ? nextChecks : ['次の価格更新後に配分と集中度を再確認'],
  };
}
