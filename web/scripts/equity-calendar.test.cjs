const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const c = require('../src/lib/japanEquityCalendar.ts');
const real = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'equity-calendar.json'), 'utf8'));

// The backend's own output passes; every row carries what it means.
assert.equal(c.validEquityCalendar(real), true);
assert(real.events.every(e => e.soWhatJa && e.whatJa && e.watchJa));
const ex = real.events.find(e => e.kind === 'EX_DIVIDEND');
assert.equal(c.equityEventWhen(ex), '12/29(火)');
const cpi = real.events.find(e => e.kind === 'JP_CPI');
assert.equal(c.equityEventWhen(cpi), '10/23(金) 8:30');
assert.equal(c.equityEventDistance({ ...cpi, daysUntil: 0 }, Date.parse('2026-10-23T08:00:00+09:00')), '今日');
assert.equal(c.equityEventDistance({ ...cpi, daysUntil: 0 }, Date.parse('2026-10-23T09:00:00+09:00')), '発表済み');

// Malformed or authority-carrying data is rejected.
for (const mutate of [
  d => { d.actionAuthority = true; },
  d => { d.events[0].soWhatJa = ''; },
  d => { d.events[0].importance = 'urgent'; },
  d => { d.automaticAiCalls = 1; },
]) {
  const copy = JSON.parse(JSON.stringify(real)); mutate(copy);
  assert.equal(c.validEquityCalendar(copy), false);
}
console.log('Equity event calendar: real output valid, every event says what it means, malformed rejected PASS');
