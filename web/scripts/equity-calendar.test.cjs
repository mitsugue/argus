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

const base={eventId:'fixture-A',kind:'CORPORATE_EARNINGS',date:'2026-11-05',dateOnly:true,at:'2026-11-05T00:00:00-05:00',rangeEndAt:'2026-11-06T23:59:59-05:00',sourceFromDate:'2026-11-05',sourceToDate:'2026-11-06',sourceTimezone:'America/New_York',market:'US',daysUntil:5,titleJa:'共有株 決算（推定）',importance:'medium',whatJa:'決算予定',soWhatJa:'業績を確認',watchJa:'会社予想',source:'Yahoo Finance',certainty:'PROVIDER_ESTIMATE',receivedAt:'2026-10-31T01:00:00Z',actionAuthority:false};
const envelope=e=>({schemaVersion:'jp-equity-event-calendar-v1',status:'AVAILABLE',events:[e],gaps:[],automaticAiCalls:0,actionAuthority:false});
assert(c.validEquityCalendar(envelope(base)));
for(const change of [{market:'OTHER'},{sourceTimezone:'UTC'},{dateOnly:false},{sourceFromDate:'2026-02-30'}, {sourceToDate:'2026-12-01'}, {sourceToDate:'2026-11-04'}, {date:'2026-11-04'}, {rangeEndAt:'invalid'}, {rangeEndAt:'2026-11-07T23:59:59-05:00'}, {at:'2026-11-05T00:00:00+09:00'}, {source:'unknown'}, {certainty:'ACTUAL'}, {receivedAt:'2026-10-31T01:00:00'}, {at:'2026-11-05T00:00:00'}, {rangeEndAt:'2026-11-06T12:00:00-05:00'}, {rangeEndAt:'2026-11-06T23:59:59-04:00'}, {certainty:'COMPANY_SCHEDULE'}]) assert.equal(c.validEquityCalendar(envelope({...base,...change})),false,JSON.stringify(change));
assert(c.validEquityCalendar(envelope({...base,eventId:'fixture-J',market:'JP',sourceTimezone:'Asia/Tokyo',at:'2026-11-05T00:00:00+09:00',rangeEndAt:'2026-11-05T23:59:59+09:00',sourceToDate:'2026-11-05',source:'J-Quants 決算発表予定日',certainty:'COMPANY_SCHEDULE'})));
console.log('予定と実公表の区別・日米の時差・範囲・受領・出典の契約を確認');
