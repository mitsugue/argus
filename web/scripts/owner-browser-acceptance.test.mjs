import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { assertNoSecrets, createBrowserOwner, isOwnerCeremony } from './owner-browser-acceptance.mjs';
const backend = 'https://api.example', publicUrl = 'https://owner.example/argus/';
const env = { ARGUS_ACCEPTANCE_OWNER_AUTH: '1', ARGUS_ACCEPTANCE_OWNER_ORIGIN: 'https://owner.example', ARGUS_ACCEPTANCE_OWNER_PASSWORD: 'fixture-"pass\\word' };
test('disabled mode verifies the executing UI without credentials', async () => {
  const owner = createBrowserOwner({ baseUrl: '', publicUrl: '', env: {} });
  const page = { waitForFunction: async () => {}, evaluate: async () => '0' };
  await owner.login(page); await owner.logout(page); await owner.locked(page); await owner.scan('/does-not-exist');
  assert.equal(owner.enabled, false);
});
for (const [label, url, overrides] of [
  ['other origin', 'https://another.example/', {}],
  ['URL credentials', 'https://name:pass@owner.example/', {}],
  ['HTTP origin', 'http://owner.example/', {}],
  ['missing secret', publicUrl, { ARGUS_ACCEPTANCE_OWNER_PASSWORD: '' }],
  ['invalid mode', publicUrl, { ARGUS_ACCEPTANCE_OWNER_AUTH: 'yes' }],
]) test('reject '+label+' before any login', () => {
  assert.throws(() => createBrowserOwner({ baseUrl: backend, publicUrl: url, env: { ...env, ...overrides } }), /configuration/);
});
test('redirected page is rejected before credentials are typed', async () => {
  const owner = createBrowserOwner({ baseUrl: backend, publicUrl, env });
  await assert.rejects(owner.login({ url: () => 'https://elsewhere.example/', getByRole: () => { throw new Error('secret access'); } }), /lock_required/);
});
test('diagnostic redaction and precise ceremony boundary', () => {
  const owner = createBrowserOwner({ baseUrl: backend, publicUrl, env });
  assert.equal(owner.redact('before '+env.ARGUS_ACCEPTANCE_OWNER_PASSWORD+' after'), 'before [redacted] after');
  for (const route of ['password','logout','session']) assert.ok(isOwnerCeremony(backend+'/api/argus/owner-auth/'+route, backend, route==='session'?'GET':'POST'));
  assert.equal(isOwnerCeremony(backend+'/api/argus/owner-auth/session', backend, 'POST'), false);
  for (const url of [backend+'/api/argus/mission',backend+'/api/argus/owner-auth/register-verify',backend+'/api/argus/owner-auth/password/extra','https://evil.example/api/argus/owner-auth/password']) assert.equal(isOwnerCeremony(url, backend, 'POST'),false);
});
for (const encoding of ['utf8','utf16le','encoded','json']) test('artifact secret scan '+encoding, async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(),'argus-secret-scan-'));
  try {
    const secret = env.ARGUS_ACCEPTANCE_OWNER_PASSWORD;
    const content = encoding==='encoded' ? encodeURIComponent(secret) : encoding==='json' ? JSON.stringify(secret).slice(1,-1) : secret;
    await fs.writeFile(path.join(dir,'data'), Buffer.concat([Buffer.alloc(65532),Buffer.from(content,encoding==='utf16le'?'utf16le':'utf8')]));
    await assert.rejects(assertNoSecrets(dir,new Set([secret])), error => error.message==='owner_browser:artifact_secret' && !error.message.includes(secret));
    await fs.writeFile(path.join(dir,'data'),'safe'); await assertNoSecrets(dir,new Set([secret]));
  } finally { await fs.rm(dir,{recursive:true,force:true}); }
});
test('missing artifact and link cannot silently pass', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(),'argus-secret-scan-'));
  try {
    await assert.rejects(assertNoSecrets(path.join(dir,'missing'),new Set(['secret'])),/artifact_read/);
    await fs.symlink('/does-not-exist',path.join(dir,'link'));
    await assert.rejects(assertNoSecrets(dir,new Set(['secret'])),/artifact_link/);
  } finally { await fs.rm(dir,{recursive:true,force:true}); }
});
