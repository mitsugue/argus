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
const restore = require(path.join(__dirname, '..', 'src', 'domain', 'restoreReadiness.ts'));
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
    { sourceName: 'stale-but-ok', status: 'ok', freshnessBucket: 'very_stale',
      lastSuccessAt: 'yesterday', ownerReadableImpactJa: 'decision confidence reduced',
      nextStepJa: 'wait for refresh', isExpectedDisabled: false },
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
check('D4 stale freshness cannot hide behind status ok', incidents.some((row) =>
  row.feature === 'stale-but-ok' && row.currentState.includes('very_stale')));

const safety = (overrides = {}) => ({
  protectionLevel: 'protected', protectionLevelJa: '保護済み',
  storageMode: 'encrypted_vault_plus_export', vaultConfigured: true,
  vaultSyncAgeDays: 0, snapshotAgeDays: 0, exportAgeDays: 3,
  restoreVerified: true, lastDrillAt: '2026-07-26T00:00:00Z',
  riskFlags: [], statusJa: '保護済み', riskJa: '', nextStepJa: '現状維持',
  whatCanBeLostJa: '直近分', ...overrides,
});
const restoreReady = restore.buildRestoreReadiness(safety());
check('B1 restore ready requires a recovery point and a passed drill',
  restoreReady.state === 'ready' && restoreReady.integrity === 'READ-BACK PASS'
  && restoreReady.sources.length === 3);
const restoreUnverified = restore.buildRestoreReadiness(safety({ restoreVerified: false }));
check('B2 configured backup is not mislabeled as restore ready',
  restoreUnverified.state === 'drill_required'
  && restoreUnverified.label === 'RESTORE NOT VERIFIED');
const noRecoveryPoint = restore.buildRestoreReadiness(safety({
  protectionLevel: 'unprotected', vaultConfigured: false, vaultSyncAgeDays: null,
  snapshotAgeDays: null, exportAgeDays: null, restoreVerified: false,
}));
check('B3 missing recovery source is explicit',
  noRecoveryPoint.state === 'recovery_point_required'
  && noRecoveryPoint.sources.length === 0);
const configuredOnly = restore.buildRestoreReadiness(safety({
  protectionLevel: 'partially_protected', vaultSyncAgeDays: null,
  snapshotAgeDays: 0, exportAgeDays: null, restoreVerified: false,
}));
check('B4 configuration and local snapshot are not durable recovery proof',
  configuredOnly.state === 'recovery_point_required'
  && configuredOnly.sources.every((source) => !source.includes('vault')));

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
const backupOverviewSource = src('src', 'components', 'system', 'BackupStatusOverview.tsx');
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
check('U4 Data Quality is a fixed public-safe lamp surface',
  dqSource.includes("schemaVersion: 'argus-public-diagnostics-v1'")
  && ['PUBLIC SERVICE STATUS', 'FRESHNESS SUMMARY', 'RECOVERY CLAIM']
    .every((label) => dqSource.includes(label))
  && !dqSource.includes('<DataQualityIncidents')
  && !dqSource.includes('ARGUS_ADMIN_TOKEN'));
check('U5 Backup defaults to restore readiness, not configured-state optimism',
  backupSource.indexOf('<BackupStatusOverview') < backupSource.indexOf('<details className=\"backup-actions\"')
  && backupOverviewSource.includes('RESTORE READINESS')
  && backupOverviewSource.includes('LATEST RECOVERY POINT')
  && backupOverviewSource.includes('LAST RESTORE DRILL'));
check('U6 Guide is contextual, searchable and collapsed',
  guideSource.includes('type=\"search\"') && guideSource.includes('guide-result')
  && guideSource.includes('guide-reference')
  && guideSource.includes('resolveGuideContext(context)')
  && guideSource.includes("window.addEventListener('hashchange'")
  && guideSource.includes('filteredGlossary'));
check('U7 every non-Guide page has a contextual Guide route',
  pageShellSource.includes('#guide:') && pageShellSource.includes('この画面のGuide')
  && appSource.includes("hash.startsWith('#guide:')"));

if (failed) {
  console.error(`\nmarket-system integrity tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\nmarket-system integrity tests: all passed');
