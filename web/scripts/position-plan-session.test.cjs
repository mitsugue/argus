#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};

const root = path.join(__dirname, '..');
const { buildPlan, projectPlanningSession, PTS_WARNING_JA, SESSION_UNKNOWN_WARNING_JA } =
  require(path.join(root, 'src/domain/positionPlan.ts'));
const { buildLocalBrief, resolveSessionJst } =
  require(path.join(root, 'src/domain/sessionBrief.ts'));
const source = fs.readFileSync(path.join(root, 'src/domain/positionPlan.ts'), 'utf8');
const briefSource = fs.readFileSync(path.join(root, 'src/domain/sessionBrief.ts'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'src/App.tsx'), 'utf8');
const hook = fs.readFileSync(path.join(root, 'src/hooks/useAssetIntel.ts'), 'utf8');
const ledgerHook = fs.readFileSync(path.join(root, 'src/hooks/useMarketLedger.ts'), 'utf8');
let failed = 0;
function check(name, condition) {
  if (condition) console.log(`  ok  ${name}`);
  else { failed++; console.error(`FAIL  ${name}`); }
}

const jp = (session, trading = true,
  observedAt = '2026-08-17T02:29:00Z', validUntil = '2026-08-17T02:30:00Z') => ({
  market: 'JP_EQUITY', marketDate: '2026-08-17', isTradingDay: trading, session,
  holidayName: trading ? null : 'Market Holiday', nextTradingDay: '2026-08-18',
  timezone: 'Asia/Tokyo', regularOpenJst: '2026-08-17T09:00:00+09:00',
  regularCloseJst: '2026-08-17T15:30:00+09:00', calendarVersion: 'cal-2026.2',
  officialCalendar: 'JPX_TSE', sessionObservedAt: observedAt, sessionValidUntil: validUntil,
});
const us = (session, openJst, trading = true,
  observedAt = '2026-08-17T14:00:00Z', validUntil = '2026-08-17T20:00:00Z') => ({
  market: 'US_EQUITY', marketDate: '2026-08-17', isTradingDay: trading, session,
  holidayName: trading ? null : 'Market Holiday', nextTradingDay: '2026-08-18',
  timezone: 'America/New_York', regularOpenJst: openJst,
  regularCloseJst: '2026-08-18T05:00:00+09:00', calendarVersion: 'cal-2026.2',
  officialCalendar: 'NYSE_NASDAQ', sessionObservedAt: observedAt, sessionValidUntil: validUntil,
});
const authority = (market, state, availability = 'available', serverAsOf = state?.sessionObservedAt,
  receivedAtMs = serverAsOf ? Date.parse(serverAsOf) + 1_000 : null) => ({
  calendar: state ? { [market]: state } : null, serverAsOf: serverAsOf ?? null,
  receivedAtMs, availability,
});
const project = (market, state, evaluatedAtMs = state?.sessionObservedAt
  ? Date.parse(state.sessionObservedAt) + 2_000 : Date.parse('2026-08-17T02:29:02Z')) =>
  projectPlanningSession(market, state ? authority(market, state) : null, evaluatedAtMs);
const pairedAuthority = (jpState, usState, serverAsOf = '2026-08-17T02:29:00Z',
  availability = 'available') => {
  const serverMs = Date.parse(serverAsOf);
  const validUntil = new Date(serverMs + 60 * 60 * 1000).toISOString();
  return {
    calendar: {
      JP: { ...jpState, sessionObservedAt: serverAsOf, sessionValidUntil: validUntil },
      US: { ...usState, sessionObservedAt: serverAsOf, sessionValidUntil: validUntil },
    },
    serverAsOf,
    receivedAtMs: serverMs + 1_000,
    availability,
  };
};
const resolvePair = (jpState, usState, serverAsOf = '2026-08-17T02:29:00Z') =>
  resolveSessionJst(pairedAuthority(jpState, usState, serverAsOf),
    Date.parse(serverAsOf) + 2_000);

check('JP morning is open from canonical session', project('JP', jp('MORNING_SESSION')).state === 'open');
check('JP lunch is closed', project('JP', jp('LUNCH_BREAK', true,
  '2026-08-17T03:00:00Z', '2026-08-17T03:30:00Z')).state === 'closed');
check('JP afternoon is open', project('JP', jp('AFTERNOON_SESSION', true,
  '2026-08-17T04:00:00Z', '2026-08-17T06:30:00Z')).state === 'open');
