"""Read the known failed tracking run once, without starting collection."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime,timezone
from scripts.run_intel_collect import private_timing_record

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
record={'schemaVersion':'argus-known-collect-terminal-v1','at':datetime.now(timezone.utc).isoformat(),
        'originalTrackingRun':42038407901,'statusOnly':True,'retryCount':0,'collectionStartRequested':False}
start=time.monotonic();opener=urllib.request.build_opener(NoRedirect())
try:
    req=urllib.request.Request('https://api.github.com/repos/mitsugue/argus-l2b-private/contents/diagnostics/warm/42038407901/collect.txt',
        headers={'Authorization':'Bearer '+os.environ['PRIVATE_DIAGNOSTICS_TOKEN'],'Accept':'application/vnd.github.raw'})
    with opener.open(req,timeout=10) as response:raw=response.read(65537)
    if len(raw)>65536:raise ValueError('stored_record_size')
    previous=json.loads(raw);run_id=previous.get('runId')
    if not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',run_id):raise ValueError('stored_identity')
    payload=json.dumps({'requestId':run_id,'statusOnly':True}).encode()
    req=urllib.request.Request('https://argus-backend-3j2m.onrender.com/api/argus/institutional-intelligence/collect',
        method='POST',data=payload,headers={'X-ARGUS-ADMIN-TOKEN':os.environ['ARGUS_ADMIN_TOKEN'],'Content-Type':'application/json'})
    with opener.open(req,timeout=20) as response:
        body=response.read(1048577);record['http']=response.status
    if len(body)>1048576:raise ValueError('body_size')
    value=json.loads(body);record.update(bytes=len(body),bodySha256=hashlib.sha256(body).hexdigest(),
        matchedOriginalRun=value.get('runId')==run_id)
    if not record['matchedOriginalRun']:raise ValueError('identity_mismatch')
    record['timing']=private_timing_record(value,include_run_context=True)
    result=value.get('result') or {};error=(result.get('jpMarketEngineInputWarm') or {}).get('error')
    record['marketInputError']=error if isinstance(error,str) and len(error)<=80 else None
    record['errorClass']=value.get('errorClass') if isinstance(value.get('errorClass'),str) else None
except urllib.error.HTTPError as e:record.update(http=e.code,errorClass='HTTP_ERROR')
except Exception as e:record['errorClass']=type(e).__name__
record['elapsedSeconds']=round(time.monotonic()-start,3)
(out/'collection-terminal.json').write_text(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
