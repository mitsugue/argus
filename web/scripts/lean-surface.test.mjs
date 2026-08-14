import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

async function importTypeScriptModule(relativePath) {
  const output = ts.transpileModule(read(relativePath), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    fileName: relativePath,
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);
}

const navigation = await importTypeScriptModule('src/navigation.ts');
const app = read('src/App.tsx');
const shell = read('src/components/AppShell.tsx');
const command = read('src/routes/CommandCenter.tsx');
const notifications = read('src/routes/NotificationsPage.tsx');
const notificationPanel = read('src/components/NotificationPanel.tsx');
const notificationEngine = read('src/lib/notifications.ts');
const settings = read('src/routes/Settings.tsx');
const watchlist = read('src/routes/Watchlist.tsx');
const backupPage = read('src/routes/BackupPage.tsx');
const assetDecision = read('src/components/assetDesk/AssetDecisionCard.tsx');
const assetSummary = read('src/components/assetDesk/AssetDecisionSummary.tsx');
const todayPanel = read('src/components/today/ArgusTodayPanel.tsx');
const aiExplanation = read('src/components/dashboard/AiExplanationBlock.tsx');
const institutional = read('src/components/dashboard/InstitutionalView.tsx');
const osintHook = read('src/hooks/useOsintInvestigation.ts');
const osintPanel = read('src/components/dashboard/OsintDeepDive.tsx');
const vault = read('src/lib/vault.ts');
const backupCard = read('src/components/guide/BackupCard.tsx');
const locales = read('src/i18n/locales.ts');
const deferredManifest = read('../docs/ARGUS_B2A_DEFERRED_UI_MANIFEST.md');

assert.deepEqual(
  navigation.PRIMARY_NAVIGATION.map(({ route, hash }) => ({ route, hash })),
  [
    { route: 'command', hash: '#today' },
    { route: 'watchlist', hash: '#holdings' },
    { route: 'notifications', hash: '#notifications' },
    { route: 'settings', hash: '#settings' },
  ],
);
assert.deepEqual(navigation.parseLocationHash('#asset/5803/evidence'), {
  route: 'watchlist', asset: { symbol: '5803', section: 'evidence' },
});
assert.deepEqual(navigation.parseLocationHash('#positions'), {
  route: 'watchlist', portfolioOpen: true,
});
assert.deepEqual(navigation.parseLocationHash('#quality'), {
  route: 'settings', settingsSection: 'status',
});
assert.deepEqual(navigation.parseLocationHash('#backup'), {
  route: 'settings', settingsSection: 'recovery',
});
assert.deepEqual(navigation.parseLocationHash('#guide:market'), {
  route: 'settings', settingsSection: 'help',
});
assert.deepEqual(navigation.parseLocationHash('#review'), {
  route: 'settings', settingsSection: 'help',
});
assert.equal(navigation.assetDetailHash(' nvda ', 'chart'), '#asset/NVDA/chart');

