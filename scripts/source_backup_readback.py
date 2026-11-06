"""Two fixed, bounded cached reads; fixed backup/FX status only, never starts a save."""
from datetime import datetime, timezone
import hashlib,json,math,os,re,sys,time
from pathlib import Path
import urllib.request,urllib.error
import argus_market_input_backup as backup
EXPECTED='97fc511722dadecb614a2f5ff1cffa146a406477'
BASE='https://argus-backend-3j2m.onrender.com'
LIMIT=1048576
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def project(value):
    raw=value.get('marketInputBackup')
    if not isinstance(raw,dict):raise ValueError('BACKUP_STATUS_ABSENT')
    remapped={**raw,'verifiedAt':raw.get('lastVerifiedAt')}
    selected=backup.status_projection(remapped,worker_active=raw.get('workerActive') is True)
    if raw!=selected:raise ValueError('BACKUP_STATUS_FIELDS')
    fx=value.get('usdJpyTokyoClose') or {};safe={}
    if fx.get('status') in {'NOT_RUN','RETAINED','MISSED','WAITING','FAILED','NOT_DURABLE'}:safe['status']=fx['status']
    for k in ('lastDate','firstKeptDate','missedDate'):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(fx.get(k) or '')):safe[k]=fx[k]
    for k in ('lastAttemptAt','keptAt'):
        v=fx.get(k)
        if isinstance(v,str) and len(v)<=40:
            try:t=datetime.fromisoformat(v.replace('Z','+00:00'))
            except ValueError:continue
            if t.tzinfo:safe[k]=v
    if type(fx.get('keptSessions')) is int and 0<=fx['keptSessions']<=10000:safe['keptSessions']=fx['keptSessions']
    offset=fx.get('offsetSeconds')
    if type(offset) in (int,float) and math.isfinite(offset) and abs(offset)<=10000000:safe['offsetSeconds']=offset
    if fx.get('reason') in {'quote_unavailable','source_time_outside_tolerance','no_read_in_window','ValueError','TimeoutError','OSError','RuntimeError','ConnectionError','ReadTimeout','ConnectTimeout','HTTPError'}:safe['reason']=fx['reason']
    return {'marketInputBackup':selected,'usdJpyTokyoClose':safe}

def main(output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);started=time.monotonic();reads=0
    result={'schemaVersion':'source-backup-fixed-readback-v1','expectedBackend':EXPECTED,'maximumReads':2,'bodyLimitBytes':LIMIT,'perReadSeconds':20,'totalSeconds':60,'retries':0,'saveOrCollectionOrAiStarted':False}
    opener=urllib.request.build_opener(NoRedirect())
    def get(path):
        nonlocal reads
        if reads>=2 or time.monotonic()-started+20>60:raise ValueError('READ_BUDGET')
        reads+=1
        req=urllib.request.Request(BASE+path,headers={'Accept':'application/json','X-ARGUS-ADMIN-TOKEN':os.environ['ARGUS_ADMIN_TOKEN']})
        with opener.open(req,timeout=20) as response:
            raw=response.read(LIMIT+1)
            if response.status!=200:raise ValueError('HTTP_STATUS')
        if len(raw)>LIMIT:raise ValueError('BODY_LIMIT')
        return json.loads(raw),hashlib.sha256(raw).hexdigest(),len(raw)
    try:
        health,_,_=get('/healthz')
        if health.get('buildSha')!=EXPECTED:raise ValueError('BACKEND_CHANGED')
        result['backendSha']=health['buildSha'];value,digest,size=get('/api/argus/admin/memory-attribution?market-input-backup=1')
        result.update(project(value),status='FIXED_STATUS_READ',bodySha256=digest,bodyBytes=size,readAt=datetime.now(timezone.utc).isoformat())
    except urllib.error.HTTPError as exc:result.update(errorClass='HTTP_ERROR',http=exc.code)
    except Exception as exc:result['errorClass']=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z_]+',str(exc)) else type(exc).__name__
    result.update(reads=reads,elapsedSeconds=round(time.monotonic()-started,3))
    (out/'source-backup-status.json').write_text(json.dumps(result,allow_nan=False)+'\n')
    return 0 if result.get('status')=='FIXED_STATUS_READ' else 1
if __name__=='__main__':sys.exit(main(sys.argv[1]))
