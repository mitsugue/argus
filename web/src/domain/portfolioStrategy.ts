// V11.19.0 — Portfolio Strategy / FIRE Alignment (device-local TS port of
// argus_portfolio_strategy.py). 短期の計画とFIRE目的を接続する戦略層。
// 保有・比率・口座情報は端末内でのみ合成され、サーバーに送られない。
// 免許を持つFP/税務/法務の助言ではない。売買指示でもない。帯のみ(精密計算なし)。

import type { PortfolioExposure, ThemeKey } from './positionExposure';
import { jpDisplay } from '../lib/displayName';

export type AssetRoleKey = 'core' | 'satellite' | 'tactical' | 'hedge' | 'cash_like' | 'watch_only' | 'unknown';
export type FireStatus = 'aligned' | 'mostly_aligned' | 'stretched' | 'misaligned' | 'unknown';
export type TacticalBudget = 'underused' | 'appropriate' | 'stretched' | 'exceeded' | 'unknown';

export const ROLE_JA: Record<AssetRoleKey, string> = {
  core: 'コア(長期)', satellite: 'サテライト', tactical: '戦術枠(短期)',
  hedge: 'ヘッジ', cash_like: '現金相当', watch_only: '監視のみ', unknown: '未分類',
};
export const FIRE_JA: Record<FireStatus, string> = {
  aligned: '整合', mostly_aligned: '概ね整合', stretched: 'やや無理あり',
  misaligned: '不整合', unknown: '判定保留',
};
export const FIRE_TONE: Record<FireStatus, string> = {
  aligned: 'var(--value-positive)', mostly_aligned: 'var(--accent)',
  stretched: 'var(--amber, #fbbf24)', misaligned: 'var(--value-negative)',
  unknown: 'var(--text-faint)',
};
export const BUDGET_JA: Record<TacticalBudget, string> = {
  underused: '余裕あり', appropriate: '許容内', stretched: '大きめ',
  exceeded: '超過', unknown: '判定保留',
};
export const STRATEGY_COMPLIANCE_JA =
  '概算の戦略整合チェックであり、免許を持つFP・税務・法務の助言ではない。売買指示でも自動売買でもない。';

const HIGH_BETA: ThemeKey[] = ['ai_infrastructure', 'physical_ai_robotics', 'semiconductor_photonics'];
const ADD_POLICY_JA: Record<string, string> = {
  systematic_accumulation: '積立継続', pullback_only: '押し目限定',
  small_tactical_only: '小さく戦術枠のみ', no_add_until_risk_reduces: 'リスク低下まで追加なし',
  monitor_only: '監視のみ', unknown: '—',
};

export interface LocalAssetRole {
  symbol: string; assetName: string;
  role: AssetRoleKey; roleJa: string;
  roleReasonJa: string;
  strategyFit: 'strong' | 'acceptable' | 'stretched' | 'weak' | 'unknown';
  addPolicy: string; addPolicyJa: string;
  trimReviewPolicy: string;
  weightPct: number | null;
  theme: ThemeKey;
}

