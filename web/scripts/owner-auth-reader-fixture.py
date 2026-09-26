"""Synthetic, stdin-only bridge to the actual Flask owner boundary for Node tests."""
import json
import hashlib
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash
from argus_owner_auth import install

with tempfile.TemporaryDirectory(prefix='argus-reader-fixture-') as directory:
    app = Flask(__name__)
    auth = install(app, {
        'ARGUS_OWNER_AUTH_REQUIRED': '1',
        'ARGUS_OWNER_AUTH_DB': str(Path(directory) / 'owner.sqlite3'),
        'ARGUS_OWNER_AUTH_ORIGIN': 'https://owner.example',
        'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash('synthetic-only-password', method='pbkdf2:sha256:1000'),
        'ARGUS_ADMIN_TOKEN': 'synthetic-admin-only',
    })
    stamp = datetime.now(timezone.utc).isoformat()
    calls = []
    @app.get('/api/argus/chart-intelligence')
    def chart():
        symbol, horizon = request.args['symbol'], request.args['horizon']
        calls.append('chart')
        return jsonify({
            'schemaVersion': 'argus-verified-view-snapshot-v1',
            'snapshotId': 'vs-' + hashlib.sha256((symbol + horizon).encode()).hexdigest()[:32],
            'kind': 'market-chart', 'market': 'JP' if symbol in ('1321', '1306') else 'US',
            'instrument': symbol, 'horizon': horizon,
            'datasetHash': 'synthetic-dataset', 'payloadHash': 'synthetic-payload',
            'methodVersion': 'synthetic-reader-contract',
            'asOf': stamp, 'generatedAt': stamp, 'verifiedAt': stamp,
            'quality': 'live', 'sourceStatus': {'chart': 'complete'},
            'verificationStatus': 'verified', 'payload': {'automaticAiCalls': 0},
            'releaseBinding': {'expectedBuildSha': 'a' * 40,
                               'producerTriggerId': 'synthetic-reader-trigger', 'triggeredAt': stamp},
        })
    @app.post('/api/argus/admin/missions/tick')
    def tick():
        if request.headers.get('X-ARGUS-ADMIN-TOKEN') != 'synthetic-admin-only':
            return jsonify(error='forbidden'), 403
        calls.append('tick')
        return jsonify(status='completed', schemaVersion='argus-release-snapshot-seed-v1',
                       producerTriggerId='synthetic-reader-trigger', expectedBuildSha='a' * 40,
                       snapshotExpected=12, snapshotReady=12,
                       persistence={'verified': True, 'readBackVerified': True})
    client = app.test_client()
    for line in sys.stdin:
        message = json.loads(line)
        if message.get('inspect'):
            with auth.db() as conn:
                sessions = conn.execute('select count(*) from owner_sessions').fetchone()[0]
            print(json.dumps({'sessions': sessions, 'calls': calls}), flush=True)
            continue
        response = client.open(message['url'], method=message.get('method', 'GET'),
                               headers=message.get('headers', {}), data=message.get('body'))
        print(json.dumps({'status': response.status_code, 'headers': dict(response.headers),
                          'body': response.get_data(as_text=True)}), flush=True)
