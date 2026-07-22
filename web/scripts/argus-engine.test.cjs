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
const { buildArgusTodayView, selectAutoMarket } = require(path.join(__dirname, '..', 'src/domain/argusTodayView.ts'));
let failed = 0;
function check(name, condition) { if (condition) console.log(`  ok  ${name}`); else { failed++; console.error(`FAIL  ${name}`); } }

check('BUY/WAIT/SELL mapping', finalActionForScore(1) === 'SELL' && finalActionForScore(2) === 'SELL'
  && finalActionForScore(3) === 'WAIT' && finalActionForScore(6) === 'WAIT' && finalActionForScore(7) === 'BUY');
const base = { market: 'JP', baseSignal: 'ENTER', confidence: .9, dataQuality: 'LIVE', calculatedAt: '2026-07-22T00:00:00Z' };
check('closing window is integrated', synthesizeArgusDecision({ ...base, closingWindowSignal: 'PAUSE' }).finalAction === 'WAIT');
check('owner policy only constrains', synthesizeArgusDecision({ ...base, ownerPolicyLimit: 'DEFEND' }).finalAction === 'SELL'
  && synthesizeArgusDecision({ ...base, baseSignal: 'DEFEND', ownerPolicyLimit: 'ENTER' }).finalAction === 'SELL');
check('data quality caps confidence', synthesizeArgusDecision({ ...base, dataQuality: 'PARTIAL' }).confidence === .6);
check('event hard veto', synthesizeArgusDecision({ ...base, eventHardVeto: true }).finalAction === 'WAIT');
check('deterministic', JSON.stringify(synthesizeArgusDecision(base)) === JSON.stringify(synthesizeArgusDecision(base)));

const state = (market, session, trading = true, next = '2026-07-23') => ({ market, marketDate: '2026-07-22', isTradingDay: trading, session,
  holidayName: trading ? null : 'Holiday', nextTradingDay: next, timezone: market === 'JP' ? 'Asia/Tokyo' : 'America/New_York' });
check('AUTO JP open', selectAutoMarket({ JP: state('JP', 'MORNING_SESSION'), US: state('US', 'PRE_MARKET') }) === 'JP');
check('AUTO JP lunch', selectAutoMarket({ JP: state('JP', 'LUNCH_BREAK'), US: state('US', 'CLOSED') }) === 'JP');
check('AUTO JP holiday + US pre', selectAutoMarket({ JP: state('JP', 'HOLIDAY_CLOSED', false), US: state('US', 'PRE_MARKET') }) === 'US');
check('AUTO US holiday + JP pre', selectAutoMarket({ JP: state('JP', 'PRE_OPEN'), US: state('US', 'HOLIDAY_CLOSED', false) }) === 'JP');
check('AUTO US open', selectAutoMarket({ JP: state('JP', 'CLOSED'), US: state('US', 'REGULAR') }) === 'US');
check('AUTO US after => next JP', selectAutoMarket({ JP: state('JP', 'CLOSED'), US: state('US', 'AFTER_HOURS') }) === 'JP');
check('AUTO JP/US closed uses next session', selectAutoMarket({ JP: state('JP', 'CLOSED', true, '2026-07-24'), US: state('US', 'CLOSED', true, '2026-07-23') }) === 'US');
check('AUTO uses calendar-normalized DST session', selectAutoMarket({ JP: state('JP', 'CLOSED'),
  US: { ...state('US', 'PRE_MARKET'), timezone: 'America/New_York', regularOpenJst: '2026-07-22T22:30:00+09:00' } }) === 'US');
check('AUTO respects early-close regular session', selectAutoMarket({ JP: state('JP', 'CLOSED'),
  US: { ...state('US', 'REGULAR'), earlyClose: true, regularCloseJst: '2026-11-28T03:00:00+09:00' } }) === 'US');
check('AUTO holidays use next date', selectAutoMarket({ JP: state('JP', 'HOLIDAY_CLOSED', false, '2026-07-24'), US: state('US', 'HOLIDAY_CLOSED', false, '2026-07-23') }) === 'US');