assert.match(app, /<NotificationsPage/);
assert.match(app, /<Settings settingsSection=/);
assert.match(app, /assetDetailHash\(symbol, section\)/);
assert.match(app, /window\.addEventListener\('popstate', onLocation\)/);
assert.match(app, /argusNavigationIndex/);
assert.match(app, /historyHashRef/);
assert.match(app, /\.\.\.currentHistoryState\(\)/);
assert.doesNotMatch(app, /from '\.\/routes\/(Guide|CorePortfolio|DataQualityPage|BackupPage)'/);
assert.doesNotMatch(app, /AIReview|#review/);
assert.doesNotMatch(app, /useImportantEvents/);
assert.doesNotMatch(command, /ImportantEventsCard/);
assert.match(notifications, /<NotificationPanel \/>/);
assert.match(notifications, /<ImportantEventsCard/);
assert.match(settings, /<PublicDiagnosticsPanel \/>/);
assert.match(settings, /<BackupSettingsPanel/);
assert.doesNotMatch(shell, /NotificationPanel|unreadCounts|setInterval/);
assert.match(notificationPanel, /timeZone: 'Asia\/Tokyo'/);
assert.doesNotMatch(notificationPanel, /createdAt\.slice\(11, 16\)/);
assert.match(notificationEngine, /migrateLegacyNotification/);
assert.match(notificationEngine, /delete lastByDedupe\.vault/);
assert.match(notificationEngine, /Settings \/ Recovery → バックアップJSONを書き出す/);
assert.equal(notificationEngine.match(/Positions & Risk/g)?.length, 1,
  'legacy surface name may appear only in the local notification migration');
assert.doesNotMatch(app, /useActionLabels/);
assert.match(app, /#settings\/\$\{settingsSection\}/);

// Expensive detail/support trees mount only after the owner opens them.
assert.match(watchlist, /\{portfolioOpen && <CorePortfolio embedded \/>\}/);
assert.match(watchlist, /setPortfolioOpen\(initialPortfolioOpen\)/);
assert.doesNotMatch(watchlist, /if \(initialPortfolioOpen\) setPortfolioOpen/);
assert.match(watchlist, /\{supportOpen && <div className="ad-support__body">/);
assert.match(assetDecision, /\{supportOpen && <div className="ad-research-drawer__body">/);
assert.match(assetDecision, /interactive=\{collapsible\}/);
assert.match(assetSummary, /interactive \? \(/);
assert.match(backupPage, /\{actionsOpen && <div className="backup-actions__body">/);
assert.match(backupPage, /setActionsOpen\(initiallyOpen\)/);
assert.doesNotMatch(backupPage, /if \(initiallyOpen\) setActionsOpen/);

// Today keeps at most three owner priorities and links each visible row to the
// contextual Asset Detail route instead of a dead inline toggle.
assert.match(command, /holdings: ownerPriorities/);
assert.match(command, /onNavigateToAsset=\{onNavigateToAsset\}/);
assert.match(todayPanel, /OWNER PRIORITIES/);
assert.match(todayPanel, /onNavigateToAsset\(item\.symbol\)/);

// Public controls are cached reads or device-local actions, never mutation
// affordances that are guaranteed to fail without operator authentication.
assert.doesNotMatch(aiExplanation, /investigateNow|<button/);
assert.doesNotMatch(institutional, /autoQueueTranslations/);
assert.doesNotMatch(osintHook, /runDeepDive|verifyGaps|verifyUrl|postTerms|method:\s*['"]POST/);
assert.doesNotMatch(osintPanel, /深掘りOSINTを実行|未回収を再探索|追加して再調査/);

// Existing encrypted recovery stays readable, while unavailable push and the
// former 15-second browser loop stay absent.
const markLocalEdit = vault.slice(
  vault.indexOf('export function markLocalEdit'),
  vault.indexOf('async function fetchRemoteEnvelope'),
);
const startCloudSync = vault.slice(vault.indexOf('export function startCloudSync'));
assert.doesNotMatch(vault, /setInterval|cloudBackupNow|maybeCloudBackup|method:\s*['"]POST/);
assert.doesNotMatch(markLocalEdit, /setTimeout|cloudSyncNow|fetch\(/);
assert.match(startCloudSync, /cloudSyncNow\(\{ rawFallback: true \}\)/);
assert.match(startCloudSync, /visibilitychange/);
assert.doesNotMatch(startCloudSync, /setInterval|setTimeout/);
assert.match(backupCard, /公開ブラウザからのクラウド送信と端末間ライブ同期は利用できません/);
assert.match(backupCard, /今すぐエクスポート/);
assert.match(backupCard, /クラウドから復元/);
assert.doesNotMatch(backupCard, /今すぐ送信|cloudBackupNow/);

assert.match(deferredManifest, /Unreachable UI modules \(47\)/);
assert.match(deferredManifest, /Newly unreachable after B2a \(16\)/);
assert.match(deferredManifest, /63 unreachable component\/route TSX/);
assert.match(deferredManifest, /No domain engine, polling hook, storage format/);
assert.doesNotMatch(locales, /Asset Deskで銘柄カード/);

console.log('lean-surface.test: ok (4-nav, contextual detail, disclosure, recovery boundary)');
