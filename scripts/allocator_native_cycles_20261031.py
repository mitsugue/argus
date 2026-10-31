"""一周ずつ計測を閉じ、計測外の確保領域と残留割当てを分ける隔離診断。"""
from pathlib import Path
import argparse,base64,gc,hashlib,json,os,subprocess,sys,time,tempfile,re
P=argparse.ArgumentParser();P.add_argument('--worker',action='store_true');P.add_argument('--mode',choices=('external',),required=True);P.add_argument('--source',required=True);P.add_argument('--code',required=True);P.add_argument('--out',required=True);P.add_argument('--cycles',type=int,default=8);P.add_argument('--protocol-test',action='store_true');a=P.parse_args()
assert 2<=a.cycles<=4
sys.path.insert(0,a.code)
import argus_checkpoint_v2 as v2
import argus_mapping_attribution as maps
from scripts import checkpoint_v2_mapping_probe as probe
out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
def send(value):
 print(json.dumps(value,separators=(',',':')),flush=True)
 if sys.stdin.readline()!='ack\n':raise RuntimeError('observer_ack_missing')
def allocator_stats():
 if a.protocol_test:return {}
 with tempfile.TemporaryFile(mode='w+b') as f:
  sys.stderr.flush();saved=os.dup(2);os.dup2(f.fileno(),2)
  try:sys._debugmallocstats()
  finally:os.dup2(saved,2);os.close(saved)
  f.seek(0);raw=f.read(65537);assert len(raw)<=65536
 text=raw.decode('ascii');fields={}
 for key,pattern in {
  'arenasCurrent':r'# arenas allocated current\s*=\s*([0-9,]+)',
  'arenasHighwater':r'# arenas highwater mark\s*=\s*([0-9,]+)',
  'bytesAllocatedBlocks':r'# bytes in allocated blocks\s*=\s*([0-9,]+)',
  'bytesAvailableBlocks':r'# bytes in available blocks\s*=\s*([0-9,]+)',
 }.items():
  m=re.search(pattern,text);fields[key]=int(m.group(1).replace(',','')) if m else None
 assert fields['arenasCurrent'] is not None
 return fields
if a.worker:
 if a.mode=='boundary':
  class BoundarySampler:
   # Diagnostic only: the parent still measures actual writer RSS at phases.
   # Boundary readings do not substitute for production peak/resource proof.
   def __init__(self):
    self.process_peak=v2._process_rss_bytes()
    self.cgroup_peak=v2._cgroup_current_bytes()
   def start(self):pass
   def finish(self):
    self.process_peak=max(self.process_peak or 0,v2._process_rss_bytes() or 0)
    self.cgroup_peak=max(self.cgroup_peak or 0,v2._cgroup_current_bytes() or 0)
  v2._ResourceSampler=BoundarySampler
 root=Path(tempfile.mkdtemp(prefix='observer-generations-'));previous=None
 raw_dir=Path(tempfile.mkdtemp(prefix='observer-private-maps-'))
 capture=probe._capture if a.mode=='inline' else (lambda *x,**k:(None,None))
 if a.protocol_test:capture=lambda *x,**k:(None,None)
 send({'phase':'initial','cycle':0,'allocatorStats':allocator_stats()})
 if a.protocol_test:
  from contextlib import nullcontext
 else:
  import memray,importlib.metadata
  assert importlib.metadata.version('memray')=='1.20.0'
  assert os.environ.get('PYTHONMALLOC') is None
 # _debugmallocstats is called only while the profiler hook is detached.
 # It cannot report pymalloc arenas while that hook owns the API.
 for i in range(1,a.cycles+1):
  tracker=(nullcontext() if a.protocol_test else memray.Tracker(
      out/f'native-{i}.bin',native_traces=True,trace_python_allocators=True,
      memory_interval_ms=10000,file_format=memray.FileFormat.AGGREGATED_ALLOCATIONS))
  with tracker:
   before_records,before=capture(raw_dir,f'cycle-{i}-before',previous)
   send({'phase':'before','cycle':i})
   with open(a.source,encoding='utf-8') as f:value=json.load(f)
   result=v2.write_generation(str(root),value,source_generation=f'observer-{i}',consume_snapshot=True,
       validation_context={'triggerSource':'resource_probe','missionWindowId':f'observer-{i}','natural':False,'formalSoakState':'not_started'})
   consumed=value=={};generation=result['generationId']
   after_records,after=capture(raw_dir,f'cycle-{i}-after',before_records,active_generation=generation)
   info={'phase':'after','cycle':i,'verified':result['verified'],'consumed':consumed,'sourceBytes':result['sourceSerializedBytes'],'sections':result['sectionCount'],'rows':result['resourceTelemetry']['rowCount']}
   del value,result
   send(info)
   # 直前の記録はGC前で、残った循環参照を保持物と区別できなかった。
   # 今回は同じ保存の後、計測中に回収してから割当て記録を閉じる。
   gc.collect()
  gc.collect();time.sleep(.25)
  if a.mode=='postgc' and not a.protocol_test:
   v2._release_unused_allocator_memory(38887032)
  quiet_records,quiet=capture(raw_dir,f'cycle-{i}-quiet',after_records,active_generation=generation)
  send({'phase':'quiet','cycle':i,'retained':len(list(root.glob('v2-generation-*'))),'pending':len(list(root.glob('.v2-pending-*'))),'allocatorStats':allocator_stats()})
  previous=quiet_records
  before=after=quiet=None
 restored=v2.restore_generation(str(root),include_archived=False)
 assert restored['verified'];del restored['snapshot'],restored;gc.collect()
 send({'phase':'final','cycle':a.cycles,'fullRestoreVerified':True});sys.exit(0)
