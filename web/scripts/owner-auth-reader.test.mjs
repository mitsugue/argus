import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createOwnerReader, withOwnerReader, OwnerReaderError } from './owner-auth-reader.mjs';
import { fetchBusinessSnapshotObservations } from './release-state-machine.mjs';
import fs from 'node:fs';
const baseUrl = 'https://backend.example';
const env = { ARGUS_ACCEPTANCE_OWNER_AUTH: '1', ARGUS_ACCEPTANCE_OWNER_ORIGIN: 'https://owner.example',
  ARGUS_ACCEPTANCE_OWNER_PASSWORD: 'synthetic-only-password' };
const token = 't'.repeat(43);
const prefix = '/api/argus/owner-auth/';
function fixture(override = () => undefined) {
  const calls = [];
  let time = 1000000;
  const fetchImpl = async (input, init = {}) => {
    const url = new URL(input), headers = new Headers(init.headers);
    const call = { url, init, headers }; calls.push(call);
    assert.equal(init.redirect, 'error'); assert.equal(init.cache, 'no-store');
    assert.ok(init.signal);
    const custom = await override(call, calls.length);
    if (custom) return custom;
    let value = {}, status = 200;
    const authenticated = headers.get('X-ARGUS-OWNER-SESSION') === token;
    if (url.pathname === prefix + 'password') {
      assert.equal(headers.get('Origin'), env.ARGUS_ACCEPTANCE_OWNER_ORIGIN);
      assert.equal(JSON.parse(init.body).password, env.ARGUS_ACCEPTANCE_OWNER_PASSWORD);
      value = { token, expiresAt: time + 1800000 };
    } else if (url.pathname === prefix + 'session') {
      status = authenticated ? 200 : 401;
      value = authenticated ? { authenticated: true } : { error: 'owner_auth_required' };
    } else if (url.pathname === prefix + 'logout') value = { loggedOut: true };
    else value = { preserved: 'saved-result' };
    return new Response(JSON.stringify(value), { status, headers: authenticated
      ? { 'X-ARGUS-OWNER-NONCE': headers.get('X-ARGUS-OWNER-NONCE') } : {} });
  };
  return { options: { baseUrl, env, fetchImpl, now: () => time }, calls, advance: (ms) => { time += ms; } };
}
test('off mode is byte-compatible transport, no login or secret use', async () => {
  const raw = () => {}; const reader = await createOwnerReader({ env: {}, fetchImpl: raw });
  assert.equal(reader.fetch, raw); await reader.close();
});
test('explicit mode and HTTPS origins/credentials fail before network', async () => {
  for (const change of [ { baseUrl: 'http://backend.example' }, { baseUrl: baseUrl + '/path' },
    { baseUrl: 'https://user:secret@backend.example' }, { baseUrl: baseUrl + '?secret=x' },
    { env: { ...env, ARGUS_ACCEPTANCE_OWNER_AUTH: 'auto' } },
    { env: { ...env, ARGUS_ACCEPTANCE_OWNER_ORIGIN: '' } },
    { env: { ...env, ARGUS_ACCEPTANCE_OWNER_PASSWORD: '' } } ]) {
    await assert.rejects(createOwnerReader({ baseUrl, env, fetchImpl: () => assert.fail('network'), ...change }), /configuration/);
  }
});
test('401 boundary, login, nonce proof, data, confirmed logout, then closed', async () => {
  const f = fixture(); const reader = await createOwnerReader(f.options);
  assert.deepEqual(await (await reader.fetch(baseUrl + '/api/argus/chart-intelligence')).json(), { preserved: 'saved-result' });
  await reader.close();
  assert.deepEqual(f.calls.map(c => c.url.pathname), [prefix+'session',prefix+'password',prefix+'session','/api/argus/chart-intelligence',prefix+'logout']);
  const nonces = f.calls.flatMap(c => c.headers.has('X-ARGUS-OWNER-NONCE') ? [c.headers.get('X-ARGUS-OWNER-NONCE')] : []);
  assert.equal(new Set(nonces).size, nonces.length);
  await assert.rejects(reader.fetch(baseUrl + '/api/argus/chart-intelligence'), /closed/);
});
for (const status of [200,403,429,500]) test(`unexpected unauthenticated boundary ${status} is fatal`, async () => {
  const f = fixture((call,n) => n===1 && new Response('{}', { status }));
  await assert.rejects(createOwnerReader(f.options), /boundary/); assert.equal(f.calls.length,1);
});
for (const status of [502,503,504]) test(`a deploy cutover (${status}) is waited out at most three times, never credentials`, async () => {
  const waits = [];
  const f = fixture((call) => call.url.pathname.endsWith('/session') && !call.headers.has('X-ARGUS-OWNER-SESSION')
    && new Response('{}', { status }));
  await assert.rejects(createOwnerReader({ ...f.options, sleep: async (ms) => { waits.push(ms); } }), /boundary/);
  assert.deepEqual(waits, [20000, 20000, 20000]); assert.equal(f.calls.length, 4);
  assert.ok(f.calls.every(c => !c.url.pathname.endsWith('/password')));
});
test('a cutover that ends proceeds to the exact boundary and login', async () => {
  let unauthenticatedCalls = 0;
  const f = fixture((call) => call.url.pathname.endsWith('/session') && !call.headers.has('X-ARGUS-OWNER-SESSION')
    && (++unauthenticatedCalls === 1 ? new Response('{}', { status: 503 }) : null));
  const reader = await createOwnerReader({ ...f.options, sleep: async () => {} });
  assert.equal(reader.enabled, true); await reader.close();
});
for (const status of [401,403,429,500]) test(`password status ${status} never retries or downgrades`, async () => {
  const f = fixture((call) => call.url.pathname.endsWith('/password') && new Response('{}', { status }));
  await assert.rejects(createOwnerReader(f.options), /login/); assert.equal(f.calls.length,2);
});
for (const field of ['token','expiresAt']) test(`malformed ${field} stops initialization`, async () => {
  const f = fixture((call) => call.url.pathname.endsWith('/password') && new Response(JSON.stringify({ token, expiresAt: 2000000, [field]: 'invalid' })));
  await assert.rejects(createOwnerReader(f.options), /session_shape/);
});
test('cross-origin, credentials, POST, auth endpoints and admin/authorization headers never transmit', async () => {
  const f = fixture(); const reader = await createOwnerReader(f.options); const before = f.calls.length;
  for (const [url, init] of [ ['https://elsewhere.example/api/argus/x',{}], [baseUrl+'/api/argus/x#s',{}],
    ['https://s@backend.example/api/argus/x',{}], [baseUrl+'/api/argus/x',{method:'POST'}],
    [baseUrl+prefix+'revoke-all',{}], [baseUrl+'/api/argus/x',{headers:{'X-ARGUS-ADMIN-TOKEN':'never'}}],
    [baseUrl+'/api/argus/x',{headers:{Authorization:'never'}}]]) await assert.rejects(reader.fetch(url,init), OwnerReaderError);
  assert.equal(f.calls.length,before); await reader.close();
});
for (const status of [301,302,307,308]) test(`redirect ${status} rejected`, async () => {
  const f = fixture(c => c.url.pathname==='/api/argus/x' && new Response('',{status,headers:{Location:'https://elsewhere.example'}}));
  await assert.rejects(withOwnerReader(f.options, r => r.fetch(baseUrl+'/api/argus/x')), /redirect/);
  assert.equal(f.calls.at(-1).url.pathname,prefix+'logout');
});
test('missing or replayed nonce is fatal and callback failures revoke', async () => {
  for (const value of ['', 'a'.repeat(36)]) {
    const f=fixture(c=>c.url.pathname==='/api/argus/x' && new Response('{}',{headers:{'X-ARGUS-OWNER-NONCE':value}}));
    await assert.rejects(withOwnerReader(f.options,r=>r.fetch(baseUrl+'/api/argus/x')), /unverified/);
    assert.equal(f.calls.at(-1).url.pathname,prefix+'logout');
  }
  const f=fixture(); await assert.rejects(withOwnerReader(f.options,()=>{throw new Error('callback-failed');}), /callback-failed/);
  assert.equal(f.calls.at(-1).url.pathname,prefix+'logout');
});
test('transport/body errors cannot expose password or token', async () => {
  for (const phase of ['transport','body']) {
    const f=fixture(c=>{if(c.url.pathname.endsWith('/password')) {
      const error=new Error(env.ARGUS_ACCEPTANCE_OWNER_PASSWORD+' '+token);
      if(phase==='transport') throw error;
      return {status:200,headers:new Headers(),json:async()=>{throw error;}};
    }});
    await assert.rejects(createOwnerReader(f.options), e=>e.message===`owner_reader:${phase}` && !e.cause);
  }
});
test('failed logout cannot produce success', async () => {
  const f=fixture(c=>c.url.pathname.endsWith('/logout') && new Response('{}',{status:503}));
  await assert.rejects(withOwnerReader(f.options,async()=> 'pass'), /owner_reader:logout/);
});
test('proactive renewal revokes previous session, no retry after rejected read', async () => {
  const f=fixture(); const reader=await createOwnerReader(f.options); f.advance(1780000);
  await reader.fetch(baseUrl+'/api/argus/x'); await reader.close();
  assert.equal(f.calls.filter(c=>c.url.pathname.endsWith('/password')).length,2);
  assert.equal(f.calls.filter(c=>c.url.pathname.endsWith('/logout')).length,2);
  const bad=fixture(c=>c.url.pathname==='/api/argus/x' && new Response('{}',{status:401}));
  await assert.rejects(withOwnerReader(bad.options,r=>r.fetch(baseUrl+'/api/argus/x')), /rejected/);
  assert.equal(bad.calls.filter(c=>c.url.pathname.endsWith('/password')).length,1);
});
test('business authentication failures stop at the first row without data retries', async () => {
  const contract=JSON.parse(fs.readFileSync(new URL('../../release/v13-snapshot-readiness-contract.json',import.meta.url)));
  let calls=0;
  await assert.rejects(fetchBusinessSnapshotObservations({baseUrl,contract,fetchImpl:async()=>{calls++;throw new OwnerReaderError('rejected');}}),/rejected/);
  assert.equal(calls,1);
});
