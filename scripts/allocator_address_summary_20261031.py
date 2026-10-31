"""割当値を読まず、新規1MiB領域に残る割当て数だけを集計する隔離器。"""
from collections import Counter
from pathlib import Path
import hashlib

def summarize(records):
    alive={}; arenas={}; representatives={}; count=0
    for row in records:
        count+=1
        if count>100_000_000:raise RuntimeError('allocation_record_limit')
        kind=int(row.allocator);address=int(row.address);size=int(row.size)
        if kind in (2,3,4):
            if address<=0 or size<0:raise RuntimeError('allocation_address_invalid')
            key=(kind,int(row.stack_id),int(row.native_stack_id),int(row.tid))
            if key not in representatives:
                if len(representatives)>=20000:raise RuntimeError('allocation_stack_limit')
                representatives[key]=row
            alive[address]=(size,key)
            if len(alive)>2_000_000:raise RuntimeError('live_allocation_limit')
        elif kind==1:
            alive.pop(address,None)
        elif kind==14 and size==1024**2:
            # A size match alone is a candidate range, not proof of a pymalloc arena.
            if len(arenas)>=4096:raise RuntimeError('arena_range_limit')
            arenas[address]=size
        elif kind==15:
            end=address+size
            for base,length in list(arenas.items()):
                if address<base+length and end>base:
                    del arenas[base]
    by_range={base:Counter()for base in arenas};unmapped=Counter();counts=Counter()
    for address,(size,key)in alive.items():
        base=next((b for b,n in arenas.items()if b<=address and address+size<=b+n),None)
        target=unmapped if base is None else by_range[base]
        target[key]+=size;counts[(base,key)]+=1
    def stacks(totals,base):
        rows=[]
        for key,size in totals.most_common(20):
            r=representatives[key]
            frames=[{'function':str(fn)[:160],'file':Path(str(file)).name[:160],'line':int(line)}for fn,file,line in r.stack_trace(max_stacks=12)]
            rows.append({'bytes':size,'allocations':counts[(base,key)],'allocator':key[0],'pythonFrames':frames})
        return rows
    mapped=[]
    for base,totals in by_range.items():
        mapped.append({'rangeId':hashlib.sha256(str(base).encode()).hexdigest()[:16],
            'rangeBytes':arenas[base],'remainingBytes':sum(totals.values()),
            'remainingAllocations':sum(counts[(base,k)]for k in totals),
            'largestRemaining':stacks(totals,base)})
    return {'records':count,'remainingBytes':sum(x[0]for x in alive.values()),
        'remainingAllocations':len(alive),'newOneMibRanges':mapped,
        'outsideNewRangesBytes':sum(unmapped.values()),'outsideLargestRemaining':stacks(unmapped,None),
        'candidateRangeIsNotArenaProof':True,'untrackedPreexistingAllocationsExcluded':True,
        'rawAddressesInSummary':False,'capturesObjectValues':False}