export function classifyRole(i: {
  symbol: string; assetName: string; theme: ThemeKey; assetType?: string;
  isHeld: boolean; weightPct?: number | null; concentrationRisk?: string | null;
  eventPending?: boolean;
}): LocalAssetRole {
  const w = i.weightPct ?? 0;
  let role: AssetRoleKey; let reason: string;
  if (i.theme === 'index_core' || i.assetType === 'fund') {
    role = 'core'; reason = 'インデックス/投信はFIREの土台(コア)。日々の判断より継続が主役です。';
  } else if (i.theme === 'gold') {
    role = 'hedge'; reason = '金はリターン源というよりヘッジ(全体の値動きを和らげる役割)として扱うのが自然です。';
  } else if (!i.isHeld) {
    role = 'watch_only'; reason = '監視のみ(保有なし)。役割はエントリー時に確定します。';
  } else if (i.theme === 'crypto') {
    role = w >= 10 ? 'tactical' : 'satellite';
    reason = role === 'tactical'
      ? '暗号資産の比率が大きく、値動きの荒さから戦術枠扱いです。'
      : '暗号資産はボラティリティが高く、コアではなくサテライト扱いです。';
  } else if (HIGH_BETA.includes(i.theme) && w >= 15) {
    role = 'tactical'; reason = '高ベータのAI関連で比率も大きいため、戦術枠(短期勝負)として扱います。';
  } else {
    role = 'satellite'; reason = '個別株はコアではなくサテライト。買い増しはポートフォリオ全体の比率を確認してからです。';
  }
  const singleCritical = ['high', 'critical'].includes(i.concentrationRisk ?? '');
  const fit = role === 'core' || role === 'hedge' ? 'strong'
    : singleCritical ? 'weak'
      : role === 'tactical' && w >= 15 ? 'stretched'
        : role === 'satellite' || role === 'tactical' ? 'acceptable' : 'unknown';
  const add = role === 'core' ? 'systematic_accumulation'
    : role === 'hedge' || role === 'watch_only' ? 'monitor_only'
      : fit === 'stretched' || fit === 'weak' ? 'no_add_until_risk_reduces'
        : role === 'tactical' ? 'small_tactical_only' : 'pullback_only';
  const trim = (role === 'core' || role === 'hedge' || role === 'watch_only') && !singleCritical ? 'not_needed'
    : fit === 'stretched' || fit === 'weak' ? 'if_overweight'
      : i.eventPending ? 'if_event_risk_rises' : 'if_scenario_breaks';
  return {
    symbol: i.symbol.toUpperCase(), assetName: i.assetName,
    role, roleJa: ROLE_JA[role], roleReasonJa: reason,
    strategyFit: fit, addPolicy: add, addPolicyJa: ADD_POLICY_JA[add],
    trimReviewPolicy: trim,
    weightPct: i.isHeld ? w : null, theme: i.theme,
  };
}

export interface LocalStrategy {
  strategyMode: string; strategyModeJa: string;
  corePct: number; satellitePct: number; tacticalPct: number; hedgePct: number;
  goldPct: number; cryptoPct: number; aiThemePct: number;
  fireStatus: FireStatus; fireStatusJa: string;
  scoreBand: string;
  tacticalBudget: TacticalBudget; tacticalBudgetJa: string;
  totalRiskLevel: string; themeRisk: string; singleNameRisk: string;
  drawdownSensitivity: string;
  summaryJa: string; riskJa: string;
  warningsJa: string[]; opportunitiesJa: string[];
  stressNotesJa: string[];
  fireWarningsJa: string[]; improveJa: string[];
  nextChecksJa: string[]; missingDataJa: string[];
  roles: LocalAssetRole[];
  noHoldings: boolean;
}

