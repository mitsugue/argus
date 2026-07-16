#!/usr/bin/env node
/* V12.2.11 — buildTodayOverview の行動テスト(実入出力検証・grepではない)。
   既存のtypescriptパッケージでTSソースをその場でtranspileして実行する —
   新しいnpm依存関係なし。`npm run lint` から呼ばれ、失敗はビルド前に止める。 */
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');

// .ts require hook(CommonJS transpile — import typeは消える)
require.extensions['.ts'] = (m, filename) => {
  const src = fs.readFileSync(filename, 'utf8');
  const out = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  m._compile(out, filename);
};

const { buildTodayOverview } = require(path.join(__dirname, '..', 'src', 'domain', 'todayOverview.ts'));

let failed = 0;
function check(name, cond) {
  if (cond) { console.log(`  ok  ${name}`); }
  else { failed++; console.error(`FAIL  ${name}`); }
}

// ── fixtures ────────────────────────────────────────────────────────────────
function apItem(o) {
  return Object.assign({
    symbol: 'XXXX', market: 'JP', assetName: 'テスト',
    priorityRank: 'P2', priorityRankJa: '', priorityScore: 10,
    category: 'no_action', actionLabel: 'MONITOR', actionLabelJa: '監視継続',
    titleJa: '', whyJa: '理由テスト。二文目。', checkNextJa: '次を確認。',
    whatWouldChangeJa: '条件。', blockingReason: 'none', isHeld: false, confidence: 0.6,
  }, o);
}
function plan(o) {
  return Object.assign({
    symbol: 'XXXX', assetName: 'テスト', isHeld: true,
    planType: 'hold', currentStance: 'monitor', currentStanceJa: '監視継続',
    summaryJa: '概要。', whyJa: '計画理由。', entryConditionsJa: [], holdConditionsJa: [],
    trimReviewConditionsJa: [], invalidationJa: [], nextChecksJa: [], whatNotToDoJa: [],
    blockingReasons: [], holdModeJa: '', evidenceQuality: 'medium',
  }, o);
}
function exposure(o) {
  return Object.assign({
    aiThemePct: null, goldPct: null, cryptoPct: null, jpyPct: null, usdPct: null,
    top1Pct: null, top1Symbol: null, singleNameRisk: null, themeRisk: null,
    risks: [], notes: {}, regimeSummaryJa: '', headwinds: [], tailwinds: [],
    noHoldings: false, watchOnlyCount: 0, unpriced: [], provisionalNoteJa: null,
  }, o);
}
function base(o) {
  return Object.assign({
    sessionType: 'morning', marketStatusJa: '寄り前',
    prevJudgment: null, todayOverall: 'HOLD', todayPosture: 'MIXED',
    usdJpy: null, us10y: null, nextEvent: null,
    apItems: [], plans: [], brief: null,
    exposure: exposure({}), strategy: null, eventLinkedHeldSymbols: [],
  }, o);
}
const note = (sym, held) => ({ symbol: sym, name: sym, held });

