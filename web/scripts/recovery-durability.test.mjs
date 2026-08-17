import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const compile = (file) => ts.transpileModule(read(file), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  fileName: file,
}).outputText;
const durability = await import(`data:text/javascript;base64,${Buffer.from(
  compile('src/domain/recoveryDurability.ts'),
).toString('base64')}`);

const existing = durability.buildRecoveryDurability({
  hasLocalData: true, existingEnvelopeAt: 100, lastLocalEditAt: 100,
});
assert.equal(existing.state, 'existing_envelope_restorable');
assert.equal(existing.existingEnvelopeRestorable, true);
assert.equal(existing.newerChangesRemoteProtected, false);

const edited = durability.buildRecoveryDurability({
  hasLocalData: true, existingEnvelopeAt: 100, lastLocalEditAt: 101,
});
assert.equal(edited.state, 'changes_after_envelope');
assert.equal(edited.newerChangesRemoteProtected, false);
assert.equal(edited.localExportRequired, true);

const exported = durability.buildRecoveryDurability({
  hasLocalData: true, existingEnvelopeAt: 100, lastLocalEditAt: 101,
  lastLocalExportAt: 102,
});
assert.equal(exported.state, 'changes_after_envelope');
assert.equal(exported.newerChangesRemoteProtected, false);
assert.equal(exported.newerChangesProtectedByLocalExport, true);
assert.equal(exported.localExportRequired, false);

const cold = durability.buildRecoveryDurability({
  hasLocalData: true, existingEnvelopeAt: null, lastLocalEditAt: 101,
});
assert.equal(cold.state, 'no_envelope');
assert.equal(cold.existingEnvelopeRestorable, false);
assert.equal(cold.localExportRequired, true);

const vault = read('src/lib/vault.ts');
const backupCard = read('src/components/guide/BackupCard.tsx');
const portfolio = read('src/components/dashboard/PortfolioSyncCard.tsx');
const decision = read('src/components/dashboard/DecisionQualityCard.tsx');
const fire = read('src/components/dashboard/FireCoreCard.tsx');
const trades = read('src/components/dashboard/TradeJournalCard.tsx');
const research = read('src/components/assetDesk/AssetResearchPanel.tsx');
const status = read('src/lib/portfolioSync.ts');
const visibleRecoveryCopy = [backupCard, portfolio, decision, fire, trades, research, status].join('\n');

// The read-only envelope can still be fetched, decrypted and restored.
const restore = vault.slice(vault.indexOf('export async function cloudRestore'));
assert.match(restore, /fetchRemoteEnvelope/);
assert.match(restore, /decryptBackup/);
assert.match(restore, /restoreBackup/);
assert.match(backupCard, /既存の暗号化バックアップから復元/);

// New records never receive remote-durability or live-sync assurance.
assert.doesNotMatch(visibleRecoveryCopy,
  /暗号化バックアップに含まれます|端末間同期中|端末内\/同期|同期対象|preserved permanently|synced via/);
assert.match(visibleRecoveryCopy, /JSON/);
assert.match(backupCard, /新しい変更はこの端末内だけ/);

// Browser upload, retry and periodic push must stay absent.
const markLocalEdit = vault.slice(
  vault.indexOf('export function markLocalEdit'),
  vault.indexOf('async function fetchRemoteEnvelope'),
);
assert.doesNotMatch(vault, /method:\s*['"]POST|setInterval|cloudBackupNow|maybeCloudBackup/);
assert.doesNotMatch(markLocalEdit, /fetch\(|cloudSyncNow|setTimeout/);
assert.match(vault, /visibilitychange/);

console.log('recovery-durability.test: ok (read-only envelope, local-only newer changes)');
