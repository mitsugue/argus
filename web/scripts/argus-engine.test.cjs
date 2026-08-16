#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }, fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};
const { synthesizeArgusDecision, finalActionForScore } = require(path.join(__dirname, '..', 'src/domain/argusEngine.ts'));
const { buildArgusTodayView, buildTodayProjection: buildTodayProjectionRaw,
  buildTodayReview, selectTodayNews,
  selectAutoMarket, quoteDisplayLabel } = require(path.join(__dirname, '..', 'src/domain/argusTodayView.ts'));
const { evaluateProbabilityTruth } = require(path.join(__dirname, '..', 'src/domain/probabilityTruth.ts'));
let failed = 0;
function check(name, condition) { if (condition) console.log(`  ok  ${name}`); else { failed++; console.error(`FAIL  ${name}`); } }
const PROJECTION_NOW = Date.parse('2026-07-22T12:00:00Z');
const buildTodayProjection = (input, action, horizon = 5, nowMs = PROJECTION_NOW) =>
  buildTodayProjectionRaw(input, action, horizon, nowMs);

check('BUY/WAIT/SELL mapping', finalActionForScore(1) === 'SELL' && finalActionForScore(2) === 'SELL'
  && finalActionForScore(3) === 'WAIT' && finalActionForScore(6) === 'WAIT' && finalActionForScore(7) === 'BUY');
const base = { market: 'JP', baseSignal: 'ENTER', confidence: .9, dataQuality: 'LIVE', calculatedAt: '2026-07-22T00:00:00Z' };
check('closing window is integrated', synthesizeArgusDecision({ ...base, closingWindowSignal: 'PAUSE' }).finalAction === 'WAIT');
check('owner policy only constrains', synthesizeArgusDecision({ ...base, ownerPolicyLimit: 'DEFEND' }).finalAction === 'SELL'
  && synthesizeArgusDecision({ ...base, baseSignal: 'DEFEND', ownerPolicyLimit: 'ENTER' }).finalAction === 'SELL');
check('data quality caps confidence', synthesizeArgusDecision({ ...base, dataQuality: 'PARTIAL' }).confidence === .6);
check('event hard veto', synthesizeArgusDecision({ ...base, eventHardVeto: true }).finalAction === 'WAIT');
check('deterministic', JSON.stringify(synthesizeArgusDecision(base)) === JSON.stringify(synthesizeArgusDecision(base)));

const CAL_NOW = Date.parse('2026-07-22T00:00:00Z');
const state = (market, session, trading = true, next = '2026-07-23') => ({
  market: market === 'JP' ? 'JP_EQUITY' : 'US_EQUITY',
  marketDate: '2026-07-22', isTradingDay: trading, session,
  holidayName: trading ? null : 'Holiday', nextTradingDay: next, timezone: market === 'JP' ? 'Asia/Tokyo' : 'America/New_York',
  calendarVersion: 'argus-market-calendar-2026.2',
  officialCalendar: market === 'JP' ? 'JPX_TSE' : 'NYSE_NASDAQ',
  sessionObservedAt: '2026-07-21T23:55:00Z', sessionValidUntil: '2026-07-22T00:15:00Z' });
const autoMarket = (calendar) => selectAutoMarket(calendar, CAL_NOW);
check('AUTO JP open', autoMarket({ JP: state('JP', 'MORNING_SESSION'), US: state('US', 'PRE_MARKET') }) === 'JP');
check('AUTO JP lunch', autoMarket({ JP: state('JP', 'LUNCH_BREAK'), US: state('US', 'CLOSED') }) === 'JP');
check('AUTO JP holiday + US pre', autoMarket({ JP: state('JP', 'HOLIDAY_CLOSED', false), US: state('US', 'PRE_MARKET') }) === 'US');
check('AUTO US holiday + JP pre', autoMarket({ JP: state('JP', 'PRE_MARKET'), US: state('US', 'HOLIDAY_CLOSED', false) }) === 'JP');
check('AUTO US open', autoMarket({ JP: state('JP', 'CLOSED'), US: state('US', 'REGULAR') }) === 'US');
check('AUTO US after => next JP', autoMarket({ JP: state('JP', 'CLOSED'), US: state('US', 'AFTER_HOURS') }) === 'JP');
check('AUTO JP/US outside-regular uses next session', autoMarket({ JP: state('JP', 'POST_MARKET', true, '2026-07-24'), US: state('US', 'OVERNIGHT_CLOSED', true, '2026-07-23') }) === 'US');
check('AUTO uses calendar-normalized DST session', autoMarket({ JP: state('JP', 'CLOSED'),
  US: { ...state('US', 'PRE_MARKET'), timezone: 'America/New_York', regularOpenJst: '2026-07-22T22:30:00+09:00' } }) === 'US');
