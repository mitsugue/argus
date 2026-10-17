// v13.5.49 — important events are named in Japanese on the owner surface.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};
const src = path.join(__dirname, '..', 'src');
const m = require(path.join(src, 'domain', 'eventTitleJa.ts'));
assert.equal(m.eventTitleJa('NFP', 'US Employment Situation'), '米雇用統計');
assert.equal(m.eventTitleJa('AUCTION', 'US Treasury 10-Year Auction'), '米10年債入札');
assert.equal(m.eventTitleJa('AUCTION', 'US Treasury 30-Year Auction'), '米30年債入札');
assert.equal(m.eventTitleJa('PCE', 'US PCE / Personal Income & Outlays'), '米PCE物価指数(個人所得・支出)');
assert.equal(m.eventTitleJa('FOMC', 'FOMC Rate Decision'), 'FOMC(米政策金利)');
assert.equal(m.eventTitleJa('ISM', 'ISM Manufacturing PMI'), '米ISM製造業景況指数');
assert.equal(m.eventTitleJa('CPI', 'Consumer Price Index (US)'), '米消費者物価指数(CPI)');   // code fallback
assert.equal(m.eventTitleJa('BOJ', '日銀金融政策決定会合'), '日銀金融政策決定会合');            // already Japanese
assert.equal(m.eventTitleJa('ZZZ', 'Some Unknown Release'), 'Some Unknown Release');       // never invented
assert.equal(m.eventTitleIsJapanese('米雇用統計'), true);
assert.equal(m.eventTitleIsJapanese('US Employment Situation'), false);
const card = fs.readFileSync(path.join(src, 'components', 'dashboard', 'ImportantEventsCard.tsx'), 'utf8');
assert.ok(card.includes('eventTitleJa('), 'card renders the Japanese title');
console.log('event-title-ja.test: important events named in Japanese ok');