check('JP holiday is closed', project('JP', jp('HOLIDAY_CLOSED', false,
  '2026-08-17T01:00:00Z', '2026-08-17T15:00:00Z')).state === 'closed');
check('JP post-market is closed', project('JP', jp('POST_MARKET', true,
  '2026-08-17T07:00:00Z', '2026-08-17T15:00:00Z')).state === 'closed');

// The frontend consumes the server session label. It does not calculate either
// US offset, so DST and standard-time REGULAR sessions have identical authority.
check('US DST regular session is open',
  project('US', us('REGULAR', '2026-08-17T22:30:00+09:00')).state === 'open');
check('US standard-time regular session is open',
  project('US', us('REGULAR', '2026-01-15T23:30:00+09:00', true,
    '2026-01-15T16:00:00Z', '2026-01-15T21:00:00Z')).state === 'open');
check('US holiday is closed',
  project('US', us('HOLIDAY_CLOSED', '2026-12-25T23:30:00+09:00', false,
    '2026-12-25T15:00:00Z', '2026-12-26T05:00:00Z')).state === 'closed');
check('US overnight is closed',
  project('US', us('OVERNIGHT_CLOSED', '2026-08-17T22:30:00+09:00', true,
    '2026-08-17T07:00:00Z', '2026-08-17T08:00:00Z')).state === 'closed');

check('absent canonical state is unknown', project('JP', null).state === 'unknown');
check('unknown canonical session fails unknown', project('US', us('MYSTERY', '')).state === 'unknown');
check('market identity mismatch fails unknown',
  projectPlanningSession('JP', authority('JP', {
    ...jp('MORNING_SESSION'), market: 'US_EQUITY' }), Date.parse('2026-08-17T02:29:02Z')).state === 'unknown');
check('trading/holiday contradiction fails unknown',
  project('JP', jp('MORNING_SESSION', false)).state === 'unknown'
  && project('JP', jp('HOLIDAY_CLOSED', true, '2026-08-17T01:00:00Z',
    '2026-08-17T15:00:00Z')).state === 'unknown');
check('non-exchange asset is explicitly not applicable',
  ['CRYPTO', 'FUND', 'CORE', 'MANUAL'].every((market) =>
    projectPlanningSession(market, null).state === 'not_applicable'));
check('unknown or malformed exchange identity fails unknown',
  ['JP_EQUITY', 'JP ', 'UNKNOWN', ''].every((market) =>
    projectPlanningSession(market, null).state === 'unknown'));

const expiringMorning = jp('MORNING_SESSION');
check('canonical session is valid immediately before its server expiry',
  project('JP', expiringMorning, Date.parse('2026-08-17T02:29:59.999Z')).state === 'open');
check('canonical session fails stale exactly at its server expiry',
  project('JP', expiringMorning, Date.parse('2026-08-17T02:30:00Z')).reason === 'contract_stale');
check('refresh failure invalidates an otherwise fresh open projection',
  projectPlanningSession('JP', authority('JP', expiringMorning, 'refresh_failed'),
    Date.parse('2026-08-17T02:29:02Z')).reason === 'refresh_failed');
check('loading or locally expired authority fails stale',
  ['loading', 'expired'].every((status) => projectPlanningSession(
    'JP', authority('JP', expiringMorning, status),
    Date.parse('2026-08-17T02:29:02Z')).reason === 'contract_stale'));
check('missing malformed future or old server asOf fails stale', [
  authority('JP', expiringMorning, 'available', null, Date.parse('2026-08-17T02:29:01Z')),
  authority('JP', expiringMorning, 'available', 'bad-time', Date.parse('2026-08-17T02:29:01Z')),
  authority('JP', { ...expiringMorning, sessionObservedAt: '2026-08-17T02:29:10Z' },
    'available', '2026-08-17T02:29:10Z', Date.parse('2026-08-17T02:29:01Z')),
  authority('JP', { ...expiringMorning, sessionObservedAt: '2026-08-17T02:00:00Z' },
    'available', '2026-08-17T02:00:00Z', Date.parse('2026-08-17T02:00:01Z')),
].every((input) => projectPlanningSession(
  'JP', input, Date.parse('2026-08-17T02:29:02Z')).state === 'unknown'));
