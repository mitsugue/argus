import assert from 'node:assert/strict';
import { formatOutcomeSummary } from '../src/lib/marketLedgerFormat.ts';

assert.equal(formatOutcomeSummary('insufficient_data'), 'insufficient_data');
assert.equal(formatOutcomeSummary(null), 'insufficient_data');
assert.equal(formatOutcomeSummary({}), 'insufficient_data');
assert.equal(
  formatOutcomeSummary({ hitRate5d: 0.5882, average5dPct: 0.3656,
    maxDrawdownPct: -22.57, noFutureLeakage: true }),
  '5日hit 58.8% · 平均5日 0.37% · 最大下落 -22.57% · future leakageなし',
);

console.log('market-ledger.test: ok');
