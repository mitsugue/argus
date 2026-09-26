import assert from 'node:assert/strict';
import {
  readAcrossNavigation,
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

const navigationError = new Error(
  'page.evaluate: Execution context was destroyed, most likely because of a navigation');
let reads = 0;
const waits = [];
const wrongIdentity = { productVersion: 'wrong', frontendSha: 'wrong' };
const identity = await readAcrossNavigation({
  read: async () => {
    reads += 1;
    if (reads === 1) throw navigationError;
    return wrongIdentity;
  },
  waitForDocument: async (attempt) => { waits.push(attempt); },
});
assert.equal(identity, wrongIdentity, 'wrong identities must reach exact checks unchanged');
assert.equal(reads, 2);
assert.deepEqual(waits, [1]);
reads = 0;
await assert.rejects(readAcrossNavigation({
  read: async () => { reads += 1; throw navigationError; },
  waitForDocument: async () => {},
}), (error) => error === navigationError);
assert.equal(reads, 3, 'navigation failure must remain bounded and fail closed');
const otherError = new Error('Target page, context or browser has been closed');
await assert.rejects(readAcrossNavigation({
  read: async () => { throw otherError; },
  waitForDocument: async () => { assert.fail('unrelated errors must not retry'); },
}), (error) => error === otherError);
const documentTimeout = new Error('document load timed out');
await assert.rejects(readAcrossNavigation({
  read: async () => { throw navigationError; },
  waitForDocument: async () => { throw documentTimeout; },
}), (error) => error === documentTimeout);
console.log('warm-profile-runtime.test: ok (bounded runtime and navigation reads)');
