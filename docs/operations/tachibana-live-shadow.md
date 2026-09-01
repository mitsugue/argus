# Tachibana live shadow production plane

## Isolation contract

Run Tachibana as a Render background worker named
`argus-tachibana-live-shadow`, in the existing Singapore Production
environment, on exactly one `0.5c-512mb` instance. A background worker has no
public or private inbound endpoint. It must not have a persistent disk, import
the scanner, receive Recovery environment variables, or access `/var/data`.

The worker start command is:

```text
python scripts/tachibana_live_sensor_service.py
```

The build command is:

```text
pip install -r requirements-tachibana.txt
```

This dedicated dependency file contains only Requests, Cryptography, and the
WebSocket client. It intentionally does not install the scanner, Moomoo,
Recovery, AI, Flask, or frontend dependency surfaces.

The service follows protected `main`. Previews are disabled. Only Tachibana
paths and its dedicated requirements file belong in its build filter.

## Required non-secret configuration

```text
ARGUS_TACHIBANA_ENABLED=true
ARGUS_TACHIBANA_SHADOW_ONLY=true
ARGUS_TACHIBANA_AUTHORITATIVE=false
ARGUS_TACHIBANA_WEBSOCKET_ENABLED=true
ARGUS_TACHIBANA_MAX_SYMBOLS=3
ARGUS_TACHIBANA_SYMBOLS=8058,9984,5803
ARGUS_TACHIBANA_REQUESTS_PER_MINUTE=12
ARGUS_TACHIBANA_MAX_READ_ATTEMPTS=1
ARGUS_TACHIBANA_EVENT_RECONNECTS_PER_DAY=3
ARGUS_TACHIBANA_AUTH_ID_PATH=/etc/secrets/e_api_authid.txt
ARGUS_TACHIBANA_PRIVATE_KEY_PATH=/etc/secrets/e_api_private_key.pem
ARGUS_TACHIBANA_SINGLETON_PATH=/tmp/argus-tachibana-live-sensor.lock
```

The only secret files are `e_api_authid.txt` and `e_api_private_key.pem`.
Provision them through Render secret files from local paths. Never place their
contents in Git, environment variables, browser automation, command arguments,
build output, or logs.

## Runtime truth and acceptance

The host `flock` lease is held for the entire process lifetime. Render is also
fixed to one instance. EVENT reconnects are bounded to three per Tokyo day.
Authentication is attempted at most once per provider operating day; the worker
waits through the documented daily auth closure and starts the next daily
session at 05:35 JST. Non-daily auth faults and non-session EVENT faults leave
the worker alive and truthfully degraded so platform restart behavior cannot
become a retry storm.

The sensor emits only aggregate operational logs. It retains a bounded window
in memory and never persists raw frames or market values. Acceptance requires:

- a verified current JPX cash-session date and open phase;
- current PRICE/EVENT observations for all three symbols;
- advancing EVENT sequence and provider frame timestamp;
- an advancing trade source timestamp and a price/quote/volume change;
- independent current-source coverage for at least two of three symbols; and
- no unclassified cross-provider mismatch.

Cross-validation allows one yen or 10 bp for independently sampled current
price, exact-to-1-bp daily reference/OHLC values, and one board lot or 2% for
volume. A classified feed-delay difference is accepted only within 50 bp for
price/OHLC or 5% for volume. Missing reference fields reduce coverage; they are
never treated as a match.

Tachibana remains `SHADOW_NON_AUTHORITATIVE`. It has no public route, no order
surface, no scanner integration, and no path to SDA authority or Japanese
execution.