check('AUTO respects early-close regular session', autoMarket({ JP: state('JP', 'CLOSED'),
  US: { ...state('US', 'REGULAR'), earlyClose: true, regularCloseJst: '2026-11-28T03:00:00+09:00' } }) === 'US');
check('AUTO holidays use next date', autoMarket({ JP: state('JP', 'HOLIDAY_CLOSED', false, '2026-07-24'), US: state('US', 'HOLIDAY_CLOSED', false, '2026-07-23') }) === 'US');
check('expired MORNING session cannot remain active',
  (() => { const expiredView = buildArgusTodayView({ now: new Date('2026-07-22T00:15:00Z'), selectionMode: 'AUTO',
    calendar: { JP: state('JP', 'MORNING_SESSION'), US: state('US', 'REGULAR') },
    baseSignal: 'ENTER', confidence: .8, dataQuality: 'LIVE' });
  return expiredView.finalAction === 'WAIT'
    && expiredView.sessionLamps.every((lamp) => lamp.key === 'FX' || lamp.key === 'CRYPTO' || !lamp.active); })());

const view = buildArgusTodayView({ now: new Date('2026-07-22T00:00:00Z'), selectionMode: 'AUTO',
  calendar: { JP: state('JP', 'MORNING_SESSION'), US: state('US', 'CLOSED') },
  baseSignal: 'ENTER', jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8, dataQuality: 'LIVE',
  events: [1,2,3,4,5].map((n) => ({ id: String(n), code: `E${n}`, title: `Event ${n}`,
    at: `2026-07-${22+n}T00:00:00Z`, impact: 'high' })),
  positioning: { JP: [1,2,3,4,5,6].map((n) => ({ key: String(n), label: String(n), value: n === 6 ? '—' : '↑' })) },
  attention: [1,2,3,4].map((n) => ({ id: String(n), label: String(n), severity: n })),
  holdings: [{ symbol: 'AAA', name: 'A', rank: 2, reasonJa: 'x', statusJa: '監視' },
    { symbol: 'AAA', name: 'A', rank: 1, reasonJa: 'y', statusJa: '要確認' },
    { symbol: 'BBB', name: 'B', rank: 3, reasonJa: 'z', statusJa: '監視' }],
  indexMoves: [1,2,3,4,5].map((n) => ({ id: `i${n}`, label: `${n}`, value: n })),
  macroMoves: [1,2,3,4].map((n) => ({ id: `m${n}`, label: n === 3 ? 'VIX' : `${n}`, value: n })),
});
check('JP/US decisions independent', view.decisions.JP.finalAction === 'WAIT' && view.decisions.US.finalAction === 'SELL');
check('one selected final decision', view.finalAction === 'WAIT' && view.selectedMarket === 'JP');
check('COMING 30D max 3', view.comingEvents.length === 3);
check('positioning max 5', view.positioning.length === 5);
check('index and macro cards have independent limits', view.indexMoves.length === 4
  && view.macroMoves.length === 3 && view.macroMoves.some((row) => row.label === 'VIX'));
check('Attention max 3', view.attention.length === 3);
check('NEXT EVENT is not duplicated in Attention', !view.attention.some((row) => row.id === view.nextEvent?.id));
check('holdings max 3 and deduped', view.holdingsReview.length === 2 && view.holdingsReview[0].reasonJa === 'y');
check('FIRE is outside the Today view contract', !Object.prototype.hasOwnProperty.call(view, 'fireProgress'));
check('footer mirrors decision', view.footerText.startsWith('JP WAIT 6/7'));
const manual = buildArgusTodayView({ ...view, now: new Date('2026-07-22T00:00:00Z'), selectionMode: 'US', baseSignal: 'ENTER',
  jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8, dataQuality: 'LIVE' });
