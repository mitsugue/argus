// Boot console contract: one centered, non-blocking status card that reports
// the real state of every Today lane until all have settled. It must never
// fabricate progress, never block the page, never issue writes, and must be
// rendered through a body portal (the shell transform pins fixed elements).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');

const component = read('src/components/today/BootConsole.tsx');
const css = read('src/components/today/BootConsole.css');
const command = read('src/routes/CommandCenter.tsx');

// Real progress only: settled lanes over total lanes.
assert.match(component, /const done = lanes\.filter\(\(lane\) => settled\(lane\.status\)\)\.length/);
assert.match(component, /Math\.round\(\(done \/ total\) \* 100\)/);
assert.doesNotMatch(component, /setInterval|Math\.random|fakeProgress|simulated/i,
  'progress must come from lane state, never a timer or a random walk');

// Lanes follow the Today screen from top to bottom (owner, 2026-10-04), in English.
const order = ['Today outlook', 'FUTURE MAP', 'Nikkei 225 & analogs', 'Decision evidence',
  'Material news', 'Event calendar'];
const positions = order.map((label) => component.indexOf(`label: '${label}'`));
assert.ok(positions.every((at) => at > 0), 'every lane is present');
assert.deepEqual([...positions].sort((a, b) => a - b), positions, 'lanes are in screen order');
assert.equal((component.match(/\{ id: '/g) ?? []).length, order.length, 'no lane outside the screen');
// The market headline feeds the Nikkei chart lane. A stored headline shown
// while it is re-read is still loading; only a failed re-read is 'cached'.
assert.match(component, /headline\.reason === 'revalidating' \? 'loading' : 'cached'/);
assert.match(component, /combine\(combine\(chart, index\), headlineStatus\)/);
assert.match(component, /status: futureMap/);

// Failure is reported, not hidden.
assert.match(component, /'unavailable'/);
assert.match(component, /STATUS_WORD/);

// The integrated outlook is a stored judgment by design (the product does not
// run the AI on every page load), so a judgment that is current for the latest
// scheduled run reads 'ready'; only a missed run reads 'cached'.
assert.match(component, /judgment\.data\.freshness === 'stale' \? 'cached' : 'ready'/);
assert.doesNotMatch(component, /judgment\.phase === 'live' \? 'ready'/,
  'a live AI run must not be the only path to a ready outlook');

// Stays until every lane settles, then closes after a short hold; the user
// can dismiss it, and nothing re-opens it during the session.
assert.match(component, /const complete = done === total/);
assert.match(component, /SETTLED_HOLD_MS/);
assert.match(component, /aria-label="Dismiss"/);

// Accessibility and rendering contract.
assert.match(component, /createPortal\(/);
assert.match(component, /document\.body/);
assert.match(component, /role="status" aria-live="polite"/);
assert.match(component, /<TriangleStepLoader compact/);
assert.doesNotMatch(component, /method: 'POST'|fetch\(/,
  'the console only reads hook state; it performs no network calls of its own');

// Non-blocking, small, centered, calm.
assert.match(css, /\.boot-console\{[^}]*position:fixed/s);
assert.match(css, /\.boot-console\{[^}]*pointer-events:none/s);
assert.match(css, /\.boot-console__dismiss\{[^}]*pointer-events:auto/s);
assert.match(css, /width:min\(300px,calc\(100vw - 32px\)\)/);
assert.match(css, /\.boot-console__bar\{[^}]*height:2px/s);
assert.match(css, /prefers-reduced-motion:reduce/);
assert.doesNotMatch(css, /rotate\(/);

// Mounted once on Today with the live hook states.
assert.match(command, /<BootConsole inputs=\{\{/);
assert.match(command, /snapshotState: selectedChart\.snapshotState/);
assert.match(command, /loading: decisionEvidence\.loading/);
assert.equal((command.match(/<BootConsole /g) ?? []).length, 1);

console.log('boot-console.test: ok (real progress, screen-order lanes, portal, non-blocking, reduced motion)');
