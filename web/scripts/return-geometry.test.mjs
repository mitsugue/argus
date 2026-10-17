import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const source = fs.readFileSync(fileURLToPath(new URL('../src/App.tsx', import.meta.url)), 'utf8');
const effect = source.slice(source.indexOf('    let settleFrame = 0;'), source.indexOf('  }, []);', source.indexOf('    let settleFrame = 0;')));
const run = vm.runInNewContext(`(function(){${effect}})`, {
  applyBoundedMobileSafeBottom: () => { measurements.push(inset); },
  window: {
    requestAnimationFrame: cb => { frames.set(++serial, cb); return serial; },
    cancelAnimationFrame: id => frames.delete(id),
    addEventListener: (kind, cb) => events.set(kind, cb),
    removeEventListener: kind => events.delete(kind),
    visualViewport: { addEventListener: (kind, cb) => events.set('viewport:' + kind, cb), removeEventListener: kind => events.delete('viewport:' + kind) },
  },
  document: { visibilityState: 'visible', addEventListener: (kind, cb) => events.set(kind, cb), removeEventListener: kind => events.delete(kind) },
});
let inset = 0, serial = 0; const measurements = [], frames = new Map(), events = new Map();
const cleanup = run();
const frame = () => { const pending = [...frames.values()]; frames.clear(); pending.forEach(cb => cb()); };
events.get('pageshow')(); assert.equal(measurements.at(-1), 0);
frame(); inset = 34; frame(); assert.equal(measurements.at(-1), 34, 'BFCache復帰後に確定した余白を反映');
events.get('viewport:resize')(); events.get('pageshow')(); assert.equal(frames.size, 1, '重複する復帰イベントをまとめる');
cleanup(); assert.equal(frames.size, 0); assert.equal(events.size, 0);
// Audit 2026-10-17: only a navigation tap opens Watchlist at its top; the
// asset back button and the overscroll page turn keep their landing position.
const tap = source.slice(source.indexOf('const handleNavTap'), source.indexOf('};', source.indexOf('const handleNavTap')));
assert.ok(tap.includes("setWatchlistScrollReset"), 'タップで先頭へ');
const select = source.slice(source.indexOf('const handleNavSelect'), source.indexOf('};', source.indexOf('const handleNavSelect')));
assert.ok(!select.includes('setWatchlistScrollReset'), '戻る・ページ送りでは先頭へ戻さない');
assert.ok(source.includes('onSelect={handleNavTap}') && source.includes('onNavigate={handleNavTap}'));
assert.ok(source.includes("onBackToHoldings={() => handleNavSelect('watchlist')}"));
assert.ok(/go: \(\) => handleNavSelect\(PRIMARY_NAVIGATION\[curIdx \+ 1\]\.route\)/.test(source));
console.log('画面復帰: 遅れて確定した34px余白・重複・破棄 PASS（実機は別確認）');