// ── A. Action Queue ─────────────────────────────────────────────────────────
{
  // A1: 同一symbol・同一action・同一timing → 1件
  const r = buildTodayOverview(base({
    apItems: [
      apItem({ symbol: 'AAAA', isHeld: true, priorityRank: 'P1', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 50 }),
      apItem({ symbol: 'AAAA', isHeld: true, priorityRank: 'P1', actionLabel: 'REVIEW_POSITION', category: 'held_risk', priorityScore: 40 }),
    ],
  }));
  check('A1 same symbol+bucket+timing merged', r.actions.filter((a) => a.symbol === 'AAAA').length === 1);

  // A2: 同一symbol・同一意味でも NOW と IF は別件
  const r2 = buildTodayOverview(base({
    sessionType: 'intraday', marketStatusJa: '東京ザラ場',
    apItems: [apItem({ symbol: 'BBBB', isHeld: true, priorityRank: 'P0', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 90 })],
    plans: [plan({ symbol: 'BBBB', currentStance: 'risk_review', currentStanceJa: 'リスク確認が先' })],
  }));
  const bb = r2.actions.filter((a) => a.symbol === 'BBBB');
  check('A2 NOW and IF kept separate', bb.length === 2
    && bb.some((a) => a.timing === 'NOW') && bb.some((a) => a.timing === 'IF'));

  // A3: WAIT(イベント)とリスク点検が同一銘柄 — held/priority規則で両方・P0系が先
  const r3 = buildTodayOverview(base({
    apItems: [apItem({ symbol: 'CCCC', isHeld: true, priorityRank: 'P1', actionLabel: 'WAIT_EVENT', category: 'event', priorityScore: 60 })],
    plans: [plan({ symbol: 'CCCC', currentStance: 'trim_consideration', currentStanceJa: '一部利確を検討する局面' })],
  }));
  check('A3 held rules order (wait first, plan follows)',
    r3.actions[0].symbol === 'CCCC' && r3.actions[0].timing === 'NEXT');

  // A4: held P0 が非保有候補より先
  const r4 = buildTodayOverview(base({
    apItems: [
      apItem({ symbol: 'ZZZZ', isHeld: false, priorityRank: 'P1', actionLabel: 'AVOID_CHASE', category: 'avoid_chase', priorityScore: 99 }),
      apItem({ symbol: 'HHHH', isHeld: true, priorityRank: 'P0', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 80 }),
    ],
  }));
  check('A4 held P0 first', r4.actions[0].symbol === 'HHHH' && r4.actions[0].timing === 'NOW');

  // A5: 条件が異なるIF項目(別銘柄)を統合しない
  const r5 = buildTodayOverview(base({
    plans: [
      plan({ symbol: 'DDDD', currentStance: 'risk_review', trimReviewConditionsJa: ['条件A。'] }),
      plan({ symbol: 'EEEE', currentStance: 'trim_consideration', trimReviewConditionsJa: ['条件B。'] }),
    ],
  }));
  check('A5 distinct IF items kept', r5.actions.length === 2
    && new Set(r5.actions.map((a) => a.conditionJa)).size === 2);

  // A6: 上限3件
  const many = ['S1', 'S2', 'S3', 'S4', 'S5'].map((s, ix) =>
    apItem({ symbol: s, isHeld: true, priorityRank: 'P1', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 50 - ix }));
  check('A6 max 3', buildTodayOverview(base({ apItems: many })).actions.length === 3);

  // A7: 入力順を入れ替えても同一結果
  const inp = [
    apItem({ symbol: 'MMMM', isHeld: true, priorityRank: 'P1', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 30 }),
    apItem({ symbol: 'NNNN', isHeld: true, priorityRank: 'P0', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 90 }),
    apItem({ symbol: 'OOOO', isHeld: false, priorityRank: 'P1', actionLabel: 'AVOID_CHASE', category: 'avoid_chase', priorityScore: 70 }),
  ];
  const a = buildTodayOverview(base({ apItems: inp })).actions.map((x) => x.id).join(',');
  const b = buildTodayOverview(base({ apItems: [...inp].reverse() })).actions.map((x) => x.id).join(',');
  check('A7 order-invariant', a === b && a.length > 0);
}

// ── B. Your Exposure ────────────────────────────────────────────────────────
{
  const risks = [{ symbol: 'RRRR', riskLevel: 'high', riskType: 'concentration', whyJa: '集中。', checkNextJa: '' }];
  const exp = exposure({ notes: { HHHH: note('HHHH', true), RRRR: note('RRRR', true) }, risks });
  const r = buildTodayOverview(base({
    exposure: exp,
    apItems: [
      apItem({ symbol: 'HHHH', isHeld: true, priorityRank: 'P0', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 90, whyJa: 'P0理由。' }),
      apItem({ symbol: 'WWWW', isHeld: false, priorityRank: 'P1', actionLabel: 'AVOID_CHASE', category: 'avoid_chase', priorityScore: 95 }),
    ],
  }));
  check('B1 held P0 first', r.exposures[0].symbol === 'HHHH' && r.exposures[0].severityEn === 'HIGH');
  check('B2 high risk second', r.exposures[1] && r.exposures[1].symbol === 'RRRR');
  check('B3 non-held never a main item', !r.exposures.some((e) => e.symbol === 'WWWW'));

  // B4: 最大3件
  const manyRisks = ['R1', 'R2', 'R3', 'R4'].map((s) =>
    ({ symbol: s, riskLevel: 'high', riskType: 'x', whyJa: 'r。', checkNextJa: '' }));
  const r4 = buildTodayOverview(base({ exposure: exposure({ notes: {}, risks: manyRisks }) }));
  check('B4 max 3', r4.exposures.length === 3);

  // B5: 保有なし=静かな空状態(項目ゼロ)
  const r5 = buildTodayOverview(base({ exposure: exposure({ noHoldings: true }) }));
  check('B5 no holdings => empty', r5.exposures.length === 0);

  // B6: 同一銘柄の重複なし(AP P0とrisk両方に登場しても1回)
  const r6 = buildTodayOverview(base({
    exposure: exposure({ notes: { HHHH: note('HHHH', true) },
      risks: [{ symbol: 'HHHH', riskLevel: 'critical', riskType: 'x', whyJa: 'r。', checkNextJa: '' }] }),
    apItems: [apItem({ symbol: 'HHHH', isHeld: true, priorityRank: 'P0', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 90 })],
  }));
  check('B6 same symbol not duplicated', r6.exposures.filter((e) => e.symbol === 'HHHH').length === 1);
}

