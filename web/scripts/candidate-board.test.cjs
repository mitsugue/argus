// Candidate scoreboard: outside Today, thin candidates say "件数不足", no trading words.
const assert = require('node:assert/strict'), path = require('node:path'), esbuild = require('esbuild'), Module = require('node:module');
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server');
const entry = path.resolve('src/components/today/CandidateBoard.tsx');
const code = esbuild.buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react-dom', 'react/jsx-runtime'], loader: { '.css': 'empty' },
  define: { 'import.meta.env': JSON.stringify({ VITE_ARGUS_BACKEND_URL: '' }) }, logLevel: 'silent' }).outputFiles[0].text;
const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
const row = (candidate, extra = {}) => ({ candidate, labelJa: candidate, dataStatus: 'RECORDING', records: 0, open: 0, reached: 0,
  broken: 0, ambiguous: 0, expired: 0, skipped: 0, medianDaysToReach: null, meanEtfReturnPct: null, enoughRecords: false, ...extra });
const candidates = { since: '2026-10-05', tradingSignal: false, noteJa: '記録中の候補(未検証)。売買の合図ではありません。',
  missedSignals: [{ candidate: 'S4', signalDate: '2026-10-06' }],
  scoreboard: [row('R1', { records: 2, open: 1, reached: 1 }), row('S6', { dataStatus: 'NOT_IN_PRODUCT' }),
    row('S3', { records: 12, reached: 7, broken: 3, expired: 2, enoughRecords: true, medianDaysToReach: 6, meanEtfReturnPct: 1.4 })] };
const html = renderToStaticMarkup(React.createElement(mod.exports.CandidateBoardView, { candidates }));
assert.ok(html.includes('候補の事前記録(未検証)') && html.includes('売買の合図ではありません'));
assert.ok(html.includes('件数不足(1/0/0/0)') && html.includes('データなし'));
assert.ok(html.includes('+1.4%') && html.includes('S4 2026-10-06'));
for (const word of ['BUY', '買い時', '確率']) assert.ok(!html.includes(word), word);
assert.equal(renderToStaticMarkup(React.createElement(mod.exports.CandidateBoardView, { candidates: null })), '');
console.log('Candidate board PASS');
