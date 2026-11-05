"""One bounded cached read; no collector, auth changes, retry or raw body output."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
r = {'at': datetime.now(timezone.utc).isoformat(), 'authority': 'EXISTING_OPERATIONAL_READ',
     'endpoint': 'index-chart:N225:live', 'retryCount': 0}
start = time.monotonic()
try:
    req = urllib.request.Request('https://argus-backend-3j2m.onrender.com/api/argus/index-chart?index=N225&live=1',
        headers={'X-ARGUS-ADMIN-TOKEN': os.environ['ARGUS_ADMIN_TOKEN']})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
        body = response.read(524289)
        r['http'] = response.status
    if len(body) > 524288:
        raise ValueError('body_size')
    r.update(bytes=len(body), bodySha256=hashlib.sha256(body).hexdigest())
    value = json.loads(body)
    for key in ('status', 'reason', 'lastError', 'lastErrorCode', 'lastAttemptAt'):
        v = value.get(key)
        r[key] = v if v is None or isinstance(v, str) and len(v) <= 100 else 'REJECTED_FIELD'
    r['workerAlive'] = value.get('workerAlive') if type(value.get('workerAlive')) is bool else None
    r['expectedServerBuild'] = '6aa923801b127a62a0df01939e9984260f9eb4a6'
    quote = value.get('quote')
    if isinstance(quote, dict):
        r['quote'] = {key: quote.get(key) for key in ('tradedAt','receivedAt','delaySeconds','sessionOpen','realtime','source','actionAuthority')}
        price = quote.get('price')
        r['quote']['positiveFinitePrice'] = type(price) in (int, float) and math.isfinite(price) and price > 0
except urllib.error.HTTPError as e:
    r.update(http=e.code, errorClass='HTTP_ERROR')
except Exception as e:
    r['errorClass'] = type(e).__name__
r['elapsedSeconds'] = round(time.monotonic() - start, 3)
(out / 'index.json').write_text(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n')
