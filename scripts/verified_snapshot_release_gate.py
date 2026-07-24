#!/usr/bin/env python3
"""Fail-closed backend-first gate for the v13.3 verified snapshot release.

The script waits for the exact Render build, invokes the existing admin
missions tick once in diagnostic mode, and verifies all public snapshot
variants including their ETag/304 contract.  Its artifact is deliberately
metadata-only and never contains the admin token or response payloads.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_verified_snapshot


INSTRUMENTS = ("1321", "1306", "SPY", "QQQ")
HORIZONS = ("1D", "5D", "20D")
SNAPSHOT_SCHEMA = argus_verified_snapshot.SCHEMA_VERSION


class GateFailure(RuntimeError):
    """A redacted release-gate failure."""


def _request(
        url: str, *, method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
        timeout: int = 60) -> Tuple[int, Dict[str, str], Any]:
    raw = (json.dumps(body, separators=(",", ":")).encode("utf-8")
           if body is not None else None)
    request = urllib.request.Request(
        url, data=raw, method=method,
        headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            response_headers = {
                key.lower(): value for key, value in response.headers.items()}
            payload = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_headers = {
            key.lower(): value for key, value in exc.headers.items()}
        payload = exc.read()
    if not payload:
        return status, response_headers, None
    try:
        return status, response_headers, json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GateFailure(f"invalid_json_http_{status}") from exc


def _sha_matches(expected: str, actual: Any) -> bool:
    expected_text = str(expected or "").strip().lower()
    actual_text = str(actual or "").strip().lower()
    return bool(expected_text and actual_text and (
        expected_text.startswith(actual_text) or
        actual_text.startswith(expected_text)))


def wait_for_backend(
        base_url: str, expected_version: str, expected_sha: str,
        timeout_seconds: int, poll_seconds: int) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last = "no_response"
    while time.monotonic() < deadline:
        attempt += 1
        try:
            status, _, health = _request(
                f"{base_url}/healthz", timeout=min(60, poll_seconds + 30))
            if isinstance(health, dict):
                version = health.get("backendVersion")
                sha = health.get("buildSha")
                healthy = status == 200 and health.get("status") == "ok"
                if healthy and version == expected_version and \
                        _sha_matches(expected_sha, sha):
                    print(
                        f"backend-ready attempt={attempt} version={version} "
                        f"sha={str(sha)[:7]}", flush=True)
                    return {
                        "status": health.get("status"),
                        "backendVersion": version,
                        "buildSha": sha,
                        "asOf": health.get("asOf"),
                    }
                last = f"http_{status}:version_{version}:sha_{str(sha)[:7]}"
            else:
                last = f"http_{status}:invalid_health"
        except (GateFailure, urllib.error.URLError, TimeoutError,
                socket.timeout) as exc:
            last = type(exc).__name__
        print(f"backend-wait attempt={attempt} state={last}", flush=True)
        time.sleep(poll_seconds)
    raise GateFailure(f"backend_readiness_timeout:{last}")


def seed_snapshots(base_url: str, expected_sha: str) -> Dict[str, Any]:
    token = os.environ.get("ARGUS_ADMIN_TOKEN", "")
    if not token:
        raise GateFailure("ARGUS_ADMIN_TOKEN_missing")
    status, _, result = _request(
        f"{base_url}/api/argus/admin/missions/tick",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ARGUS-ADMIN-TOKEN": token,
        },
        body={
            "triggerSource": "manual",
            "runId": f"verified-snapshot-release-{expected_sha[:12]}",
            "expectedBuildSha": expected_sha,
        },
        timeout=360,
    )
    if status != 200 or not isinstance(result, dict):
        raise GateFailure(f"seed_http_{status}")
    if result.get("status") not in ("completed", "expected_skip"):
        raise GateFailure(f"seed_business_{result.get('status') or 'unknown'}")
    chart = result.get("chartIntelligence")
    if (result.get("status") == "completed"
            and (not isinstance(chart, dict)
                 or chart.get("status") == "degraded")):
        raise GateFailure("seed_chart_degraded")
    chart = chart if isinstance(chart, dict) else {}
    return {
        "httpStatus": status,
        "businessStatus": result.get("status"),
        "verifiedViewsStateHash": chart.get("verifiedViewsStateHash"),
        "viewPublications": chart.get("viewPublications"),
        "remoteJournal": {
            key: (result.get("remoteJournal") or {}).get(key)
            for key in ("readBackVerified", "remoteCommitSha", "errorClass")
        },
        "automaticAiExecutions": (
            result.get("costPolicy") or {}).get("automaticAiExecutions"),
    }


def verify_matrix(base_url: str) -> list[Dict[str, Any]]:
    matrix = []
    for instrument in INSTRUMENTS:
        for horizon in HORIZONS:
            query = urllib.parse.urlencode({
                "scope": "market",
                "timeframe": "daily",
                "symbol": instrument,
                "horizon": horizon,
                "snapshot": "verified",
            })
            url = f"{base_url}/api/argus/chart-intelligence?{query}"
            status, headers, snapshot = _request(url, timeout=60)
            if status != 200 or not isinstance(snapshot, dict):
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_http_{status}")
            ok, reason = argus_verified_snapshot.verify_snapshot(
                snapshot, expected_kind="market-chart",
                expected_instrument=instrument,
                expected_horizon=horizon)
            if not ok:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_{reason}")
            if snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_schema")
            payload = snapshot.get("payload") or {}
            bars = (payload.get("indicators") or {}).get("bars")
            if not isinstance(bars, list) or not bars:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_empty_payload")
            if payload.get("automaticAiCalls") != 0:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_ai_calls")
            etag = headers.get("etag")
            if not etag:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_etag_missing")
            if headers.get("x-argus-compute-mode") != "read-only":
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_not_read_only")
            second_status, second_headers, second_body = _request(
                url, headers={"If-None-Match": etag}, timeout=60)
            if second_status != 304 or second_body is not None:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_304_failed")
            if second_headers.get("etag") != etag:
                raise GateFailure(
                    f"snapshot_{instrument}_{horizon}_etag_changed")
            matrix.append({
                "instrument": instrument,
                "horizon": horizon,
                "httpStatus": status,
                "notModifiedStatus": second_status,
                "snapshotId": snapshot.get("snapshotId"),
                "schemaVersion": snapshot.get("schemaVersion"),
                "datasetHash": snapshot.get("datasetHash"),
                "methodVersion": snapshot.get("methodVersion"),
                "asOf": snapshot.get("asOf"),
                "generatedAt": snapshot.get("generatedAt"),
                "verifiedAt": snapshot.get("verifiedAt"),
                "quality": snapshot.get("quality"),
                "cacheStatus": (
                    payload.get("marketReplay") or {}).get("cacheStatus"),
                "etag": etag,
                "payloadHash": snapshot.get("payloadHash"),
                "verificationStatus": snapshot.get("verificationStatus"),
                "computeMode": headers.get("x-argus-compute-mode"),
                "automaticAiCalls": payload.get("automaticAiCalls"),
            })
            print(
                f"snapshot-ready {instrument} {horizon} "
                f"id={snapshot.get('snapshotId')} etag=verified",
                flush=True)
    return matrix


def verify_concurrent_reads(
        base_url: str, matrix: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Prove concurrent public reads return the already-published identities."""
    expected = {
        (row["instrument"], row["horizon"]): row["snapshotId"]
        for row in matrix
    }

    def read_one(key: Tuple[str, str]) -> Dict[str, Any]:
        instrument, horizon = key
        query = urllib.parse.urlencode({
            "scope": "market",
            "timeframe": "daily",
            "symbol": instrument,
            "horizon": horizon,
            "snapshot": "verified",
        })
        status, headers, snapshot = _request(
            f"{base_url}/api/argus/chart-intelligence?{query}",
            timeout=60)
        snapshot_id = snapshot.get("snapshotId") \
            if isinstance(snapshot, dict) else None
        if status != 200 or snapshot_id != expected[key]:
            raise GateFailure(
                f"concurrent_{instrument}_{horizon}_identity")
        if headers.get("x-argus-compute-mode") != "read-only":
            raise GateFailure(
                f"concurrent_{instrument}_{horizon}_not_read_only")
        return {
            "instrument": instrument,
            "horizon": horizon,
            "httpStatus": status,
            "snapshotId": snapshot_id,
            "computeMode": headers.get("x-argus-compute-mode"),
        }

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(expected)) as executor:
        rows = list(executor.map(read_one, expected))
    return rows


