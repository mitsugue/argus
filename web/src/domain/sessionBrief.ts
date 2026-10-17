// V11.13.0 — Session Brief (device-local TS port of argus_session_brief.py).
// 保有を加味したAPItem群から「今日の作戦」を端末内で合成する。売買指示ではない。

import type { APItem } from './actionPriority';
import { jpDisplay } from '../lib/displayName';
import {
  projectPlanningSession,
  type PlanningSessionAuthority,
} from './positionPlan';

export type OwnerMode = 'attack' | 'wait' | 'protect' | 'monitor' | 'review' | 'no_action' | 'unknown';
export const MODE_JA: Record<OwnerMode, string> = {
  attack: '攻める日', wait: '待つ日', protect: '守る日', monitor: '監視の日',
  review: '反省/記録の日', no_action: '対応不要の日', unknown: '判定保留',
};
export const MODE_TONE: Record<OwnerMode, string> = {
  attack: 'var(--value-positive)', wait: 'var(--amber, #fbbf24)',
  protect: 'var(--value-negative)', monitor: 'var(--text-muted)',
  review: 'var(--accent)', no_action: 'var(--text-faint)', unknown: 'var(--text-faint)',
};

export interface LocalBrief {
  sessionType: string;
  marketStatusJa: string;
  ownerMode: OwnerMode;
  ownerModeJa: string;
  headlineJa: string;
  bullets: string[];
  whatNotToDoJa: string[];
  nextChecksJa: string[];
  afterCloseReviewJa: string[];
  heldRiskLines: string[];
  confidence: number;
}

export type SessionBriefAuthority = PlanningSessionAuthority;

const FULL_CLOSE = new Set(['HOLIDAY_CLOSED', 'WEEKEND_CLOSED', 'EMERGENCY_CLOSED']);

/** Project the canonical server session contract into the global brief label.
 *
 * This function contains no exchange clock, offset, DST, holiday, or browser
 * fallback.  Both exchange projections must be currently verifiable; a stale
 * or partial authority is ``unknown`` and cannot turn a positive AP item into
 * an attack brief.
 */
export function resolveSessionJst(
  authority?: SessionBriefAuthority | null,
  evaluatedAtMs = Date.now(),
): { sessionType: string; marketStatusJa: string } {
  const jp = projectPlanningSession('JP', authority, evaluatedAtMs);
  const us = projectPlanningSession('US', authority, evaluatedAtMs);
  if (jp.state === 'unknown' || us.state === 'unknown') {
    return { sessionType: 'unknown', marketStatusJa: '市場セッション未確認' };
  }

  const jpSession = jp.canonicalSession;
  const usSession = us.canonicalSession;
  const jpMarketClosed = jp.state === 'closed' && jp.reason === 'market_closed'
    && jpSession != null && FULL_CLOSE.has(jpSession);
  const usMarketClosed = us.state === 'closed' && us.reason === 'market_closed'
    && usSession != null && FULL_CLOSE.has(usSession);

  if (jp.state === 'open') {
    return { sessionType: 'intraday', marketStatusJa: '東京ザラ場' };
  }
  if (jpSession === 'LUNCH_BREAK') {
    return { sessionType: 'lunch_break', marketStatusJa: '東京昼休み' };
  }
  if (us.state === 'open') {
    return { sessionType: 'intraday', marketStatusJa: jpMarketClosed ? '米国ザラ場（JP休場）' : '米国ザラ場' };
  }
  if (usSession === 'PRE_MARKET') {
    return { sessionType: 'morning', marketStatusJa: jpMarketClosed ? '米国プレマーケット（JP休場）' : '米国プレマーケット' };
  }
  if (usSession === 'AFTER_HOURS') {
    return { sessionType: 'after_close', marketStatusJa: jpMarketClosed ? '米国時間外（JP休場）' : '米国時間外' };
  }
  if (jpSession === 'PRE_MARKET') {
    return { sessionType: 'morning', marketStatusJa: '東京寄り前' };
  }
  if (jpMarketClosed && usMarketClosed) {
    return jpSession === 'WEEKEND_CLOSED' && usSession === 'WEEKEND_CLOSED'
      ? { sessionType: 'weekend', marketStatusJa: 'JP・US休場' }
      : { sessionType: 'holiday', marketStatusJa: 'JP・US休場' };
  }
  if (jpMarketClosed) {
    return { sessionType: 'holiday', marketStatusJa: 'JP休場・米国通常立会前' };
  }
  return { sessionType: 'after_close', marketStatusJa: '通常立会時間外' };
}

