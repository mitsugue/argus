// FUTURE MAP without a restart: read again when the app comes to the front,
// when Today is shown, and every five minutes while in front (not in the
// background); the table is replaced only when the server's version changed.
const assert = require('node:assert/strict'), path = require('node:path'), esbuild = require('esbuild'), Module = require('node:module');
const entry = path.resolve('src/hooks/useFutureMap.ts');
const code = esbuild.buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs',
  external: ['react'], define: { 'import.meta.env': JSON.stringify({ VITE_ARGUS_BACKEND_URL: 'https://be.example' }) },
  logLevel: 'silent' }).outputFiles[0].text;
const handlers = {}; let intervalFn = null, intervalMs = null, cleared = 0;
global.document = { visibilityState: 'visible',
  addEventListener: (name, fn) => { handlers[name] = fn; }, removeEventListener: name => { delete handlers[name]; } };
global.window = { setInterval: (fn, ms) => { intervalFn = fn; intervalMs = ms; return 1; }, clearInterval: () => { cleared += 1; } };
let server = null, reads = 0;
global.fetch = async url => { reads += 1; assert.equal(url, 'https://be.example/api/argus/future-map');
  return { ok: true, json: async () => server }; };
const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
const m = mod.exports;
const doc = (updatedAt, lastChangedAt, position) => ({ schemaVersion: 'argus-future-map-public-v1', availability: 'AVAILABLE',
  updatedAt, lastChangedAt, today: '2026-10-05', rows: [{ id: 'a', view: 'v', tag: '底' }],
  status: { position }, record: { scored: 0, reached: 0 }, argusValidated: false, actionAuthority: false });
const flush = () => new Promise(r => setImmediate(r));

(async () => {
  assert.equal(m.FUTURE_MAP_POLL_MS, 5 * 60_000);
  let renders = 0;
  const stop = m.futureMapSubscribeForTest(() => { renders += 1; });
  assert.equal(intervalMs, 5 * 60_000, 'one five-minute check while subscribed');
  // Today is shown: read at once.
  server = doc('2026-10-04T21:00:00+09:00', '2026-10-04T12:15:50Z', '天井圏');
  await m.refreshFutureMap(); await flush();
  assert.equal(reads, 1); assert.equal(renders, 1);
  // Five minutes in front, same version: read, but the table is not replaced.
  intervalFn(); await flush();
  assert.equal(reads, 2); assert.equal(renders, 1);
  // In the background: no check.
  document.visibilityState = 'hidden'; intervalFn(); await flush();
  assert.equal(reads, 2);
  // A new table arrives while in the background; back to the front: read at once and replace.
  server = doc('2026-10-06T00:00:00+09:00', '2026-10-05T15:01:00Z', '下落局面');
  document.visibilityState = 'visible'; handlers.visibilitychange(); await flush();
  assert.equal(reads, 3); assert.equal(renders, 2);
  // Only lastChangedAt changed (same updatedAt): still replaced.
  server = doc('2026-10-06T00:00:00+09:00', '2026-10-05T16:00:00Z', '下落局面');
  intervalFn(); await flush(); assert.equal(renders, 3);
  // Scoring matures while the forecast document stays unchanged.
  server = { ...server, scoring: { resultVersion: 'scored-a', status: 'AVAILABLE', lastError: null },
    record: { scored: 1, reached: 1 } };
  intervalFn(); await flush(); assert.equal(renders, 4);
  intervalFn(); await flush(); assert.equal(renders, 4, 'unchanged result must not replace the table');
  // A failed read keeps the last table.
  global.fetch = async () => { reads += 1; throw new Error('offline'); };
  intervalFn(); await flush(); assert.equal(renders, 4);
  // Unsubscribing stops the timer and the front/back listener.
  stop(); assert.equal(cleared, 1); assert.equal(handlers.visibilitychange, undefined);
  // The 30-minute reuse is gone.
  const src = require('node:fs').readFileSync(entry, 'utf8');
  assert.ok(!src.includes('30 * 60_000') && src.includes("useEffect(() => { void refreshFutureMap(); }, [])"));
  console.log('Future map refresh PASS');
})().catch(e => { console.error(e); process.exit(1); });