def write_artifact(path: str, result: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    result: Dict[str, Any] = {
        "schemaVersion": "verified-snapshot-release-gate-v1",
        "status": "failure",
        "expectedVersion": args.expected_version,
        "expectedSha": args.expected_sha,
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "snapshotExpected": len(INSTRUMENTS) * len(HORIZONS),
        "snapshotReady": 0,
        "failures": [],
    }
    try:
        base_url = args.base_url.rstrip("/")
        result["backend"] = wait_for_backend(
            base_url, args.expected_version, args.expected_sha,
            args.timeout_seconds, args.poll_seconds)
        result["seed"] = seed_snapshots(base_url, args.expected_sha)
        result["matrix"] = verify_matrix(base_url)
        result["snapshotReady"] = len(result["matrix"])
        result["concurrentReads"] = verify_concurrent_reads(
            base_url, result["matrix"])
        result["getPurity"] = {
            "providerFetchDuringGet": 0,
            "automaticAiCallsDuringGet": 0,
            "concurrentReadCount": len(result["concurrentReads"]),
            "evidence": (
                "read-only response header + stable ETag/304 + "
                "concurrent snapshot identity"),
        }
        result["status"] = "ready"
        return_code = 0
    except Exception as exc:  # artifact must survive every fail-closed path
        failure = str(exc) if isinstance(exc, GateFailure) \
            else type(exc).__name__
        result["failures"].append(failure)
        print(f"release-gate failure={failure}", file=sys.stderr, flush=True)
        return_code = 1
    finally:
        result["completedAt"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_artifact(args.artifact, result)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
