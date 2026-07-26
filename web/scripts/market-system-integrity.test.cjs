#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');

require.extensions['.ts'] = (module, filename) => {
  const source = fs.readFileSync(filename, 'utf8');
  module._compile(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText, filename);
};

let failed = 0;
function check(name, condition) {
  if (condition) console.log(`  ok  ${name}`);
  else { failed += 1; console.error(`FAIL  ${name}`); }
}
const src = (...parts) => fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');
const market = require(path.join(__dirname, '..', 'src', 'domain', 'marketContextView.ts'));
const dq = require(path.join(__dirname, '..', 'src', 'domain', 'dataQualityIncidents.ts'));
const notifications = require(path.join(__dirname, '..', 'src', 'lib', 'notifications.ts'));

const view = market.buildMarketContextView({
  market: 'JP', periodEnd: '2026-07-24',
  indicators: { bars: [{ close: 100 }, { close: 102 }] },
  eventMarkers: [
    { id: 'old', date: '2026-07-20', labelJa: '過去', kind: 'macro' },
    { id: 'next', date: '2026-07-27', labelJa: '日銀', kind: 'macro' },
  ],
}, {
  currentRegime: { trend: 'UP', volatility: 'HIGH' },
  probabilityQuality: { brierSkill: null },
  changeConditions: [{ price: 99, event: null }],
});
check('M1 market summary uses observed price change', view.changed.includes('+2.0%'));
check('M2 market summary preserves independent market treatment',
  view.jpImplication.includes('trend UP') && view.usImplication.includes('独立市場'));
check('M3 next event excludes past events', view.nextEvent.includes('日銀') && !view.nextEvent.includes('過去'));
check('M4 risk does not fabricate direction skill', view.primaryRisk.includes('方向Skill未確認'));
check('M5 change condition uses verified close level', view.changeCondition.includes('99'));

const incidents = dq.buildDataQualityIncidents({
  sourceHealth: [
    { sourceName: 'ok', status: 'ok', lastSuccessAt: 'now', ownerReadableImpactJa: '',
      nextStepJa: '', isExpectedDisabled: false },
    { sourceName: 'expected', status: 'disabled', lastSuccessAt: null, ownerReadableImpactJa: '',
      nextStepJa: '', isExpectedDisabled: true },
    { sourceName: 'prices', status: 'failed', lastSuccessAt: null,
      ownerReadableImpactJa: 'chart unavailable', nextStepJa: 'retry', isExpectedDisabled: false },
  ],
  remoteJournalVerification: {
    readBackVerified: false, committedAt: null, readBackAt: null, pendingCount: 2, errorClass: null,
  },
  publicLeakSafe: true,
});
check('D1 expected disabled and healthy sources stay out of incidents',
  !incidents.some((row) => ['ok', 'expected'].includes(row.feature)));
check('D2 critical incident is first and actionable',
  incidents[0].feature === 'prices' && incidents[0].severity === 'critical'
  && incidents[0].ownerAction === 'retry');
check('D3 Remote Journal pending is explicit', incidents.some((row) =>
  row.feature === 'Remote Journal' && row.impact.includes('pending 2')));

const baseNotification = {
  id: 'a', createdAt: '2026-07-26T01:00:00Z', eventType: 'event_before',
  severity: 'medium', symbol: '5803', assetName: null, titleJa: 'イベント接近',
  bodyJa: 'body', whyJa: 'why', checkNextJa: 'next', deliveryState: 'seen',
  dedupeKey: 'event|5803|day1', isPrivate: false,
};
const compact = notifications.compactNotificationFeed([
  baseNotification, { ...baseNotification, id: 'b', dedupeKey: 'event|5803|day2' },
]);
check('N1 notification feed renders one semantic incident', compact.length === 1
  && compact[0].occurrenceCount === 2 && compact[0].notificationIds.length === 2);

const marketSource = src('src', 'components', 'marketReplay', 'MarketContextReplay.tsx');
const dqSource = src('src', 'routes', 'DataQualityPage.tsx');
const backupSource = src('src', 'routes', 'BackupPage.tsx');
const guideSource = src('src', 'routes', 'Guide.tsx');
const pageShellSource = src('src', 'routes', 'PageShell.tsx');
const appSource = src('src', 'App.tsx');
check('U1 first market viewport exposes seven decision contracts',
  ['CURRENT REGIME', 'WHAT CHANGED', 'PRIMARY RISK', 'JP IMPLICATION', 'US IMPLICATION',
    'NEXT EVENT', 'WHAT CHANGES IT'].every((label) => marketSource.includes(label)));
check('U2 Replay and Ledger remain secondary navigation',
  marketSource.includes("type Tab = 'OVERVIEW' | 'REPLAY' | 'LEDGER'"));
check('U3 FROZEN market path remains cached GET with AI POST 0',
  marketSource.includes('useChartIntelligence') && marketSource.includes('AI POST 0')
  && !marketSource.includes("method: 'POST'"));
check('U4 Data Quality defaults to actionable incidents',
  dqSource.indexOf('<DataQualityIncidents') < dqSource.indexOf('<details className=\"dq-diagnostics\"'));
check('U5 Backup defaults to a compact protection contract',
  backupSource.indexOf('<BackupStatusOverview') < backupSource.indexOf('<details className=\"backup-actions\"'));
check('U6 Guide is contextual, searchable and collapsed',
  guideSource.includes('type=\"search\"') && guideSource.includes('guide-result')
  && guideSource.includes('guide-reference'));
check('U7 every non-Guide page has a contextual Guide route',
  pageShellSource.includes('#guide:') && pageShellSource.includes('この画面のGuide')
  && appSource.includes("hash.startsWith('#guide:')"));

if (failed) {
  console.error(`\nmarket-system integrity tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\nmarket-system integrity tests: all passed');
