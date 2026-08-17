import assert from 'node:assert/strict';
import {
  runtimeProofReady,
  stabilizeWarmProfileRuntime,
} from './warm-profile-runtime.mjs';

const ready = {
  databaseNames: ['argus-verified-snapshots', 'workbox-expiration'],
  serviceWorkerReady: true,
  verifiedSnapshotRecordCount: 4,
};

assert.equal(runtimeProofReady(ready), true);
assert.equal(runtimeProofReady({ ...ready, serviceWorkerReady: false }), false);
assert.equal(runtimeProofReady({ ...ready, verifiedSnapshotRecordCount: 0 }), false);

let probes = 0;
let reloads = 0;
const recovered = await stabilizeWarmProfileRuntime({
  probe: async () => {
    probes += 1;
    if (probes === 1) throw new Error('service_worker_ready_timeout');
    return ready;
  },
  reload: async () => { reloads += 1; },
});
assert.equal(probes, 2);
assert.equal(reloads, 1);
assert.deepEqual(recovered.runtimeProof, ready);
assert.deepEqual(recovered.diagnostics.map((row) => row.status), ['ERROR', 'READY']);

await assert.rejects(
  stabilizeWarmProfileRuntime({
    probe: async () => ({
      databaseNames: [], serviceWorkerReady: false,
      verifiedSnapshotRecordCount: 0,
    }),
    reload: async () => {},
    attempts: 3,
  }),
  /warm_profile_runtime_unready/,
);

console.log('warm-profile-runtime.test: ok (bounded real-runtime stabilization)');
