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
const many=bar({text:'次の予定',events:[
  {name:'米国 中間選挙',when:'11/3・時刻未公表',remaining:null},
  {name:'米雇用統計',when:'11/6 22:30',remaining:null},
  {name:'日本SQ',when:'11/13・時刻未公表',remaining:null},
  {name:'4件目',when:'11/20',remaining:null},
]});
assert.equal((many.match(/<button /g)||[]).length,3);
assert(many.indexOf('中間選挙')<many.indexOf('雇用統計')&&many.indexOf('雇用統計')<many.indexOf('日本SQ'));
assert(!many.includes('4件目')&&many.includes('data-event-count="3"'));
assert.equal((many.match(/予定の一覧へ移る/g)||[]).length,3,'each preview retains its accessible EVENTS jump');

// The click handler is the shared jumpTo to #today-events; the Today strip uses the same function.
const src = fs.readFileSync('src/components/dashboard/MobileStickyCommand.tsx', 'utf8');
assert.ok(src.includes("onClick={() => jumpTo('today-events')}"));
assert.ok(src.includes("from '../../lib/todayJump'"));
const strip = fs.readFileSync('src/components/today/TodayDecisionStrip.tsx', 'utf8');
assert.ok(strip.includes("import { jumpTo } from '../../lib/todayJump'") && !strip.includes('function jumpTo('));
assert.ok(fs.readFileSync('src/components/today/ArgusTodayPanel.tsx', 'utf8').includes('<section id="today-events"'));
console.log('画面下の帯の次の予定 → EVENTS へ移る PASS');
