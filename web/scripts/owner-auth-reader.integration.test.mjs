import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { test } from 'node:test';
import { withOwnerReader } from './owner-auth-reader.mjs';
import { fetchBusinessSnapshots, triggerBusinessSnapshots, evaluateBusinessSnapshotSet,
  loadSnapshotContract } from './release-state-machine.mjs';

const contract = loadSnapshotContract(new URL('../../release/v13-snapshot-readiness-contract.json', import.meta.url));
const baseUrl = 'https://backend.example';
const env = { ARGUS_ACCEPTANCE_OWNER_AUTH: '1', ARGUS_ACCEPTANCE_OWNER_ORIGIN: 'https://owner.example',
  ARGUS_ACCEPTANCE_OWNER_PASSWORD: 'synthetic-only-password' };

test('actual Flask boundary → Node reader → exact 12 acceptance and admin trigger isolation → logout', async () => {
  const bridge = spawn(process.env.ARGUS_TEST_PYTHON || 'python3',
    [new URL('./owner-auth-reader-fixture.py', import.meta.url).pathname], { stdio: ['pipe','pipe','pipe'] });
  const lines = createInterface({input:bridge.stdout}); const queue=[]; let errors='';
  bridge.stderr.on('data',data=>{errors+=data;});
  lines.on('line',line=>queue.shift()?.resolve(JSON.parse(line)));
  bridge.on('exit',code=>{for(const q of queue.splice(0)) q.reject(new Error(`fixture_exit:${code}`));});
  const request=(message)=>new Promise((resolve,reject)=>{
    queue.push({resolve,reject}); bridge.stdin.write(JSON.stringify(message)+'\n');
  });
  const seen=[];
  const fetchImpl=async(url, init={})=>{
    const headers=Object.fromEntries(new Headers(init.headers));
    seen.push({path:new URL(url).pathname,headers});
    const reply=await request({url,method:init.method||'GET',headers,body:init.body});
    return new Response(reply.body,{status:reply.status,headers:reply.headers});
  };
  try {
    const options={baseUrl,env,fetchImpl};
    const before=await fetchImpl(baseUrl+'/api/argus/chart-intelligence?symbol=1321&horizon=5D');
    assert.equal(before.status,401);
    const observed=await withOwnerReader(options,r=>fetchBusinessSnapshots({baseUrl,contract,fetchImpl:r.fetch}));
    const result=evaluateBusinessSnapshotSet({contract,observed,expectedBuildSha:'a'.repeat(40),producerTriggerId:'synthetic-reader-trigger'});
    assert.equal(result.pass,true,result.reason); assert.equal(observed.length,12);
    assert.equal((await request({inspect:true})).sessions,0);
    assert.equal(evaluateBusinessSnapshotSet({contract,observed,expectedBuildSha:'b'.repeat(40),producerTriggerId:'synthetic-reader-trigger'}).pass,false);
    assert.equal(evaluateBusinessSnapshotSet({contract,observed,expectedBuildSha:'a'.repeat(40),producerTriggerId:'wrong'}).pass,false);
    const triggered=await withOwnerReader(options,r=>triggerBusinessSnapshots({baseUrl,contract,
      expectedBuildSha:'a'.repeat(40),producerTriggerId:'synthetic-reader-trigger',adminToken:'synthetic-admin-only',
      fetchImpl,readbackFetchImpl:r.fetch}));
    assert.equal(triggered.status,'completed');
    const inspector=await request({inspect:true});
    assert.equal(inspector.sessions,0); assert.equal(inspector.calls.filter(x=>x==='chart').length,24);
    assert.equal(inspector.calls.filter(x=>x==='tick').length,1);
    assert.ok(seen.filter(c=>c.path.includes('chart-intelligence')).slice(1).every(c=>
      !c.headers['x-argus-admin-token'] && c.headers['x-argus-owner-session'] && c.headers['x-argus-owner-nonce']));
    const tick=seen.find(c=>c.path.endsWith('/tick'));
    assert.equal(tick.headers['x-argus-admin-token'],'synthetic-admin-only');
    assert.equal(tick.headers['x-argus-owner-session'],undefined);
    await assert.rejects(withOwnerReader(options,async()=>{throw new Error('synthetic-data-failure');}),/synthetic-data-failure/);
    assert.equal((await request({inspect:true})).sessions,0);
    assert.equal(errors,'');
  } finally { bridge.stdin.end(); lines.close(); bridge.kill(); }
});
