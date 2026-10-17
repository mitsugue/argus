"""Dedicated loopback HTTPS fixture using the real owner authentication boundary.
Only synthetic requests to the fixed local release fixture are forwarded.
Configuration arrives on stdin; no production credential or configuration read.
"""
import json
from pathlib import Path
import sys
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, request, Response
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler
from argus_owner_auth import install

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Quiet(WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        route = self.path.split('?', 1)[0]
        # Fixed synthetic endpoints and status only; no headers, bodies or query.
        if route.startswith('/api/argus/'):
            print(json.dumps({'route': route, 'status': code}), file=sys.stderr, flush=True)

config = json.loads(sys.stdin.readline())
assert config['mode'] in ('0', '1')
assert config['upstream'] == 'http://127.0.0.1:4399'
assert config['origin'] == 'https://argus-fixture.test'
assert Path(config['root']).is_dir() and Path(config['root']).name.startswith('argus-owner-today-')
app = Flask(__name__)
install(app, {
    'ARGUS_OWNER_AUTH_REQUIRED': config['mode'],
    'ARGUS_OWNER_AUTH_DB': str(Path(config['root']) / 'owner.sqlite3'),
    'ARGUS_OWNER_AUTH_ORIGIN': config['origin'],
    'ARGUS_OWNER_PASSWORD_HASH': generate_password_hash(config['password']),
    'ARGUS_ADMIN_TOKEN': config['admin'],
})
opener = build_opener(ProxyHandler({}), NoRedirect())

@app.after_request
def cors(response):
    if request.headers.get('Origin') == config['origin']:
        response.headers['Access-Control-Allow-Origin'] = config['origin']
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,X-ARGUS-OWNER-SESSION,X-ARGUS-OWNER-NONCE,X-ARGUS-ADMIN-TOKEN'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
        response.headers['Access-Control-Expose-Headers'] = 'X-ARGUS-OWNER-NONCE,Retry-After'
        response.headers.add('Vary', 'Origin')
    return response

@app.route('/<path:route>', methods=['GET', 'POST', 'OPTIONS'])
def forward(route):
    if request.method == 'OPTIONS':
        return Response(status=204)
    if not (route.startswith('api/argus/') or route in ('healthz', 'readyz')):
        return Response(status=404)
    # User input cannot select a host; redirects and environment proxies disabled.
    url = config['upstream'] + '/' + route
    if request.query_string:
        url += '?' + request.query_string.decode('ascii')
    headers = {'Content-Type': request.headers.get('Content-Type', 'application/json')}
    if request.headers.get('X-ARGUS-ADMIN-TOKEN'):
        headers['X-ARGUS-ADMIN-TOKEN'] = request.headers['X-ARGUS-ADMIN-TOKEN']
    req = Request(url, data=request.get_data() if request.method == 'POST' else None,
                  headers=headers, method=request.method)
    try:
        reply = opener.open(req, timeout=10)
    except HTTPError as error:
        reply = error
    with reply:
        body = reply.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            return Response(status=502)
        return Response(body, status=reply.status,
                        content_type=reply.headers.get('Content-Type', 'application/json'))

server = make_server('127.0.0.1', 4499, app, threaded=True,
                     ssl_context=(config['cert'], config['key']), request_handler=Quiet)
print('READY', flush=True)
server.serve_forever()
