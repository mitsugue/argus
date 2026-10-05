// FUTURE MAP: three boxes, the table with the seven tags, the current row,
// the emphasised row, four rows first and the "show all" button, no names.
const assert = require('node:assert/strict'), path = require('node:path'), esbuild = require('esbuild'), Module = require('node:module');
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server');
const entry = path.resolve('src/components/today/FutureMapCard.tsx');
const code = esbuild.buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs',
  jsx: 'automatic', external: ['react', 'react-dom', 'react/jsx-runtime'], loader: { '.css': 'empty' },
  define: { 'import.meta.env': JSON.stringify({ VITE_ARGUS_BACKEND_URL: '' }) }, logLevel: 'silent' }).outputFiles[0].text;
const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
const { FutureMapView, futureMapUpdateAge } = mod.exports;
const tone = { '売り時': 'red', '急落': 'red', '下落': 'red', '戻り': 'amber', '注意': 'amber', '底': 'green', '大底': 'green', '―': 'grey' };
const row = (id, periodLabel, view, tag, extra = {}) => ({ id, periodLabel, start: '2026-10-01', end: '2026-10-10', view,
  reason: null, alt: null, level: null, tag, tone: tone[tag], agree: 1, emphasis: false, changed: false, result: null,
  isNow: false, past: false, ...extra });
const doc = { schemaVersion: 'argus-future-map-public-v1', updatedAt: '2026-10-04T21:00:00+09:00', today: '2026-10-04',
  status: { position: '天井圏', nextAlert: { date: '2026-10-14', label: '米CPI' }, nextBottom: { date: '2026-10-30', label: '10/30ごろ' } },
  rows: [row('a', '10/1〜10/10', '天井。上がっても7万円前後まで', '売り時', { isNow: true, agree: 2, level: { low: 69700, high: 72000 } }),
    row('b', '10/14前後', '米CPIで急落の恐れ', '急落'),
    row('c', '10月中旬〜', '下げ相場に入る', '下落', { reason: 'AI投資の反動' }),
    row('d', '10/19ごろ', '一時的な戻り', '戻り', { level: { low: 65500, high: 65500 } }),
    row('e', '11/3', '中間選挙。結果しだいで急落', '急落', { alt: '選挙後は上がる' }),
    row('f', '12/25前後', 'クリスマスが底', '大底', { emphasis: true }),
    row('g', '1月〜', '見立てなし', '―', { agree: 0 })],
  record: { scored: 0, reached: 0 }, argusValidated: false, actionAuthority: false };
const html = renderToStaticMarkup(React.createElement(FutureMapView, { doc }));
assert.ok(html.includes('FUTURE MAP') && html.includes('外部の見立て') && html.includes('ARGUS未検証') && html.includes('10/4更新'));
assert.ok(html.includes('いまの位置') && html.includes('天井圏') && html.includes('10/14 米CPI') && html.includes('10/30ごろ'));
assert.ok(html.includes('いまここ') && html.includes('●●') && html.includes('69,700〜72,000'));
assert.ok(html.includes('AI投資の反動') && html.includes('別の見方: 選挙後は上がる') === false, 'only four rows at first');
assert.ok(html.includes('すべて表示（残り3件・12/25前後 クリスマスが底まで）'));
assert.ok(html.includes('見立ての成績: 10/5から採点') && html.includes('●の数 = 同じことを言っている見立ての数'));
for (const word of ['src_a', 'src_b', 'BUY', '確率']) assert.ok(!html.includes(word), word);
assert.equal(renderToStaticMarkup(React.createElement(FutureMapView, { doc: null })), '');
const scored = renderToStaticMarkup(React.createElement(FutureMapView, { doc: { ...doc, record: { scored: 3, reached: 2 } } }));
assert.ok(scored.includes('見立ての成績: 3件中2件到達'));
const at = stamp => Date.parse(stamp);
assert.deepEqual(futureMapUpdateAge(doc.updatedAt, at('2026-10-05T11:59:59Z')),
  { days: 0, warning: false, label: '24時間以内の更新' });
assert.equal(futureMapUpdateAge(doc.updatedAt, at('2026-10-07T11:59:59Z')).warning, false);
assert.deepEqual(futureMapUpdateAge(doc.updatedAt, at('2026-10-07T12:00:00Z')),
  { days: 3, warning: true, label: '3日前の更新・古い予測です' });
for (const stamp of ['', 'not-a-time', '2026-10-04T21:00:00', '2026-10-08T12:00:00Z']) {
  assert.deepEqual(futureMapUpdateAge(stamp, at('2026-10-07T12:00:00Z')),
    { days: null, warning: true, label: '更新日時を確認できません' });
}
const stale = renderToStaticMarkup(React.createElement(FutureMapView,
  { doc, nowMs: at('2026-10-07T12:00:00Z') }));
assert.ok(stale.includes('3日前の更新・古い予測です') && stale.includes('fm-age is-warning'));
assert.ok(stale.includes('69,700〜72,000') && stale.includes('いまここ'), 'stale warning preserves saved view');
const fresh = renderToStaticMarkup(React.createElement(FutureMapView,
  { doc, nowMs: at('2026-10-04T12:01:00Z') }));
assert.ok(fresh.includes('24時間以内の更新') && !fresh.includes('fm-age is-warning'));
console.log('Future map card: exact age threshold, unknown clock, saved table preservation PASS');
