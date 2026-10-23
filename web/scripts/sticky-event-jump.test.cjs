// Owner request 2026-10-23: the bottom bar's next event opens Today's EVENTS block,
// with the same smooth move the Today tiles use (src/lib/todayJump.ts).
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const esbuild = require('esbuild'), Module = require('node:module');
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server');
const load = (file) => {
  const entry = path.resolve(file);
  const code = esbuild.buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react-dom', 'react/jsx-runtime'], loader: { '.css': 'empty' }, logLevel: 'silent' }).outputFiles[0].text;
  const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
  return mod.exports;
};
const calls = [];
const target = { scrollIntoView: (opts) => calls.push(['events', opts]) };
global.document = { getElementById: (id) => (id === 'today-events' ? target : null), querySelector: () => null };

const { jumpTo } = load('src/lib/todayJump.ts');
jumpTo('today-events');
assert.deepEqual(calls.pop(), ['events', { behavior: 'smooth', block: 'start' }]);

const sticky = load('src/components/dashboard/MobileStickyCommand.tsx');
const bar = (props) => renderToStaticMarkup(React.createElement(sticky.MobileStickyBar, props));
const withEvent = bar({ text: '次: 米CPI', event: { name: '米CPI', when: '10/24 21:30', remaining: 'あと2時間' } });
assert.ok(/<button type="button" class="msc__jump"/.test(withEvent), withEvent);
assert.ok(withEvent.includes('次: 米CPI') && withEvent.includes('10/24 21:30 · あと2時間'));
const plain = bar({ text: '予定はありません', event: null });
assert.ok(!plain.includes('<button') && plain.includes('予定はありません'), 'no event, no button');

// The click handler is the shared jumpTo to #today-events; the Today strip uses the same function.
const src = fs.readFileSync('src/components/dashboard/MobileStickyCommand.tsx', 'utf8');
assert.ok(src.includes("onClick={() => jumpTo('today-events')}"));
assert.ok(src.includes("from '../../lib/todayJump'"));
const strip = fs.readFileSync('src/components/today/TodayDecisionStrip.tsx', 'utf8');
assert.ok(strip.includes("import { jumpTo } from '../../lib/todayJump'") && !strip.includes('function jumpTo('));
assert.ok(fs.readFileSync('src/components/today/ArgusTodayPanel.tsx', 'utf8').includes('<section id="today-events"'));
console.log('画面下の帯の次の予定 → EVENTS へ移る PASS');
