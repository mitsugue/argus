"""Bounded derived index reports; numerical engines and original histories stay authoritative."""
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = 'argus-index-research-cache-v1'
MAX_BYTES = 24 * 1024 * 1024
KEYS = {f'chart:{index}:{frame}' for index in ('N225', 'TOPIX', 'SPX', 'NDX')
        for frame in ('daily', 'weekly')} | {f'comparison:N225:{h}' for h in (1, 5, 10, 20)}

# Only small completed studies are retained. Sealed episodes can exceed the
# existing file bound; rebuild them from current inputs and validate the
# engine's content key before reusing any study. No chart or original is added.
CALIBRATION_FIELDS = frozenset(('key', 'result', 'search', 'materialReactionResearch', 'yardstickResearch'))
CALIBRATION_MAX_BYTES = 2 * 1024 * 1024


@lru_cache(maxsize=1)
def calibration_method():
    root = Path(__file__).resolve().parent
    modules = ('argus_index_research_cache.py', 'jp_market_price_paths.py', 'jp_market_analog_backtest.py',
               'jp_market_analogs.py', 'jp_market_engine.py', 'jp_market_level_map.py')
    return digest({'schema': 'comparison-calibration-v1',
                   'python': list(sys.version_info[:3]),
                   'platform': sys.platform,
                   'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                               for name in modules}})


def calibration_record(state, *, method, at):
    if not state:
        return None
    if not CALIBRATION_FIELDS <= state.keys():
        raise ValueError('research_calibration_incomplete')
    selected = {key: state[key] for key in CALIBRATION_FIELDS}
    key = selected['key']
    if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('research_calibration_identity')
    if not isinstance(selected['result'], dict) or any(
            selected[k] is not None and not isinstance(selected[k], dict)
            for k in ('search', 'materialReactionResearch', 'yardstickResearch')):
        raise ValueError('research_calibration_result')
    raw = json.dumps(selected, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(raw.encode()) > CALIBRATION_MAX_BYTES:
        raise ValueError('research_calibration_size_bound')
    stamp(at)
    if not method:
        raise ValueError('research_calibration_method')
    body = {'methodVersion': method, 'savedAt': at, 'state': json.loads(raw)}
    return {**body, 'sha256': digest(body)}


def digest(value):
    from argus_market_artifact_store import payload_sha256
    return payload_sha256(value, depth=3)


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
    # Stored exactly as it reads back: a tuple in a policy becomes a list in
    # the file, so the in-memory record takes the JSON form too (2026-10-19:
    # every fresh comparison failed the save's read-back comparison).
    body = {'key': key, 'methodVersion': method, 'calculatedAt': at,
            'payload': json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))}
    return {**body, 'sha256': digest(body)}


def read(records, key, *, method, now):
    value = records.get(key)
    # Records enter memory only via record() or load(); screen reads never rehash history.
    return deepcopy(value) if _current_record(value, method=method, now=now) else None


def _current_record(value, *, method, now):
    return bool(value and value.get('methodVersion') == method
                and not stamp(value['calculatedAt']) > stamp(now))


def envelope(records, *, calibration=None):
    if set(records) - KEYS:
        raise ValueError('research_cache_key_bound')
    doc = {'schemaVersion': SCHEMA, 'records': records, 'sha256': digest(records)}
    if calibration is not None:
        doc['comparisonCalibration'] = calibration
        if _encoded_size(doc) > MAX_BYTES:
            del doc['comparisonCalibration']
    return doc


def _encoded_size(value):
    # Preserve the original default separators (including their spaces),
    # UTF-8 byte count and full validation, without retaining the whole text.
    # Do not stop at MAX_BYTES: invalid later values must still be rejected.
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False)
    return sum(len(piece.encode()) for piece in encoder.iterencode(value))


def load(path, *, method, now):
    return load_with_calibration(path, method=method, now=now)[0]


