// V11.13.0 — Session Brief (device-local TS port of argus_session_brief.py).
// 保有を加味したAPItem群から「今日の作戦」を端末内で合成する。売買指示ではない。

import type { APItem } from './actionPriority';
import type { MarketCalendarState } from '../types/marketLedger';
import { jpDisplay } from '../lib/displayName';

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

export function resolveSessionJst(now = new Date(),
  calendar?: Record<string, MarketCalendarState>): { sessionType: string; marketStatusJa: string } {
  const jp = calendar?.JP;
  const us = calendar?.US;
  if (jp && us) {
    const jpOpen = ['MORNING_SESSION', 'AFTERNOON_SESSION'].includes(jp.session);
    if (jpOpen) return { sessionType: 'intraday', marketStatusJa: '東京ザラ場' };
    if (jp.session === 'LUNCH_BREAK') {
      return { sessionType: 'lunch_break', marketStatusJa: '東京昼休み' };
    }
    const jpClosed = !jp.isTradingDay;
    if (us.session === 'REGULAR') {
      return { sessionType: 'intraday', marketStatusJa: jpClosed ? '米国ザラ場（JP休場）' : '米国ザラ場' };
    }
    if (us.session === 'PRE_MARKET') {
      return { sessionType: 'morning', marketStatusJa: jpClosed ? '米国プレマーケット（JP休場）' : '米国プレマーケット' };
    }
    if (us.session === 'AFTER_HOURS') {
      return { sessionType: 'after_close', marketStatusJa: jpClosed ? '米国時間外（JP休場）' : '米国時間外' };
    }
    if (jpClosed && us.isTradingDay) {
      return { sessionType: 'holiday', marketStatusJa: 'JP休場・米国通常立会前' };
    }
    if (jpClosed && !us.isTradingDay) {
      return { sessionType: 'weekend', marketStatusJa: 'JP・US休場' };
    }
  }
  const jst = new Date(now.getTime() + 9 * 3600_000);
  const wd = jst.getUTCDay();           // 0=Sun
  const h = jst.getUTCHours();
  if (wd === 0 || wd === 6) return { sessionType: 'weekend', marketStatusJa: '休場(週末)' };
  if (h >= 9 && h < 16) return { sessionType: 'intraday', marketStatusJa: '東京ザラ場' };
  if (h >= 22 || h < 5) return { sessionType: 'intraday', marketStatusJa: '米国ザラ場' };
  if (h >= 5 && h < 9) return { sessionType: 'morning', marketStatusJa: '寄り前' };
  return { sessionType: 'after_close', marketStatusJa: '引け後' };
}

export function buildLocalBrief(items: APItem[], ctx: {
  eventNames?: string[]; riskOff?: boolean; missingDataJa?: string[];
  marketCalendar?: Record<string, MarketCalendarState>;
}, now = new Date()): LocalBrief {
  const { sessionType, marketStatusJa } = resolveSessionJst(now, ctx.marketCalendar);
  const events = (ctx.eventNames ?? []).filter(Boolean);
  const p0 = items.filter((i) => i.priorityRank === 'P0');
  const p1 = items.filter((i) => i.priorityRank === 'P1');
  const heldRisks = items.filter((i) =>
    ['held_risk', 'flow_watch', 'supply_demand_watch'].includes(i.category) && i.isHeld);
  const avoid = items.filter((i) => i.category === 'avoid_chase');
  const adds = items.filter((i) => ['add_candidate', 'add_only_on_pullback'].includes(i.category));
  const eventWait = items.filter((i) => i.blockingReason === 'event_pending');
  const dataMissing = items.filter((i) => i.category === 'data_missing');
  const nm = (i: APItem) => jpDisplay(i.symbol, i.assetName);

  let mode: OwnerMode;
  if (sessionType === 'weekend') mode = 'review';
  else if (p0.length) mode = 'protect';
  else if (events.length || eventWait.length) mode = 'wait';
  else if (heldRisks.length) mode = heldRisks.some((i) => i.priorityRank === 'P1') ? 'protect' : 'monitor';
  else if (ctx.riskOff) mode = 'monitor';
  else if (adds.length && !avoid.length) mode = adds.some((i) => i.category === 'add_candidate') ? 'attack' : 'monitor';
  else if (items.some((i) => i.priorityRank !== 'Ignore')) mode = 'monitor';
  else mode = 'no_action';

  const headlineJa = sessionType === 'weekend'
    ? '週末レビュー：市場は休場です。新規判断より記録と確認の日。'
    : p0.length
      ? `最優先確認あり：${nm(p0[0])} — ${p0[0].whyJa.slice(0, 40)}`
      : events.length
        ? `今日は${MODE_JA[mode]}。${events.slice(0, 2).join('/')}の結果を見てから動く日です。`
        : `今日は${MODE_JA[mode]}。P0(最優先)はありません。`;

  const bullets: string[] = [];
  if (sessionType === 'weekend') {
    bullets.push('今日は新規判断より、保有数量・取得単価・スナップショット同期の確認が優先です。');
    if (dataMissing.length) bullets.push(`データ未入力の保有銘柄が${dataMissing.length}件あります。`);
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
  if (sessionType === 'weekend') whatNot.push('休場中の値動き予想で新規判断をしない');
  if (!whatNot.length) whatNot.push('一度に大きく買わない(分割が基本)');

  const checks: string[] = [];
  for (const i of [...p0, ...p1].slice(0, 3)) checks.push(`${nm(i)}: ${i.checkNextJa.slice(0, 42)}`);
  if (sessionType === 'weekend' && !checks.length) {
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
