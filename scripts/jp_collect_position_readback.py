"""One new incident's fixed stack/timing projection; no inventory or retry."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from scripts.run_intel_collect import private_timing_record

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
result={'schemaVersion':'argus-collect-position-readback-v1','at':datetime.now(timezone.utc).isoformat(),
        'case':'new-233-cold-collection-after-6aa-900s-timeout','retryCount':0,'inventoryRequested':False}
start=time.monotonic()
try:
    req=urllib.request.Request('https://argus-backend-3j2m.onrender.com/api/argus/admin/memory-attribution?threads=1',
        headers={'X-ARGUS-ADMIN-TOKEN':os.environ['ARGUS_ADMIN_TOKEN']})
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
        raw=response.read(1048577);result['http']=response.status
    if len(raw)>1048576: raise ValueError('body_size')
    body=json.loads(raw);result.update(bodySha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    result['collection']=private_timing_record((body.get('intelCollect') or {}).get('currentRun') or {},include_run_context=True)
    threads=body.get('runtimeThreads') or {}
    if threads.get('schemaVersion')=='argus-runtime-thread-dump-v1':
        result['threads']=[{'name':str(t.get('name',''))[:80],
            'frames':[{'file':str(f.get('file',''))[:120],'line':f.get('line') if type(f.get('line')) is int else None,
                       'function':str(f.get('function',''))[:80]} for f in (t.get('frames') or [])[:18]]}
            for t in (threads.get('threads') or [])[:64] if isinstance(t,dict)]
        result['singleFlight']=threads.get('singleFlight')
    result['rssMiB']=body.get('currentRssMib') if type(body.get('currentRssMib')) in (int,float) else None
except urllib.error.HTTPError as e: result.update(http=e.code,errorClass='HTTP_ERROR')
except Exception as e: result['errorClass']=type(e).__name__
result['elapsedSeconds']=round(time.monotonic()-start,3)
(out/'collection-position.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
