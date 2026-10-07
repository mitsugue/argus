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
function setup(first, historyValid = true, cached = null) {
  const sessionValues = new Map(cached ? [["argus.marketBrief.session.v1", JSON.stringify(cached)]] : []);
  const sessionStorage = { getItem: key => sessionValues.get(key) || null, setItem: (key,value) => sessionValues.set(key,value), removeItem: key => sessionValues.delete(key) };
  let subscriber, interval; const calls = [], timers = new Map(), modules = new Map();
  let now = Date.parse('2026-10-06T13:00:00Z');
  class ClockDate extends Date { static now() { return now; } }
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
    const sandbox = { exports, sessionStorage, Date: ClockDate, Set, URL, AbortController, fetch, document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
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
  return { hook, calls, timers, stop, sessionValues, get: () => hook.useMarketBrief(), interval, advance(ms) { now += ms; interval(); } };
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
  const cached = setup(({signal})=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout')))),true,saved);
  assert.equal(cached.get().brief.generatedAt,saved.generatedAt,'通信を待たず保存した完全な見立てを表示');
  assert.equal(cached.get().loading,true);cached.stop();await settle();
  const deniedCache=setup(()=>response({},401),true,saved);await settle();
  assert.equal(deniedCache.get().brief,null);assert.equal(deniedCache.sessionValues.size,0,'認証拒否時は画面用保存版も消去');deniedCache.stop();
  const ownerCache=setup(()=>response({},401),true,{...saved,unifiedSummary:{...saved.unifiedSummary,ownerContextAvailable:true}});
  assert.equal(ownerCache.get().brief,null,'所有者情報を含む説明を画面用の保存へ受け入れない');await settle();ownerCache.stop();
  const timeout = setup(({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('timeout')))));
  [...timeout.timers.values()][0](); await settle();
  assert.equal(timeout.get().brief.generatedAt, saved.generatedAt, 'current timeout cannot cancel saved-history recovery');
  assert.equal(timeout.get().error, true); timeout.stop();
  const invalid = setup(() => response({}, 502), false); await settle();
  assert.equal(invalid.get().brief, null); assert.equal(invalid.get().error, true); invalid.stop();
  const forbidden = setup(() => response({}, 401)); await settle();
  assert.equal(forbidden.calls.length, 1, 'no history retry after authentication rejection'); forbidden.stop();
  const current = setup(() => response(saved)); await settle();
  assert.equal(current.calls.length, 1, 'readable current text needs no layout-history round trip');
  current.advance(30_000); await settle(); assert.equal(current.calls.length, 1, 'completed edition keeps the five-minute cadence');
  current.advance(270_000); await settle(); assert.equal(current.calls.length, 2); current.stop();
  for (const generationWorker of [{status:'RUNNING'}, {status:'AWAITING_AI'}, {status:'GENERATED'}]) {
    let reads = 0;
    const pending = setup(() => response(++reads === 1 ? {...saved, unifiedStatus:'AWAITING_AI', unifiedSummary:null, generationWorker} : saved));
    await settle();
    assert.equal(pending.calls.length, 3); assert.ok(pending.get().brief.retainedPresentation, 'saved view is readable before the worker finishes');
    pending.advance(29_999); await settle(); assert.equal(pending.calls.length, 3);
    pending.advance(1); await settle(); assert.equal(pending.calls.length, 4, 'a saved edition must not postpone the completed current view for five minutes');
    assert.equal(pending.get().brief.generatedAt, saved.generatedAt); assert.equal(pending.get().brief.retainedPresentation, undefined);
    pending.advance(30_000); await settle(); assert.equal(pending.calls.length, 4, 'return to normal polling after completion');
    assert.equal(pending.calls.filter(url => url.includes('history')).length, 2, 'pending polls reuse memory rather than re-reading history');
    pending.stop();
  }
  const stopped = setup(({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('stopped')))));
  stopped.stop(); await settle(); assert.equal(stopped.calls.length, 1);
  console.log('統合AI: 取得失敗・時間切れ・生成待ちの保存復元、根拠一体保持、認証拒否・停止後の取得抑止 PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
