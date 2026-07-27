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
const internal = require(path.join(__dirname, '..', 'src', 'domain', 'assetDeskInternal.ts'));

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
// 12. 未校正の確度は疑似精度を避け、定性的に表示
check('B12 confidence stays qualitative without calibration',
  view({}, {}).confidenceJa === '高' && view({}, {}).ai.confidenceJa === '高');
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
const flowPanel = fs.readFileSync(path.join(__dirname, '..', 'src', 'components', 'assetDesk', 'AssetFlowPanel.tsx'), 'utf8');
const chartPanel = fs.readFileSync(path.join(__dirname, '..', 'src', 'components', 'chart', 'ChartIntelligencePanel.tsx'), 'utf8');
const researchPanel = fs.readFileSync(path.join(__dirname, '..', 'src', 'components', 'assetDesk', 'AssetResearchPanel.tsx'), 'utf8');
check('D10b individual supply/demand numeric evidence remains visible',
  ['marginBuyingBalance', 'marginSellingBalance', 'lendingBorrowingRatio', 'marginBalanceChange',
    'volumeTrend', 'closeLocation', 'supplyDemandRank'].every((key) => flowPanel.includes(key)));
check('D10bb individual raw volume remains visible', flowPanel.includes('d.strat.volume'));
check('D10c individual turning points remain in Chart Intelligence', chartPanel.includes('最新転換点')
  && chartPanel.includes('turningPoints'));
check('D10d historical outcomes remain in Research & Notes', researchPanel.includes('outcomeReturn5d')
  && researchPanel.includes('結果待ち'));
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

// ── ④ Decision-first information architecture ───────────────────────────────
const decisionView = desk.buildDecisionFirstView({
  symbol: '5803', name: 'フジクラ', market: 'JP', held: true,
  signalCode: 'HOLD_ONLY', actionOverride: null, ownerLabel: '保有継続',
  priceText: '¥4,593', changePct: -2.83, pnlPct: -35.1,
  priority: 'P1', dataStatus: 'live', rank: 2,
  // HOLD/保有継続 is synonymous with the command and must be skipped.
  whyCandidates: ['HOLD', '決算前で需給の下げ止まりを未確認'],
  nextCandidates: ['様子見', '出来高を伴う支持帯回復を確認'],
  changeCandidates: ['25日線回復で再判定'],
});
check('E1 one normalized dominant command',
  decisionView.currentActionJa === '保有継続・買い増し禁止');
check('E2 synonymous HOLD conclusion is removed',
  decisionView.whyJa === '決算前で需給の下げ止まりを未確認');
check('E3 overview text fields stay bounded',
  [decisionView.whyJa, decisionView.nextJa, decisionView.whatChangesJa]
    .every((line) => line.length <= 70));
check('E4 closed row retains owner P/L, priority and data',
  decisionView.pnlPct === -35.1 && decisionView.priority === 'P1'
  && decisionView.dataStatus === 'live');
const command = desk.buildPortfolioCommand([decisionView]);
check('E5 page has one portfolio command with four counters',
  /^最優先：/.test(command.primaryCommandJa) && command.counters.length === 4);

const cardSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetDecisionCard.tsx'), 'utf8');
const summarySource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetDecisionSummary.tsx'), 'utf8');
const overviewSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetDecisionDetails.tsx'), 'utf8');
const downsideSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'dashboard', 'DownsideIncidentCard.tsx'), 'utf8');
const commandSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetPortfolioCommand.tsx'), 'utf8');
const listSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetDeskList.tsx'), 'utf8');
const evidenceSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetEvidenceSummary.tsx'), 'utf8');
const whySource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetWhyPanel.tsx'), 'utf8');
check('E6 detail sections are tab-gated and initially decision',
  cardSource.includes("useState<DeskTab>('decision')")
  && cardSource.includes("tab === 'chart'")
  && cardSource.includes("tab === 'evidence'")
  && (cardSource.match(/id: '(decision|chart|evidence|position)'/g) || []).length === 4);
check('E7 chart does not mount in closed or overview card',
  cardSource.indexOf('<ChartIntelligencePanel') > cardSource.indexOf("tab === 'chart'"));
check('E8 closed row is exactly two semantic lines',
  summarySource.includes('className=\"ad-l1\"') && summarySource.includes('className=\"ad-l2\"')
  && !summarySource.includes('ad-reason') && !summarySource.includes('ad-foot'));
check('E9 expanded default contains required decision fields',
  ['CURRENT ACTION', 'WHY NOW', 'NEXT CHECK', 'WHAT CHANGES IT']
    .every((label) => overviewSource.includes(label)));
check('E10 downside initial queue is bounded to four rows',
  downsideSource.includes('maxItems = 4') && downsideSource.includes('incidents.slice(0, maxItems)'));
check('E11 tabs expose keyboard navigation and ARIA contract',
  cardSource.includes('role=\"tablist\"') && cardSource.includes('role=\"tab\"')
  && cardSource.includes('ArrowRight') && cardSource.includes('aria-selected'));
check('E12 portfolio counters are exclusive accessible filters',
  commandSource.includes('aria-pressed={activeKey === counter.key}')
  && commandSource.includes('onClick={() => onSelect?.(counter.key)}'));
check('E12b sort and filter chips expose selected state',
  listSource.includes("aria-pressed={sortMode === 'priority'}")
  && listSource.includes("aria-pressed={sortMode === 'manual'}")
  && listSource.includes("aria-pressed={filter === 'all'}")
  && listSource.includes("aria-pressed={filter === 'risk'}")
  && listSource.includes("aria-pressed={filter === 'held'}"));
