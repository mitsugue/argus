"""Bounded cache of the existing public ledger's replaceable result lookup."""
import copy
import json
import threading
import time
from datetime import datetime, timezone

URL = 'https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/event-prediction-results/v1/recent.json'
MAX_BYTES = 1024 * 1024 + 32 * 1024
_LOCK = threading.Lock()
_CACHE = None
_RETRY_AT = 0.0


def read_source():
    global _CACHE, _RETRY_AT
    with _LOCK:
        if time.monotonic() < _RETRY_AT:
            return copy.deepcopy(_CACHE)
        import requests
        try:
            deadline = time.monotonic() + 10
            with requests.get(URL, stream=True, timeout=(3, 7), allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('event_result_source_http_status')
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    if time.monotonic() > deadline or len(raw) + len(chunk) > MAX_BYTES:
                        raise ValueError('event_result_source_read_bound')
                    raw.extend(chunk)
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('schemaVersion') != 'argus-event-result-source-v1':
                raise ValueError('event_result_source_schema')
            _CACHE = {'status': 'AVAILABLE', 'data': data,
                      'readAt': datetime.now(timezone.utc).isoformat()}
            _RETRY_AT = time.monotonic() + 300
        except Exception as exc:
            # Preserve the last successful read time without presenting a failed read as fresh data.
            previous = _CACHE or {}
            _CACHE = {'status': 'UNAVAILABLE', 'errorClass': type(exc).__name__,
                      'lastSuccessfulReadAt': previous.get('readAt') or previous.get('lastSuccessfulReadAt')}
            _RETRY_AT = time.monotonic() + 30
        return copy.deepcopy(_CACHE)