check('manual US selection', manual.selectedMarket === 'US' && manual.finalAction === 'SELL');
check('manual JP selection', buildArgusTodayView({ ...manual, now: new Date('2026-07-22T00:00:00Z'),
  selectionMode: 'JP', baseSignal: 'ENTER', jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8,
  dataQuality: 'LIVE' }).selectedMarket === 'JP');
check('AUTO return', buildArgusTodayView({ ...manual, now: new Date('2026-07-22T00:00:00Z'), selectionMode: 'AUTO',
  baseSignal: 'ENTER', jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8, dataQuality: 'LIVE',
  calendar: { JP: state('JP', 'MORNING_SESSION'), US: state('US', 'CLOSED') } }).selectedMarket === 'JP');

const bars = Array.from({ length: 25 }, (_, index) => ({ date: `2026-06-${String(index + 1).padStart(2, '0')}`,
  close: 100 + index, atr14: 2 }));
const projection = buildTodayProjection({ symbol: '1321', label: '日経225 ETF', asOf: '2026-07-21', status: 'live', bars,
  zones: [{ center: 95, lower: 94, upper: 96, status: 'active' }, { center: 130, lower: 129, upper: 131, status: 'active' }] }, 'WAIT');
check('projection uses real bars and deterministic zones', projection?.current === 124 && projection.baseLow === 122
  && projection.baseHigh === 126 && projection.upside === 130 && projection.downside === 95);
check('projection levels cannot invert', projection.downside < projection.baseLow && projection.baseHigh < projection.upside);
check('projection does not fabricate probability', projection?.directionProbabilities === null && projection.confidenceLabel === '中');
check('projection identifies timeframe, state and source coverage', projection?.timeframeLabel === '日足'
  && projection.quoteState === 'CLOSE' && projection.sourceHistoryCount === 25);
check('quote time semantics never call prior close current', quoteDisplayLabel('CLOSE') === '終値'
  && quoteDisplayLabel('D20') === '現在 D20' && quoteDisplayLabel('RT') === '現在 RT'
  && quoteDisplayLabel('STALE') === '最終値 STALE');
const d20Projection = buildTodayProjection({ symbol: '1321', label: '日経225 ETF',
  asOf: '2026-07-22T10:20:00+09:00', status: 'live', quoteState: 'D20', bars, zones: [] }, 'WAIT');
check('D20 is displayed only from an explicit authoritative state',
  d20Projection?.quoteState === 'D20' && quoteDisplayLabel(d20Projection.quoteState) === '現在 D20');
check('legacy delayed state is not promoted to D20',
  buildTodayProjection({ symbol: '1321', label: 'x', asOf: '2026-07-22',
    status: 'delayed', bars, zones: [] }, 'WAIT')?.quoteState === 'CLOSE');
check('projection refuses insufficient history', buildTodayProjection({ symbol: '1321', label: 'x', asOf: null,
  status: 'live', bars: bars.slice(0, 5), zones: [] }, 'WAIT') === null);
const reclaimedProjection = buildTodayProjection({ symbol: '1321', label: '日経225 ETF',
  asOf: '2026-07-21', status: 'live', bars,
  zones: [{ id: 'broken', center: 122, lower: 121, upper: 123, status: 'broken' },
    { id: 'reclaimed', center: 120, lower: 119, upper: 121, status: 'reclaimed' },
    { id: 'crossing', center: 125, lower: 123, upper: 127, status: 'active' },
    { id: 'resistance', center: 130, lower: 129, upper: 131, status: 'active' }] }, 'WAIT');
check('zone roles are price-relative and reclaimed becomes support', reclaimedProjection.support.status === 'reclaimed'
  && reclaimedProjection.support.high < reclaimedProjection.current
  && reclaimedProjection.resistance.low > reclaimedProjection.current
  && !reclaimedProjection.supportResistanceIds.includes('broken')
  && !reclaimedProjection.supportResistanceIds.includes('crossing'));
