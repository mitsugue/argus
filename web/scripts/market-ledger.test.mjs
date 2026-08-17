import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const hook = readFileSync(new URL('../src/hooks/useMarketLedger.ts', import.meta.url), 'utf8');
const command = readFileSync(new URL('../src/routes/CommandCenter.tsx', import.meta.url), 'utf8');
const today = readFileSync(new URL('../src/components/today/ArgusTodayPanel.tsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

assert.match(hook, /createSharedPollingStore/, 'market ledger keeps one background lifecycle');
assert.match(hook, /\/api\/argus\/market-ledger/);
assert.doesNotMatch(hook, /method:\s*['"]POST/);
assert.match(command, /useMarketLedger/);
assert.match(command, /marketLedger\.ledger\?\.phase3\?\.calendar/);
assert.match(command, /positioning/);
assert.match(today, /className="at-positioning"/,
  'minimum ledger-derived positioning evidence remains in Today');
assert.doesNotMatch(app, /MarketRegime|#market/);
assert.equal(existsSync(new URL('../src/components/regime/MarketLedgerPanel.tsx', import.meta.url)), false);

console.log('market-ledger.test: ok (background ledger preserved, evidence moved to Today)');
