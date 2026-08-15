#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const esbuild = require('esbuild');

function loadBundled(entry) {
  const output = esbuild.buildSync({
    entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs',
    define: { __APP_VERSION__: JSON.stringify('backup-contract-test') },
    logLevel: 'silent',
  }).outputFiles[0].text;
  const bundled = new Module(entry, module);
  bundled.filename = entry;
  bundled.paths = module.paths;
  bundled._compile(output, entry);
  return bundled.exports;
}

class MemoryLocalStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
  clear() { this.values.clear(); }
}

global.localStorage = new MemoryLocalStorage();
global.window = {};

const downloads = [];
let pendingBlob = null;
global.document = {
  createElement(tag) {
    assert.equal(tag, 'a');
    return {
      href: '', download: '',
      click() { downloads.push({ filename: this.download, blob: pendingBlob }); },
    };
  },
};
global.URL.createObjectURL = (blob) => { pendingBlob = blob; return `blob:test-${downloads.length}`; };
global.URL.revokeObjectURL = () => {};

const root = path.join(__dirname, '..', 'src');
const backup = loadBundled(path.join(root, 'lib', 'backup.ts'));
const portfolio = loadBundled(path.join(root, 'lib', 'portfolioSync.ts'));
const safety = loadBundled(path.join(root, 'lib', 'backupSafety.ts'));

const now = Date.now();
const oldEnvelopeAt = now - 120_000;
const postEnvelopeEditAt = now - 30_000;
const oldCompleteExportAt = new Date(now - 90_000).toISOString();
const asset = {
  id: 'asset-5803', market: 'JP', assetType: 'jp_equity', source: 'manual',
  symbol: '5803', displayName: 'Fujikura', displayNameJa: 'フジクラ',
  quantity: 10, avgCost: 1000, memo: 'core', updatedAt: postEnvelopeEditAt,
};
const snapshot = {
  schemaVersion: 'portfolio-snapshot-v1', snapshotId: 'snap-test', portfolioId: 'default',
  asOf: new Date(now).toISOString().slice(0, 10), createdAt: new Date(now).toISOString(),
};
const decision = {
  schemaVersion: 'decision-audit-v1', id: 'decision-test', asOf: new Date(now).toISOString(),
  symbol: '5803', market: 'JP', decisionContext: 'hold', ownerAction: null,
  reasonCodes: ['test'], flowClass: null, positionRisk: null, marketRegime: null,
  priceAtDecision: 1000, futureReturn1d: null, futureReturn3d: null,
  futureReturn5d: null, futureReturn20d: null, reviewNote: null, privacyLevel: 'local_only',
};

const protectedStores = {
  'argus.assets.v1': [asset],
  'argus.judgmentLog.v1': [{ id: 'judgment-test', note: 'owner judgment' }],
  'argus.trades.v1': [{ id: 'trade-test', symbol: '5803', quantity: 1 }],
  'argus.research.v1': [{ id: 'research-test', symbol: '5803', note: 'post-envelope research' }],
  'argus.assetTombstones.v1': {},
  'argus.portfolio.snapshots.v1': [snapshot],
  'argus.decision.audit.v1': [decision],
  'argus.portfolioSync.meta.v1': { lastExportAt: oldCompleteExportAt },
  'argus.notifications.v1': [{ id: 'notification-test', title: 'local notice' }],
  'argus.backupSafety.meta.v1': {
    restoreVerified: true, restoreContractVersion: backup.BACKUP_CONTRACT_VERSION,
    lastDrillAt: new Date(now - 60_000).toISOString(),
  },
  'argus.fireCore.v1': { monthlyContributionTotal: 100_000, note: 'post-envelope FIRE edit' },
};
for (const [key, value] of Object.entries(protectedStores)) {
  localStorage.setItem(key, JSON.stringify(value));
}
localStorage.setItem('argus.vaultPass.v1', 'read-only-envelope-pass');
localStorage.setItem('argus.lastCloudBackup.v1', String(oldEnvelopeAt));
localStorage.setItem('argus.lastLocalEditAt.v1', String(postEnvelopeEditAt));