const calibratedInput = { symbol: 'SPY', instrumentId: 'US:SPY:ETF', label: 'S&P 500 ETF（SPY）',
  asOf: '2026-07-22', status: 'live', timeframe: 'daily', quoteState: 'close', bars, zones: [],
  calibration: { historyCount: 1338, calibrationVersion: 'beta-dirichlet-walk-forward-v2', horizons: {
    '5': { horizon: 5, rawOccurrenceCount: 64, episodeCount: 38, effectiveSampleCount: 38,
      calibrationStatus: 'calibrated', probabilities: { UP: 28, RANGE: 51, DOWN: 21 },
      directionProbabilities: { UP: 28, RANGE: 51, DOWN: 21 },
      calibrationIntegrity: 'PASS', modelBrier: .54, baselineBrier: .6, brierSkill: .1,
      probabilityEligibility: { eligible: true, reasonCodes: [], effectiveSample: 38,
        modelBrier: .54, baselineBrier: .6, brierSkill: .1, calibrationIntegrity: 'PASS',
        probabilitySum: 100, calibrationVersion: 'beta-dirichlet-walk-forward-v2',
        datasetHash: 'fixture', evaluatedAt: '2026-07-22T00:00:00Z',
        contractVersion: 'probability-eligibility-v1' },
      confidenceInterval: { UP: { low: 18, high: 39 } }, averageReactionDelay: 2.6,
      returnDistribution: { q10: -.08, q25: -.02, median: .01, q75: .04, q90: .09, meanMfe: .03, meanMae: -.02 },
      expectedValue: { horizon: 5, expectedReturn: .01, medianReturn: .01, q10: -.08, q90: .09,
        expectedUpside: .03, expectedDownside: .02, rewardRisk: 1.5 },
      levelProbabilities: { upperTargetTouch: 24, baseRangeClose: 55, lowerTargetTouch: 21, invalidationTouch: 16 } },
  } } };
const calibratedProjection = buildTodayProjection(calibratedInput, 'WAIT');
check('legacy server eligibility alone cannot expose exact probability',
  calibratedProjection.instrumentId === 'US:SPY:ETF'
  && calibratedProjection.directionProbabilities === null
  && calibratedProjection.referenceDirectionProbabilities.RANGE === 51
  && calibratedProjection.probabilityTruth.label === 'EXPERIMENTAL'
  && calibratedProjection.probabilityTruth.directionalLean === 'RANGE'
  && calibratedProjection.effectiveSampleCount === 38 && calibratedProjection.modelBrier === .54);
check('level touch and close-in-band remain distinct', calibratedProjection.levelProbabilities.upperTargetTouch === 24
  && calibratedProjection.levelProbabilities.baseRangeClose === 55);
const uncalibrated = buildTodayProjection({ ...calibratedInput, calibration: { ...calibratedInput.calibration,
  horizons: { '5': { ...calibratedInput.calibration.horizons['5'], calibrationStatus: 'insufficient_sample',
    effectiveSampleCount: 29, probabilities: null, directionProbabilities: null,
    probabilityEligibility: { ...calibratedInput.calibration.horizons['5'].probabilityEligibility,
      eligible: false, reasonCodes: ['effective_sample_below_30'], effectiveSample: 29 } } } } }, 'WAIT');
check('missing probability remains hidden', uncalibrated.directionProbabilities === null
  && uncalibrated.referenceDirectionProbabilities === null
  && uncalibrated.effectiveSampleCount === 29);
const backendReference = buildTodayProjection({ ...calibratedInput, calibration: { ...calibratedInput.calibration,
  horizons: { '5': { ...calibratedInput.calibration.horizons['5'],
    probabilities: null, directionProbabilities: null,
    referenceDirectionProbabilities: { UP: 28, RANGE: 51, DOWN: 21 },
    probabilityEligibility: { ...calibratedInput.calibration.horizons['5'].probabilityEligibility,
      eligible: false, reasonCodes: ['brier_skill_non_positive'], brierSkill: 0 } } } } }, 'WAIT');
check('backend reference vector renders percentages without becoming verified',
  backendReference.directionProbabilities === null
  && backendReference.referenceDirectionProbabilities.RANGE === 51
  && backendReference.probabilityTruth.exactPercentageAllowed === false);
