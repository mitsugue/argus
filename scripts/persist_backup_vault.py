#!/usr/bin/env python3
"""既存の暗号化バックアップだけを保存する。応答本文・識別子は出力しない。"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error

# workflow checkout後も、同じ実行SHAからstageしたHTTP実装を使う。
try:
    from scripts.workflow_http import request_json
except ModuleNotFoundError:
    from workflow_http import request_json


class VaultFailure(Exception):
    pass


def validated_slots(raw):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise VaultFailure('invalid_json') from None
    if not isinstance(value, dict) or not isinstance(value.get('slots'), dict):
        raise VaultFailure('invalid_slots')
    slots = value['slots']
    if len(slots) > 10:
        raise VaultFailure('slots_bound')
    checked = []
    for identity, slot in slots.items():
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
            raise VaultFailure('invalid_slot')
        if not isinstance(slot, dict):
            raise VaultFailure('invalid_slot')
        timestamp, blob = slot.get('ts'), slot.get('blob')
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp <= 0:
            raise VaultFailure('invalid_timestamp')
        try:
            stamp = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')
        except (ValueError, OverflowError, OSError):
            raise VaultFailure('invalid_timestamp') from None
        if not isinstance(blob, str) or not 1 <= len(blob.encode('utf-8')) <= 256 * 1024:
            raise VaultFailure('invalid_envelope')
        try:
            envelope = json.loads(blob)
            if not isinstance(envelope, dict) or set(envelope) != {'v', 'salt', 'iv', 'ct', 'exportedAt'} or type(envelope['v']) is not int or envelope['v'] != 1:
                raise ValueError()
            if not isinstance(envelope['exportedAt'], str) or len(envelope['exportedAt']) > 40:
                raise ValueError()
            for key, size in (('salt', 16), ('iv', 12), ('ct', None)):
                if not isinstance(envelope[key], str):
                    raise ValueError()
                decoded = base64.b64decode(envelope[key], validate=True)
                if (size is not None and len(decoded) != size) or (size is None and len(decoded) < 16):
                    raise ValueError()
        except (ValueError, TypeError):
            raise VaultFailure('invalid_envelope') from None
        checked.append((identity, stamp, blob))
    return checked


def fetch_slots(url, token, *, attempts=3, timeout=45, retry_delay=5):
    if not token:
        raise VaultFailure('missing_admin_token')
    reason = 'not_attempted'
    for attempt in range(1, attempts + 1):
        retry = False
        try:
            code, raw = request_json(url=url, method='POST', timeout=timeout,
                                     headers={'X-ARGUS-ADMIN-TOKEN': token})
            if not 200 <= code < 300:
                reason = f'http_{code}'
                retry = code in (408, 425, 500, 502, 503, 504)
            else:
                try:
                    return validated_slots(raw)
                except VaultFailure as exc:
                    reason = str(exc)
                    retry = reason == 'invalid_json'
        except (TimeoutError, socket.timeout):
            reason, retry = 'timeout', True
        except (urllib.error.URLError, OSError):
            reason, retry = 'transport_error', True
        if not retry or attempt == attempts:
            raise VaultFailure(reason)
        print(f'backup-vault retry={attempt}/{attempts} reason={reason}', file=sys.stderr)
        time.sleep(retry_delay)
    raise VaultFailure(reason)


def persist_slots(slots, root):
    root = Path(root)
    # Validate collisions for the complete batch before replacing any saved data.
    for identity, stamp, blob in slots:
        path = root / identity / (stamp + '.json')
        if path.exists() and path.read_text() != blob:
            raise VaultFailure('existing_snapshot_conflict')
    for identity, stamp, blob in slots:
        directory = root / identity
        directory.mkdir(parents=True, exist_ok=True)
        historical = directory / (stamp + '.json')
        if not historical.exists():
            temporary = directory / (stamp + '.pending')
            temporary.write_text(blob, encoding='utf-8')
            temporary.replace(historical)
        history = sorted(p for p in directory.glob('*.json') if p.name != 'latest.json')
        # A late replay cannot move latest backwards; keep the existing eight-copy policy.
        latest = directory / 'latest.pending'
        latest.write_bytes(history[-1].read_bytes())
        latest.replace(directory / 'latest.json')
        for old in history[:-8]:
            old.unlink()
    return len(slots)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--ledger-root', required=True)
    args = parser.parse_args(argv)
    try:
        slots = fetch_slots(args.url, os.environ.get('ARGUS_ADMIN_TOKEN', ''))
        count = persist_slots(slots, args.ledger_root)
    except VaultFailure as exc:
        print(f'::error title=Backup persistence failed::backup-vault reason={exc}; existing backups retained', file=sys.stderr)
        return 1
    except OSError:
        print('::error title=Backup persistence failed::backup-vault reason=storage_error', file=sys.stderr)
        return 1
    print(f'backup-vault status=saved envelopes={count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
