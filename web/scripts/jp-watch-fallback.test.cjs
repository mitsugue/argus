// v13.5.43 — dynamic JP watchlist fallback: the public dynamic path answers an
// EMPTY mock snapshot when nothing is cached; the owner's symbols resolve from
// the curated J-Quants rows, never fabricated, never marked live.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};

const src = path.join(__dirname, '..', 'src');
const fb = require(path.join(src, 'domain', 'jpWatchFallback.ts'));

// production shape observed 2026-09-03: dynamic → {status:'mock', stocks:[]}
assert.equal(fb.dynamicSnapshotIsEmpty({ status: 'mock', asOf: null, stocks: [] }), true);
assert.equal(fb.dynamicSnapshotIsEmpty({ status: 'mock', stocks: [{ symbol: '5803', status: 'mock' }] }), true);
assert.equal(fb.dynamicSnapshotIsEmpty({ status: 'delayed', stocks: [{ symbol: '5803', status: 'delayed', price: 4951 }] }), false);
assert.equal(fb.dynamicSnapshotIsEmpty(null), true);

const curated = { status: 'delayed', asOf: '2026-09-03', stocks: [
  { symbol: '5803', status: 'delayed', price: 4951, source: 'jquants' },
  { symbol: '8058', status: 'delayed', price: 5059, source: 'jquants' },
  { symbol: '7203', status: 'delayed', price: 2900, source: 'jquants' },
  { symbol: '6758', status: 'mock' },
] };
const resolved = fb.resolveFromCurated(curated, ['5803', '9984', '6758']);
assert.equal(resolved.stocks.length, 1);                       // 9984 absent, 6758 mock → omitted
assert.equal(resolved.stocks[0].symbol, '5803');
assert.equal(resolved.stocks[0].price, 4951);
assert.equal(resolved.status, 'delayed');                      // never upgraded to live
assert.equal(resolved.resolvedFromCurated, true);
assert.equal(resolved.requestedCount, 3);
assert.equal(curated.stocks.length, 4);                        // input untouched
assert.equal(fb.resolveFromCurated(curated, ['9984']), null);  // nothing covered → caller keeps truthful empty
assert.equal(fb.resolveFromCurated(null, ['5803']), null);
assert.equal(fb.resolveFromCurated(curated, []), null);
const mixed = fb.resolveFromCurated({ status: 'mixed', stocks: [
  { symbol: '5803', status: 'delayed', price: 1 }, { symbol: '8058', status: 'live', price: 2 } ] }, ['5803', '8058']);
assert.equal(mixed.status, 'mixed');
// the hook wires the fallback only in dynamic mode and only when the dynamic answer is empty
const hook = fs.readFileSync(path.join(src, 'hooks', 'useJapanWatchlist.ts'), 'utf8');
assert.ok(hook.includes('if (dynamic && dynamicSnapshotIsEmpty('), 'fallback gated on dynamic + empty');
assert.ok(hook.includes('await fetchJson(curatedUrl)'), 'fallback reads the curated snapshot');
assert.ok(hook.includes('return normalizeJapanWatchSnapshot(dynamicSnapshot)'), 'dynamic answer kept when nothing resolves');
console.log('jp-watch-fallback.test: dynamic empty → curated rows, truthful status, no fabrication ok');

// ── v13.5.44: owner symbols the curated list lacks resolve from cached daily history ──
const hist = { symbol: '6965', available: true, dates: ['2026-09-03', '2026-09-02'], closes: [17280, 17000] };
const row = fb.rowFromPriceHistory('6965', hist);
assert.equal(row.price, 17280);
assert.equal(row.changePct, 1.65);
assert.equal(row.status, 'delayed'); assert.equal(row.source, 'jquants'); assert.equal(row.delayClass, 'EOD');
assert.equal(row.date, '2026-09-03');
assert.equal(row.volumeUnavailable, true);
assert.equal(fb.rowFromPriceHistory('6965', { available: false, closes: [], dates: [] }), null);
assert.equal(fb.rowFromPriceHistory('6965', null), null);
const merged = fb.mergeHistoryRows(resolved, [row], ['5803', '6965', '9984']);
assert.equal(merged.stocks.length, 2);
assert.equal(merged.stocks[1].symbol, '6965');
assert.equal(merged.status, 'delayed');
assert.equal(merged.historyRowCount, 1);
assert.equal(merged.asOf, '2026-09-03');
assert.equal(fb.mergeHistoryRows(resolved, [], ['5803']), resolved);      // nothing to add → identity
const fromEmpty = fb.mergeHistoryRows(null, [row], ['6965']);
assert.equal(fromEmpty.status, 'delayed'); assert.equal(fromEmpty.stocks.length, 1);
const hook2 = fs.readFileSync(path.join(src, 'hooks', 'useJapanWatchlist.ts'), 'utf8');
assert.ok(hook2.includes('/api/argus/price-history?symbol='), 'history fallback wired');
assert.ok(hook2.includes('.slice(0, 8)'), 'history fallback is bounded');
console.log('jp-watch-fallback.test: v13.5.44 history rows for owner symbols ok');
