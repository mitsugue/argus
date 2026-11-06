"""One fixed cash-index cache read for N31; no generation or provider call."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

EXPECTED = '992ebcc90ffef4c30181bf4423a3a13a3afe1f01'
BASE = 'https://argus-backend-3j2m.onrender.com'
BODY_LIMIT = 16 * 1024 * 1024

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None

def project(value):
    metadata = value.get('instrumentMetadata') or {}
    if (value.get('index') != 'N225' or value.get('symbol') != 'N225'
            or value.get('market') != 'JP' or value.get('timeframe') != 'daily'
            or value.get('automaticAiCalls') != 0
            or metadata.get('instrumentId') != 'INDEX:NIKKEI_225_INDEX'
            or metadata.get('assetType') != 'INDEX'
            or metadata.get('source') != 'yahoo_index_ohlcv'
            or metadata.get('proxyFor') is not None):
        raise ValueError('CASH_INDEX_SCOPE')
    return {key: value.get(key) for key in (
        'schemaVersion', 'methodVersion', 'asOf', 'symbol', 'market', 'index',
        'timeframe', 'reportId', 'source', 'periodEnd', 'availableFrom',
        'calculatedAt', 'status', 'instrumentMetadata', 'indicators',
        'pointInTime', 'automaticAiCalls')}

def main(output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();reads=0
    result={'schemaVersion':'n31-cash-index-cache-readback-v1','expectedBackend':EXPECTED,
        'maximumReads':2,'retryCount':0,'maximumBodyBytes':BODY_LIMIT,
        'newMarketOrAiStarts':0,'ownerScopeAccepted':False}
    opener=urllib.request.build_opener(NoRedirect())
    def get(path):
        nonlocal reads
        if reads>=2 or time.monotonic()-started+20>60:raise ValueError('READ_BUDGET')
        reads+=1
        req=urllib.request.Request(BASE+path,headers={'X-ARGUS-ADMIN-TOKEN':os.environ['ARGUS_ADMIN_TOKEN'],'Accept':'application/json'})
        with opener.open(req,timeout=20) as response:
            raw=response.read(BODY_LIMIT+1)
            if response.status!=200:raise ValueError('HTTP_STATUS')
        if len(raw)>BODY_LIMIT:raise ValueError('BODY_LIMIT')
        return json.loads(raw),hashlib.sha256(raw).hexdigest(),len(raw)
    try:
        health,_,_=get('/healthz')
        if health.get('buildSha')!=EXPECTED:raise ValueError('BACKEND_CHANGED')
        result.update(backendSha=health['buildSha'],backendVersion=health.get('backendVersion'))
        value,digest,size=get('/api/argus/index-chart?index=N225&timeframe=daily')
        cash=project(value)
        (out/'cash-index-selected.json').write_text(json.dumps(cash,ensure_ascii=False,allow_nan=False)+'\n')
        result.update(status='CASH_INDEX_SELECTED_FIELDS_RECORDED_NOT_JOIN_ACCEPTANCE',
            httpBodyHash=digest,httpBodyBytes=size,serialization='selected-parsed-fields-not-original-http-bytes',
            readAt=datetime.now(timezone.utc).isoformat(),reportId=cash['reportId'],
            barCount=len((cash.get('indicators') or {}).get('bars') or []))
    except urllib.error.HTTPError as exc:result.update(errorClass='HTTP_ERROR',http=exc.code)
    except Exception as exc:
        result['errorClass']=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z_]+',str(exc)) else type(exc).__name__
    result.update(readCount=reads,elapsedSeconds=round(time.monotonic()-started,3))
    (out/'cash-index-readback.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
    return 0 if result.get('status')=='CASH_INDEX_SELECTED_FIELDS_RECORDED_NOT_JOIN_ACCEPTANCE' else 1

if __name__=='__main__':sys.exit(main(sys.argv[1]))
