#!/usr/bin/env node
/* V12.2.12 — Asset Desk 行動テスト(実入出力検証・grepではない)。
   ①assessAi/mergeAiPrimary=AI主判定の12ケース(Todayと Asset Deskの判断一致の正本)
   ②resolveAssetDecision=カード表示ビュー(RULE TEMPORARY理由・source追跡)14ケース
   ③deskRank/sortDesk=デフォルト並びの決定論(順序不変)
   既存typescriptパッケージのrequire hookでTSを直接実行 — 新npm依存なし。 */
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');

require.extensions['.ts'] = (m, filename) => {
  const src = fs.readFileSync(filename, 'utf8');
  const out = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  m._compile(out, filename);
};

const dec = require(path.join(__dirname, '..', 'src', 'domain', 'assetDecision.ts'));
const desk = require(path.join(__dirname, '..', 'src', 'domain', 'assetDesk.ts'));

let failed = 0;
function check(name, cond) {
  if (cond) { console.log(`  ok  ${name}`); }
  else { failed++; console.error(`FAIL  ${name}`); }
}

const NOW = Date.parse('2026-07-16T10:00:00+09:00');
const rule = (o) => Object.assign({
  symbol: '7203', action: 'HOLD', reasonJa: 'ルール理由', nextConditionJa: 'ルール次条件',
  confidence: 0.55,
}, o);
const aiData = (o) => Object.assign({
  status: 'live', freshness: 'fresh', asOf: '2026-07-16T09:30:00+09:00',
  models: { primary: 'gpt-5.5', checker: 'gemini' },
  labels: [{ symbol: '7203', aiFinalAction: 'WAIT', reasonJa: 'AI理由', confidence: 0.7, aiView: 'caution', redFlags: ['過熱'] }],
}, o);

// ── ① AI主判定(12ケース) ──────────────────────────────────────────────────
// 1. live+fresh → AI主
check('A1 live+fresh => AI primary', dec.assessAi(aiData(), NOW).primary === true);
// 2. partial+persisted → AI主(従来条件そのまま)
check('A2 partial+persisted => AI primary',
  dec.assessAi(aiData({ status: 'partial', freshness: 'persisted' }), NOW).primary === true);
// 3. stale → ルール暫定+正確な理由
{ const m = dec.assessAi(aiData({ freshness: 'stale' }), NOW);
  check('A3 stale => rule temporary with reason',
    m.primary === false && /古い/.test(m.unavailableReasonJa || '')); }
// 4. mock status → ルール暫定
check('A4 mock status => not primary', dec.assessAi(aiData({ status: 'mock' }), NOW).primary === false);
// 5. disabled → ルール暫定
check('A5 disabled => not primary', dec.assessAi(aiData({ status: 'disabled' }), NOW).primary === false);
// 6. AIデータなし → rule_only+未取得理由(取得を保証できない=16:05を約束しない)
{ const m = dec.assessAi(null, NOW);
  check('A6 no ai data => rule_only + 未取得 + no promise',
    m.primary === false && m.freshness === 'rule_only'
    && /未取得/.test(m.unavailableReasonJa || '') && m.nextRunJa === null); }
// 7. 次回16:05はスケジュールが保証できる状態でのみ案内(状態別文言)
check('A7a no_cached_result => 16:05 promised + 未実行',
  (() => { const m = dec.assessAi(aiData({ status: 'no_cached_result' }), NOW);
    return /16:05/.test(m.nextRunJa || '') && /未実行/.test(m.unavailableReasonJa || ''); })());
check('A7b disabled => 無効化中 + no 16:05 promise',
  (() => { const m = dec.assessAi(aiData({ status: 'disabled' }), NOW);
    return m.nextRunJa === null && /無効化中/.test(m.unavailableReasonJa || ''); })());
check('A7c mock => 取得できません + no 16:05 promise',
  (() => { const m = dec.assessAi(aiData({ status: 'mock' }), NOW);
    return m.nextRunJa === null && /取得できません/.test(m.unavailableReasonJa || ''); })());
check('A7d stale => 16:05 promised (schedule real)',
  /16:05/.test(dec.assessAi(aiData({ freshness: 'stale' }), NOW).nextRunJa || ''));
// 8. AI主のとき対象銘柄はaction/理由/確度/sourceがAI側
{ const { labels } = dec.mergeAiPrimary(aiData(), [rule()], NOW);
  check('A8 merge swaps to AI action/reason/conf/source',
    labels[0].action === 'WAIT' && labels[0].reasonJa === 'AI理由'
    && labels[0].confidence === 0.7 && labels[0].judgmentSource === 'ai'
    && labels[0].aiReasonJa === 'AI理由'); }
// 9. AI主でも「その銘柄のAIラベルが無い」行はルールのまま
{ const { labels } = dec.mergeAiPrimary(aiData(), [rule({ symbol: '9984' })], NOW);
  check('A9 symbol without ai label stays rule',
    labels[0].judgmentSource === 'rule' && labels[0].action === 'HOLD' && labels[0].aiReasonJa === null); }
