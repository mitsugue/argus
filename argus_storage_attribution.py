"""What occupies the persistent disk, measured stat-only (2026-10-20).

The start of 2026-10-20 stopped because free space fell below what the
storage check requires, and the free space fell by about 44 MiB a day after
2026-10-11. This walks the persistent root once with lstat only: no file is
opened, read, written, moved or deleted, and no file name leaves the module.
Groups follow the 2026-10-11 stat-only attribution; files that match none of
them are further split by their top-level directory and their kind (the file
extension), so the unexplained share can be located.

Bounded (entries, depth, seconds); a bounded stop is reported as incomplete.
"""
import os
import re
import stat
import time
from typing import Any, Dict, Optional

SCHEMA = 'argus-storage-attribution-stat-only-v2'
MAX_ENTRIES = 20000
MAX_DEPTH = 8
MAX_SECONDS = 5.0
TOP = 30
_KIND_RE = re.compile(r'^[a-z0-9]{1,12}$')
_DIR_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')


def _group(path: str, name: str, root: str, checkpoint: str, wal: str) -> str:
    base = os.path.basename(checkpoint)
    rel = os.path.relpath(path, root).split(os.sep)
    if path == checkpoint:
        return 'activeLegacyCheckpoint'
    if name.startswith(base + '.') and (name.endswith('.tmp') or '.bootstrap-' in name):
        return 'checkpointTemp'
    if name.startswith(base + '.quarantine'):
        return 'checkpointQuarantine'
    if path == wal:
        return 'missionWal'
    if 'argus_checkpoint_v2' in rel:
        return 'checkpointV2'
    if name == 'market_analysis_history.sqlite3':
        return 'analysisHistoryDb'
    if name == 'jp_market_source_history.sqlite3':
        return 'sourceHistoryDb'
    if name in ('owner_dialogue.sqlite3', 'owner_vault_uploads.sqlite3', 'web_push.sqlite3'):
        return 'ownerStorage'
    if name.endswith('.json'):
        return 'otherJson'
    if name.endswith('.jsonl'):
        return 'otherJsonl'
    if name.endswith(('.sqlite3', '.db', '.sqlite3-wal', '.sqlite3-shm', '.db-wal', '.db-shm')):
        return 'otherDatabase'
    return 'otherFiles'


def _kind(name: str) -> str:
    stem, dot, ext = name.rpartition('.')
    if not dot or not stem:
        return 'noExtension'
    ext = ext.lower()
    return ext if _KIND_RE.fullmatch(ext) else 'otherExtension'


def _top_directory(path: str, root: str) -> str:
    parts = os.path.relpath(path, root).split(os.sep)
    if len(parts) == 1:
        return '(root)'
    return parts[0] if _DIR_RE.fullmatch(parts[0]) else '(unnamed)'


def _add(table: Dict[str, Dict[str, int]], key: str, st: os.stat_result) -> None:
    row = table.setdefault(key, {'files': 0, 'logicalBytes': 0, 'allocatedBytes': 0})
    row['files'] += 1
    row['logicalBytes'] += int(st.st_size)
    row['allocatedBytes'] += int(getattr(st, 'st_blocks', 0)) * 512


def _top(table: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    ranked = sorted(table.items(), key=lambda kv: (-kv[1]['allocatedBytes'], kv[0]))
    return dict(ranked[:TOP])


def attribute(root: str, *, checkpoint: str, wal: str, now=time.monotonic,
              statvfs=os.statvfs) -> Dict[str, Any]:
    started = now()
    root = os.path.realpath(root)
    try:
        device = os.lstat(root).st_dev
    except OSError:
        return {'schemaVersion': SCHEMA, 'complete': False, 'reason': 'root_unreadable'}
    groups: Dict[str, Dict[str, int]] = {}
    other_dirs: Dict[str, Dict[str, int]] = {}
    other_kinds: Dict[str, Dict[str, int]] = {}
    all_dirs: Dict[str, Dict[str, int]] = {}
    visited = errors = links = 0
    stopped = False
    stack = [(root, 0)]
    while stack:
        path, depth = stack.pop()
        if visited >= MAX_ENTRIES or depth > MAX_DEPTH or now() - started > MAX_SECONDS:
            stopped = True
            break
        try:
            st = os.lstat(path)
        except OSError:
            errors += 1
            continue
        visited += 1
        if stat.S_ISLNK(st.st_mode):
            links += 1
            continue
        if st.st_dev != device:
            continue
        if stat.S_ISDIR(st.st_mode):
            try:
                stack.extend((os.path.join(path, n), depth + 1) for n in os.listdir(path))
            except OSError:
                errors += 1
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        name = os.path.basename(path)
        group = _group(path, name, root, checkpoint, wal)
        _add(groups, group, st)
        top_dir = _top_directory(path, root)
        _add(all_dirs, top_dir, st)
        if group == 'otherFiles':
            _add(other_dirs, top_dir, st)
            _add(other_kinds, _kind(name), st)
    try:
        vfs = statvfs(root)
        available: Optional[int] = int(vfs.f_bavail * vfs.f_frsize)
        total: Optional[int] = int(vfs.f_blocks * vfs.f_frsize)
    except OSError:
        available = total = None
    return {'schemaVersion': SCHEMA, 'complete': not stopped and not errors,
            'boundedStopped': stopped, 'visitedEntries': visited, 'errors': errors,
            'symlinksSkipped': links, 'availableBytes': available, 'totalBytes': total,
            'groups': dict(sorted(groups.items())), 'byTopDirectory': _top(all_dirs),
            'otherFilesByTopDirectory': _top(other_dirs), 'otherFilesByKind': _top(other_kinds),
            'elapsedSeconds': round(now() - started, 3), 'fileNamesOutput': False,
            'bodyReads': 0, 'writes': 0, 'deletions': 0}