const weakSkill = buildTodayProjection({ ...calibratedInput, calibration: { ...calibratedInput.calibration,
  horizons: { '5': { ...calibratedInput.calibration.horizons['5'], brierSkill: 0,
    probabilityEligibility: { ...calibratedInput.calibration.horizons['5'].probabilityEligibility,
      eligible: false, reasonCodes: ['brier_skill_non_positive'], brierSkill: 0 } } } } }, 'WAIT');
check('BSS zero hides probability', weakSkill.directionProbabilities === null);
check('BSS zero is visibly reference-only and never verified',
  weakSkill.referenceDirectionProbabilities.RANGE === 51
  && weakSkill.probabilityTruth.exactPercentageAllowed === false);
const strictEvidence = {
  serverEligible: true, oosEffectiveN: 140, ruleEffectiveN: 80,
  holdouts: [
    { start: '2022-01-01', end: '2023-12-31', brierSkill: .07 },
    { start: '2024-01-01', end: '2025-12-31', brierSkill: .06 },
  ],
  beatsUnconditional: true, beatsMomentum: true, wilsonHalfWidthPt: 8.4,
  ece: .04, breadthLagTradingDays: 1, unresolvedPartitionCount: 0, duplicateCount: 0,
};
check('strict truth gate exposes exact probability only when every condition passes',
  evaluateProbabilityTruth(strictEvidence, { UP: 49, RANGE: 29, DOWN: 22 }).exactPercentageAllowed === true
  && evaluateProbabilityTruth({ ...strictEvidence, duplicateCount: 1 },
    { UP: 49, RANGE: 29, DOWN: 22 }).exactPercentageAllowed === false);
const upPluralityInput = { ...calibratedInput, calibration: { ...calibratedInput.calibration,
  horizons: { '5': { ...calibratedInput.calibration.horizons['5'],
    effectiveSampleCount: 140, episodeCount: 80, probabilityTruthEvidence: strictEvidence,
    probabilities: { UP: 49, RANGE: 29, DOWN: 22 },
    directionProbabilities: { UP: 49, RANGE: 29, DOWN: 22 } } } } };
const upPluralityView = buildArgusTodayView({ now: new Date('2026-07-22T00:00:00Z'),
  selectionMode: 'JP', baseSignal: 'PREPARE', jpSignal: 'PREPARE', confidence: .8,
  dataQuality: 'LIVE', projection: { JP: upPluralityInput } });
check('UP 49/RANGE 29/DOWN 22 never maps WAIT to BUY',
  upPluralityView.finalAction === 'WAIT'
  && upPluralityView.directionProbabilities.UP === 49);

check('pure projection boundary rejects ancient/future/malformed asOf',
  buildTodayProjection({ ...calibratedInput, asOf: '2020-01-01' }, 'WAIT') === null
  && buildTodayProjection({ ...calibratedInput, asOf: '2026-07-23' }, 'WAIT') === null
  && buildTodayProjection({ ...calibratedInput, asOf: '2026-02-30' }, 'WAIT') === null);
const buyProjectionInput = { ...upPluralityInput, authorityState: 'current',
  calibration: { ...upPluralityInput.calibration, horizons: {
    '5': { ...upPluralityInput.calibration.horizons['5'],
      expectedValue: { ...upPluralityInput.calibration.horizons['5'].expectedValue,
        q10: -.07 } },
  } } };
const buyWithCurrentProjection = buildArgusTodayView({ now: new Date('2026-07-22T00:00:00Z'),
  selectionMode: 'JP', baseSignal: 'ENTER', jpSignal: 'ENTER', confidence: .8,
  dataQuality: 'LIVE', calendar: { JP: state('JP', 'MORNING_SESSION') },
  projection: { JP: buyProjectionInput } });
const buyWithStaleProjection = buildArgusTodayView({ now: new Date('2026-07-22T00:00:00Z'),
  selectionMode: 'JP', baseSignal: 'ENTER', jpSignal: 'ENTER', confidence: .8,
  dataQuality: 'LIVE', calendar: { JP: state('JP', 'MORNING_SESSION') },
  projection: { JP: { ...buyProjectionInput, authorityState: 'stale' } } });
