import test from 'node:test';
import assert from 'node:assert/strict';
import { assertModes, htmlOwnerMode, verifyOwnerModes } from './owner-mode-consistency.mjs';
import { createBrowserOwner } from './owner-browser-acceptance.mjs';
const sha = 'a'.repeat(40);
const html = mode => `globalThis.__ARGUS_OWNER_AUTH_MODE__="${mode}";globalThis.__ARGUS_BUILD_SHA__="${sha}";`;
const args = { publicUrl: 'https://ui.example/argus/', baseUrl: 'https://api.example', expectedSha: sha, mode: '1' };
for (const frontend of ['0','1']) for (const reader of ['0','1']) for (const server of ['0','1']) {
  test(`configuration matrix ${frontend}/${reader}/${server}`, async () => {
    const match = frontend === reader && reader === server;
    let reads = 0;
    const fetchImpl = async (url, init) => {
      assert.equal(init.redirect, 'error'); assert.equal(init.cache, 'no-store');
      assert.equal(init.headers, undefined); assert.equal(init.body, undefined);
      assert.ok(new URL(url).searchParams.get('owner-mode-probe'));
      reads++;
      return reads === 1 ? new Response(html(frontend)) : new Response(JSON.stringify({ error: server === '1' ? 'owner_auth_required' : 'owner_auth_disabled' }), { status: server === '1' ? 401 : 503 });
    };
    const result = verifyOwnerModes({ ...args, mode: reader, fetchImpl });
    if (match) assert.deepEqual(await result, { status: 'PASS', mode: reader });
    else await assert.rejects(result, /owner_mode:mismatch/);
    assert.equal(reads, frontend === reader ? 2 : 1);
  });
}
for (const [label, value, expectedSha] of [
  ['missing', '', sha], ['duplicate', html('1')+html('1'), sha],
  ['invalid', html('true'), sha], ['different SHA', html('1'), 'b'.repeat(40)],
]) test('reject frontend '+label, () => assert.throws(() => htmlOwnerMode(value, expectedSha), /owner_mode:/));
for (const [label, response, error] of [
  ['anonymous 200', () => new Response('{}'), 'server_boundary'],
  ['DB failure', () => new Response('{"error":"owner_auth_unavailable"}', { status: 503 }), 'server_boundary'],
  ['wrong body', () => new Response('{"error":"wrong"}', { status: 401 }), 'server_boundary'],
  ['invalid JSON', () => new Response('secret-invalid-json', { status: 401 }), 'server_body'],
  ['redirect', () => new Response(null, { status: 302 }), 'redirect'],
]) test('reject '+label+' without response contents', async () => {
  let calls = 0;
  await assert.rejects(verifyOwnerModes({ ...args, fetchImpl: async () => ++calls === 1 ? new Response(html('1')) : response() }), e => e.message === 'owner_mode:'+error);
});
test('transport failure never discloses error text', async () => {
  await assert.rejects(verifyOwnerModes({ ...args, fetchImpl: async () => { throw new Error('secret transport text'); } }), e => e.message === 'owner_mode:transport');
});
test('invalid reader/origin stops before network', async () => {
  for (const override of [{ mode: 'true' }, { baseUrl: 'http://api.example' }, { publicUrl: 'https://name:secret@ui.example/' }]) {
    await assert.rejects(verifyOwnerModes({ ...args, ...override, fetchImpl: () => { throw new Error('must not fetch'); } }), /owner_mode:configuration/);
  }
  assert.throws(() => assertModes({ frontend: null, reader: '0', server: '0' }), /configuration/);
});
test('OFF reader refuses an executing ON bundle', async () => {
  const reader = createBrowserOwner({ baseUrl: '', publicUrl: '', env: {} });
  await assert.rejects(reader.login({ waitForFunction: async () => {}, evaluate: async () => '1' }), /owner_browser:mode_mismatch/);
});
test('missing executing marker is rejected', async () => {
  const reader = createBrowserOwner({ baseUrl: '', publicUrl: '', env: {} });
  await assert.rejects(reader.login({ waitForFunction: async () => { throw new Error('secret diagnostic'); } }), e => e.message === 'owner_browser:mode_unavailable');
});