check('E13 evidence summary keeps explicit truth states',
  ['VERIFIED_FACT', 'SUPPORTED_HYPOTHESIS', 'UNRESOLVED', 'UNAVAILABLE', 'STALE', 'CONFLICT']
    .every((state) => evidenceSource.includes(state))
  && evidenceSource.includes('data-evidence-state={truth.state}'));
check('E14 research and raw evidence are secondary disclosures',
  cardSource.includes('className="ad-evidence-details"')
  && cardSource.includes('className="ad-research-drawer"'));
check('E15 chart turning points are semantically deduplicated',
  chartPanel.includes('uniqueTurningPoints(payload')
  && chartPanel.includes("fact.replace(/\\s+/g, ' ').trim()")
  && chartPanel.includes('if (seen.has(key)) return false'));
check('E16 unsupported Asset Why percentages are not rendered as probabilities',
  whySource.includes('probabilityDisplay')
  && !whySource.includes('Math.round(d.cause.confidence * 100)'));
check('E17 per-asset cards do not repeat the page disclaimer',
  !cardSource.includes('判断支援のみ。自動売買'));

// ── ⑤ Asset Desk internal function contract (PR B) ────────────────────────
const computedPosition = internal.buildAssetPositionView({
  held: true,
  quantity: 100,
  averageCost: 1200,
  currentPrice: 1500,
  portfolioConcentrationPct: 12.5,
  theme: 'AIインフラ',
  themeConcentrationPct: 28.4,
  eventLabels: ['EARNINGS D-2'],
  volume: 250000,
  ownerRiskLine: 1300,
  trimReviewCondition: '集中が25%を超えた場合',
});
check('F1 Position uses deterministic valuation math',
  computedPosition.currentValue === 150000
  && computedPosition.unrealizedPl === 30000
  && computedPosition.unrealizedPlPct === 25
  && Math.abs(computedPosition.breakEvenDistancePct - (-20)) < 0.0001);
check('F2 Position computes concentration and owner risk-line distance',
  computedPosition.portfolioConcentrationPct === 12.5
  && computedPosition.themeConcentrationPct === 28.4
  && Math.abs(computedPosition.ownerRiskLineDistancePct - (-13.3333333333)) < 0.0001);
check('F3 Position never manufactures unsupported metrics',
  computedPosition.supportDistancePct === null
  && computedPosition.unavailable.includes('支持線距離')
  && computedPosition.unavailable.includes('流動性判定')
  && computedPosition.unavailable.includes('追加余力'));

const supportedEvidence = internal.buildAssetEvidenceView({
  state: 'SUPPORTED_HYPOTHESIS',
  asOf: '2026-07-27T09:00:00+09:00',
  confirmed: ['指数比 -2.1%', '同業比 -1.2%', '出来高 250,000', '余分'],
  hypothesis: '決算前のポジション調整',
  contradicting: ['状態がCONFLICTでないため表示禁止'],
  missing: ['個別開示', '大口フロー', '余分'],
  nextInvestigation: 'TDnetを確認',
  sources: [
    { label: 'Market quote', asOf: '2026-07-27', freshness: 'current' },
    { label: 'Market quote', asOf: '2026-07-27', freshness: 'current' },
    { label: 'Supply / Demand', asOf: '2026-07-25', freshness: 'stale' },
  ],
});
check('F4 Evidence integrates verified/hypothesis/unresolved contract',
  supportedEvidence.truth.state === 'SUPPORTED_HYPOTHESIS'
  && supportedEvidence.truth.alternative === '決算前のポジション調整'
  && supportedEvidence.truth.confirmed.length === 3
  && supportedEvidence.truth.missing.length === 2);
check('F5 Evidence only exposes contradictions in CONFLICT state',
  supportedEvidence.contradicting.length === 0
  && internal.buildAssetEvidenceView({
    state: 'CONFLICT',
    contradicting: ['価格と開示時刻が矛盾'],
  }).contradicting.length === 1);
check('F6 Evidence sources require source and asOf and deduplicate',
  supportedEvidence.sources.length === 2
  && supportedEvidence.sources[0].freshness === 'current'
  && supportedEvidence.sources[1].freshness === 'stale');

const positionSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetPositionPanel.tsx'), 'utf8');
const scenarioSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'assetDesk', 'AssetScenarioPanel.tsx'), 'utf8');
const riskLineSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'lib',
  'assetRiskLine.ts'), 'utf8');
check('F7 Position does not repeat Decision conclusions',
  !positionSource.includes('readinessJa')
  && !positionSource.includes('currentStanceJa')
  && !positionSource.includes('summaryJa')
  && !positionSource.includes('hp.labelJa'));
check('F8 Scenarios are conditions inside Decision, not a primary tab',
  cardSource.includes('<AssetScenarioPanel d={d} />')
  && scenarioSource.includes('data-scenario-role="decision-conditions"')
  && !cardSource.includes("{ id: 'scenarios'"));
check('F9 Research and Data is explicitly a secondary utility',
  cardSource.includes('data-secondary-utility="research-data"')
  && !cardSource.includes("{ id: 'research'"));
check('F10 Decision owns no duplicate position valuation block',
  !overviewSource.includes('OWNER POSITION')
  && !overviewSource.includes('fmtMoney')
  && positionSource.includes('data-position-kind="computed"'));
check('F11 owner risk line remains device-local and has no network fallback',
  riskLineSource.includes('localStorage.getItem')
  && riskLineSource.includes('localStorage.setItem')
  && !riskLineSource.includes('fetch('));

if (failed) { console.error(`\nasset-desk behavioral tests: ${failed} FAILED`); process.exit(1); }
console.log('\nasset-desk behavioral tests: all passed');
