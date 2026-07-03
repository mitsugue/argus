#!/usr/bin/env python3
"""ARGUS V11.5.4 — optional always-on Watchtower worker (Render background worker).

GitHub cron gives ~15-min granularity; this optional loop gives ~5-min. It only
POSTs the SAME admin endpoints the cron uses — no separate logic, no LLM here.

DISABLED BY DEFAULT. To enable on Render, add a Background Worker service with:
    Start command: python3 scripts/caos_watchtower_worker.py
    Env: CAOS_WATCHTOWER_WORKER_ENABLED=true
         CAOS_WATCHTOWER_INTERVAL_SEC=300          (min 120)
         ARGUS_ADMIN_TOKEN=<same token as the web service>
         ARGUS_BACKEND_URL=https://argus-backend-3j2m.onrender.com

Never logs the token. Never stores article bodies. Keeps going on any failure.
"""
import os
import sys
import time

import requests

ENABLED = os.environ.get("CAOS_WATCHTOWER_WORKER_ENABLED", "false").lower() in ("1", "true", "yes")
INTERVAL = max(120, int(os.environ.get("CAOS_WATCHTOWER_INTERVAL_SEC", "300")))
BASE = os.environ.get("ARGUS_BACKEND_URL", "https://argus-backend-3j2m.onrender.com").rstrip("/")
TOKEN = os.environ.get("ARGUS_ADMIN_TOKEN", "")


def _post(path, timeout=240):
    try:
        r = requests.post(BASE + path, headers={"X-ARGUS-ADMIN-TOKEN": TOKEN,
                                                "User-Agent": "argus-watchtower-worker"},
                          timeout=timeout)
        body = (r.text or "")[:200]
        print(f"[worker] POST {path} -> {r.status_code} {body}", flush=True)
    except Exception as e:
        print(f"[worker] POST {path} failed: {type(e).__name__}", flush=True)


def main():
    if not ENABLED:
        print("[worker] CAOS_WATCHTOWER_WORKER_ENABLED is not true — exiting (by design).")
        return 0
    if not TOKEN:
        print("[worker] ARGUS_ADMIN_TOKEN missing — exiting.")
        return 1
    print(f"[worker] patrol every {INTERVAL}s against {BASE} (near-real-time; "
          "not a terminal replacement)", flush=True)
    while True:
        _post("/api/argus/admin/caos-watchtower/refresh")
        _post("/api/argus/admin/news/translate-visible", timeout=120)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main() or 0)
