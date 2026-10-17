// Test-only trust of a freshly generated loopback fixture key, not global TLS
// disabling. Production acceptance never loads this module.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
for (const key of ['ARGUS_PUBLIC_URL', 'ARGUS_BACKEND_URL']) {
  const url = new URL(process.env[key]);
  assert.equal(url.hostname, 'argus-fixture.test'); assert.equal(url.protocol, 'https:');
  assert.equal(url.port, '');
}
assert.equal(process.env.ARGUS_SYNTHETIC_OWNER_TODAY, '1');
const spki = process.env.ARGUS_FIXTURE_SPKI;
assert.match(spki, /^[A-Za-z0-9+/]{43}=$/);
const options = value => ({ ...value, proxy: { server: 'http://127.0.0.1:4480' },
  args: [...(value?.args ?? []), `--ignore-certificate-errors-spki-list=${spki}`] });
const launch = chromium.launch.bind(chromium);
const persistent = chromium.launchPersistentContext.bind(chromium);
chromium.launch = value => launch(options(value));
chromium.launchPersistentContext = (directory, value) => persistent(directory, options(value));
