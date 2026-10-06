const fs = require('node:fs'), vm = require('node:vm'), ts = require('typescript');
const assert = require('node:assert/strict');
const factId = 'brief-fact-' + 'a'.repeat(64), contextId = 'b'.repeat(64), recordId = 'c'.repeat(64);
const fact = { evidenceId: factId, text: '保存した市場の根拠', source: 'official_sensor', priority: 'P0', verification: 'VERIFIED' };
const saved = { schemaVersion: 'argus-market-brief-v1', generatedAt: '2026-10-05T01:00:00Z',
  sdaAuthority: false, now: '要約', why: '理由', next: '確認', chips: { chart: '', news: '', nextEvent: '', mainRisk: '' }, facts: [fact],
  unifiedStatus: 'GENERATED', unifiedContext: { contextId, facts: [fact], previousFacts: [] },
  unifiedSummary: { schemaVersion: 'argus-unified-brief-v1', contextId, actionAuthority: false,
    ownerContextAvailable: false, historyStatus: 'LOCAL_DURABLE', sections: Object.fromEntries(
      ['view', 'reasons', 'changes', 'impact', 'next', 'invalidation'].map(key => [key, {
        textJa: '保存済みの見立てです。', kind: ['changes', 'impact'].includes(key) ? 'UNKNOWN' : 'INFERENCE',
        evidenceIds: ['changes', 'impact'].includes(key) ? [] : [factId] }])) } };
const response = (value, status = 200) => ({ ok: status === 200, status, json: async () => structuredClone(value) });
function setup(first, historyValid = true) {
  let subscriber, interval; const calls = [], timers = new Map(), modules = new Map();
  const fetch = async (url, options) => {
    calls.push(url);
    if (url.endsWith('/market-brief')) return first(options);
    if (url.endsWith('?history=1')) return response({ scope: 'PUBLIC_MARKET', actionAuthority: false, rows: [{ recordId }] });
    return response({ scope: 'PUBLIC_MARKET', readOnly: true, record: { recordId,
      brief: historyValid ? saved : { ...saved, unifiedContext: { ...saved.unifiedContext, contextId: 'd'.repeat(64) } }, calculations: { '5': { original: true } } } });
  };
  function module(path) {
    if (modules.has(path)) return modules.get(path);
    const exports = {}; modules.set(path, exports);
    const sandbox = { exports, Date, Set, URL, AbortController, fetch, document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
      window: { setTimeout(fn) { const id = timers.size + 1; timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); },
        setInterval(fn) { interval = fn; return 1; }, clearInterval() {} },
      require(name) {
        if (name === 'react') return { useSyncExternalStore(subscribe, get) { subscriber = subscribe; return get(); } };
        if (name.endsWith('/pollingPolicy')) return { scheduleVisibleInterval(fn) { interval = fn; return () => {}; }, subscribeInitialVisibleRead() { return () => {}; } };
        if (name.endsWith('/japanMarketComparison')) return { validJapanMarketComparison: () => false };
        return module(require('node:path').resolve(require('node:path').dirname(path), name + '.ts'));
      } };
    let source = fs.readFileSync(path, 'utf8').replaceAll('import.meta.env.VITE_ARGUS_BACKEND_URL', "'https://example.invalid'");
    vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, sandbox);
    return exports;
  }
  const hook = module(require('node:path').resolve('src/hooks/useMarketBrief.ts'));
  hook.useMarketBrief(); const stop = subscriber(() => {});
  return { hook, calls, timers, stop, get: () => hook.useMarketBrief(), interval };
}
const settle = async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); };
(async () => {
  for (const first of [() => response({}, 502), () => response({ status: 'unavailable' }),
      () => response({ ...saved, unifiedStatus: 'AWAITING_AI', unifiedSummary: null })]) {
    const test = setup(first); await settle();
    const result = test.get(); const edition = result.brief.unifiedSummary ? result.brief : result.brief.retainedPresentation;
    assert.equal(edition.generatedAt, saved.generatedAt);
    assert.equal(edition.calculationSnapshots['5'].original, true);
    assert.equal(edition.unifiedContext.contextId, contextId);
    assert.equal(result.loading, false); assert.equal(test.calls.length, 3);
    test.stop();
  }
  const timeout = setup(({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('timeout')))));
  [...timeout.timers.values()][0](); await settle();
  assert.equal(timeout.get().brief.generatedAt, saved.generatedAt, 'current timeout cannot cancel saved-history recovery');
  assert.equal(timeout.get().error, true); timeout.stop();
  const invalid = setup(() => response({}, 502), false); await settle();
  assert.equal(invalid.get().brief, null); assert.equal(invalid.get().error, true); invalid.stop();
  const forbidden = setup(() => response({}, 401)); await settle();
  assert.equal(forbidden.calls.length, 1, 'no history retry after authentication rejection'); forbidden.stop();
  const current = setup(() => response(saved)); await settle();
  assert.equal(current.calls.length, 1, 'readable current text needs no layout-history round trip'); current.stop();
  const stopped = setup(({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('stopped')))));
  stopped.stop(); await settle(); assert.equal(stopped.calls.length, 1);
  console.log('統合AI: 取得失敗・時間切れ・生成待ちの保存復元、根拠一体保持、認証拒否・停止後の取得抑止 PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
