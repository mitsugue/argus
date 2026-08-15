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

const { createSharedPollingStore } = await importTypeScriptModule('src/lib/sharedPollingStore.ts');

let starts = 0;
let stops = 0;
const shared = createSharedPollingStore({ value: 0 }, () => {
  starts += 1;
  return () => { stops += 1; };
});
const notifications = [0, 0, 0];
const unsubscribe = notifications.map((_, index) => shared.subscribe(() => { notifications[index] += 1; }));
assert.equal(starts, 1, 'three consumers must start one acquisition lifecycle');
shared.setSnapshot((current) => ({ value: current.value + 1 }));
assert.deepEqual(notifications, [1, 1, 1]);
unsubscribe[0]();
unsubscribe[1]();
assert.equal(stops, 0, 'polling must continue while one consumer remains');
unsubscribe[2]();
assert.equal(stops, 1, 'the final consumer must stop the shared lifecycle');

let quoteStarts = 0;
const quoteStore = () => createSharedPollingStore({}, () => {
  quoteStarts += 1;
  return () => {};
});
const jp = quoteStore();
const usQuotes = quoteStore();
const quoteUnsubscribe = [jp.subscribe(() => {}), jp.subscribe(() => {}),
  usQuotes.subscribe(() => {}), usQuotes.subscribe(() => {})];
assert.equal(quoteStarts, 2, 'two JP and two US consumers must start two keyed lifecycles');
quoteUnsubscribe.forEach((stop) => stop());

const important = read('src/hooks/useImportantEvents.ts');
const ledger = read('src/hooks/useMarketLedger.ts');
const actions = read('src/hooks/useActionLabels.ts');
const japan = read('src/hooks/useJapanWatchlist.ts');
const us = read('src/hooks/useUSWatchlist.ts');
const pwa = read('src/main.tsx');
const command = read('src/routes/CommandCenter.tsx');
const diagnostics = read('src/routes/DataQualityPage.tsx');
const systemHealth = read('src/hooks/useSystemHealth.ts');
const activeEvents = read('src/hooks/useEventsActive.ts');
const assetsStore = read('src/hooks/useAssets.ts');
const assetIntel = read('src/hooks/useAssetIntel.ts');
const fundNav = read('src/hooks/useFundNav.ts');
const holdings = read('src/routes/Watchlist.tsx');
const assetDesk = read('src/components/assetDesk/AssetDeskList.tsx');
const portfolio = read('src/routes/CorePortfolio.tsx');
const trades = read('src/components/dashboard/TradeJournalCard.tsx');

for (const source of [important, ledger, actions, japan, us]) {
  assert.match(source, /useSyncExternalStore/);
  assert.match(source, /createSharedPollingStore/);
  assert.doesNotMatch(source, /useEffect|useState/);
}
for (const source of [important, actions, japan, us]) {
  assert.match(source, /const controllers = new Set<AbortController>\(\)/);
  assert.match(source, /for \(const controller of controllers\) controller\.abort\(\)/);
}
assert.match(important, /const importantEventsStore = createSharedPollingStore/);
assert.match(important, /if \(acquisition\) return acquisition/);
assert.match(ledger, /const marketLedgerStore = createSharedPollingStore/);
assert.match(actions, /const actionLabelStores = new Map/);
assert.match(actions, /JSON\.stringify\(\[jpKey, usKey\]\)/);
assert.match(japan, /const japanWatchlistStores = new Map/);
assert.match(us, /const usWatchlistStores = new Map/);
for (const source of [actions, japan, us]) {
  assert.match(source, /void acquire\(run\)/);
  assert.match(source, /void acquire\(refresh\)/);
}

// The PWA update and deployed-version checks share one 60-second scheduler.
assert.equal((pwa.match(/(?:window\.)?setInterval\(/g) ?? []).length, 1);
assert.match(pwa, /signal: ctrl\.signal/);
assert.match(pwa, /serviceWorkerUpdateInFlight/);
assert.match(pwa, /versionReconcileInFlight/);
assert.match(pwa, /waitAtMost\(updateServiceWorkerOnce\(\), PWA_STEP_TIMEOUT_MS\)/);
assert.match(pwa, /waitAtMost\(reconcileVersionOnce\(\), PWA_RECONCILE_TIMEOUT_MS\)/);
assert.match(pwa, /if \(pwaPollInFlight\) return pwaPollInFlight/);
assert.match(pwa, /pollPwaState\(false\)/);

// System health is nested in the canonical public diagnostics response. The
// module-level request is shared and deliberately has no persistent timer.
assert.match(systemHealth, /\/api\/argus\/data-quality\/status/);
assert.doesNotMatch(systemHealth, /\/api\/argus\/system-health|setInterval/);
assert.match(command, /usePublicDiagnostics/);
assert.match(diagnostics, /usePublicDiagnostics/);

// Event list and status share one 15-second endpoint read.
assert.match(activeEvents, /\/api\/argus\/events-active/);
assert.doesNotMatch(activeEvents, /event-backbone-status|Promise\.all/);
assert.equal((activeEvents.match(/fetch\(/g) ?? []).length, 1);

// The protected asset store has one provider-owned persistence/sync lifecycle.
assert.match(assetsStore, /function useAssetsStore/);
assert.match(assetsStore, /export function AssetsProvider/);
assert.match(pwa, /<AssetsProvider>/);

// Holdings mounts one intelligence pipeline. Its children are prop-driven;
// Fund NAV is acquired once inside that pipeline and Trade owns no quote loop.
assert.equal((holdings.match(/useAssetIntel\(/g) ?? []).length, 1);
assert.doesNotMatch(assetIntel, /useAssets\(/);
assert.equal((assetIntel.match(/useFundNav\(/g) ?? []).length, 1);
assert.equal((fundNav.match(/\/api\/argus\/fund-nav/g) ?? []).length, 1);
for (const source of [assetDesk, portfolio]) {
  assert.doesNotMatch(source, /useAssetIntel\(|useFundNav\(/);
}
assert.doesNotMatch(trades, /useJapanWatchlist|useUSWatchlist|setInterval/);
assert.match(trades, /priceBySymbol/);

console.log('polling-singleton.test: ok (assets/intel/NAV 1, Trade loops 0, event read 1, health timer 0)');
