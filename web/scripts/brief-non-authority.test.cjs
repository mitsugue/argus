// v13.5.33 — MARKET SITUATION BRIEF non-authority guard (TS import boundary).
// Invariant: the brief is OUTPUT/EXPLANATION ONLY. The decision layer
// (domain/*, useAssetIntel, useDecisionEvidence) must never import or
// reference it; the ONLY permitted consumer is the Today display card.
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..', 'src');
const read = (p) => fs.readFileSync(p, 'utf8');
const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap(
  (e) => e.isDirectory() ? walk(path.join(dir, e.name))
    : /\.(ts|tsx)$/.test(e.name) ? [path.join(dir, e.name)] : []);

let failures = 0;
const fail = (msg) => { failures += 1; console.error('FAIL:', msg); };

// 1) authority layer never references the brief
const authorityFiles = [
  ...walk(path.join(root, 'domain')),
  path.join(root, 'hooks', 'useAssetIntel.ts'),
  path.join(root, 'hooks', 'useDecisionEvidence.ts'),
];
for (const file of authorityFiles) {
  const text = read(file);
  for (const banned of ['useMarketBrief', 'market-brief', 'MarketBrief']) {
    if (text.includes(banned)) {
      fail(`${path.relative(root, file)} references forbidden "${banned}"`);
    }
  }
}

// 2) import-boundary: enumerate every importer of the brief hook — the set
//    must be exactly the Today display card.
const importers = [];
for (const file of walk(root)) {
  if (file.endsWith(`hooks${path.sep}useMarketBrief.ts`)) continue;
  const text = read(file);
  if (/import[^;]*useMarketBrief/.test(text)) {
    importers.push(path.relative(root, file).split(path.sep).join('/'));
  }
}
const expected = ['components/today/ArgusTodayPanel.tsx'];
if (JSON.stringify(importers.sort()) !== JSON.stringify(expected)) {
  fail(`useMarketBrief importers must be exactly ${JSON.stringify(expected)}, `
    + `got ${JSON.stringify(importers)}`);
}

// 3) reverse coupling: the brief hook must not import the decision layer.
const hookText = read(path.join(root, 'hooks', 'useMarketBrief.ts'));
for (const banned of ['domain/', 'useAssetIntel', 'useDecisionEvidence',
  'assetDecision']) {
  if (hookText.includes(banned)) {
    fail(`useMarketBrief.ts must not couple to the decision layer ("${banned}")`);
  }
}

if (failures > 0) process.exit(1);
console.log('brief-non-authority.test: ok (display-only importer set; '
  + 'decision layer clean; no reverse coupling)');
