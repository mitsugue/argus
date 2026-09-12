"""Private, append-only dialogue jobs. Reading never resumes a paid request."""
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import uuid
from contextlib import closing
from argus_owner_dialogue import digest, instant
from argus_product_naming import require_allowed

MAX_BYTES = 196608


def encoded(value):
    require_allowed(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('dialogue_record_bound')
    return raw


def connect(path, readonly=False):
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('dialogue_regular_file_required')
    db = sqlite3.connect(path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=5, isolation_level=None)
    if db.execute('PRAGMA user_version').fetchone()[0] != 1:
        db.close(); raise ValueError('dialogue_schema_invalid')
    if not readonly:
        db.execute('PRAGMA synchronous=FULL')
    return db


def initialize(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        connect(path, True).close(); return
    fd, temporary = tempfile.mkstemp(prefix='.owner-dialogue-', dir=path.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript('''PRAGMA synchronous=FULL;
                BEGIN IMMEDIATE;
                CREATE TABLE requests(sequence INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    input_hash TEXT NOT NULL, boot_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE completions(request_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                PRAGMA user_version=1; COMMIT;''')
        with open(temporary, 'rb') as handle: os.fsync(handle.fileno())
        try: os.link(temporary, path)
        except FileExistsError: connect(path, True).close()
        folder = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(folder)
        finally: os.close(folder)
    finally: os.unlink(temporary)


def request_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('dialogue_request_id_invalid')
    return value


def decode(raw):
    value = json.loads(raw)
    if value.get('recordDigest') != digest({k: v for k, v in value.items() if k != 'recordDigest'}):
        raise ValueError('dialogue_record_integrity')
    require_allowed(value)
    return value


def sealed(value):
    return encoded({**value, 'recordDigest': digest(value)})


def submit(path, *, identity, input_hash, boot_id, context):
    request_id(identity)
    instant(context['receivedAt'])
    if context.get('scope') != 'OWNER_PRIVATE' or context.get('contextId') != digest({k:v for k,v in context.items() if k!='contextId'}):
        raise ValueError('dialogue_context_integrity')
    body = sealed({'requestId': identity, 'inputHash': input_hash, 'bootId': boot_id, 'context': context})
    with closing(connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT input_hash FROM requests WHERE request_id=?', (identity,)).fetchone()
        if old:
            if old[0] != input_hash: raise ValueError('dialogue_request_conflict')
            db.commit(); return False
        if db.execute('SELECT 1 FROM requests r LEFT JOIN completions c USING(request_id) WHERE r.boot_id=? AND c.request_id IS NULL LIMIT 1', (boot_id,)).fetchone():
            raise ValueError('dialogue_busy')
        db.execute('INSERT INTO requests(request_id,input_hash,boot_id,body) VALUES(?,?,?,?)', (identity,input_hash,boot_id,body))
        db.commit()
    return True


def complete(path, identity, result):
    request_id(identity)
    if result.get('status') not in ('SUCCEEDED', 'REJECTED', 'FAILED', 'UNAVAILABLE'):
        raise ValueError('dialogue_completion_status')
    raw = sealed(result)
    with closing(connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM requests WHERE request_id=?', (identity,)).fetchone():
            raise ValueError('dialogue_request_missing')
        old = db.execute('SELECT body FROM completions WHERE request_id=?', (identity,)).fetchone()
        if old and old[0] != raw: raise ValueError('dialogue_completion_conflict')
        db.execute('INSERT OR IGNORE INTO completions VALUES(?,?)', (identity,raw))
        db.commit()


def read(path, identity, boot_id):
    request_id(identity)
    if not Path(path).exists(): return None
    with closing(connect(path, True)) as db:
        row = db.execute('SELECT r.sequence,r.body,c.body FROM requests r LEFT JOIN completions c USING(request_id) WHERE r.request_id=?', (identity,)).fetchone()
    if not row: return None
    request = decode(row[1]); result = decode(row[2]) if row[2] else None
    return {'requestId': identity, 'sequence': row[0], 'inputHash': request['inputHash'], 'context': request['context'],
        'status': result['status'] if result else ('RUNNING' if request['bootId']==boot_id else 'INTERRUPTED'),
        'result': result, 'persistenceStatus': 'LOCAL_DURABLE', 'remoteRecoveryVerified': False}


def history(path, boot_id, *, before=None):
    if not Path(path).exists(): return {'items':[], 'nextBefore':None}
    if before is not None and (type(before) is not int or before<1): raise ValueError('dialogue_cursor_invalid')
    with closing(connect(path, True)) as db:
        rows = db.execute('SELECT request_id,sequence FROM requests WHERE sequence<? ORDER BY sequence DESC LIMIT 21', (before or 9223372036854775807,)).fetchall()
    return {'items':[read(path, row[0], boot_id) for row in rows[:20]], 'nextBefore': rows[19][1] if len(rows)>20 else None}
