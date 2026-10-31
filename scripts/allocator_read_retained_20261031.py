"""保存できた一周の割当て記録を読むだけ。元入力の保存復元は実行しない。"""
from pathlib import Path
import json,hashlib,collections,importlib.metadata
import memray
profile=Path('/input/native.bin');out=Path('/out')
expected='25ce551a3a123d77efcbad26818a94454e8f5df393b4d1d8d67604c4916aea2a'
assert importlib.metadata.version('memray')=='1.20.0'
assert profile.stat().st_size==127788 and hashlib.sha256(profile.read_bytes()).hexdigest()==expected

def frames(row,native=False):
 try:
  values=row.native_stack_trace(max_stacks=12) if native else row.stack_trace(max_stacks=12)
  return [{'function':str(fn)[:160],'file':Path(str(file)).name[:160],'line':int(line)}for fn,file,line in values],None
 except (NotImplementedError,OSError,ValueError)as exc:
  return None,type(exc).__name__

def summarize(records):
 totals=collections.defaultdict(lambda:{'bytes':0,'allocations':0});largest=[];count=0
 for row in records:
  count+=1;assert count<=50000
  kind=memray.AllocatorType(row.allocator).name
  totals[kind]['bytes']+=row.size;totals[kind]['allocations']+=row.n_allocations
  py,py_error=frames(row);native,native_error=frames(row,True)
  largest.append({'allocator':kind,'bytes':row.size,'allocations':row.n_allocations,'pythonFrames':py,'pythonFrameErrorClass':py_error,'nativeFrames':native,'nativeFrameErrorClass':native_error})
  largest.sort(key=lambda r:r['bytes'],reverse=True);del largest[40:]
 return {'records':count,'byAllocator':dict(totals),'largest':largest}
with memray.FileReader(profile,report_progress=False,max_memory_records=512)as reader:
 remaining=summarize(reader.get_leaked_allocation_records())
 peak=summarize(reader.get_high_watermark_allocation_records())
assert hashlib.sha256(profile.read_bytes()).hexdigest()==expected
report={'schema':'allocator-preserved-partial-capture-analysis-v1','originalRun':41166376788,'originalRunConclusion':'failure','completedWrites':1,'fullRestoreObserved':False,'profileSha256':expected,'remaining':remaining,'atPeak':peak,'newReplay':0,'originalInputDownloaded':False,'formalAcceptance':False,'rootCauseProven':False,'sourceScope':'OCTOBER_8_ONLY_NOT_OCTOBER_20'}
raw=json.dumps(report,sort_keys=True,indent=2)+'\n';assert len(raw.encode())<=2*1024**2
(out/'retainers-analysis.json').write_text(raw)
print('Existing capture analyzed; no replay, acceptance or production change')
