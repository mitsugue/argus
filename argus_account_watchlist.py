"""Owner registrations in the existing authenticated persistent SQLite database.

No provider requests, public repository writes, or separate browser secrets.
Field patches and revision checks preserve concurrent edits; receipts make a
lost acknowledgement safe to retry. Deleted identities are retained for old
installation migration and never inferred from an incomplete device snapshot.
"""
import hashlib
from datetime import datetime, timezone
import json
import math
import sqlite3
import uuid

from flask import jsonify, request


class StoredStateError(RuntimeError):
    pass


MAX_BODY = 256 * 1024
REQUIRED = {'id', 'symbol', 'displayName', 'market', 'assetType', 'source',
            'enabled', 'sortOrder', 'createdAt', 'updatedAt'}
OPTIONAL = {'displayNameJa', 'memo', 'quantity', 'avgCost', 'purchaseReason',
            'holdingPeriod', 'monthlyContribution', 'targetAllocation', 'currentAllocation'}
FIELDS = REQUIRED | OPTIONAL
FORBIDDEN = {'__proto__', 'prototype', 'constructor', 'admin', 'ownerToken', 'password', 'session', 'order'}


def safe_json(value, depth=0):
    if depth > 8:
        raise ValueError('invalid_archive')
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError('invalid_archive')
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 160 or key in FORBIDDEN:
                raise ValueError('invalid_archive')
            safe_json(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 100:
            raise ValueError('invalid_archive')
        for child in value:
            safe_json(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > 4000:
            raise ValueError('invalid_archive')
    elif type(value) in (int, float):
        if not math.isfinite(value) or abs(value) > 9e15:
            raise ValueError('invalid_archive')
    elif value is not None and type(value) is not bool:
        raise ValueError('invalid_archive')


NUMERIC = {'sortOrder', 'createdAt', 'updatedAt', 'quantity', 'avgCost',
           'monthlyContribution', 'targetAllocation', 'currentAllocation'}
ENUMS = {'market': {'JP', 'US', 'CRYPTO', 'FUND', 'CORE', 'MANUAL'},
         'assetType': {'jp_equity', 'us_equity', 'crypto', 'listed_etf', 'core_fund', 'manual_fund'},
         'source': {'jquants', 'twelvedata', 'coingecko', 'manual', 'mock'}}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def validate_asset(asset):
    if not isinstance(asset, dict) or not REQUIRED <= asset.keys() or len(asset) > 100:
        raise ValueError('invalid_asset')
    safe_json(asset)
    for key, value in asset.items():
        if key not in FIELDS:
            continue  # Unknown historical archive fields have no product authority.
        if key in ENUMS:
            if not isinstance(value, str) or value not in ENUMS[key]:
                raise ValueError('invalid_asset')
        elif key == 'enabled':
            if type(value) is not bool:
                raise ValueError('invalid_asset')
        elif key in NUMERIC:
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 9e15:
                raise ValueError('invalid_asset')
            if key != 'sortOrder' and value < 0:
                raise ValueError('invalid_asset')
        elif not isinstance(value, str) or len(value) > (2000 if key in OPTIONAL else 160):
            raise ValueError('invalid_asset')
    if any(not asset[key].strip() for key in ('id', 'symbol', 'displayName')):
        raise ValueError('invalid_asset')
    return asset


def prepare(auth):
    if not auth.enabled:
        return
    with auth.db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS owner_watchlist (
                id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS owner_watchlist_receipts (
                batch_id TEXT PRIMARY KEY, digest TEXT NOT NULL);
        ''')


def read_state(conn):
    row = conn.execute('SELECT revision, document FROM owner_watchlist WHERE id=1').fetchone()
    if not row:
        return {'revision': 0, 'initialized': False, 'assets': [], 'deleted': []}
    try:
        document = json.loads(row['document'])
    except (ValueError, TypeError):
        raise StoredStateError('stored_state_invalid') from None
    # Corruption is unavailable, never an empty account that replaces registrations.
    if not isinstance(document, dict) or set(document) != {'assets', 'deleted', 'updatedAt'}:
        raise StoredStateError('stored_state_invalid')
    if not isinstance(document['assets'], list) or not isinstance(document['deleted'], list):
        raise StoredStateError('stored_state_invalid')
    try:
        stamp = datetime.fromisoformat(document['updatedAt'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('invalid_timestamp')
        for asset in document['assets']:
            validate_asset(asset)
        if len(document['assets']) > 50 or len({a['id'] for a in document['assets']}) != len(document['assets']) or any(
                not isinstance(value, str) for value in document['deleted']):
            raise ValueError('invalid_document')
    except (ValueError, AttributeError):
        raise StoredStateError('stored_state_invalid') from None
    return {'revision': row['revision'], 'initialized': True, **document}


def apply_operations(state, operations):
    if not isinstance(operations, list) or len(operations) > 150:
        raise ValueError('invalid_operations')
    assets = {item['id']: dict(item) for item in state['assets']}
    deleted = set(state['deleted'])
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError('invalid_operation')
        if op.get('kind') in ('add', 'import') and set(op) == {'kind', 'asset'}:
            asset = validate_asset(op['asset'])
            identity = asset['id']
            if op['kind'] == 'import':
                # First join of an old device adds unique real registrations,
                # but never resurrects a deletion or replaces a newer device.
                if identity in deleted:
                    continue
                if identity in assets:
                    assets[identity] = {**asset, **assets[identity]}
                    continue
            assets[identity] = dict(asset)
            deleted.discard(identity)
        elif op.get('kind') == 'remove' and set(op) == {'kind', 'id'}:
            if not isinstance(op['id'], str) or not 0 < len(op['id']) <= 160:
                raise ValueError('invalid_identity')
            assets.pop(op['id'], None)
            deleted.add(op['id'])
        elif op.get('kind') == 'update' and set(op) == {'kind', 'id', 'set', 'unset'}:
            if not isinstance(op['id'], str) or not isinstance(op['set'], dict) or not isinstance(op['unset'], list):
                raise ValueError('invalid_patch')
            safe_json(op['set'])
            if op['set'].keys() & {'id', 'createdAt', 'market', 'symbol'} or any(
                    not isinstance(key, str) or key in REQUIRED or key in FORBIDDEN or len(key) > 160 for key in op['unset']):
                raise ValueError('invalid_patch')
            # An edit based on a now-deleted item does not re-create it.
            if op['id'] not in assets:
                continue
            item = {**assets[op['id']], **op['set']}
            for key in op['unset']:
                item.pop(key, None)
            assets[op['id']] = validate_asset(item)
        else:
            raise ValueError('invalid_operation')
    if len(assets) > 50:
        raise ValueError('asset_limit')
    return {'assets': sorted(assets.values(), key=lambda a: (a['sortOrder'], a['id'])),
            'deleted': sorted(deleted)}


def action(auth):
    if not auth.enabled:
        return jsonify(error='owner_auth_disabled'), 503
    try:
        if not auth.session():
            return jsonify(error='owner_auth_required'), 401
        if request.method == 'GET':
            with auth.reader() as conn:
                return jsonify(read_state(conn))
        if request.headers.get('Origin') != auth.origin:
            return jsonify(error='origin_rejected'), 403
        if request.content_length is None or request.content_length > MAX_BODY:
            return jsonify(error='body_limit'), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'revision', 'batchId', 'operations'}:
            return jsonify(error='invalid_request'), 400
        revision = body['revision']
        if type(revision) is not int or revision < 0 or str(uuid.UUID(body['batchId'])) != body['batchId']:
            return jsonify(error='invalid_request'), 400
        digest = hashlib.sha256(canonical(body['operations']).encode()).hexdigest()
        with auth.db() as conn:
            current = read_state(conn)
            receipt = conn.execute('SELECT digest FROM owner_watchlist_receipts WHERE batch_id=?',
                                   (body['batchId'],)).fetchone()
            if receipt:
                if receipt['digest'] != digest:
                    return jsonify(error='batch_reused'), 409
                return jsonify(batchId=body['batchId'], **current)
            if revision != current['revision']:
                return jsonify(error='revision_conflict'), 409
            document = apply_operations(current, body['operations'])
            document['updatedAt'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            next_revision = revision + 1
            conn.execute('INSERT INTO owner_watchlist VALUES (1,?,?) ON CONFLICT(id) DO UPDATE '
                         'SET revision=excluded.revision, document=excluded.document',
                         (next_revision, canonical(document)))
            conn.execute('INSERT INTO owner_watchlist_receipts VALUES (?,?)', (body['batchId'], digest))
            saved = read_state(conn)
            if saved['assets'] != document['assets'] or saved['deleted'] != document['deleted']:
                raise sqlite3.DatabaseError('readback_mismatch')
        return jsonify(batchId=body['batchId'], **saved)
    except (ValueError, TypeError, KeyError, AttributeError):
        # Stored-state corruption must not be exposed as user error or empty.
        return jsonify(error='watchlist_invalid_request'), 400
    except (sqlite3.Error, StoredStateError):
        return jsonify(error='watchlist_unavailable'), 503


def account_state(auth):
    """Trusted internal reader, with no browser credential or provider request."""
    if not auth or not auth.enabled:
        return None
    with auth.reader() as conn:
        value = read_state(conn)
    return value if value['initialized'] else None


def membership_snapshot(auth, legacy=None):
    """One current registration source; retain existing non-monetary settings."""
    value = account_state(auth)
    if value is None:
        return legacy
    import argus_watchlist_sync as membership
    previous = {(item.get('market'), str(item.get('symbol', '')).upper()): item
                for item in (legacy or {}).get('members', []) if isinstance(item, dict)}
    rows = []
    for asset in value['assets']:
        if not asset['enabled'] or asset['market'] not in ('JP', 'US', 'CRYPTO'):
            continue
        old = previous.get((asset['market'], asset['symbol'].upper()), {})
        row = {key: old[key] for key in ('ownerState', 'downsideStrictness', 'priority') if key in old}
        rows.append({**row, 'symbol': asset['symbol'], 'market': asset['market'],
                     'name': asset.get('displayNameJa') or asset['displayName'], 'enabled': True})
    valid, cleaned, _ = membership.validate_sync_payload({'items': rows})
    if not valid:
        raise StoredStateError('membership_projection_invalid')
    effective = datetime.fromisoformat(value['updatedAt'].replace('Z', '+00:00'))
    from datetime import timedelta
    return membership.build_membership_snapshot(cleaned['items'],
        effective_date=effective.astimezone(timezone(timedelta(hours=9))).date().isoformat(),
        generated_at=value['updatedAt'], snapshot_id='account-' + str(value['revision']))
