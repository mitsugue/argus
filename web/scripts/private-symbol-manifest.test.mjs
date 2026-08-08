import assert from 'node:assert/strict';
import { buildPrivateSymbolManifest } from '../src/lib/privateSymbolManifest.mjs';

const manifest = buildPrivateSymbolManifest([
  { market: 'JP', symbol: '7203', enabled: false, quantity: 10,
    avgCost: 2100, currentValue: 999999, pnl: 123, allocation: 20,
    memo: 'private note', displayName: 'Toyota', label: 'owner' },
  { market: 'US', symbol: 'nvda', enabled: true, quantity: 0, avgCost: 100 },
  { market: 'JP', symbol: '7203', enabled: true },
  { market: 'CORE', symbol: 'PRIVATE-FUND', enabled: true, quantity: 5 },
], '2026-08-05T00:00:00.000Z');

assert.deepEqual(manifest.symbols, ['JP.7203', 'US.NVDA']);
assert.deepEqual(Object.keys(manifest).sort(),
  ['asOf', 'revision', 'schemaVersion', 'symbols']);
const serialized = JSON.stringify(manifest).toLowerCase();
for (const forbidden of ['quantity', 'avgcost', 'value', 'pnl', 'allocation',
  'memo', 'note', 'label', 'displayname', 'toyota']) {
  assert.equal(serialized.includes(forbidden), false, forbidden);
}
assert.equal(manifest.revision.length >= 8, true);
assert.equal(buildPrivateSymbolManifest([], '2026-08-05T00:00:00.000Z'), null);
console.log('private-symbol-manifest: ok');
