import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { fetchBusinessSnapshotObservations, evaluateBusinessSnapshotObservations,
  loadSnapshotContract, validateSnapshotContract } from './release-state-machine.mjs';
import { OwnerReaderError } from './owner-auth-reader.mjs';

const root = fileURLToPath(new URL('../..', import.meta.url));
const contractPath = path.join(root, 'release/v13-snapshot-readiness-contract.json');
const contract = validateSnapshotContract(loadSnapshotContract(contractPath));
const secret = 'synthetic-private-body-never-publish';
for (const [name, value, expected] of [
  ['abort', Object.assign(new Error(secret), { name: 'AbortError' }), 'readback_body_aborted'],
  ['json', new SyntaxError(secret), 'readback_json_invalid'],
  ['body', new Error(secret), 'readback_body_failed'],
  ['null', null, 'readback_json_empty'],
]) {
  test(`HTTP 200 ${name} retains status, fails and omits body text`, async () => {
    let requests = 0, cleared = 0;
    const observations = await fetchBusinessSnapshotObservations({ baseUrl: 'https://fixture.test', contract,
      fetchImpl: async () => { requests++; return { status: 200, json: async () => {
        if (value instanceof Error) throw value; return value;
      } }; },
      setTimeoutImpl: (_callback, timeout) => { assert.equal(timeout, 30_000); return requests; },
      clearTimeoutImpl: () => { cleared++; },
    });
    assert.equal(requests, 12); assert.equal(cleared, 12);
    assert.ok(observations.every(row => row.status === 200 && row.snapshot === null
      && row.error.code === expected));
    assert.equal(evaluateBusinessSnapshotObservations({ contract, observations }).outcome, 'INCOMPLETE');
    assert.ok(!JSON.stringify(observations).includes(secret));
  });
}
test('owner rejection escapes the data retry path immediately', async () => {
  let requests = 0;
  await assert.rejects(fetchBusinessSnapshotObservations({ baseUrl: 'https://fixture.test', contract,
    fetchImpl: async () => { requests++; throw new OwnerReaderError('rejected'); },
  }), OwnerReaderError);
  assert.equal(requests, 1);
});
test('unknown transport error fields are replaced by fixed diagnostics', async () => {
  const observations = await fetchBusinessSnapshotObservations({ baseUrl: 'https://fixture.test', contract,
    fetchImpl: async () => { throw Object.assign(new Error(secret), { name: secret, code: secret }); },
  });
  assert.ok(observations.every(row => row.status === null && row.error.code === 'readback_request_failed'));
  assert.ok(!JSON.stringify(observations).includes(secret));
});

