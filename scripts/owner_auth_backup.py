#!/usr/bin/env python3
"""Offline SQLite backup/restore preparation. Never overwrites a live DB.

Restore writes a NEW private file with sessions/challenges/passkeys removed. The backup keeps the original keys. The
operator retains the original and switches ARGUS_OWNER_AUTH_DB while stopped.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile


def copy_database(source, destination, *, restore=False):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination_exists')
    fd, temporary = tempfile.mkstemp(prefix='.owner-auth-', dir=destination.parent)
    os.close(fd)
    try:
        src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        dst = sqlite3.connect(temporary)
        try:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('database_integrity')
            expected = {'owner_sessions', 'owner_challenges', 'owner_passkeys', 'owner_rate'}
            tables = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != expected:
                raise ValueError('database_schema')
            if restore:
                with dst:
                    dst.execute('DELETE FROM owner_sessions')
                    dst.execute('DELETE FROM owner_challenges')
                    # A historical backup may predate a lost-device revocation.
                    # Keep keys in the source archive, never reactivate them.
                    dst.execute('DELETE FROM owner_passkeys')
            key_count = dst.execute('SELECT count(*) FROM owner_passkeys').fetchone()[0]
        finally:
            src.close()
            dst.close()
        with open(temporary, 'rb') as handle:
            os.fsync(handle.fileno())
        # Atomic no-replace installation. A concurrent destination is preserved.
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        return {'passkeys': key_count, 'sessionsInvalidated': restore}
    finally:
        os.unlink(temporary)


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('backup', 'prepare-restore'))
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    print(json.dumps(copy_database(args.source, args.destination, restore=args.operation == 'prepare-restore')))