const impossibleObserved = '2026-02-30T02:29:00Z';
const normalizedImpossibleMs = Date.parse(impossibleObserved);
check('impossible server/observed calendar date cannot normalize into authority',
  projectPlanningSession('JP', authority('JP', {
    ...expiringMorning,
    sessionObservedAt: impossibleObserved,
    sessionValidUntil: '2026-03-02T02:40:00Z',
  }, 'available', impossibleObserved, normalizedImpossibleMs + 1_000),
  normalizedImpossibleMs + 2_000).state === 'unknown');
check('impossible validUntil calendar date cannot normalize into authority',
  projectPlanningSession('JP', authority('JP', {
    ...expiringMorning,
    sessionValidUntil: '2026-02-30T02:40:00Z',
  }), Date.parse('2026-08-17T02:29:02Z')).state === 'unknown');

const favorable = {
  symbol: '7203', market: 'JP', assetName: 'Toyota', isHeld: false,
  sdRank: 'A', flowClass: 'institutional_accumulation', scenarioDominant: 'bullish',
  missing: [],
};
const buildAt = (iso, inputs) => {
  const originalNow = Date.now;
  Date.now = () => Date.parse(iso);
  try { return buildPlan(inputs); }
  finally { Date.now = originalNow; }
};
const openProjection = project('JP', jp('MORNING_SESSION'));
const openPlan = buildAt('2026-08-17T02:29:02Z', {
  ...favorable, marketSession: openProjection });
check('canonical open permits the existing positive planning path',
  openPlan.planType === 'entry' && openPlan.currentStance === 'small_add_allowed');
const missingQuotePlan = buildAt('2026-08-17T02:29:02Z', {
  ...favorable, sdCondition: 'improving_but_heavy', missing: ['現在価格未確認'],
  marketSession: openProjection,
});
check('missing quote suppresses improving-heavy entry before its positive branch',
  missingQuotePlan.planType === 'unknown'
  && missingQuotePlan.currentStance === 'unknown'
  && missingQuotePlan.blockingReasons.includes('decision_evidence_missing'));
check('duplicate primary stance resolver is retired',
  !fs.existsSync(path.join(root, 'src/domain/primaryStance.ts'))
  && !hook.includes('stanceBySymbol'));
const closedPlan = buildAt('2026-08-17T03:00:02Z', {
  ...favorable, marketSession: project('JP', jp('LUNCH_BREAK', true,
  '2026-08-17T03:00:00Z', '2026-08-17T03:30:00Z')),
});
check('canonical closed suppresses positive planning and adds regular-session warning',
  closedPlan.planType === 'wait' && closedPlan.currentStance === 'wait'
  && closedPlan.whatNotToDoJa.includes(PTS_WARNING_JA)
  && closedPlan.summaryJa.includes(PTS_WARNING_JA));
const unknownPlan = buildPlan({ ...favorable, marketSession: project('JP', null) });
check('missing canonical state suppresses a positive plan',
  unknownPlan.planType === 'unknown' && unknownPlan.currentStance === 'unknown'
  && unknownPlan.blockingReasons.includes('market_session_unknown')
  && unknownPlan.whatNotToDoJa.includes(SESSION_UNKNOWN_WARNING_JA));
const missingProjectionPlan = buildPlan(favorable);
check('omitted projection also fails conservative',
  missingProjectionPlan.planType === 'unknown'
  && missingProjectionPlan.marketSession.state === 'unknown');

const forgedOpenNullEvidence = buildAt('2026-08-17T02:29:02Z', { ...favorable,
  marketSession: {
    schemaVersion: 'planning-session-projection-v1', market: 'JP', state: 'open',
    canonicalSession: null, calendarVersion: null, observedAt: null,
    validUntil: null, reason: 'regular_session',
  },
});
check('forged open with null canonical evidence fails unknown',
  forgedOpenNullEvidence.planType === 'unknown'
  && forgedOpenNullEvidence.currentStance === 'unknown'
  && forgedOpenNullEvidence.marketSession.reason === 'contract_invalid'
  && forgedOpenNullEvidence.blockingReasons.includes('market_session_unknown'));

const malformedStates = ['OPEN', 'open ', true, 1, null].map((state) => buildAt(
  '2026-08-17T02:29:02Z', { ...favorable,
  marketSession: { ...openProjection, state },
}));
check('malformed session state values never authorize a positive plan',
  malformedStates.every((plan) => plan.planType === 'unknown'
    && plan.currentStance === 'unknown'
    && plan.marketSession.reason === 'contract_invalid'));