check('stale-cache projection cannot preserve BUY authority',
  buyWithCurrentProjection.finalAction === 'BUY'
  && buyWithStaleProjection.finalAction === 'WAIT'
  && buyWithStaleProjection.projection === null);

const todayWithSession = (market, session, trading = true, signal = 'ENTER') =>
  buildArgusTodayView({ now: new Date(CAL_NOW), selectionMode: market,
    baseSignal: signal, jpSignal: signal, usSignal: signal, confidence: .8,
    dataQuality: 'LIVE', calendar: { [market]: state(market, session, trading) },
    projection: { [market]: buyProjectionInput } });
const positiveSessionVetoed = (market, session, trading = true) => {
  const result = todayWithSession(market, session, trading);
  return result.finalAction === 'WAIT'
    && result.decisions[market].internalAction === 'PAUSE'
    && result.permissions.newEntry === false
    && result.permissions.add === false;
};
check('canonical JP holiday and lunch veto Today entry/add',
  positiveSessionVetoed('JP', 'HOLIDAY_CLOSED', false)
  && positiveSessionVetoed('JP', 'LUNCH_BREAK'));
check('canonical closed/post/after-hours/overnight sessions veto Today entry/add',
  positiveSessionVetoed('JP', 'POST_MARKET')
  && positiveSessionVetoed('JP', 'CLOSED')
  && positiveSessionVetoed('US', 'HOLIDAY_CLOSED', false)
  && positiveSessionVetoed('US', 'AFTER_HOURS')
  && positiveSessionVetoed('US', 'OVERNIGHT_CLOSED')
  && positiveSessionVetoed('US', 'CLOSED'));
const regularSessionBuy = todayWithSession('US', 'REGULAR');
check('canonical US regular session preserves otherwise-valid Today BUY authority',
  regularSessionBuy.finalAction === 'BUY'
  && regularSessionBuy.decisions.US.internalAction === 'ENTER'
  && regularSessionBuy.permissions.newEntry === true
  && regularSessionBuy.permissions.add === true);
const afterHoursDefend = todayWithSession('US', 'AFTER_HOURS', true, 'DEFEND');
check('closed session preserves defensive held-position risk action',
  afterHoursDefend.finalAction === 'SELL'
  && afterHoursDefend.decisions.US.internalAction === 'DEFEND'
  && afterHoursDefend.permissions.hold === true);
const forgedOpenInput = { now: new Date(CAL_NOW), selectionMode: 'JP',
  baseSignal: 'ENTER', jpSignal: 'ENTER', confidence: .8, dataQuality: 'LIVE',
  projection: { JP: buyProjectionInput } };
const freshButShapeless = buildArgusTodayView({ ...forgedOpenInput, calendar: { JP: {
  isTradingDay: true, session: 'MORNING_SESSION',
  sessionObservedAt: '2026-07-21T23:55:00Z', sessionValidUntil: '2026-07-22T00:15:00Z',
} } });
const wrongMarketOpen = buildArgusTodayView({ ...forgedOpenInput, calendar: { JP: {
  ...state('JP', 'MORNING_SESSION'), market: 'US_EQUITY',
} } });
const wrongTimezoneOpen = buildArgusTodayView({ ...forgedOpenInput, calendar: { JP: {
  ...state('JP', 'MORNING_SESSION'), timezone: 'America/New_York',
} } });
const wrongCalendarOpen = buildArgusTodayView({ ...forgedOpenInput, calendar: { JP: {
  ...state('JP', 'MORNING_SESSION'), officialCalendar: 'NYSE_NASDAQ',
} } });
const missingVersionOpen = buildArgusTodayView({ ...forgedOpenInput, calendar: { JP: {
  ...state('JP', 'MORNING_SESSION'), calendarVersion: '',
} } });
check('fresh forged open session cannot authorize Today entry/add',
  [freshButShapeless, wrongMarketOpen, wrongTimezoneOpen, wrongCalendarOpen,
    missingVersionOpen].every((result) => result.finalAction === 'WAIT'
    && result.decisions.JP.internalAction === 'PAUSE'
    && result.permissions.newEntry === false
    && result.permissions.add === false));