def load_with_calibration(path, *, method, now, calibration_method=None):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('research_cache_symlink')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('research_cache_size_bound')
    doc = json.loads(raw)
    # JSON parsing already gives this call sole ownership of every record.
    # Returning those admitted records does not alias any caller's objects;
    # copying them all again only overlaps two complete container graphs.
    return _admit_document(doc, method=method, now=now,
                           calibration_method=calibration_method)


def validate_for_persistence(doc, *, method, now, calibration_method=None):
    """Validate the source using the restore rules, without a second cache.

    Every record is still reconstructed and checked individually. Only the
    admitted output mapping borrows records, and it never escapes this call.
    Startup parsing and public reads retain their independent ownership.
    """
    restored, calibration = _admit_document(doc, method=method, now=now,
        calibration_method=calibration_method)
    if restored != doc['records']:
        raise ValueError('index_research_readback_mismatch')
    if calibration != (doc.get('comparisonCalibration') or {}).get('state', {}):
        raise ValueError('research_calibration_readback_mismatch')


def _admit_document(doc, *, method, now, calibration_method):
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
        admitted = value if _current_record(value, method=method, now=now) else None
        if admitted:
            restored[key] = admitted
    saved = doc.get('comparisonCalibration')
    calibration = {}
    if saved is not None:
        if not isinstance(saved, dict):
            raise ValueError('research_calibration_schema')
        expected = calibration_record(saved['state'], method=saved['methodVersion'], at=saved['savedAt'])
        if saved != expected:
            raise ValueError('research_calibration_integrity')
        if (calibration_method and saved['methodVersion'] == calibration_method
                and stamp(saved['savedAt']) <= stamp(now)):
            calibration = saved['state']
    return restored, calibration


def comparison_availability_improved(records, previous, *, method, now):
    """Cheap readiness check on already admitted memory records; no copying/replay.

    Ordinary price updates remain subject to normal edition coalescing. Only
    an absent comparison becoming usable warrants completing an earlier edition.
    """
    for horizon in (1, 5, 10, 20):
        old = (previous or {}).get(str(horizon)) or {}
        if isinstance(old.get('comparison'), dict):
            continue
        row = records.get(f'comparison:N225:{horizon}') or {}
        if row.get('methodVersion') != method:
            continue
        try:
            if stamp(row['calculatedAt']) > stamp(now):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if isinstance((row.get('payload') or {}).get('comparison'), dict):
            return True
    return False


RETENTION_MAX_AGE_HOURS = 72


def comparison_retention_reason(payload, previous, *, feature_history_available, now,
                                max_age_hours=RETENTION_MAX_AGE_HOURS):
    """Why a freshly calculated comparison must NOT replace the saved one.

    While the market-condition history is being recalculated (after a deploy
    that changed its method, or while its collection fails) the engine can
    only compare price shape, and its candidates and computed forecast differ
    from the market-condition comparison. Replacing a saved market-condition
    document with that would make the chart swap candidates twice for no new
    information (2026-09-30). Keep the saved document, bounded in age, until
    the history is available again. Returns a fixed reason token or None.
    """
    if feature_history_available:
        return None
    new_candidates = ((payload or {}).get('comparison') or {}).get('candidates') or []
    if any('marketState' not in (c.get('missingGroups') or []) for c in new_candidates if isinstance(c, dict)):
        return None  # the new document does carry market conditions
    old_payload = (previous or {}).get('payload') or {}
    old_candidates = (old_payload.get('comparison') or {}).get('candidates') or []
    if not any('marketState' not in (c.get('missingGroups') or []) for c in old_candidates if isinstance(c, dict)):
        return None  # nothing better saved
    try:
        age = stamp(now) - stamp(previous['calculatedAt'])
    except (KeyError, TypeError, ValueError):
        return None
    if age.total_seconds() < 0 or age.total_seconds() > max_age_hours * 3600:
        return None
    return 'feature_history_recalculating'
