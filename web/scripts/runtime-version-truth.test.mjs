import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'src/domain/runtimeVersionTruth.ts'), 'utf8');
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  fileName: 'runtimeVersionTruth.ts',
}).outputText;
const truth = await import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);

const manifest = {
  schema: 'argus-production-release-manifest-v1',
  service: 'argus-backend',
  environment: 'production',
  verifiedHealth: true,
  verifiedReady: true,
  version: '13.4.5',
  buildSha: '183b940c08505f1373a3b34b0c7fc2bc37bbae90',
  deploymentId: 'dep-d9rrkmgae00c73a9acl0',
  deployedAt: '2026-08-08T23:52:52Z',
};
const identity = truth.parseProductionBackendIdentity(manifest);
assert.deepEqual(identity, {
  backendVersion: '13.4.5',
  backendSha: '183b940c08505f1373a3b34b0c7fc2bc37bbae90',
  deploymentId: 'dep-d9rrkmgae00c73a9acl0',
  deployedAt: '2026-08-08T23:52:52Z',
});
assert.equal(truth.runtimeVersionLabel('13.3.6', identity), 'UI v13.3.6 · API v13.4.5');

for (const malformed of [
  null,
  {},
  { ...manifest, schema: 'wrong' },
  { ...manifest, version: '13.4' },
  { ...manifest, buildSha: 'short' },
  { ...manifest, deploymentId: 'github-main-123' },
  { ...manifest, deployedAt: 'yesterday' },
  { ...manifest, verifiedReady: false },
]) {
  assert.equal(truth.parseProductionBackendIdentity(malformed), null);
}
assert.equal(truth.runtimeVersionLabel('13.3.6', null), 'UI v13.3.6 · API UNKNOWN');
assert.equal(truth.runtimeVersionLabel('malformed', identity), 'UI UNKNOWN · API v13.4.5');

console.log('runtime version truth tests passed');