const incoherentOpenClaims = [
  { ...openProjection, reason: 'refresh_failed' },
  { ...openProjection, canonicalSession: 'LUNCH_BREAK' },
  { ...openProjection, market: 'US' },
  { ...openProjection, unexpectedAuthority: true },
  { ...openProjection, observedAt: null },
  { ...openProjection, observedAt: 'bad-time' },
  { ...openProjection, observedAt: '2026-02-30T02:29:00Z' },
  { ...openProjection, observedAt: '2026-08-17T02:30:01Z' },
  { ...openProjection, validUntil: '2026-08-17T02:29:02Z' },
  { ...openProjection, validUntil: '2026-02-30T02:40:00Z' },
  { ...openProjection, calendarVersion: '' },
].map((marketSession) => buildAt('2026-08-17T02:29:02Z', {
  ...favorable, marketSession,
}));
check('cross-market reason timestamp and canonical-evidence contradictions fail unknown',
  incoherentOpenClaims.every((plan) => plan.planType === 'unknown'
    && plan.currentStance === 'unknown'
    && plan.marketSession.reason === 'contract_invalid'));

const staleStoredUsProjection = project('US', us(
  'REGULAR', '2026-08-17T22:30:00+09:00', true,
  '2026-08-17T14:00:00Z', '2026-08-17T20:00:00Z'));
const staleStoredUsPlan = buildAt('2026-08-17T14:20:00.001Z', {
  ...favorable, market: 'US', marketSession: staleStoredUsProjection,
});
check('stored open projection older than twenty minutes cannot authorize entry',
  staleStoredUsPlan.planType === 'unknown'
  && staleStoredUsPlan.currentStance === 'unknown'
  && staleStoredUsPlan.marketSession.reason === 'contract_invalid');

const forgedUnknownWithEvidence = buildAt('2026-08-17T02:29:02Z', {
  ...favorable,
  marketSession: {
    ...openProjection, state: 'unknown', reason: 'refresh_failed',
  },
});
check('refresh-failed state cannot retain stale MORNING evidence',
  forgedUnknownWithEvidence.planType === 'unknown'
  && forgedUnknownWithEvidence.marketSession.reason === 'contract_invalid');
const malformedMarketPlan = buildPlan({ ...favorable, market: 'JP_EQUITY',
  marketSession: projectPlanningSession('JP_EQUITY', null) });
const omittedMalformedMarketPlan = buildPlan({ ...favorable, market: 'JP_EQUITY' });
const mismatchedMalformedMarketPlan = buildPlan({ ...favorable, market: 'JP_EQUITY',
  marketSession: projectPlanningSession('CRYPTO', null) });
check('malformed market identity cannot bypass explicit omitted or mismatched projection',
  malformedMarketPlan.planType === 'unknown'
  && malformedMarketPlan.currentStance === 'unknown'
  && omittedMalformedMarketPlan.planType === 'unknown'
  && omittedMalformedMarketPlan.marketSession.reason === 'contract_invalid'
  && mismatchedMalformedMarketPlan.planType === 'unknown'
  && mismatchedMalformedMarketPlan.marketSession.reason === 'contract_invalid');
const defensivePlan = buildPlan({ ...favorable, isHeld: true, sdRank: 'D',
  flowClass: 'distribution', scenarioDominant: 'bearish', positionRiskLevel: 'high',
  marketSession: project('JP', null) });
check('unknown session does not hide a defensive held-position review',
  defensivePlan.planType === 'exit_review' && defensivePlan.currentStance === 'risk_review');
const staleDefensivePlan = buildPlan({ ...favorable, isHeld: true, sdRank: 'D',
  flowClass: 'distribution', scenarioDominant: 'bearish', positionRiskLevel: 'high',
  marketSession: project('JP', expiringMorning, Date.parse('2026-08-17T02:30:01Z')) });
check('expired session does not hide a defensive held-position review',
  staleDefensivePlan.planType === 'exit_review'
  && staleDefensivePlan.currentStance === 'risk_review');

// Session Brief and the shell status consume the same bounded server authority
// as Position Plan.  The browser clock is freshness input only, never exchange
// calendar/session authority.
const usPre = us('PRE_MARKET', '2026-08-17T21:00:00+09:00', true);
const usOvernight = us('OVERNIGHT_CLOSED', '2026-08-17T22:30:00+09:00', true);
check('Session Brief maps canonical JP morning without a browser clock',
  resolvePair(jp('MORNING_SESSION'), usPre).sessionType === 'intraday');