export function buildStrategy(pe: PortfolioExposure, roles: LocalAssetRole[],
  ctx: { eventPending?: boolean; recurringAccumulationKnown?: boolean }): LocalStrategy {
  const themePct = (k: ThemeKey) => pe.byTheme.find((t) => t.key === k)?.pct ?? 0;
  const alloc = (r: AssetRoleKey) =>
    Math.round(roles.filter((x) => x.role === r).reduce((s, x) => s + (x.weightPct ?? 0), 0) * 10) / 10;
  const core = alloc('core'), sat = alloc('satellite'), tac = alloc('tactical'), hedge = alloc('hedge');
  const gold = themePct('gold'), crypto = themePct('crypto');
  const ai = HIGH_BETA.reduce((s, k) => s + themePct(k), 0);
  const noHold = pe.noHoldings;

  const tacBudget: TacticalBudget = noHold ? 'unknown'
    : tac > 40 ? 'exceeded' : tac > 25 ? 'stretched' : tac >= 10 ? 'appropriate' : 'underused';
  const themeRisk = noHold ? 'unknown' : ai >= 60 ? 'critical' : ai >= 45 ? 'high' : ai >= 30 ? 'medium' : 'low';
  const singleRisk = noHold ? 'unknown' : (pe.singleNameRisk ?? 'low');
  const totalRisk = noHold ? 'unknown'
    : themeRisk === 'critical' || singleRisk === 'critical' || tacBudget === 'exceeded' ? 'critical'
      : themeRisk === 'high' || singleRisk === 'high' || tacBudget === 'stretched' ? 'high' : 'medium';
  const ddSens = noHold ? 'unknown' : ai >= 50 || crypto >= 20 ? 'high' : ai >= 30 ? 'medium' : 'low';

  const coreLike = core + hedge;
  let fire: FireStatus; let band: string;
  if (noHold) { fire = 'unknown'; band = 'insufficient_data'; }
  else if (tacBudget === 'exceeded' || singleRisk === 'critical' || (coreLike < 10 && tac > 30)) { fire = 'misaligned'; band = 'weak'; }
  else if (tacBudget === 'stretched' || themeRisk === 'high' || themeRisk === 'critical' || coreLike < 25) {
    fire = 'stretched'; band = themeRisk === 'critical' ? 'weak' : 'moderate';
  } else if (coreLike >= 40 && tac <= 25 && !['high', 'critical'].includes(singleRisk)) { fire = 'aligned'; band = 'strong'; }
  else { fire = 'mostly_aligned'; band = 'moderate'; }

  const mode = noHold ? 'unknown'
    : tacBudget === 'stretched' || tacBudget === 'exceeded' ? 'tactical_aggressive'
      : coreLike >= 40 ? 'fire_growth' : 'balanced_growth';
  const MODE_JA: Record<string, string> = {
    fire_growth: 'FIRE成長型', balanced_growth: 'バランス型',
    tactical_aggressive: '戦術寄り', unknown: '判定保留',
  };

  const riskJa = tacBudget === 'stretched' || tacBudget === 'exceeded'
    ? '短期勝負枠が大きくなっているため、追加よりも既存ポジションの整理・押し目限定が優先です。'
    : ddSens === 'high'
      ? `AI関連への集中(約${Math.round(ai)}%)が下落感応度を高めています。同時に下がる前提での比率確認を。`
      : noHold ? '保有数量が未入力のため、リスク予算は判定できません(捏造しません)。'
        : 'リスク配分は現時点で極端な偏りは確認されていません(不明項目は下記)。';

  const warningsJa = [
    ...(tacBudget === 'stretched' || tacBudget === 'exceeded'
      ? ['短期勝負枠が大きくなっています。新規追加よりも、既存ポジションの集中度とイベントリスクの確認が先です。'] : []),
    ...(!noHold && coreLike < 25
      ? ['長期のFIRE目的に対して、コア資産の比率が不足している可能性があります。個別株の追加判断とは別に、インデックス積立の継続確認が必要です。'] : []),
    ...(themeRisk === 'high' || themeRisk === 'critical'
      ? ['AI/フィジカルAI関連への集中が高まっています。テーマが当たれば伸びますが、金利上昇やAI投資鈍化のニュースに弱くなります。'] : []),
    ...(['high', 'critical'].includes(singleRisk) && pe.top1Symbol
      ? [`1銘柄(${pe.top1Symbol})への集中が${singleRisk === 'critical' ? '危険' : '高い'}水準です。`] : []),
    ...(crypto >= 15 ? [`暗号資産が約${Math.round(crypto)}%と大きめです(戦術枠として管理)。`] : []),
  ].slice(0, 4);

  return {
    strategyMode: mode, strategyModeJa: MODE_JA[mode],
    corePct: core, satellitePct: sat, tacticalPct: tac, hedgePct: hedge,
    goldPct: Math.round(gold * 10) / 10, cryptoPct: Math.round(crypto * 10) / 10,
    aiThemePct: Math.round(ai * 10) / 10,
    fireStatus: fire, fireStatusJa: FIRE_JA[fire], scoreBand: band,
    tacticalBudget: tacBudget, tacticalBudgetJa: BUDGET_JA[tacBudget],
    totalRiskLevel: totalRisk, themeRisk, singleNameRisk: singleRisk,
    drawdownSensitivity: ddSens,
    summaryJa: noHold
      ? '保有数量が未入力のため、戦略判定は保留です(Watchlistで入力すると端末内で判定します)。'
      : `現在の構成は${MODE_JA[mode]}(コア+ヘッジ約${Math.round(coreLike)}% / サテライト約${Math.round(sat)}% / 戦術枠約${Math.round(tac)}%)。FIRE整合は「${FIRE_JA[fire]}」、短期勝負枠は${BUDGET_JA[tacBudget]}です。`,
    riskJa,
    warningsJa,
    opportunitiesJa: [
      ...(gold > 0 ? ['金の比率はポートフォリオの値動きを和らげる役割があります。ただしリターン源というよりヘッジとして扱う方が自然です。'] : []),
      ...(tacBudget === 'underused' ? ['戦術枠に余裕があります。ただし使い切る必要はありません(見送りも選択肢)。'] : []),
      ...(fire === 'aligned' ? ['コア比率が確保できており、短期の分岐に振り回されにくい構成です。'] : []),
    ].slice(0, 3),
    stressNotesJa: noHold ? [] : [
      ...(ai >= 30 ? [`AI調整局面: AI関連約${Math.round(ai)}%が同時に下がる想定(個別の分散は効きにくい)`] : []),
      ...((pe.usdPct ?? 0) >= 40 ? ['円高/ドル安局面: 米国株・ドル資産の円建て評価が同方向に動く'] : []),
      ...(ddSens !== 'low' ? ['金利ショック: 高ベータ(AI/暗号資産)ほど下落感応度が高い'] : []),
      ...(tac > 0 ? ['イベント直後: 戦術枠の含み損益が最も振れやすい'] : []),
    ].slice(0, 4),
    fireWarningsJa: warningsJa.slice(0, 2),
    improveJa: [
      ...(fire === 'stretched' || fire === 'misaligned' ? ['コア(インデックス)比率の引き上げ、または戦術枠の縮小'] : []),
      ...(themeRisk === 'high' || themeRisk === 'critical' ? ['テーマ集中を上げない形での分散(現金/金/インデックス)'] : []),
      ...(!ctx.recurringAccumulationKnown ? ['毎月の積立額を入力すると長期整合の判定精度が上がります'] : []),
    ].slice(0, 3),
    nextChecksJa: [
      ...(tacBudget === 'stretched' || tacBudget === 'exceeded' ? ['戦術枠の比率が下がったか(次回スナップショット比較)'] : []),
      '積立(コア)の継続 — 個別株の判断とは独立に確認',
      'テーマ集中と1銘柄集中の週次確認',
    ].slice(0, 3),
    missingDataJa: [
      '現金比率(証券口座外の現金は未入力)',
      ...(!ctx.recurringAccumulationKnown ? ['毎月の積立額・入金力(未入力)'] : []),
      '住宅ローン・生活キャッシュフロー(未入力)',
      'NISA/iDeCo口座区分(未入力)',
      ...(pe.unpriced.length ? [`価格未取得${pe.unpriced.length}銘柄`] : []),
    ].slice(0, 5),
    roles, noHoldings: noHold,
  };
}

