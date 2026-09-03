// v13.5.36 — glossary coverage + display-only guard.
const fs = require('node:fs');
const path = require('node:path');
const src = path.join(__dirname, '..', 'src');
const read = (p) => fs.readFileSync(p, 'utf8');
let failures = 0;
const fail = (m) => { failures += 1; console.error('FAIL:', m); };

const glossary = read(path.join(src, 'domain', 'glossary.ts'));
const keys = new Set([...glossary.matchAll(/^  ([a-z_]+): \{/gm)].map((m) => m[1]));

// 1) display-only: the glossary imports nothing.
if (/^import /m.test(glossary)) fail('glossary.ts must not import anything');

// 2) every mapped rendered-state resolves to a real entry.
for (const name of ['REVERSAL_STATE_GLOSSARY', 'FAMILY_STATE_GLOSSARY',
  'MARKET_SIGNAL_STATE_GLOSSARY', 'TACHIBANA_STATUS_GLOSSARY']) {
  const block = glossary.split(name)[1]?.split('};')[0] ?? '';
  for (const m of block.matchAll(/'([a-z_]+)'/g)) {
    if (!keys.has(m[1])) fail(`${name} references missing glossary key ${m[1]}`);
  }
}

// 3) every SHO reversal state rendered in the panel has a glossary mapping.
const panel = read(path.join(src, 'components', 'today', 'ArgusTodayPanel.tsx'));
const shoStates = [...(panel.split('SHO_STATE_JA')[1]?.split('};')[0] ?? '')
  .matchAll(/([A-Z_]+):/g)].map((m) => m[1]);
const reversalMap = glossary.split('REVERSAL_STATE_GLOSSARY')[1]?.split('};')[0] ?? '';
for (const state of shoStates) {
  if (!reversalMap.includes(`${state}:`)) fail(`SHO state ${state} lacks glossary mapping`);
}

// 4) the panel actually uses the tap tips.
if (!panel.includes('GlossaryTip')) fail('ArgusTodayPanel must render GlossaryTip');

// 5) GlossaryTip stays decoupled from the decision layer.
const tip = read(path.join(src, 'components', 'common', 'GlossaryTip.tsx'));
for (const banned of ['assetDecision', 'useAssetIntel', 'singleDecisionAuthority',
  'useDecisionEvidence', 'newsSignalGate']) {
  if (tip.includes(banned)) fail(`GlossaryTip must not couple to ${banned}`);
}

if (failures > 0) process.exit(1);
console.log(`glossary.test: ok (${keys.size} entries; states covered; display-only)`);