// 10. aiFinalAction空はAI主にしない
{ const d = aiData(); d.labels[0].aiFinalAction = '';
  const { labels } = dec.mergeAiPrimary(d, [rule()], NOW);
  check('A10 empty aiFinalAction stays rule', labels[0].judgmentSource === 'rule'); }
// 11. AI理由欠落: 表示文はルール理由へフォールバックするがaiReasonJaはnull(sourceを偽らない)
{ const d = aiData(); d.labels[0].reasonJa = '';
  const { labels } = dec.mergeAiPrimary(d, [rule()], NOW);
  check('A11 missing ai reason tracked (aiReasonJa=null, display falls back)',
    labels[0].judgmentSource === 'ai' && labels[0].aiReasonJa === null && labels[0].reasonJa === 'ルール理由'); }
// 12. stale時はマージ自体が発生しない(全行ルール)
{ const { labels, meta } = dec.mergeAiPrimary(aiData({ freshness: 'stale' }), [rule()], NOW);
  check('A12 stale => no swap at all', labels[0].judgmentSource === 'rule' && meta.freshness === 'stale'); }

// ── ①b Today/Asset Desk一致(同一入力→同一出力の純関数性) ────────────────────
{ const a = dec.mergeAiPrimary(aiData(), [rule()], NOW);
  const b = dec.mergeAiPrimary(aiData(), [rule()], NOW);
  check('C1 same inputs => identical judgment (Today vs Asset Desk)',
    JSON.stringify(a.labels) === JSON.stringify(b.labels)); }

// ── ② resolveAssetDecision(表示ビュー14ケース) ─────────────────────────────
function view(aiOpt, ruleOpt, symbolHasAi = true, mutate) {
  const d = aiOpt === null ? null : aiData(aiOpt);
  if (d && mutate) mutate(d);
  const rl = ruleOpt === null ? [] : [rule(ruleOpt)];
  const { labels, meta } = dec.mergeAiPrimary(d, rl, NOW);
  return dec.resolveAssetDecision({
    symbol: '7203', merged: labels[0], ruleLabel: rl[0],
    aiLabel: d?.labels?.find((l) => l.symbol === '7203'), meta, symbolHasAi,
  });
}
// 1. AI主 → AI PRIMARYタグ
check('B1 AI PRIMARY tag', view({}, {}).sourceTagEn === 'AI PRIMARY');
// 2. AI主 → sourceDetailにage
check('B2 source detail carries age', /分前|時間前/.test(view({}, {}).sourceDetailJa));
// 3. stale → RULE TEMPORARY+理由
{ const v = view({ freshness: 'stale' }, {});
  check('B3 stale => RULE TEMPORARY + reason',
    v.sourceTagEn === 'RULE TEMPORARY' && /古い/.test(v.sourceDetailJa)); }
// 4. AIなし → RULE TEMPORARY+未取得(取得を保証できないため16:05は約束しない)
{ const v = view(null, {});
  check('B4 no AI => RULE TEMPORARY + 未取得', v.sourceTagEn === 'RULE TEMPORARY' && /未取得/.test(v.sourceDetailJa)); }
// 5. AI主だが銘柄ラベルなし → 「この銘柄のAI判断なし」
{ const d = aiData(); d.labels = [{ symbol: '9984', aiFinalAction: 'HOLD', reasonJa: 'x', confidence: 0.5 }];
  const { labels, meta } = dec.mergeAiPrimary(d, [rule()], NOW);
  const v = dec.resolveAssetDecision({ symbol: '7203', merged: labels[0], ruleLabel: rule(),
    aiLabel: undefined, meta, symbolHasAi: false });
  check('B5 primary but symbol lacks ai => この銘柄のAI判断なし',
    v.sourceTagEn === 'RULE TEMPORARY' && /この銘柄のAI判断なし/.test(v.sourceDetailJa)); }
// 5b. 銘柄ラベルなしは「次回実行がこの銘柄を含む」保証がない → 16:05を約束しない
{ const d = aiData(); d.labels = [{ symbol: '9984', aiFinalAction: 'HOLD', reasonJa: 'x', confidence: 0.5 }];
  const { labels, meta } = dec.mergeAiPrimary(d, [rule()], NOW);
  const v = dec.resolveAssetDecision({ symbol: '7203', merged: labels[0], ruleLabel: rule(),
    aiLabel: undefined, meta, symbolHasAi: false });
  check('B5b symbol without ai label => no 16:05 promise', v.ai.nextRunJa === null); }
// 5c. AI最新+ルール判定行が未取得(コールド) → 「AI未実行」と偽らない
{ const { meta } = dec.mergeAiPrimary(aiData(), [], NOW);
  const v = dec.resolveAssetDecision({ symbol: '7203', merged: undefined, ruleLabel: undefined,
    aiLabel: aiData().labels[0], meta, symbolHasAi: true });
  check('B5c ai fresh but rule label cold => ルール判定ラベル未取得',
    v.sourceTagEn === 'RULE TEMPORARY' && /ルール判定ラベル未取得/.test(v.sourceDetailJa)); }
