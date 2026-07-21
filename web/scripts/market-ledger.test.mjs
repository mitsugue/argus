import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const formatter = readFileSync(new URL('../src/lib/marketLedgerFormat.ts', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../src/components/regime/MarketLedgerPanel.tsx', import.meta.url), 'utf8');

assert.match(formatter, /typeof summary === 'string'/, 'legacy string summaries stay supported');
assert.match(formatter, /typeof summary\.hitRate5d === 'number'/, 'structured hit rate is formatted');
assert.match(formatter, /summary\.noFutureLeakage === true/, 'leakage result is formatted');
assert.match(formatter, /return parts\.length \? parts\.join\(' · '\) : 'insufficient_data'/,
  'empty structured summaries fail closed');
assert.match(panel, /formatOutcomeSummary\(rule\.outcomeSummary\)/,
  'Rule Card must never render the structured object directly');
assert.doesNotMatch(panel, /<small>\{rule\.outcomeSummary\}/,
  'the regression-causing React child is absent');

console.log('market-ledger.test: ok');