const reviewBars = [{ date: '2026-07-20', close: 100 }, { date: '2026-07-21', close: 101.4 }];
const matureReview = buildTodayReview(reviewBars, '日経225 ETF（1321）', 'WAIT', '2026-07-20');
check('previous decision uses matching instrument and one-day horizon', matureReview.marketLabel.includes('1321')
  && matureReview.horizon === '翌1営業日' && matureReview.returnPct === 1.4 && matureReview.outcomeDate === '2026-07-21');
const pendingReview = buildTodayReview(reviewBars, '日経225 ETF（1321）', 'WAIT', '2026-07-21');
check('immature previous decision never fabricates +0.00', !pendingReview.matured
  && pendingReview.returnPct === null && pendingReview.evaluationJa === '答え合わせ待ち');
check('zero or missing start price is never scored', buildTodayReview([{ date: '2026-07-20', close: 0 }], 'x', 'WAIT', '2026-07-20').returnPct === null);

const newsBase = { source: 'official', url: 'https://example.test/item', publishedAt: 1,
  major: true, relevant: true, translationStatus: 'translated', corroboration: 'official' };
const selectedNews = selectTodayNews([
  { ...newsBase, id: 'held', titleJa: 'NVDA 重大開示', linkedSymbols: ['NVDA'], scope: 'holding' },
  { ...newsBase, id: 'watch', titleJa: 'AAPL 重大開示', linkedSymbols: ['AAPL'], scope: 'watchlist', publishedAt: 2 },
  { ...newsBase, id: 'index', titleJa: 'NASDAQ指数に重大影響', scope: 'index', publishedAt: 3 },
  { ...newsBase, id: 'global', titleJa: '金融危機で緊急決定', scope: 'global', publishedAt: 4 },
], ['NVDA', 'AAPL']);
check('major news is newest-first and capped at 3', selectedNews.length === 3 && selectedNews[0].id === 'global');
for (const [id, titleJa, scope, linkedSymbols] of [
  ['held', 'NVDA 重大開示', 'holding', ['NVDA']], ['watch', 'AAPL 重大開示', 'watchlist', ['AAPL']],
  ['index', 'NASDAQ指数に重大影響', 'index', []], ['global', '金融危機で緊急決定', 'global', []],
]) check(`major news includes ${id}`, selectTodayNews([{ ...newsBase, id, titleJa, scope, linkedSymbols }], ['NVDA', 'AAPL']).length === 1);
check('unrelated disclosure is filtered', selectTodayNews([{ ...newsBase, id: 'noise', titleJa: '無関係な一般開示', scope: 'other' }], ['NVDA']).length === 0);
check('translation-pending news is filtered', selectTodayNews([{ ...newsBase, id: 'pending', titleJa: '翻訳待ち', scope: 'global', translationStatus: 'pending' }], []).length === 0);
check('headline-only single-source news is filtered', selectTodayNews([{ ...newsBase, id: 'single', titleJa: '金融危機', scope: 'global', corroboration: 'single' }], []).length === 0);

const panel = fs.readFileSync(path.join(__dirname, '..', 'src/components/today/ArgusTodayPanel.tsx'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'src/components/today/ArgusToday.css'), 'utf8');
const route = fs.readFileSync(path.join(__dirname, '..', 'src/routes/CommandCenter.tsx'), 'utf8');
const shell = fs.readFileSync(path.join(__dirname, '..', 'src/components/AppShell.tsx'), 'utf8');
const nav = fs.readFileSync(path.join(__dirname, '..', 'src/components/NavRail.tsx'), 'utf8');
const navCss = fs.readFileSync(path.join(__dirname, '..', 'src/components/NavRail.css'), 'utf8');
const navigation = fs.readFileSync(path.join(__dirname, '..', 'src/navigation.ts'), 'utf8');
const marketNewsHook = fs.readFileSync(path.join(__dirname, '..', 'src/hooks/useMarketNews.ts'), 'utf8');
check('single decision card', (panel.match(/at-decision card/g) || []).length === 1);
check('Market changes and Next Check absent', !route.includes('<MarketIntelligenceChanges') && !route.includes('<NextCheckCard'));
check('Notifications is a first-class route with no shell polling dropdown',
  navigation.includes("route: 'notifications'")
  && !shell.includes('NotificationPanel') && !shell.includes('unreadCounts'));
