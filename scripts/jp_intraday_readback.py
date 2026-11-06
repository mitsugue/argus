"""Two bounded cached samples; private fixed metadata only, no price/owner text."""
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

EXPECTED = '717072492f1ded2426e6f5a35aeea219e83a6074'
BASE = 'https://argus-backend-3j2m.onrender.com'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None


def moment(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.timestamp() if dt.tzinfo else None
    except (TypeError, ValueError, OverflowError): return None


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def members(document):
    rows = document.get('members')
    if not isinstance(rows, list): raise ValueError('MEMBERSHIP_SCHEMA')
    return sorted({r['symbol'].upper().removesuffix('.T') for r in rows
        if isinstance(r, dict) and r.get('market') == 'JP' and r.get('enabled', True) is True
        and isinstance(r.get('symbol'), str)
        and re.fullmatch(r'[0-9][0-9A-Z]{3}(?:\.T)?', r['symbol'].upper())})[:50]


def projection(value, codes, read_at):
    delayed = value.get('japaneseDelayed') or {}
    if delayed.get('schemaVersion') != 'argus-jp-delayed-display-v1' or delayed.get('actionAuthority') is not False:
        raise ValueError('DELAYED_SCHEMA')
    rows = delayed.get('symbols') or {}; errors = delayed.get('errors') or {}
    live = value.get('japaneseLive') or {}
    projected = []; raw = {}
    for slot, code in enumerate(codes):
        row = rows.get(code) or {}; source = moment(row.get('sourceTimestamp')); receipt = moment(row.get('receivedAt'))
        valid = positive(row.get('price')) and source is not None and receipt is not None and source <= receipt <= read_at
        recent = valid and read_at - receipt <= 180 and read_at - source <= 2400
        projected.append({'slot': slot, 'present': bool(row), 'positiveFinitePrice': positive(row.get('price')),
            'sourceTimestamp': row.get('sourceTimestamp'), 'receivedAt': row.get('receivedAt'),
            'realtime': row.get('realtime'), 'actionAuthority': row.get('actionAuthority'),
            'recentWithinDisplayLimits': bool(recent), 'hasError': bool(errors.get(code) or row.get('lastError'))})
        if valid: raw[code] = (row['price'], source, receipt)
    counts = Counter(str(v) if re.fullmatch(r'(?:HTTP_[0-9]{3}|[A-Z_]+|Timeout|ReadTimeout|ConnectTimeout|ConnectionError)',str(v)) else 'OTHER' for v in errors.values())
    return {'registeredCount': len(codes), 'displayRowCount': len(rows), 'rows': projected,
        'errorsByClass': dict(counts), 'membershipErrorPresent': bool(delayed.get('membershipError')),
        'brokerEnabled': live.get('enabled') is True, 'brokerDisplayApproved': live.get('displayApproved') is True}, raw


def main(output):
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic(); deadline = start + 240; reads = 0
    result = {'schemaVersion': 'jp-cached-intraday-two-samples-v1', 'samples': [],
              'expectedBackend': EXPECTED, 'retryCount': 0, 'newCollectorStarts': 0,
              'newAiCalls': 0, 'ownerSymbolsOrPricesRecorded': False}
    opener = urllib.request.build_opener(NoRedirect())
    def get(url, token):
        nonlocal reads
        if reads >= 8 or time.monotonic() + 20 > deadline: raise ValueError('READ_BUDGET')
        reads += 1
        header = 'Authorization' if url.startswith('https://api.github.com/') else 'X-ARGUS-ADMIN-TOKEN'
        headers = {header: ('Bearer ' + token) if header == 'Authorization' else token, 'Accept': 'application/json'}
        with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as response:
            raw = response.read(1048577)
            if response.status != 200: raise ValueError('HTTP_STATUS')
        if len(raw) > 1048576: raise ValueError('BODY_LIMIT')
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    try:
        entry, _ = get('https://api.github.com/repos/mitsugue/argus-l2b-private/contents/membership/latest.json', os.environ['PRIVATE_DIAGNOSTICS_TOKEN'])
        original = base64.b64decode(entry['content']); codes = members(json.loads(original))
        if not codes: raise ValueError('MEMBERSHIP_EMPTY')
        result['membershipHash'] = hashlib.sha256(original).hexdigest()
        previous = previous_index = None
        for number in range(2):
            if number: time.sleep(60)
            health, _ = get(BASE + '/healthz', os.environ['ARGUS_ADMIN_TOKEN'])
            if health.get('buildSha') != EXPECTED: raise ValueError('BACKEND_CHANGED')
            index, index_hash = get(BASE + '/api/argus/index-chart?index=N225&live=1', os.environ['ARGUS_ADMIN_TOKEN'])
            watch, watch_hash = get(BASE + '/api/argus/japan-watchlist?symbols=' + urllib.parse.quote(','.join(codes)), os.environ['ARGUS_ADMIN_TOKEN'])
            now = time.time(); projected, prices = projection(watch, codes, now)
            quote = index.get('quote') or {}; index_price = quote.get('price')
            index_state = (index_price, moment(quote.get('tradedAt')), moment(quote.get('receivedAt')))
            sample = {'at': datetime.now(timezone.utc).isoformat(), 'backendVersion': health.get('backendVersion'),
                'backendSha': health['buildSha'], 'indexBodyHash': index_hash, 'watchBodyHash': watch_hash,
                'index': {key: quote.get(key) for key in ('tradedAt', 'receivedAt', 'delaySeconds', 'sessionOpen', 'realtime', 'source', 'actionAuthority')},
                'delayed': projected}
            sample['index'].update(positiveFinitePrice=positive(index_price), workerAlive=index.get('workerAlive'), lastErrorPresent=bool(index.get('lastError')))
            if previous is not None:
                common = set(previous) & set(prices)
                result['change'] = {'comparable': len(common),
                    'priceChanged': sum(prices[s][0] != previous[s][0] for s in common),
                    'sourceAdvanced': sum(prices[s][1] > previous[s][1] for s in common),
                    'receiptAdvanced': sum(prices[s][2] > previous[s][2] for s in common),
                    'indexPriceChanged': positive(index_state[0]) and positive(previous_index[0]) and index_state[0] != previous_index[0],
                    'indexSourceAdvanced': index_state[1] is not None and previous_index[1] is not None and index_state[1] > previous_index[1]}
            previous, previous_index = prices, index_state
            result['samples'].append(sample)
        result['status'] = 'TWO_CACHED_SAMPLES_RECORDED_NOT_DEVICE_ACCEPTANCE'
        try:
            brief, brief_hash = get(BASE + '/api/argus/market-brief', os.environ['ARGUS_ADMIN_TOKEN'])
            context = brief.get('unifiedContext') or {}
            if (brief.get('schemaVersion') != 'argus-market-brief-v1'
                    or brief.get('sdaAuthority') is not False
                    or context.get('scope') != 'PUBLIC_MARKET'
                    or context.get('ownerContextAvailable') is not False):
                raise ValueError('PUBLIC_BRIEF_SCOPE')
            (out / 'market-brief-public.json').write_text(json.dumps(brief, ensure_ascii=False, allow_nan=False) + '\n')
            result['brief'] = {'bodyHash': brief_hash, 'generatedAt': brief.get('generatedAt'),
                'serialization': 'parsed-json-reserialized-not-original-http-bytes',
                'unifiedStatus': brief.get('unifiedStatus'), 'presentationStatus': brief.get('presentationStatus'),
                'contextId': context.get('contextId'), 'planId': (brief.get('presentationPlan') or {}).get('planId')}
            result['briefReadStatus'] = 'RECORDED_PUBLIC_MARKET'
        except urllib.error.HTTPError as exc:
            result.update(briefReadStatus='FAILED', briefErrorClass='HTTP_ERROR', briefHttp=exc.code)
        except Exception as exc:
            result.update(briefReadStatus='FAILED', briefErrorClass=(str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'[A-Z_]+', str(exc)) else type(exc).__name__))
    except urllib.error.HTTPError as exc: result.update(errorClass='HTTP_ERROR', http=exc.code)
    except Exception as exc: result['errorClass'] = str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z_]+',str(exc)) else type(exc).__name__
    result.update(readCount=reads, elapsedSeconds=round(time.monotonic() - start, 3))
    (out / 'intraday.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')


if __name__ == '__main__': main(sys.argv[1])
