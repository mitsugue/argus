"""Bounded derived index reports; numerical engines and original histories stay authoritative."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

SCHEMA = 'argus-index-research-cache-v1'
MAX_BYTES = 24 * 1024 * 1024
KEYS = {f'chart:{index}:{frame}' for index in ('N225', 'TOPIX', 'SPX', 'NDX')
        for frame in ('daily', 'weekly')} | {f'comparison:N225:{h}' for h in (1, 5, 10, 20)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('research_cache_timestamp')
    return parsed


def record(key, payload, *, method, at):
    if key not in KEYS or not isinstance(payload, dict) or not method:
        raise ValueError('research_cache_identity')
    stamp(at)
    if key.startswith('chart:'):
        _, index, frame = key.split(':')
        if payload.get('symbol') != index or payload.get('timeframe') != frame or payload.get('index') != index:
            raise ValueError('research_cache_report_identity')
        if not payload.get('reportId'):
            raise ValueError('research_cache_report_missing')
    elif not isinstance(payload.get('comparison'), dict):
        raise ValueError('research_cache_comparison_missing')
    body = {'key': key, 'methodVersion': method, 'calculatedAt': at, 'payload': deepcopy(payload)}
    return {**body, 'sha256': digest(body)}


def read(records, key, *, method, now):
    value = records.get(key)
    if not value or value.get('methodVersion') != method:
        return None
    if stamp(value['calculatedAt']) > stamp(now):
        return None
    # Records enter memory only via record() or load(); screen reads never rehash history.
    return deepcopy(value)


def envelope(records):
    if set(records) - KEYS:
        raise ValueError('research_cache_key_bound')
    return {'schemaVersion': SCHEMA, 'records': records, 'sha256': digest(records)}


def load(path, *, method, now):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('research_cache_symlink')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('research_cache_size_bound')
    doc = json.loads(raw)
    records = doc.get('records')
    if doc.get('schemaVersion') != SCHEMA or not isinstance(records, dict) or set(records) - KEYS:
        raise ValueError('research_cache_schema')
    if doc.get('sha256') != digest(records):
        raise ValueError('research_cache_integrity')
    restored = {}
    for key, value in records.items():
        expected = record(key, value['payload'], method=value['methodVersion'], at=value['calculatedAt'])
        if value != expected:
            raise ValueError('research_cache_record_integrity')
        admitted = read({key: value}, key, method=method, now=now)
        if admitted:
            restored[key] = admitted
    return restored
