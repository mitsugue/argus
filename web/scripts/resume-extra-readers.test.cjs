const assert=require('node:assert/strict'),fs=require('node:fs'),ts=require('typescript'),vm=require('node:vm');
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function isolated(file,saved,answer={items:[]}){
 const effects=[],timers=[],writes=[],slots=[];let calls=0,slot=0,online;
 const checkpoint={restoredValue:key=>saved[key],hasRestored:key=>key in saved,keep:(key,value)=>{writes.push({key,value});return true;},flush:async()=>true};
 const policy={FEED_VISIBLE_MS:600000,isPageVisible:()=>true,
  scheduleVisibleInterval:(fn,ms)=>{const t={fn,ms,stopped:false};timers.push(t);return()=>{t.stopped=true;};},
  subscribeInitialVisibleRead:()=>()=>{}};
 const react={useMemo:fn=>fn(),useState:initial=>{const i=slot++;slots[i]=typeof initial==='function'?initial():initial;return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useEffect:fn=>effects.push(fn)};
 const ctx={exports:{},Date,URL,TextEncoder,AbortController,document:{visibilityState:'visible',hidden:false},
  window:{setTimeout:()=>1,clearTimeout(){},addEventListener:(name,fn)=>{if(name==='online')online=fn;},removeEventListener(){}},
  fetch:async()=>{calls++;return {ok:true,json:async()=>answer};},
  require:name=>name==='react'?react:name.includes('sessionViewCheckpoint')?{sessionViewCheckpoint:checkpoint}
   :name.includes('pollingPolicy')?policy:name.includes('japanMarketComparisonReply')?{
    comparisonReply:()=>({document:null,levelMap:null,reason:'fixture_unavailable',lastSuccessfulAcquisitionAt:null}),
    retainComparisonReply:result=>result,comparisonReadInterval:()=>600000}
   :{validJapanMarketComparison:()=>false,validLevelMap:()=>false,validResearchChart:()=>false,validForecastTrackRecord:()=>false}};
 const source=fs.readFileSync(file,'utf8').replaceAll('import.meta.env.VITE_ARGUS_BACKEND_URL',"'https://fixture.test'");
 vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,ctx);
 return {exports:ctx.exports,effects,timers,writes,slots,get calls(){return calls;},get online(){return online;}};
}
(async()=>{
 for(const [file,hook,key,schema] of [
  ['useMarketShock.ts','useMarketShock','market-shock','argus-market-shock-v1'],
  ['useNewsIntelligence.ts','useNewsIntelligence','news-intelligence','argus-news-intelligence-v1']]){
  const original={status:'error',view:{schemaVersion:schema,generatedAt:'2026-10-01T01:02:03Z',events:[]}};
  const x=isolated('src/hooks/'+file,{[key]:original});const first=x.exports[hook]();
  assert.equal(first.status,'error','restoration never relabels a previous failed refresh');assert.equal(first.view.generatedAt,original.view.generatedAt);
  const stops=x.effects.map(fn=>fn());await flush();assert.equal(x.calls,0,'restored view performs no initial HTTP');
  x.timers[0].fn();await flush();assert(x.calls>=1,'existing periodic read remains enabled');
  assert.equal(x.slots.at(-1).status,'error','invalid fresh reply retains the error, not a fabricated current result');
  for(const stop of stops)stop();assert(x.timers.every(t=>t.stopped));
  const cold=isolated('src/hooks/'+file,{});cold.exports[hook]();cold.effects.forEach(fn=>fn());await flush();assert(cold.calls>=1,'cold acquisition still runs');
 }
 const macro=isolated('src/hooks/useMacroEventAnalysis.ts',{'macro-event-analysis':{}});
 macro.exports.useMacroEventAnalysis();macro.effects[0]();await flush();assert.equal(macro.calls,0);macro.timers[0].fn();await flush();assert.equal(macro.calls,1);
 const ownerMacro=isolated('src/hooks/useMacroEventAnalysis.ts',{}, {items:[{eventId:'fixture',post:{portfolioImpactJa:'fixture-private-context'}}]});
 ownerMacro.exports.useMacroEventAnalysis();ownerMacro.effects[0]();await flush();assert.equal(ownerMacro.calls,1);assert.equal(ownerMacro.writes.length,0,'owner-context explanations remain memory-only');
 const state={document:null,loading:false,error:true,levelMap:null,levelMapError:true,reason:'fixture_unavailable',lastSuccessfulAcquisitionAt:null};
 const comparison=isolated('src/hooks/useJapanMarketComparison.ts',{'jp-comparison:https://fixture.test:5':state});
 comparison.exports.useJapanMarketComparison(5);const end=comparison.effects[0]();await flush();assert.equal(comparison.calls,0);
 const retry=comparison.timers.find(t=>t.ms===30000);assert(retry,'original 30-second retry remains armed after restoring a failed view');
 retry.fn();await flush();assert.equal(comparison.calls,1);assert(retry.stopped,'one retry flight cancels its old schedule');end();assert(comparison.timers.every(t=>t.stopped));
 // Execute the actual sector acquisition callback, substituting only its
 // shared-store/React seams. This catches freezing periodic reads after restore.
 let sectorStart;let sectorCalls=0;const sectorTimers=[];
 const sectorCtx={exports:{},AbortController,setTimeout:()=>1,clearTimeout(){},fetch:async()=>{sectorCalls++;return{ok:true,json:async()=>({schemaVersion:'jp-sector-heatmap-v1',rows:[]})};},
  require:name=>name.includes('sharedPollingStore')?{createSharedPollingStore:(_initial,start)=>{sectorStart=start;return {};}}
    :name.includes('pollingPolicy')?{isPageVisible:()=>true,FEED_VISIBLE_MS:600000,scheduleVisibleInterval:fn=>{sectorTimers.push(fn);return()=>{};},subscribeInitialVisibleRead:()=>()=>{}}
    :name.endsWith('.css')?{}:{}};
 const sectorSource=fs.readFileSync('src/components/today/SectorHeatmap.tsx','utf8').replaceAll('import.meta.env.VITE_ARGUS_BACKEND_URL',"'https://fixture.test'");
 vm.runInNewContext(ts.transpileModule(sectorSource,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,sectorCtx);
 const stopSector=sectorStart(()=>{},()=>({data:null,error:false,loading:false}),true);await flush();assert.equal(sectorCalls,0);sectorTimers[0]();await flush();assert.equal(sectorCalls,1);stopSector();
 console.log('PASS actual extra-reader lifecycles: restored state/old failure and times, no initial fetch, cold and periodic fetch retained, owner explanation not stored, comparison 30s retry and sector cadence preserved. Authentication/AES/Safari acceptance are separate.');
})().catch(e=>{console.error(e);process.exitCode=1;});