check('manual market local persistence', route.includes('argus.today.marketSelection.v1'));
check('selected instrument is device-local only', route.includes('argus.today.selectedInstrument.v1')
  && !/fetch\([^)]*selectedInstrument/.test(route));
check('four instrument contracts are isolated', route.includes("symbol: '1306'") && route.includes("symbol: 'SPY'")
  && route.includes("symbol: 'QQQ'") && route.includes('selectedJpChart') && route.includes('selectedUsChart'));
check('Today consumes only current chart and calendar authority',
  route.includes('selectedChart.decisionData')
  && route.includes('decisionCalendar')
  && !route.includes("? selectedChart.data"));
check('no AI POST on Today interactions', !/fetch\([^\n]+method:\s*['"]POST/.test(route + panel));
check('unknown event time is not fabricated', !route.includes('T23:59:00+09:00'));
check('market levels do not get a synthetic plus sign', !panel.includes("v > 0 ? '+'"));
check('Today removes FIRE and duplicate concentration card', !panel.includes('fireProgress') && !panel.includes('portfolioConcentration'));
check('Today has required prediction graphic', panel.includes('at-proj-actual') && panel.includes('at-proj-base')
  && panel.includes('at-proj-up') && panel.includes('at-proj-down') && panel.includes('at-proj-inv')
  && panel.includes('at-proj-boundary'));
check('forecast supports 1D 5D 20D and expands evidence in Today', panel.includes('([1, 5, 20] as const)')
  && panel.includes('onActivate={() => setDetail(true)}')
  && !panel.includes('argus.replayContext') && !panel.includes("onNavigate('regime')"));
check('mobile nav is the four-destination Lean v13 surface',
  nav.includes('PRIMARY_NAVIGATION.map') && !nav.includes('SYSTEM_NAVIGATION')
  && navigation.includes("mobileLabel: 'Today'")
  && navigation.includes("mobileLabel: 'Holdings'")
  && navigation.includes("mobileLabel: 'Alerts'")
  && navigation.includes("mobileLabel: 'Settings'")
  && navCss.includes('position: fixed') && navCss.includes('grid-template-columns: repeat(4'));
check('actual line alone is white', css.includes('.at-proj-actual { fill:none; stroke:#fff')
  && css.includes('.at-proj-up { stroke:#22c55e') && css.includes('.at-proj-down { stroke:#ef4444'));
check('market card renamed MACRO and VIX retained', panel.includes('title="MACRO"') && route.includes("addRate('vix'"));
check('JP positioning remains visible in Today without an engine deep-link', panel.includes('className="at-positioning"')
  && !panel.includes("argus.scrollTo', 'market-ledger'") && !panel.includes("onNavigate('regime')"));
check('zero-news state preserves card and last check', panel.includes('at-news-zero')
  && panel.includes('現在なし') && panel.includes('ニュース確認要') && panel.includes('最終確認'));
check('seven action stages have seven distinct colors', [1,2,3,4,5,6,7].every((n) => css.includes(`nth-child(${n})`)));
check('major news is capped and processed', panel.includes('重大ニュース') && !panel.includes('Related Signal'));
check('market headlines poll 60m in-session and 120m off-hours', marketNewsHook.includes('60 * 60_000')
  && marketNewsHook.includes('120 * 60_000') && marketNewsHook.includes('marketNewsRefreshInterval()'));
check('market positioning is explicitly scoped', panel.includes('`${view.selectedMarket} 需給`'));
const handoff = fs.readFileSync(path.join(__dirname, '..', 'src/components/dashboard/ProHandoffButton.tsx'), 'utf8');
check('AI consultation scope is honest', handoff.includes("kind === 'event' && nextEvent ? 'event'")
  && handoff.includes("kind === 'portfolio' ? 'portfolio'") && handoff.includes('disabled={!selectedSymbol}'));

if (failed) { console.error(`\nargus-engine tests: ${failed} FAILED`); process.exit(1); }
console.log('\nargus-engine tests: all passed');