async function main() {
  // Exact old failure: the partial portfolio action may download its file, but
  // cannot advance the global complete-backup timestamp or protected state.
  portfolio.downloadPortfolioBackup([asset], 'test');
  const partialMeta = portfolio.syncMeta();
  assert.equal(partialMeta.lastExportAt, oldCompleteExportAt);
  assert.ok(Date.parse(partialMeta.lastPortfolioExportAt) >= postEnvelopeEditAt);
  const afterPartial = safety.assessBackupSafety([asset]);
  assert.notEqual(afterPartial.protectionLevel, 'protected');
  assert.equal(afterPartial.exportAgeDays, null);
  assert.ok(afterPartial.riskFlags.includes('no_export_backup'));

  const partialDownload = downloads.at(-1);
  const partialPayload = JSON.parse(await partialDownload.blob.text());
  assert.match(partialDownload.filename, /^argus-portfolio-/);
  assert.deepEqual(Object.keys(partialPayload).sort(), [
    'app', 'appVersion', 'decisionAudit', 'exportedAt', 'kind',
    'positions', 'schemaVersion', 'snapshots',
  ]);
  assert.equal(partialPayload.data, undefined);

  // Portfolio Decision Audit and snapshots now execute a real merge import.
  const portfolioFile = portfolio.buildPortfolioBackup([asset], 'test');
  localStorage.setItem('argus.decision.audit.v1', '[]');
  localStorage.setItem('argus.portfolio.snapshots.v1', '[]');
  const applied = portfolio.applyImport(portfolioFile, [asset], 'merge', {
    updateHolding() {}, add() { return null; },
  });
  assert.equal(applied.decisionAuditMerged, 1);
  assert.equal(applied.snapshotsMerged, 1);
  assert.equal(portfolio.listAudit()[0].id, decision.id);
  assert.equal(portfolio.listSnapshots()[0].snapshotId, snapshot.snapshotId);

  // The drill invokes the same full restore path against isolated storage.
  assert.equal(localStorage.getItem('argus.deviceId.v1'), null);
  const drill = safety.runRecoveryDrill([asset], 'test');
  assert.equal(drill.passed, true);
  assert.match(drill.resultJa, /隔離領域へ実復元/);
  assert.equal(safety.drillMeta().restoreContractVersion, backup.BACKUP_CONTRACT_VERSION);
  assert.equal(localStorage.getItem('argus.deviceId.v1'), null);

  // Only a complete, proven round-trip download advances global protection.
  localStorage.setItem('argus.lastLocalEditAt.v1', String(Date.now() - 1));
  const exportedCount = backup.downloadBackup(false);
  assert.equal(exportedCount, backup.BACKUP_KEYS.length);
  const completeMeta = portfolio.syncMeta();
  assert.ok(Date.parse(completeMeta.lastExportAt) >= Number(localStorage.getItem('argus.lastLocalEditAt.v1')));
  assert.equal(completeMeta.lastExportContractVersion, backup.BACKUP_CONTRACT_VERSION);
  assert.equal(completeMeta.lastPortfolioExportAt, partialMeta.lastPortfolioExportAt);

  const completeDownload = downloads.at(-1);
  const completePayload = JSON.parse(await completeDownload.blob.text());
  assert.match(completeDownload.filename, /^argus-backup-/);
  assert.deepEqual(Object.keys(completePayload.data).sort(), [...backup.BACKUP_KEYS].sort());
  for (const key of ['argus.trades.v1', 'argus.research.v1', 'argus.fireCore.v1',
    'argus.decision.audit.v1', 'argus.assets.v1', 'argus.portfolio.snapshots.v1']) {
    assert.notEqual(completePayload.data[key], undefined, `${key} must be in the complete export`);
  }
  const proof = backup.verifyBackupRoundTrip(completePayload);
  assert.equal(proof.passed, true);
  assert.deepEqual(proof.restoredKeys.sort(), [...backup.BACKUP_KEYS].sort());
  assert.equal(safety.assessBackupSafety([asset]).protectionLevel, 'protected');

  // An unreadable protected store blocks certification instead of being
  // silently omitted while lastExportAt advances.
  const certifiedAt = portfolio.syncMeta().lastExportAt;
  const downloadCount = downloads.length;
  localStorage.setItem('argus.research.v1', '{broken-json');
  assert.equal(backup.downloadBackup(false), 0);
  assert.equal(portfolio.syncMeta().lastExportAt, certifiedAt);
  assert.equal(downloads.length, downloadCount);

  // The exported production import restores every covered store, not only the
  // isolated verifier's projection.
  localStorage.clear();
  assert.equal(backup.restoreBackup(completePayload), backup.BACKUP_KEYS.length);
  for (const key of backup.BACKUP_KEYS) {
    assert.notEqual(localStorage.getItem(key), null, `${key} must survive production restore`);
  }
  assert.equal(JSON.parse(localStorage.getItem('argus.trades.v1'))[0].id, 'trade-test');
  assert.equal(JSON.parse(localStorage.getItem('argus.research.v1'))[0].id, 'research-test');
  assert.equal(JSON.parse(localStorage.getItem('argus.fireCore.v1')).monthlyContributionTotal, 100_000);
  assert.equal(JSON.parse(localStorage.getItem('argus.decision.audit.v1'))[0].id, decision.id);

  // Protection discovery covers non-portfolio stores even when no holding is
  // present; FIRE/trade/research-only data must never be labelled no-data.
  localStorage.clear();
  localStorage.setItem('argus.fireCore.v1', JSON.stringify({ monthlyContributionTotal: 100_000 }));
  assert.notEqual(safety.assessBackupSafety([]).protectionLevel, 'unknown');

  const portfolioCard = fs.readFileSync(path.join(root, 'components', 'dashboard', 'PortfolioSyncCard.tsx'), 'utf8');
  const backupCard = fs.readFileSync(path.join(root, 'components', 'guide', 'BackupCard.tsx'), 'utf8');
  const backupOverview = fs.readFileSync(path.join(root, 'components', 'system', 'BackupStatusOverview.tsx'), 'utf8');
  assert.match(portfolioCard, /ポートフォリオのみJSONを書き出す/);
  assert.match(portfolioCard, /部分ファイル/);
  assert.match(backupCard, /完全バックアップJSONを書き出す/);
  assert.match(backupOverview, /certifiedCompleteExportAt\(local\)/);
  assert.doesNotMatch(backupOverview, /local\.lastExportAt/);

  console.log('backup-protection-contract.test: ok (complete certification + isolated round-trip)');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