check('Session Brief maps canonical JP lunch without a browser clock',
  resolvePair(jp('LUNCH_BREAK'), usPre).sessionType === 'lunch_break');
check('Session Brief maps canonical JP afternoon without a browser clock',
  resolvePair(jp('AFTERNOON_SESSION'), usPre).sessionType === 'intraday');
check('Session Brief maps canonical JP holiday without a browser clock',
  resolvePair(jp('HOLIDAY_CLOSED', false), usOvernight).sessionType === 'holiday');
check('Session Brief maps canonical US regular without calculating DST',
  resolvePair(jp('POST_MARKET'), us('REGULAR',
    '2026-08-17T22:30:00+09:00')).sessionType === 'intraday');
check('Session Brief maps canonical US regular in standard time identically',
  resolvePair(jp('POST_MARKET', true, '2026-01-15T16:00:00Z',
    '2026-01-15T17:00:00Z'), us('REGULAR', '2026-01-15T23:30:00+09:00', true,
    '2026-01-15T16:00:00Z', '2026-01-15T17:00:00Z'),
  '2026-01-15T16:00:00Z').sessionType === 'intraday');
check('Session Brief maps canonical JP and US holiday closure', (() => {
  const resolved = resolvePair(jp('HOLIDAY_CLOSED', false),
    us('HOLIDAY_CLOSED', '2026-12-25T23:30:00+09:00', false));
  return resolved.sessionType === 'holiday' && resolved.marketStatusJa === 'JP・US休場';
})());

const addCandidate = {
  symbol: '5803', market: 'JP', assetName: 'Fujikura', isHeld: false,
  priorityRank: 'Watch', priorityScore: 8, category: 'add_candidate',
  blockingReason: 'none', whyJa: '需給とフローは良好です',
  checkNextJa: '出来高の継続を確認',
};
const freshPair = pairedAuthority(jp('MORNING_SESSION'), usPre);
const stalePair = pairedAuthority(jp('MORNING_SESSION'), usPre,
  '2026-08-17T02:00:00Z');
const failedBriefs = [
  buildLocalBrief([addCandidate], { sessionAuthority: null },
    Date.parse('2026-08-17T02:29:02Z')),
  buildLocalBrief([addCandidate], { sessionAuthority: {
    ...freshPair, serverAsOf: 'not-a-timestamp',
  } }, Date.parse('2026-08-17T02:29:02Z')),
  buildLocalBrief([addCandidate], { sessionAuthority: stalePair },
    Date.parse('2026-08-17T02:21:00.001Z')),
  buildLocalBrief([addCandidate], { sessionAuthority: {
    ...freshPair, availability: 'refresh_failed',
  } }, Date.parse('2026-08-17T02:29:02Z')),
];
check('absent malformed stale and refresh-failed authority make Session Brief unknown',
  failedBriefs.every((brief) => brief.sessionType === 'unknown'
    && brief.ownerMode === 'unknown'));
check('unknown Session Brief suppresses add-candidate and buy-increase language',
  failedBriefs.every((brief) => {
    const rendered = JSON.stringify(brief);
    return !['買い増し候補', '小さく分けて', '小さく買い増し可', '攻める日']
      .some((phrase) => rendered.includes(phrase));
  }));

const closedBriefs = [
  buildLocalBrief([addCandidate], {
    sessionAuthority: pairedAuthority(
      jp('HOLIDAY_CLOSED', false), usOvernight),
  }, Date.parse('2026-08-17T02:29:02Z')),
  buildLocalBrief([addCandidate], {
    sessionAuthority: pairedAuthority(jp('LUNCH_BREAK'), usOvernight),
  }, Date.parse('2026-08-17T02:29:02Z')),
];
check('canonical holiday and lunch suppress positive Session Brief language',
  closedBriefs.every((brief) => {
    const rendered = JSON.stringify(brief);
    return brief.ownerMode !== 'attack'
      && !['買い増し候補', '小さく分けて', '小さく買い増し可', '攻める日']
        .some((phrase) => rendered.includes(phrase));
  }));

