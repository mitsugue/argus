# Owner authentication: complete Today acceptance

This local acceptance unit depends on the owner server boundary, owner readers,
browser continuity, and the WebAuthn CI dependency candidate. It is not a release
or permission to publish those candidates.

## Behavior and integration

The fixed application shell previously covered the sibling owner account bar.
Account controls now live in a compact `本人設定` disclosure in the actual header.
The disclosure provides passkey registration, lost-device recovery and logout.
The locked screen and all existing authentication checks remain in force.

Canonical snapshot acceptance reloads the page as its causal trigger. Owner-mode
callers explicitly log out before that reload and use the normal password UI
afterwards. The same request/response observers, three-attempt 429 handling,
90-second boundary, content-addressed snapshot equality, and state machine remain.
No token is injected into a page and no administrator token is used for a browser.
Failed cleanup remains failure, while its fixed diagnostic no longer replaces the
original acceptance error.

The shared pre-mutation build receives `owner-auth` from the same repository
variable used by production readers. Only `0` or `1` is accepted; default remains
`0`. This does not change the server setting, install a password, enable production
authentication, or demonstrate an old iPhone's update/registration/recovery.

## Dedicated synthetic HTTPS environment

From `web/`, with Node 24 supporting `--use-env-proxy`, Python with the repository
requirements, OpenSSL and the existing Playwright Chromium available:

```
ARGUS_TEST_PYTHON=/path/to/python3 node scripts/owner-today-https.mjs 1 /absolute/new-evidence-directory
ARGUS_TEST_PYTHON=/path/to/python3 node scripts/owner-today-https.mjs 0 /absolute/another-new-evidence-directory
```

The runner builds the actual React product for the selected mode, starts the
existing twelve-snapshot release fixture, and places the real Flask owner boundary
in front of it. Credentials, database and certificate are generated per execution.
A loopback CONNECT proxy accepts only `argus-fixture.test:443` and maps it to the
fixture HTTPS listener. Other authorities are rejected. Node trusts the generated
certificate; Chromium pins its generated public key. Global TLS verification is
not disabled. The test-only preload is not used by production acceptance.

The original mobile Today engine runs all M01–M15, the twelve research combinations,
seven viewport geometries, the 225 ms loader boundary, response failure/304/429,
and offline continuity. In owner mode, offline means locked, stored contents
unchanged, then fresh online authentication and the same snapshot ID. Results are
synthetic local evidence, not production acceptance, an iPhone test, a resource
qualification or a formal 72-hour run.

Ports 4373, 4399, 4473, 4480 and 4499 must be free. No privileged port, production
endpoint, existing browser profile, original research input, external data source,
paid API or order endpoint is needed. The runner closes its own services and removes
only its generated temporary directory. Supply a new evidence directory each time
so previous failures remain available.

## Rollout and preservation

Keep all authentication candidates local until their exact admission and public
submission permissions are resolved. Recompute the final candidate's exact scope,
then run its release gate and both applicable detached proofs. The older candidate's
manifest/proof is not evidence for this unit. Production activation still requires
coherent server/build/reader settings, protected acceptance-artifact destinations,
old PWA data-preserving updates and actual owner device registration/recovery.
Do not discard stored results or relax acceptance to complete the migration.