# source identity is checked in the observer process, never preloaded by writer.
def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for chunk in iter(lambda:f.read(1024**2),b''):h.update(chunk)
 return h.hexdigest()
source_sha=digest(a.source);files=('argus_checkpoint_v2.py','argus_mapping_attribution.py','argus_persistent_storage.py','argus_tick_durability.py','scripts/checkpoint_v2_resource_probe.py','scripts/checkpoint_v2_mapping_probe.py');code_hash={n:digest(Path(a.code)/n) for n in files}
if not a.protocol_test:
 assert source_sha=='bde53e2b5dc40a06e248e3a905e797b7876c4319d49a97b191b4465641b2519e'
 assert code_hash['argus_checkpoint_v2.py']=='b21d3f229e0ec9220752c8eb45bf0e765b717e7865576ce603ec8d6f31ea0796'
 assert code_hash['argus_mapping_attribution.py']=='0fa10f76f29dfb6de94886f2a7e8fcf9fdee461f11ac59c2a3644f1b8a0fb3d7'
cmd=[sys.executable,'-B',__file__,'--worker','--mode',a.mode,'--source',a.source,'--code',a.code,'--out',str(out),'--cycles',str(a.cycles)]
if a.protocol_test:cmd.append('--protocol-test')
stderr=open(out/'worker-stderr.txt','w');child=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True);samples=[];previous=None
try:
 while True:
  line=child.stdout.readline(65537)
  if not line:break
  assert len(line)<=65536;msg=json.loads(line)
  assert set(msg)<= {'phase','cycle','verified','consumed','sourceBytes','sections','rows','retained','pending','fullRestoreVerified','allocatorStats'}
  assert msg['phase'] in ('initial','before','after','quiet','final') and isinstance(msg['cycle'],int)
  if not a.protocol_test:
   text=Path(f'/proc/{child.pid}/smaps').read_text();assert len(text.encode())<=8*1024**2
   records=maps.parse_smaps(text);categories=maps.category_summary(records,previous);previous=records
   msg.update(categories=categories,writerPid=child.pid,rssBytes=categories['__total__']['rssBytes'],anonymousBytes=categories['__total__']['anonymousResidentBytes'])
   # All parsing/record retention above belongs to this observer, not writer.
  samples.append(msg)
  with (out/'samples.ndjson').open('a') as f:f.write(json.dumps(msg,sort_keys=True)+'\n')
  child.stdin.write('ack\n');child.stdin.flush()
 rc=child.wait(timeout=10);assert rc==0,rc
 assert samples[-1].get('fullRestoreVerified') is True
 writes=[s for s in samples if s['phase']=='after'];quiets=[s for s in samples if s['phase']=='quiet']
 assert len(writes)==len(quiets)==a.cycles and all(s['verified'] and s['consumed'] for s in writes)
 assert all(s['retained']<=4 and s['pending']==0 for s in quiets)
 if not a.protocol_test:assert all((s['sourceBytes'],s['sections'],s['rows'])==(38887032,46,25115) for s in writes)
 assert source_sha==digest(a.source) and all(digest(Path(a.code)/n)==h for n,h in code_hash.items())
 report={'schema':'allocator-native-retainers-diagnostic-v1','mode':a.mode,'cycles':a.cycles,'sourceSha256':source_sha,'originalCodeHashes':code_hash,'allWritesVerified':True,'allConsumed':True,'fullRestoreVerified':True,'pending':0,'retainedMaximum':max(s['retained'] for s in quiets),'formalAcceptance':False,'protocolTest':a.protocol_test,'additionalProviderOrAiCalls':0,'originalSourceAndCodeUnchanged':True,'writerPid':child.pid}
 if not a.protocol_test:
  report.update(quietRssBytes=[s['rssBytes'] for s in quiets],quietAnonymousBytes=[s['anonymousBytes'] for s in quiets],rssGrowthAfterWarmup=quiets[-1]['rssBytes']-quiets[1]['rssBytes'],anonymousGrowthAfterWarmup=quiets[-1]['anonymousBytes']-quiets[1]['anonymousBytes'])
 if not a.protocol_test:
  import memray,collections
  profiles=[]
  for i in range(1,a.cycles+1):
   capture=out/f'native-{i}.bin';assert capture.is_file() and 0<capture.stat().st_size<=32*1024**2
   totals=collections.defaultdict(lambda:{'bytes':0,'allocations':0});largest=[];count=0
   with memray.FileReader(capture,report_progress=False,max_memory_records=512) as reader:
    for row in reader.get_leaked_allocation_records():
     count+=1;assert count<=50000
     kind=memray.AllocatorType(row.allocator).name
     totals[kind]['bytes']+=row.size;totals[kind]['allocations']+=row.n_allocations
     frames=[{'function':str(fn)[:160],'file':Path(str(file)).name[:160],'line':int(line)}
             for fn,file,line in row.stack_trace(max_stacks=12)]
     largest.append({'allocator':kind,'bytes':row.size,'allocations':row.n_allocations,'pythonFrames':frames})
     largest.sort(key=lambda r:r['bytes'],reverse=True);del largest[40:]
   profiles.append({'cycle':i,'records':count,'allocatorTotals':dict(totals),'largestRemaining':largest,
       'profileBytes':capture.stat().st_size,'profileSha256':digest(capture)})
  native={'schema':'allocator-native-per-cycle-v1','toolVersion':'1.20.0',
      'profiles':profiles,'statisticsWithHookDetached':True,'captureIncludesPostGc':True,
      'comparisonRunBeforeGc':41167424470,
      'capturesObjectValues':False,'formalAcceptance':False,'rootCauseProven':False,
      'originalFailureRun':41166376788,'originalFailurePreserved':True,
      'scope':'OCTOBER_8_ONLY_NOT_OCTOBER_20','newProviderAiOrProductionWrites':0}
  raw=json.dumps(native,sort_keys=True,indent=2)+'\n';assert len(raw.encode())<=2*1024**2
  (out/'retainers.json').write_text(raw)
  report.update(nativeProfileComplete=True,profileCount=len(profiles),statisticsWithHookDetached=True,
       instrumentationChanged=True,originalFourCycleRunAcceptance=False)
 else:
  report.update(nativeProfileComplete=False,protocolOnly=True)
 (out/'summary.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
finally:
 if child.poll() is None:child.terminate();child.wait(timeout=10)
 stderr.close()
