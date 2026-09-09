#!/usr/bin/env python3
"""Follow one admin collection through cold-start warming; never retry its work."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from urllib.error import URLError

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.workflow_http import request_json


def run(*, base: str, token: str, timeout: float = 900, request=request_json,
        clock=time.monotonic, sleep=time.sleep, request_id: str | None = None) -> dict:
    if not token:
        return {"status": "failed", "errorClass": "admin_token_missing"}
    run_id = request_id or uuid.uuid4().hex
    url = base.rstrip("/") + "/api/argus/institutional-intelligence/collect"
    headers = {"X-ARGUS-ADMIN-TOKEN": token, "Content-Type": "application/json"}
    deadline = clock() + timeout
    started = False
    last_error = None
    while clock() < deadline:
        payload = {"requestId": run_id, "statusOnly" if started else "async": True}
        # If the initial connection is lost, submit the SAME identity again.
        # The server either starts it once or returns its existing record.
        try:
            code, raw = request(url=url, method="POST", headers=headers,
                                data=json.dumps(payload), timeout=max(1, min(30, int(deadline - clock()))))
            body = json.loads(raw)
        except (OSError, URLError, TimeoutError, ValueError):
            last_error = "collect_transport_or_json_error"
        else:
            if code in (401, 403, 404) or (400 <= code < 500 and code != 429):
                return {"status": "failed", "runId": run_id, "httpStatus": code,
                        "errorClass": "collect_run_missing_or_rejected"}
            if 200 <= code < 300:
                if not isinstance(body, dict) or body.get("status") not in ("running", "done", "failed"):
                    return {"status": "failed", "errorClass": "collect_tracking_protocol_missing"}
                received_id = body.get("runId")
                if not isinstance(received_id, str) or not received_id or (started and received_id != run_id):
                    return {"status": "failed", "errorClass": "collect_run_identity_mismatch"}
                run_id, started = received_id, True
                if body["status"] in ("done", "failed"):
                    # Persist only bounded status/counts, no provider payloads.
                    result = body.get("result") or {}
                    failed_feeds = result.get("failedFeeds") or []
                    all_feeds_failed = bool(result.get("feeds")) and len(failed_feeds) >= result["feeds"]
                    return {"status": "failed" if all_feeds_failed else body["status"], "runId": run_id,
                            "startedAt": body.get("startedAt"), "finishedAt": body.get("finishedAt"),
                            "errorClass": "all_intel_feeds_unavailable" if all_feeds_failed else body.get("errorClass"),
                            "collected": result.get("collected"), "stored": result.get("stored"),
                            "failedFeedCount": len(failed_feeds), "feedCount": result.get("feeds"),
                            "supplyDemandWarm": result.get("supplyDemandWarm"),
                            "jpMarketEngineInputWarm": result.get("jpMarketEngineInputWarm")}
            else:
                last_error = "collect_http_transient"
        sleep(max(0, min(5, deadline - clock())))
    return {"status": "failed", "runId": run_id,
            "errorClass": "collect_poll_timeout", "lastErrorClass": last_error}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://argus-backend-3j2m.onrender.com")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    result = run(base=args.base, token=os.environ.get("ARGUS_ADMIN_TOKEN", ""), timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
