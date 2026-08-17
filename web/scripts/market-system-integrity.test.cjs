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
const restore = require(path.join(__dirname, '..', 'src', 'domain', 'restoreReadiness.ts'));
const notifications = require(path.join(__dirname, '..', 'src', 'lib', 'notifications.ts'));

const todaySource = src('src', 'routes', 'CommandCenter.tsx');
const todayPanelSource = src('src', 'components', 'today', 'ArgusTodayPanel.tsx');
const chartSource = src('src', 'hooks', 'useChartIntelligence.ts');
const verifiedSnapshotSource = src('src', 'lib', 'verifiedSnapshot.ts');
const ledgerSource = src('src', 'hooks', 'useMarketLedger.ts');
check('M1 Today owns verified market chart evidence',
  todaySource.includes('useChartIntelligence') && todayPanelSource.includes('ProjectionChart'));
check('M2 Today retains market ledger context',
  todaySource.includes('useMarketLedger') && todaySource.includes('marketLedger.ledger'));
check('M3 Today retains decision-relevant market news',
  todaySource.includes('useMarketNews') && todayPanelSource.includes('重大ニュース'));
check('M4 background chart/replay intelligence remains cached GET only',
  chartSource.includes('readVerifiedSnapshot') && chartSource.includes('writeVerifiedSnapshot')
  && chartSource.includes("method: 'GET'") && !chartSource.includes("method: 'POST'")
  && verifiedSnapshotSource.includes('value.marketReplay?.contexts'));
check('M5 market ledger background lifecycle remains shared',
  ledgerSource.includes('createSharedPollingStore'));

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

const dqSource = src('src', 'routes', 'DataQualityPage.tsx');
const healthSource = src('src', 'hooks', 'useSystemHealth.ts');
const backupSource = src('src', 'routes', 'BackupPage.tsx');
const backupOverviewSource = src('src', 'components', 'system', 'BackupStatusOverview.tsx');
const settingsSource = src('src', 'routes', 'Settings.tsx');
const pageShellSource = src('src', 'routes', 'PageShell.tsx');
const appSource = src('src', 'App.tsx');
check('U1 Today exposes chart, positioning, news and evidence details',
  ['at-projection', 'at-positioning', '重大ニュース', '根拠・市場データ・システム情報']
    .every((label) => todayPanelSource.includes(label)));
check('U2 independent Market/Replay/Ledger surface is absent',
  !appSource.includes('MarketRegime') && !appSource.includes("'#market'"));
check('U3 Today market evidence remains read-only',
  !todaySource.includes("method: 'POST'") && !todayPanelSource.includes("method: 'POST'"));
check('U4 Data Quality is a fixed public-safe lamp surface',
  healthSource.includes("schemaVersion: 'argus-public-diagnostics-v1'")
  && healthSource.includes('systemHealth: SystemHealth')
  && ['PUBLIC SERVICE STATUS', 'FRESHNESS SUMMARY', 'RECOVERY CLAIM']
    .every((label) => dqSource.includes(label))
  && !dqSource.includes('<DataQualityIncidents')
  && !dqSource.includes('ARGUS_ADMIN_TOKEN'));
check('U5 Backup defaults to restore readiness, not configured-state optimism',
  backupSource.indexOf('<BackupStatusOverview') < backupSource.indexOf('<details className=\"backup-actions\"')
  && backupOverviewSource.includes('RESTORE READINESS')
  && backupOverviewSource.includes('LATEST RECOVERY POINT')
  && backupOverviewSource.includes('LAST RESTORE DRILL'));
check('U6 Settings owns language, status, recovery and minimal help',
  settingsSource.includes('<PublicDiagnosticsPanel />')
  && settingsSource.includes('<BackupSettingsPanel')
  && settingsSource.includes('aria-pressed={locale === value}')
  && settingsSource.includes('id="settings-help"'));
check('U7 contextual help resolves into Settings without mounting legacy Guide',
  pageShellSource.includes('href="#settings/help"')
  && appSource.includes('parseLocationHash')
  && !appSource.includes("from './routes/Guide'"));

if (failed) {
  console.error(`\nmarket-system integrity tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\nmarket-system integrity tests: all passed');