export function buildLocalBrief(items: APItem[], ctx: {
  eventNames?: string[]; riskOff?: boolean; missingDataJa?: string[];
  sessionAuthority?: SessionBriefAuthority | null;
}, evaluatedAtMs = Date.now()): LocalBrief {
  const { sessionType, marketStatusJa } = resolveSessionJst(
    ctx.sessionAuthority, evaluatedAtMs);
  const events = (ctx.eventNames ?? []).filter(Boolean);
  const p0 = items.filter((i) => i.priorityRank === 'P0');
  const p1 = items.filter((i) => i.priorityRank === 'P1');
  const heldRisks = items.filter((i) =>
    ['held_risk', 'flow_watch', 'supply_demand_watch'].includes(i.category) && i.isHeld);
  const avoid = items.filter((i) => i.category === 'avoid_chase');
  const rawAdds = items.filter((i) => ['add_candidate', 'add_only_on_pullback'].includes(i.category));
  const sessionBlocksOpportunity = ['lunch_break', 'after_close', 'holiday', 'weekend', 'unknown']
    .includes(sessionType);
  const adds = sessionBlocksOpportunity ? [] : rawAdds;
  const eventWait = items.filter((i) => i.blockingReason === 'event_pending');
  const dataMissing = items.filter((i) => i.category === 'data_missing');
  const nm = (i: APItem) => jpDisplay(i.symbol, i.assetName);

  let mode: OwnerMode;
  if (sessionType === 'unknown') {
    mode = p0.length ? 'protect'
      : heldRisks.length ? (heldRisks.some((i) => i.priorityRank === 'P1') ? 'protect' : 'monitor')
        : 'unknown';
  } else if (sessionType === 'weekend' || sessionType === 'holiday') mode = 'review';
  else if (sessionType === 'lunch_break' || sessionType === 'after_close') {
    mode = heldRisks.length ? (heldRisks.some((i) => i.priorityRank === 'P1') ? 'protect' : 'monitor') : 'monitor';
  }
  else if (p0.length) mode = 'protect';
  else if (events.length || eventWait.length) mode = 'wait';
  else if (heldRisks.length) mode = heldRisks.some((i) => i.priorityRank === 'P1') ? 'protect' : 'monitor';
  else if (ctx.riskOff) mode = 'monitor';
  else if (adds.length && !avoid.length) mode = adds.some((i) => i.category === 'add_candidate') ? 'attack' : 'monitor';
  else if (items.some((i) => i.priorityRank !== 'Ignore')) mode = 'monitor';
  else mode = 'no_action';

  const headlineJa = p0.length
    ? `最優先確認あり：${nm(p0[0])} — ${p0[0].whyJa.slice(0, 40)}`
    : sessionType === 'unknown'
      ? '市場セッションの正本を確認できないため、新規・追加判断は保留です。'
      : sessionType === 'holiday'
        ? '休場レビュー：取引所カレンダーは休場です。新規・追加判断は行いません。'
        : sessionType === 'lunch_break'
          ? '昼休み：後場の公式セッション確認まで新規・追加判断は保留です。'
      : sessionType === 'weekend'
    ? '週末レビュー：市場は休場です。新規判断より記録と確認の日。'
      : events.length
        ? `今日は${MODE_JA[mode]}。${events.slice(0, 2).join('/')}の結果を見てから動く日です。`
        : `今日は${MODE_JA[mode]}。P0(最優先)はありません。`;

  const bullets: string[] = [];
  if (sessionType === 'unknown') {
    for (const i of heldRisks.slice(0, 2)) bullets.push(`${nm(i)}：${i.whyJa.slice(0, 56)}`);
    bullets.push('市場セッションを確認できるまで、新規・追加候補は判断材料に使いません。');
    if ((ctx.missingDataJa ?? []).length) bullets.push(`データ不足: ${ctx.missingDataJa![0]}。`);
  } else if (sessionType === 'weekend' || sessionType === 'holiday') {
    bullets.push('今日は新規判断より、保有数量・取得単価・スナップショット同期の確認が優先です。');
    if (dataMissing.length) bullets.push(`データ未入力の保有銘柄が${dataMissing.length}件あります。`);
  } else if (sessionType === 'lunch_break' || sessionType === 'after_close') {
    for (const i of heldRisks.slice(0, 2)) bullets.push(`${nm(i)}：${i.whyJa.slice(0, 56)}`);
    bullets.push('公式セッションが新規・追加判断可能な状態ではないため、機会候補は保留します。');
  } else {
    for (const i of heldRisks.slice(0, 2)) bullets.push(`${nm(i)}：${i.whyJa.slice(0, 56)}`);
    if (events.length) bullets.push(`${events.slice(0, 2).join('/')}の発表前 — 関連銘柄の積極判断は結果確認後。`);
    for (const i of avoid.slice(0, 1)) bullets.push(`${nm(i)}は追いかけ買い注意(高値掴み/買い戻し主導の可能性)。`);
    for (const i of adds.slice(0, 1)) {
      bullets.push(`買い増し候補：${nm(i)}(${i.category === 'add_only_on_pullback' ? '押し目限定' : '小さく分けて'})。`);
    }
    if ((ctx.missingDataJa ?? []).length) bullets.push(`データ不足: ${ctx.missingDataJa![0]}。`);
    if (!bullets.length) bullets.push('大きな材料・需給変化・保有リスクはありません。定例の巡回で十分です。');
  }

  const whatNot: string[] = [];
  if (avoid.length) whatNot.push(`急伸中の${nm(avoid[0])}を追いかけて買わない`);
  if (events.length || eventWait.length) whatNot.push('イベント結果を見る前に買い増ししない');
  if (p0.length || heldRisks.length) whatNot.push('原因未確認のまま保有銘柄をナンピンしない');
  if (sessionType === 'unknown') whatNot.push('市場セッション未確認のまま新規・追加判断をしない');
  if (sessionType === 'weekend' || sessionType === 'holiday') whatNot.push('休場中の値動き予想で新規判断をしない');
  else if (sessionBlocksOpportunity) whatNot.push('公式セッション確認前に新規・買い増し判断をしない');
  if (!whatNot.length) whatNot.push('一度に大きく買わない(分割が基本)');

  const checks: string[] = [];
  for (const i of [...p0, ...p1].slice(0, 3)) checks.push(`${nm(i)}: ${i.checkNextJa.slice(0, 42)}`);
  if (sessionType === 'unknown') checks.unshift('公式カレンダー由来の市場セッションを再取得');
  if ((sessionType === 'weekend' || sessionType === 'holiday') && !checks.length) {
    checks.push('保有数量・取得単価の入力状態', 'バックアップ/スナップショットの最終日時');
  }
  if (!checks.length && events.length) checks.push(`${events[0]}の結果と直後の金利・指数反応`);
  if (!checks.length) checks.push('需給・フローの翌営業日更新');

  const afterClose: string[] = [];
  if (['after_close', 'intraday'].includes(sessionType)) {
    afterClose.push('今日動いた保有銘柄の理由を記録(Decision Qualityに自動記録)');
    if (avoid.length) afterClose.push(`${nm(avoid[0])}の終値位置(失速したか)を確認`);
  }

  let confidence = 0.6;
  if ((ctx.missingDataJa ?? []).length || dataMissing.length) confidence -= 0.1;
  if (sessionType === 'unknown') confidence -= 0.2;
  if (!items.length) confidence -= 0.1;

  return {
    sessionType, marketStatusJa, ownerMode: mode, ownerModeJa: MODE_JA[mode],
    headlineJa, bullets: bullets.slice(0, 5),
    whatNotToDoJa: whatNot.slice(0, 3), nextChecksJa: checks.slice(0, 4),
    afterCloseReviewJa: afterClose.slice(0, 3),
    heldRiskLines: heldRisks.slice(0, 4).map((i) => `${nm(i)}：${i.whyJa.slice(0, 56)}`),
    confidence: Math.max(0.2, Math.round(confidence * 100) / 100),
  };
}

/** Pro Handoff / AI Review — device-local held-aware brief lines. */
export function sbHandoffTextJa(b: LocalBrief | null): string {
  if (!b) return '';
  const L = ['## Session Brief (device-local, held-aware)',
    `モード: ${b.ownerModeJa}(${b.marketStatusJa}) — ${b.headlineJa}`,
    ...b.bullets.map((x) => `- ${x}`)];
  if (b.whatNotToDoJa.length) L.push(`やらないこと: ${b.whatNotToDoJa.join(' / ')}`);
  if (b.nextChecksJa.length) L.push(`次の確認: ${b.nextChecksJa.join(' / ')}`);
  L.push('注意: 今日の作戦メモであり売買指示ではない。');
  return L.join('\n');
}
