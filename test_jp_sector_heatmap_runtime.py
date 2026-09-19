from datetime import datetime, timezone
from jp_sector_heatmap_runtime import Runtime

SAT = datetime(2026,9,19,1,tzinfo=timezone.utc)

def test_public_reads_make_no_external_calls_and_closed_market_is_bounded():
    calls=[]
    def unavailable(*a,**k):
        calls.append(a)
        raise OSError('offline')
    runtime=Runtime(unavailable)
    runtime.read(SAT);runtime.read(SAT)
    assert calls==[]
    assert runtime.tick(SAT)
    assert len(calls)==9
    assert not runtime.tick(datetime(2026,9,19,3,tzinfo=timezone.utc))
    assert len(calls)==9
    result=runtime.read(SAT)
    assert len(result['collectionErrors'])==9
    assert all(r['state']=='MISSING' for r in result['rows'])