// 6. AI欄は非表示にならない: unavailable理由+nextRunが必ず入る
{ const v = view({ freshness: 'stale' }, {});
  check('B6 ai panel never silent (reason + next run)',
    !!v.ai.unavailableReasonJa && /16:05/.test(v.ai.nextRunJa)); }
// 7. AI理由欠落 → reasonMissing=true・ai.reasonJa=null(ルール理由を混ぜない)
{ const v = view({}, {}, true, (d) => { d.labels[0].reasonJa = ''; });
  check('B7 missing ai reason honest', v.ai.reasonMissing === true && v.ai.reasonJa === null); }
// 8. reasonSource追跡: AI理由ありはai
check('B8 reasonSource=ai', view({}, {}).reasonSource === 'ai');
// 9. reasonSource追跡: AI主でも理由欠落はrule
{ const v = view({}, {}, true, (d) => { d.labels[0].reasonJa = ''; });
  check('B9 reasonSource=rule when ai reason missing', v.reasonSource === 'rule'); }
// 10. AIとルールの不一致を明示
{ const v = view({}, { action: 'HOLD' });
  check('B10 disagreement string', v.rule.disagreementJa === 'AI=WAIT / ルール=HOLD'); }
// 11. 一致なら不一致表示なし
{ const v = view({}, { action: 'WAIT' });
  check('B11 no disagreement when equal', v.rule.disagreementJa === null); }
// 12. 確度は%整数
check('B12 confidence pct', view({}, {}).confidencePct === 70);
// 13. aiViewの語彙変換(caution)
check('B13 aiView vocab', view({}, {}).ai.viewJa === 'ルール判定より注意');
// 14. RULE CHECKにルール原文(action/理由/次条件)が残る
{ const v = view({}, {});
  check('B14 rule check keeps raw rule',
    v.rule.action === 'HOLD' && v.rule.reasonJa === 'ルール理由' && v.rule.nextConditionJa === 'ルール次条件'); }

// ── ③ deskRank/sortDesk(決定論・順序不変) ──────────────────────────────────
const ri = (o) => Object.assign({
  symbol: 'AAAA', genre: 'jp', held: false, signalCode: 'HOLD_ONLY', apRank: null,
  positionRiskLevel: null, hasIncident: false, aiRuleDisagree: false, eventSoon: false,
}, o);
check('D1 held EXIT first', desk.deskRank(ri({ held: true, signalCode: 'EXIT' })) === 0);
check('D2 held DEFEND first', desk.deskRank(ri({ held: true, signalCode: 'DEFEND' })) === 0);
check('D3 held P0', desk.deskRank(ri({ held: true, apRank: 'P0' })) === 1);
check('D4 held P1/high risk', desk.deskRank(ri({ held: true, apRank: 'P1' })) === 2
  && desk.deskRank(ri({ held: true, positionRiskLevel: 'critical' })) === 2);
check('D5 incident', desk.deskRank(ri({ hasIncident: true })) === 3);
check('D6 disagreement', desk.deskRank(ri({ aiRuleDisagree: true })) === 4);
check('D7 event proximity', desk.deskRank(ri({ eventSoon: true })) === 5);
check('D8 other held', desk.deskRank(ri({ held: true })) === 6);
check('D9 watch stocks then funds then crypto',
  desk.deskRank(ri({})) === 7 && desk.deskRank(ri({ genre: 'funds' })) === 8
  && desk.deskRank(ri({ genre: 'crypto' })) === 9);
// 非保有のEXIT/DEFENDは最上位に来ない(保有条件つき)
check('D10 non-held EXIT not rank0', desk.deskRank(ri({ signalCode: 'EXIT' })) !== 0);
// 順序不変: 入力順を入れ替えても同一出力
{ const items = [
    { rankInput: ri({ symbol: 'CCCC', genre: 'crypto' }) },
    { rankInput: ri({ symbol: 'BBBB', held: true, signalCode: 'EXIT' }) },
    { rankInput: ri({ symbol: 'AAAA', hasIncident: true }) },
    { rankInput: ri({ symbol: 'DDDD', held: true, signalCode: 'EXIT' }) },
  ];
  const a = desk.sortDesk(items).map((x) => x.rankInput.symbol);
  const b = desk.sortDesk(items.slice().reverse()).map((x) => x.rankInput.symbol);
  check('D11 order-invariant', JSON.stringify(a) === JSON.stringify(b));
  check('D12 rank then symbol', JSON.stringify(a) === JSON.stringify(['BBBB', 'DDDD', 'AAAA', 'CCCC'])); }

if (failed) { console.error(`\nasset-desk behavioral tests: ${failed} FAILED`); process.exit(1); }
console.log('\nasset-desk behavioral tests: all passed');