// ── C. Overnight Changes ────────────────────────────────────────────────────
{
  // C1: previousなし(NaN)では項目ごと出さない=矢印なし
  const r1 = buildTodayOverview(base({
    usdJpy: { latestValue: 150.1, previousValue: NaN, change: 0, latestDate: '2026-07-16', status: 'live' },
  }));
  check('C1 no baseline => no arrow row', !r1.changes.some((c) => c.kind === 'fx'));

  // C2: mock(非live)をliveのように表示しない
  const r2 = buildTodayOverview(base({
    usdJpy: { latestValue: 150.1, previousValue: 149.2, change: 0.9, latestDate: '2026-07-16', status: 'mock' },
  }));
  check('C2 non-live rates excluded', !r2.changes.some((c) => c.kind === 'fx'));

  // C3: timestampなしではas-ofを捏造しない
  const r3 = buildTodayOverview(base({
    usdJpy: { latestValue: 150.1, previousValue: 149.2, change: 0.9, latestDate: '', status: 'live' },
  }));
  const fx3 = r3.changes.find((c) => c.kind === 'fx');
  check('C3 no as-of fabrication', fx3 && fx3.asOfJa == null);

  // C4: 変化なし => 「大きな変化なし」1件
  const r4 = buildTodayOverview(base({}));
  check('C4 quiet state', r4.changes.length === 1 && r4.changes[0].kind === 'quiet');

  // C5: 最大4件
  const r5 = buildTodayOverview(base({
    prevJudgment: { date: '2026-07-15', overall: 'WAIT', posture: 'EVENT_WAIT' },
    todayOverall: 'HOLD', todayPosture: 'MIXED',
    usdJpy: { latestValue: 150.1, previousValue: 149.2, change: 0.9, latestDate: '2026-07-16', status: 'live' },
    us10y: { latestValue: 4.5, previousValue: 4.4, change: 0.1, latestDate: '2026-07-16', status: 'live' },
    nextEvent: { eventCode: 'CPI', title: 'US CPI', dateJa: '7/17', timeJa: '21:30 JST', daysUntil: 1, labelJa: '' },
  }));
  check('C5 max 4', r5.changes.length === 4);

  // C6: イベントは方向予測ではなくリスクウィンドウ表現
  const ev = r5.changes.find((c) => c.kind === 'event');
  check('C6 event = risk window (no direction words)', ev
    && /リスクウィンドウ|積極判断を控える/.test(ev.subJa || '')
    && !/(上昇|下落|上がる|下がる)/.test((ev.mainJa || '') + (ev.subJa || '')));
}

// ── D. Next Check ───────────────────────────────────────────────────────────
{
  // D1: 必ず1件(オブジェクト)
  const r1 = buildTodayOverview(base({}));
  check('D1 exactly one next check', !!r1.nextCheck && typeof r1.nextCheck.whenJa === 'string');

  // D2: held critical(P0)条件が最優先
  const r2 = buildTodayOverview(base({
    nextEvent: { eventCode: 'CPI', title: 'US CPI', dateJa: '7/17', timeJa: '21:30 JST', daysUntil: 1, labelJa: '' },
    apItems: [apItem({ symbol: 'HHHH', isHeld: true, priorityRank: 'P0', actionLabel: 'CHECK_NOW', category: 'held_risk', priorityScore: 90, checkNextJa: '出来高を確認。' })],
  }));
  check('D2 held condition wins', r2.nextCheck.source === 'held_condition'
    && r2.nextCheck.whatJa.includes('出来高'));

  // D3: 過去イベントは選ばれない(builderにはnextUpcomingEventの未来のみが渡る —
  //     nullなら別ソースへフォールバックすることを検証)
  const r3 = buildTodayOverview(base({ sessionType: 'after_close', marketStatusJa: '引け後', nextEvent: null }));
  check('D3 no past event fallback', r3.nextCheck.source !== 'event');

  // D4: 日付はあるが時刻不明のイベントを日時付きで表示しない(brief/定期へ)
  const r4 = buildTodayOverview(base({
    sessionType: 'after_close', marketStatusJa: '引け後',
    nextEvent: { eventCode: 'AUCTION', title: 'Auction', dateJa: '7/18', timeJa: '', daysUntil: 2, labelJa: '' },
  }));
  check('D4 time-unknown event not shown with time', r4.nextCheck.source !== 'event');

  // D5: 週末に「本日09:00」を生成しない
  const r5 = buildTodayOverview(base({ sessionType: 'weekend', marketStatusJa: '休場(週末)' }));
  check('D5 weekend no false 09:00 today', r5.nextCheck.source !== 'market_open'
    && !/^09:00 JST$/.test(r5.nextCheck.whenJa));

  // 16:05の定期フォールバックは対象(AI見解+自己採点)を明示する
  const r6 = buildTodayOverview(base({ sessionType: 'intraday', marketStatusJa: '東京ザラ場' }));
  check('D6 16:05 fallback names its target', r6.nextCheck.source !== 'routine'
    || (r6.nextCheck.whatJa.includes('AI') && r6.nextCheck.whatJa.includes('自己採点')));
}

if (failed) {
  console.error(`\ntoday-overview behavioral tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\ntoday-overview behavioral tests: all passed');