const heldDefensive = {
  symbol: '7203', market: 'JP', assetName: 'Toyota', isHeld: true,
  priorityRank: 'P1', priorityScore: 65, category: 'held_risk',
  blockingReason: 'supply_demand_bad', whyJa: '需給悪化と売り圧力を確認',
  checkNextJa: '下落理由と大口フローを確認',
};
const unknownHeldBrief = buildLocalBrief([heldDefensive], {
  sessionAuthority: null,
}, Date.parse('2026-08-17T02:29:02Z'));
check('unknown session retains defensive held-risk evidence',
  unknownHeldBrief.sessionType === 'unknown'
  && unknownHeldBrief.heldRiskLines.some((line) => line.includes('7203'))
  && unknownHeldBrief.bullets.some((line) => line.includes('7203')));

check('position plan contains no browser clock/calendar authority',
  !/new Date|getTimezoneOffset|getHours|getMinutes|Intl\.DateTimeFormat/.test(source));
check('asset pipeline passes the canonical projection and no legacy clock helper',
  hook.includes('projectPlanningSession(') && hook.includes('phase3?.calendar')
  && hook.includes('phase3?.asOf') && hook.includes('fetchedAtMs')
  && hook.includes('marketLedger.error') && hook.includes('marketLedger.sessionExpired')
  && !hook.includes('marketOpenNow'));
check('session expiry schedules invalidation before the background poll',
  ledgerHook.includes('sessionValidUntil') && ledgerHook.includes('sessionExpired: true')
  && ledgerHook.includes('refreshMarketLedger(true)'));
check('unsubscribe/remount lifecycle re-arms expiry on a fresh cache hit',
  /createSharedPollingStore<[\s\S]*scheduleSessionExpiry\(cache\);[\s\S]*refresh\(\)/
    .test(ledgerHook)
  && /Date\.now\(\) - cache\.fetchedAtMs < STALE_MS\) \{[\s\S]*scheduleSessionExpiry\(cache\);[\s\S]*return cache;/
    .test(ledgerHook));
check('Session Brief delegates to canonical projection and owns no exchange clock',
  briefSource.includes("projectPlanningSession('JP'")
  && briefSource.includes("projectPlanningSession('US'")
  && !briefSource.includes('marketCalendar')
  && !/getTimezoneOffset|getHours|getMinutes|getUTCHours|getUTCMinutes|getDay|getUTCDay|Intl\.DateTimeFormat/.test(briefSource)
  && !/\b(?:holidayName|nextTradingDay|marketDate|regularOpenJst|regularCloseJst|timezone|officialCalendar)\b/.test(briefSource)
  && !/\b(?:JST|DST)_OFFSET\b|9\s*\*\s*3600/.test(briefSource));
check('Session Brief hook passes server authority and refresh state, not a raw calendar',
  /const canonicalSessionAuthority[\s\S]{0,1200}calendar:[\s\S]{0,300}serverAsOf:[\s\S]{0,300}receivedAtMs:[\s\S]{0,300}availability:/.test(hook)
  && /buildLocalBrief\(apItems,\s*\{[\s\S]{0,900}sessionAuthority:\s*canonicalSessionAuthority/.test(hook)
  && hook.includes('phase3?.asOf') && hook.includes('fetchedAtMs')
  && hook.includes('marketLedger.error') && hook.includes('marketLedger.sessionExpired')
  && !/buildLocalBrief\(apItems,\s*\{[\s\S]{0,1000}marketCalendar:/.test(hook));
check('App passes bounded server authority and owns no JST hour DST or holiday calculation',
  /const canonicalSessionAuthority[\s\S]{0,1200}calendar:[\s\S]{0,300}serverAsOf:[\s\S]{0,300}receivedAtMs:[\s\S]{0,300}availability:/.test(appSource)
  && /resolveSessionJst\(\s*canonicalSessionAuthority\s*\)/.test(appSource)
  && appSource.includes('phase3?.asOf') && appSource.includes('fetchedAtMs')
  && appSource.includes('marketLedger.error') && appSource.includes('marketLedger.sessionExpired')
  && !/resolveSessionJst\(\s*new Date/.test(appSource)
  && !/getTimezoneOffset|getHours|getMinutes|getUTCHours|getUTCMinutes|getDay|getUTCDay|Intl\.DateTimeFormat/.test(appSource));

if (failed) {
  console.error(`\nposition-plan session tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\nposition-plan session tests: all passed');