// The child runs the actual CLI and owner reader. Its only fetch implementation
// accepts one synthetic origin and never calls the network or a production API.
const preload = `
import fs from 'node:fs';
const mode = process.env.FIXTURE_CASE, secret = ${JSON.stringify(secret)};
const sha = 'a'.repeat(40), token = 'P'.repeat(48);
const contract = JSON.parse(fs.readFileSync(process.env.FIXTURE_CONTRACT, 'utf8'));
const stats = {reads: 0, logouts: 0, logins: 0};
process.on('exit', () => fs.writeFileSync(process.env.FIXTURE_STATS, JSON.stringify(stats)));
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(input); if (url.origin !== 'https://fixture.test') throw new Error('unexpected fixture target');
  const headers = new Headers(init.headers), nonce = headers.get('X-ARGUS-OWNER-NONCE');
  const reply = (status, body) => ({status, url: url.href, headers: new Headers(nonce ? {'X-ARGUS-OWNER-NONCE': nonce} : {}), json: async () => body});
  if (url.pathname.endsWith('/password')) { stats.logins++; return reply(200, {token, expiresAt: Date.now() + 600_000}); }
  if (url.pathname.endsWith('/session')) return headers.has('X-ARGUS-OWNER-SESSION') ? reply(200, {authenticated:true}) : reply(401, {error:'owner_auth_required'});
  if (url.pathname.endsWith('/logout')) { stats.logouts++; return reply(mode.endsWith('logout') ? 500 : 200, {loggedOut: !mode.endsWith('logout')}); }
  if (url.pathname !== '/api/argus/chart-intelligence') throw new Error('unexpected fixture path');
  stats.reads++;
  if (mode === 'request') throw Object.assign(new Error(secret), {name:secret, code:secret});
  if (mode === 'auth') return reply(401, {error:secret});
  if (mode === 'http') return reply(500, {private:secret});
  if (mode.startsWith('abort')) return {...reply(200,null),json:async()=>{throw Object.assign(new Error(secret),{name:'AbortError'});}};
  if (mode === 'json') return {...reply(200,null),json:async()=>{throw new SyntaxError(secret);}};
  if (mode === 'null') return reply(200, null);
  const row = contract.snapshots.find(r => r.instrument === url.searchParams.get('symbol') && r.horizon === url.searchParams.get('horizon'));
  const at = new Date(Date.now() - 1_000).toISOString();
  const snapshot = {schemaVersion:'argus-verified-view-snapshot-v1',snapshotId:'vs-'+'1'.repeat(32),kind:row.kind,market:row.market,instrument:row.instrument,horizon:row.horizon,datasetHash:'d',payloadHash:'p',methodVersion:'fixture-v1',quality:'live',verificationStatus:'verified',payload:{private:secret},generatedAt:at,releaseBinding:{expectedBuildSha:sha,producerTriggerId:'synthetic-trigger',triggeredAt:at}};
  if (mode === 'build') snapshot.releaseBinding.expectedBuildSha = 'b'.repeat(40);
  if (mode === 'trigger') snapshot.releaseBinding.producerTriggerId = secret;
  if (mode === 'stale') snapshot.generatedAt = '2000-01-01T00:00:00Z';
  if (mode === 'identity') snapshot.instrument = secret + row.instrument;
  if (mode === 'duplicate') snapshot.instrument = secret;
  if (mode === 'malformed') snapshot.snapshotId = secret;
  return reply(200, snapshot);
};
`;
for (const [mode, auth, expected, code] of [
  ['good', '0', 0], ['good', '1', 0],
  ['abort', '0', 1, 'readback_body_aborted'], ['abort', '1', 1, 'readback_body_aborted'],
  ['json', '0', 1, 'readback_json_invalid'], ['null', '0', 1, 'readback_json_empty'],
  ['request', '0', 1, 'readback_request_failed'], ['http', '0', 1, 'readback_http_failed'],
  ['build', '0', 1, 'wrong_build'], ['trigger', '0', 1, 'wrong_trigger'],
  ['stale', '0', 1, 'stale_snapshot'], ['identity', '0', 1, 'snapshot_set_mismatch'],
  ['duplicate', '0', 1, 'duplicate_snapshot'], ['malformed', '0', 1, 'malformed_snapshot'], ['auth', '1', 1, 'owner_reader:rejected'],
  ['abort-logout', '1', 1, 'owner_reader:operation_and_logout'],
]) {
  test(`real CLI ${mode} owner=${auth} writes exact outcome with safe evidence`, () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'argus-failure-evidence-'));
    try {
      const pre = path.join(dir, 'preload.mjs'), trigger = path.join(dir, 'trigger.json');
      const artifact = path.join(dir, 'gate.json'), statsPath = path.join(dir, 'stats.json');
      fs.writeFileSync(pre, preload); fs.writeFileSync(trigger, JSON.stringify({producerTriggerId:'synthetic-trigger'}));
      const result = spawnSync(process.execPath, ['--import', pre, path.join(root, 'web/scripts/release-state-machine.mjs'), 'verify-business', '--contract', contractPath,
        '--base-url', 'https://fixture.test', '--expected-sha', 'a'.repeat(40), '--trigger-artifact', trigger, '--out', artifact], {
        encoding: 'utf8', timeout: 20_000, env: {...process.env, ARGUS_ACCEPTANCE_OWNER_AUTH:auth,
          ARGUS_ACCEPTANCE_OWNER_ORIGIN:'https://fixture.test', ARGUS_ACCEPTANCE_OWNER_PASSWORD:'fixture-password',
          FIXTURE_CASE:mode,FIXTURE_CONTRACT:contractPath,FIXTURE_STATS:statsPath},
      });
      assert.equal(result.status, expected, result.stderr);
      const raw = fs.readFileSync(artifact, 'utf8'), evidence = JSON.parse(raw), stats = JSON.parse(fs.readFileSync(statsPath));
      assert.equal(evidence.status, expected === 0 ? 'pass' : 'failed');
      for (const text of [secret,'fixture-password','P'.repeat(48)]) assert.ok(!(raw+result.stdout+result.stderr).includes(text));
      assert.equal(stats.reads, mode === 'auth' ? 1 : 12);
      assert.equal(stats.logouts, auth === '1' ? 1 : 0);
      if (code) assert.ok(raw.includes(code), raw);
      if (mode === 'abort-logout') assert.ok(raw.includes('readback_body_aborted'));
      if (expected === 0) { assert.equal(evidence.expectedSet.length,12); assert.deepEqual(evidence.expectedSet,evidence.observedSet); }
    } finally { fs.rmSync(dir, {recursive:true,force:true}); }
  });
}