const view = buildArgusTodayView({ now: new Date('2026-07-22T00:00:00Z'), selectionMode: 'AUTO',
  calendar: { JP: state('JP', 'MORNING_SESSION'), US: state('US', 'CLOSED') },
  baseSignal: 'ENTER', jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8, dataQuality: 'LIVE',
  events: [1,2,3,4,5].map((n) => ({ id: String(n), code: `E${n}`, title: `Event ${n}`,
    at: `2026-07-${22+n}T00:00:00Z`, impact: 'high' })),
  positioning: [1,2,3,4,5,6].map((n) => ({ key: String(n), label: String(n), value: '↑' })),
  attention: [1,2,3,4].map((n) => ({ id: String(n), label: String(n), severity: n })),
  holdings: [{ symbol: 'AAA', name: 'A', rank: 2, reasonJa: 'x', statusJa: '監視' },
    { symbol: 'AAA', name: 'A', rank: 1, reasonJa: 'y', statusJa: '要確認' },
    { symbol: 'BBB', name: 'B', rank: 3, reasonJa: 'z', statusJa: '監視' }],
  totalAssetJpy: null,
});
check('JP/US decisions independent', view.decisions.JP.finalAction === 'BUY' && view.decisions.US.finalAction === 'SELL');
check('one selected final decision', view.finalAction === 'BUY' && view.selectedMarket === 'JP');
check('COMING 30D max 3', view.comingEvents.length === 3);
check('positioning max 5', view.positioning.length === 5);
check('Attention max 3', view.attention.length === 3);
check('NEXT EVENT is not duplicated in Attention', !view.attention.some((row) => row.id === view.nextEvent?.id));
check('holdings max 3 and deduped', view.holdingsReview.length === 2 && view.holdingsReview[0].reasonJa === 'y');
check('FIRE honest empty', view.fireProgress === null);
check('footer mirrors decision', view.footerText.startsWith('JP BUY 7/7'));
const manual = buildArgusTodayView({ ...view, now: new Date('2026-07-22T00:00:00Z'), selectionMode: 'US', baseSignal: 'ENTER',
  jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8, dataQuality: 'LIVE' });
check('manual US selection', manual.selectedMarket === 'US' && manual.finalAction === 'SELL');
check('manual JP selection', buildArgusTodayView({ ...manual, now: new Date('2026-07-22T00:00:00Z'),
  selectionMode: 'JP', baseSignal: 'ENTER', jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8,
  dataQuality: 'LIVE' }).selectedMarket === 'JP');
check('AUTO return', buildArgusTodayView({ ...manual, now: new Date('2026-07-22T00:00:00Z'), selectionMode: 'AUTO',
  baseSignal: 'ENTER', jpSignal: 'ENTER', usSignal: 'DEFEND', confidence: .8, dataQuality: 'LIVE',
  calendar: { JP: state('JP', 'MORNING_SESSION'), US: state('US', 'CLOSED') } }).selectedMarket === 'JP');

const panel = fs.readFileSync(path.join(__dirname, '..', 'src/components/today/ArgusTodayPanel.tsx'), 'utf8');
const route = fs.readFileSync(path.join(__dirname, '..', 'src/routes/CommandCenter.tsx'), 'utf8');
const shell = fs.readFileSync(path.join(__dirname, '..', 'src/components/AppShell.tsx'), 'utf8');
check('single decision card', (panel.match(/at-decision card/g) || []).length === 1);
check('Market changes and Next Check absent', !route.includes('<MarketIntelligenceChanges') && !route.includes('<NextCheckCard'));
check('Today notification bell hidden', shell.includes('hideNotifications') && route.includes('ArgusTodayPanel'));
check('manual market local persistence', route.includes('argus.today.marketSelection.v1'));
check('no AI POST on Today interactions', !/fetch\([^\n]+method:\s*['"]POST/.test(route + panel));
check('unknown event time is not fabricated', !route.includes('T23:59:00+09:00'));
check('market levels do not get a synthetic plus sign', !panel.includes("v > 0 ? '+'"));
const handoff = fs.readFileSync(path.join(__dirname, '..', 'src/components/dashboard/ProHandoffButton.tsx'), 'utf8');
check('AI consultation scope is honest', handoff.includes("kind === 'event' && nextEvent ? 'event'")
  && handoff.includes("kind === 'portfolio' ? 'portfolio'") && handoff.includes('disabled={!selectedSymbol}'));

if (failed) { console.error(`\nargus-engine tests: ${failed} FAILED`); process.exit(1); }
console.log('\nargus-engine tests: all passed');