/** Pro Handoff / AI Review — device-local strategy lines. */
export function psHandoffTextJa(s: LocalStrategy | null): string {
  if (!s) return '';
  const L = ['## Portfolio Strategy / FIRE Alignment (device-local, 概算・助言ではない)'];
  L.push(s.summaryJa);
  L.push(`リスク予算: ${s.riskJa}`);
  for (const w of s.warningsJa) L.push(`- 警告: ${w}`);
  for (const o of s.opportunitiesJa.slice(0, 2)) L.push(`- 機会: ${o}`);
  if (s.missingDataJa.length) L.push(`不足データ: ${s.missingDataJa.slice(0, 3).join(' / ')}`);
  L.push('最強の反対view: この整合判定は入力済みデータのみに基づく概算であり、現金・入金力・ローン次第で結論が変わり得る。戦術枠の縮小が常に正しいわけでもない。');
  L.push(`注意: ${STRATEGY_COMPLIANCE_JA}`);
  return L.join('\n');
}

/** Today用 — 出すべき戦略警告があれば1行だけ返す(なければnull=非表示)。 */
export function todayStrategicNoteJa(s: LocalStrategy | null):
{ tone: string; textJa: string } | null {
  if (!s || s.noHoldings) return null;
  if (s.tacticalBudget === 'exceeded') {
    return { tone: 'var(--value-negative)', textJa: '戦略注意: 短期勝負枠が超過しています。新規追加よりも、既存ポジションの集中度とイベントリスクの確認が先です。' };
  }
  if (s.singleNameRisk === 'critical') {
    return { tone: 'var(--value-negative)', textJa: `戦略注意: 1銘柄(${jpDisplay(s.roles.find((r) => r.strategyFit === 'weak')?.symbol ?? '', undefined)})への集中が危険水準です。追加の前に比率確認を。` };
  }
  if (s.themeRisk === 'critical') {
    return { tone: 'var(--amber, #fbbf24)', textJa: `戦略注意: AI関連テーマが約${Math.round(s.aiThemePct)}%に集中。同時に下がる前提での比率確認が先です。` };
  }
  if (s.fireStatus === 'misaligned' || s.fireStatus === 'stretched') {
    return { tone: 'var(--amber, #fbbf24)', textJa: `戦略注意: FIRE整合が「${s.fireStatusJa}」です。個別株の判断とは別に、コア(積立)比率の確認を。` };
  }
  return null;
}
