"""The local form of the market analysis history: calculation parts kept once (2026-10-20).

Owner decision 2026-10-20 (design: 設計_分析履歴の手元の保存の形_2026-10-20.md):
each edition's calculations (market features, internals, comparisons, ...)
repeat the previous edition almost entirely, so they are stored once per
content (SHA-256 of the canonical JSON, zlib-compressed) and the edition keeps
a skeleton with `{"$part": id}` in their place. The brief stays in the row, so
every SQL read of brief fields works unchanged. A row is replaced by its
skeleton only after the skeleton and parts rebuild the original body byte for
byte, and every read checks the rebuilt body against the original SHA-256.

Pure functions plus SQLite statements on a connection the caller owns; no
clock, no network. Nothing is deleted: the original body is the rebuilt one.
"""
import copy
import hashlib
import json
import zlib
from typing import Any, Callable, Dict, Tuple

PART_MIN_BYTES = 2048
VOLATILE_KEYS = frozenset({'informationCutoff', 'createdAt', 'lastAttemptAt', 'asOf',
                           'generatedAt', 'composedAt', 'measuredAt', 'checkedAt'})
FORM_SCHEMA_VERSION = 2
TABLES = '''CREATE TABLE IF NOT EXISTS view_parts(identity TEXT PRIMARY KEY,
      codec TEXT NOT NULL CHECK(codec='zlib'), raw_bytes INTEGER NOT NULL, body BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS form_migrations(record_id TEXT PRIMARY KEY,
      full_sha256 TEXT NOT NULL, full_bytes INTEGER NOT NULL, skeleton_bytes INTEGER NOT NULL,
      migrated_at TEXT NOT NULL);'''


def canonical(value: Any) -> str:
    """The same canonical JSON the history uses for its bodies."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _placeholder(value: Any) -> bool:
    return (isinstance(value, dict) and '$part' in value and set(value) <= {'$part', '$volatile'}
            and isinstance(value['$part'], str) and len(value['$part']) == 64
            and isinstance(value.get('$volatile', {}), dict))


def _has_placeholder(value: Any) -> bool:
    if _placeholder(value):
        return True
    if isinstance(value, dict):
        return any(_has_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(v) for v in value)
    return False


def split(record: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    """(skeleton, {identity: canonical bytes}); only calculation values are parted."""
    if _has_placeholder(record):
        raise ValueError('history_local_reserved_placeholder')
    skeleton = copy.deepcopy(record)
    parts: Dict[str, bytes] = {}
    calculations = skeleton.get('calculations')
    if not isinstance(calculations, dict):
        return skeleton, parts
    for horizon in sorted(calculations):
        container = calculations[horizon]
        if not isinstance(container, dict):
            continue
        for key in sorted(container):
            value = container[key]
            if len(canonical(value).encode()) < PART_MIN_BYTES:
                continue
            volatile = {}
            if isinstance(value, dict):
                volatile = {k: value[k] for k in value if k in VOLATILE_KEYS}
                value = {k: value[k] for k in value if k not in VOLATILE_KEYS}
            raw = canonical(value).encode()
            identity = digest(raw)
            parts[identity] = raw
            container[key] = {'$part': identity, **({'$volatile': volatile} if volatile else {})}
    return skeleton, parts


def assemble(skeleton: Dict[str, Any], part: Callable[[str], Any]) -> Dict[str, Any]:
    record = copy.deepcopy(skeleton)
    calculations = record.get('calculations')
    if not isinstance(calculations, dict):
        return record
    for container in calculations.values():
        if not isinstance(container, dict):
            continue
        for key in list(container):
            value = container[key]
            if not _placeholder(value):
                continue
            body = part(value['$part'])
            volatile = value.get('$volatile') or {}
            if volatile:
                if not isinstance(body, dict) or set(body) & set(volatile):
                    raise ValueError('history_local_volatile_conflict')
                body = {**body, **volatile}
            container[key] = body
    if _has_placeholder(record):
        raise ValueError('history_local_unresolved_part')
    return record


def ensure_tables(conn) -> None:
    conn.executescript(TABLES)


def tables_present(conn) -> bool:
    return conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND "
                        "name IN ('view_parts','form_migrations')").fetchone()[0] == 2


def read_part(conn, identity: str) -> Any:
    row = conn.execute('SELECT codec, raw_bytes, body FROM view_parts WHERE identity=?', (identity,)).fetchone()
    if not row or row[0] != 'zlib':
        raise ValueError('history_local_part_missing')
    raw = zlib.decompress(row[2])
    if len(raw) != row[1] or digest(raw) != identity:
        raise ValueError('history_local_part_integrity')
    return json.loads(raw)


def store_part(conn, identity: str, raw: bytes) -> int:
    """Insert once; an existing part must hold the same content. Returns bytes added."""
    if digest(raw) != identity:
        raise ValueError('history_local_part_identity')
    packed = zlib.compress(raw, 6)
    cursor = conn.execute('INSERT OR IGNORE INTO view_parts(identity,codec,raw_bytes,body) VALUES(?,?,?,?)',
                          (identity, 'zlib', len(raw), packed))
    if cursor.rowcount == 0:
        read_part(conn, identity)          # verifies the stored content against its identity
        return 0
    return len(packed)


def full_body(conn, record_id: str, body: str) -> str:
    """The original body of a row in either form; a mismatch is an error, never a guess."""
    if not tables_present(conn):
        return body
    row = conn.execute('SELECT full_sha256, full_bytes FROM form_migrations WHERE record_id=?',
                       (record_id,)).fetchone()
    if not row:
        return body
    rebuilt = canonical(assemble(json.loads(body), lambda identity: read_part(conn, identity)))
    encoded = rebuilt.encode()
    if len(encoded) != row[1] or digest(encoded) != row[0]:
        raise ValueError('history_local_rebuild_mismatch')
    return rebuilt
