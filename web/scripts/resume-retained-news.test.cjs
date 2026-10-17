const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const vm = require('node:vm');
const harness = fs.readFileSync('scripts/resume-extra-readers.test.cjs', 'utf8').split('(async()=>{')[0];
const isolated = new Function('require', harness + '\nreturn isolated;')(require);
const tick = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
const gateContext = { exports: {} };
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/domain/newsSignalGate.ts', 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, gateContext);
const event = { eventId: 'fixture', severity: 'HIGH', confirmationState: 'MARKET_CONFIRMED',
  staleness: 'FRESH', sourceReceivedAt: '2026-10-01T01:00:00Z', ageMinutes: 2,
  impactDirection: { directionByTarget: { broadMarket: 'BEARISH' } } };
const original = { status: 'data', view: { schemaVersion: 'argus-news-intelligence-v1',
  generatedAt: '2026-10-01T01:02:00Z', intakeStatus: 'HEALTHY', events: [event] } };
const immutable = JSON.stringify(original);
const fresh = { ...original.view, generatedAt: '2026-10-14T01:00:00Z' };
(async () => {
  const subject = { symbol: 'fixture', market: 'JP', theme: null };
  assert(gateContext.exports.newsKernelGate(original.view.events, subject), 'fresh server observation keeps its original gate');
  const health = { status: 'HEALTHY', threadAlive: true, configured: true, pending: 0, lastSyncAt: original.view.generatedAt };
  const x = isolated('src/hooks/useNewsIntelligence.ts', { 'news-intelligence': original, 'news-intake-health': health }, fresh);
  const prior = x.exports.useNewsIntelligence();
  assert.equal(prior.previousObservation, true, 'restored successful view is explicitly a previous observation');
  assert.equal(prior.intakeHealth.previousObservation, true, 'stored alive health is also a prior observation');
  assert.equal(prior.intakeHealth.lastSyncAt, health.lastSyncAt);
  assert.equal(health.previousObservation, undefined);
  assert.equal(prior.view.events[0].observationBasis, 'PREVIOUS_SESSION_VIEW');
  assert.equal(gateContext.exports.newsKernelGate(prior.view.events, subject), null,
    'a previously fresh/confirmed event cannot become a current gate just by restoring the screen');
  assert.equal(JSON.stringify(original), immutable, 'original server freshness, receipt and confirmation remain untouched');
  assert.equal(prior.view.events[0].sourceReceivedAt, event.sourceReceivedAt);
  assert.equal(prior.view.events[0].ageMinutes, 2, 'old computed age remains identified as prior, not a new server calculation');
  x.effects.forEach(fn => fn()); await tick(); assert.equal(x.calls, 0);
  x.timers[0].fn(); await tick();
  assert.equal(x.slots.at(-1).view.generatedAt, fresh.generatedAt, 'ordinary refresh replaces the retained observation');
  assert.equal(x.slots.at(-1).view.observationBasis, undefined);
  assert(gateContext.exports.newsKernelGate(x.slots.at(-1).view.events, subject));
  const laterReader = x.exports.useNewsIntelligence();
  assert.equal(laterReader.view.generatedAt, fresh.generatedAt, 'later mounting reader cannot replace a new reply with its older checkpoint');
  assert.equal(laterReader.previousObservation, false);
  const shock = { status: 'data', view: { schemaVersion: 'argus-market-shock-v1', generatedAt: original.view.generatedAt, events: [] } };
  const s = isolated('src/hooks/useMarketShock.ts', { 'market-shock': shock });
  assert.equal(s.exports.useMarketShock().previousObservation, true,
    'empty restored shock view is not evidence that there is currently no shock');
  console.log('PASS retained rich news/shock observations: original receipt/freshness unchanged, explicit prior basis, no current news gate from restoration, zero startup reads, normal refreshed gate preserved.');
})().catch(e => { console.error(e); process.exitCode = 1; });
