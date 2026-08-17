#!/usr/bin/env python3
"""Run the existing breadth incremental worker on a bounded natural schedule.

This control-plane runner intentionally does not import backend application
code. It uses public GETs for before/after evidence and invokes only the
existing JQUANTS_BREADTH_INCREMENTAL foundation job. It never calls a mission
tick, heartbeat, restart, deploy, or Soak mutation endpoint.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from zoneinfo import ZoneInfo


TERMINAL = {"completed", "failed", "cancelled"}
PROVIDER_NOT_READY_MARKERS = (
    "provider_not_ready",
    "recent_confirmed",
    "no_trading_dates",
    "jquants_not_ready",
    "jquants_rate",
    "rate_limit",
    "http_429",
    "http_502",
    "http_503",
    "http_504",
    "temporarily_unavailable",
)
RATIO_WINDOWS = (6, 10, 15, 25)
JST = ZoneInfo("Asia/Tokyo")


class RequestFailure(RuntimeError):
    """A secret-safe HTTP or transport failure."""


def _request(
    url: str,
    *,
    token: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 180,
) -> Dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "argus-breadth-freshness/1"}
    data = None
    method = "GET"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode()
        method = "POST"
    if token:
        headers["X-ARGUS-ADMIN-TOKEN"] = token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RequestFailure(f"http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RequestFailure(f"transport_{type(exc).__name__.lower()}") from None
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise RequestFailure("invalid_json") from None
    if not isinstance(body, dict):
        raise RequestFailure("invalid_json_shape")
    return body


def _date(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def weekday_candidate(now: dt.datetime) -> str:
    """Return the latest weekday candidate; provider evidence is authoritative."""
    local = now.astimezone(JST).date()
    while local.weekday() >= 5:
        local -= dt.timedelta(days=1)
    return local.isoformat()


def _walk(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _expected_date(ledger: Dict[str, Any], now: dt.datetime) -> Tuple[str, str]:
    for row in _walk(ledger):
        for key in (
            "expectedTradingDate",
            "latestExpectedTradingDate",
            "latestConfirmedTradingDate",
            "recentConfirmedTradingDay",
        ):
            parsed = _date(row.get(key))
            if parsed:
                return parsed, f"ledger:{key}"
    return weekday_candidate(now), "weekday_candidate_provider_confirmed"


def _series_periods(ledger: Dict[str, Any]) -> Dict[str, str]:
    periods: Dict[str, str] = {}
    for row in ledger.get("table") or []:
        if not isinstance(row, dict):
            continue
        series_id = str(row.get("seriesId") or "")
        period = _date(row.get("periodEnd") or row.get("latestDate"))
        if series_id and period:
            periods[series_id] = period
    for row in ledger.get("observations") or []:
        if not isinstance(row, dict):
            continue
        series_id = str(row.get("seriesId") or "")
        period = _date(row.get("periodEnd") or row.get("date"))
        if series_id and period and period > periods.get(series_id, ""):
            periods[series_id] = period
    return periods


def _ratio_values(ledger: Dict[str, Any]) -> Dict[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {str(window): None for window in RATIO_WINDOWS}
    for row in _walk(ledger):
        identity = " ".join(str(row.get(key) or "") for key in
                            ("metricId", "seriesId", "id", "name")).lower()
        for window in RATIO_WINDOWS:
            if result[str(window)] is not None:
                continue
            markers = (f"ratio{window}", f"ratio_{window}", f"ratio.{window}")
            if not any(marker in identity for marker in markers):
                continue
            value = row.get("latestValue", row.get("value", row.get("ratio")))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[str(window)] = float(value)
    return result


def ledger_summary(ledger: Dict[str, Any]) -> Dict[str, Any]:
    periods = _series_periods(ledger)
    breadth_periods = [
        period for series_id, period in periods.items()
        if series_id.startswith("breadth.") and series_id != "breadth.topixProxyClose"
    ]
    price_period = periods.get("breadth.topixProxyClose")
    if price_period is None:
        other_prices = [
            period for series_id, period in periods.items()
            if "price" in series_id.lower() or "close" in series_id.lower()
        ]
        price_period = max(other_prices, default=None)
    observations = ledger.get("observations")
    turning = ledger.get("turningPoints")
    turning_page = ledger.get("turningPointPage")
    return {
        "breadthNewestDate": max(breadth_periods, default=None),
        "marketPriceNewestDate": price_period,
        "lagTradingDays": ledger.get("lagTradingDays"),
        "ratios": _ratio_values(ledger),
        "rowCount": ledger.get("observationCount")
        if isinstance(ledger.get("observationCount"), int)
        else len(observations) if isinstance(observations, list) else None,
        "turningPointCount": ledger.get("turningPointCount")
        if isinstance(ledger.get("turningPointCount"), int)
        else turning_page.get("totalStoredCount")
        if isinstance(turning_page, dict)
        and isinstance(turning_page.get("totalStoredCount"), int)
        else len(turning) if isinstance(turning, list) else None,
        "stateHash": ledger.get("stateHash"),
        "methodVersion": ledger.get("methodVersion"),
    }


def _identity(body: Dict[str, Any]) -> Dict[str, Any]:
    source = body.get("buildIdentity") if isinstance(body.get("buildIdentity"), dict) else body
    return {
        "version": source.get("appVersion") or source.get("version"),
        "sha": source.get("buildSha") or source.get("sha") or source.get("commit"),
        "bootTime": body.get("bootTime") or body.get("processBootTime")
        or source.get("bootTime"),
    }


def _data_quality_identity(body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(body, dict):
        return {"version": None, "sha": None, "bootTime": None}
    build = body.get("buildIdentity") if isinstance(body.get("buildIdentity"), dict) else {}
    runtime = body.get("runtimeIdentity") if isinstance(body.get("runtimeIdentity"), dict) else {}
    return {
        "version": build.get("backendVersion") or body.get("appVersion"),
        "sha": build.get("backendBuildSha") or runtime.get("buildSha"),
        "bootTime": runtime.get("processBootedAt"),
    }


def _soak_identity(body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(body, dict):
        return {"soakId": None, "startedAt": None, "restartCount": None}
    soak = body.get("buildSoak") if isinstance(body.get("buildSoak"), dict) else {}
    continuity = body.get("soakContinuity") if isinstance(body.get("soakContinuity"), dict) else {}
    return {
        "soakId": soak.get("soakId"),
        "startedAt": soak.get("startedAt"),
        "restartCount": continuity.get("restartCount"),
    }


def _weekday_gap(start: Any, end: Any) -> Optional[int]:
    first = _date(start)
    last = _date(end)
    if not first or not last or first >= last:
        return 0 if first and last and first == last else None
    cursor = dt.date.fromisoformat(first)
    target = dt.date.fromisoformat(last)
    count = 0
    while cursor < target:
        cursor += dt.timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count


def _job_row(body: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    rows = body.get("jobs")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and str(row.get("jobId") or "") == job_id:
                return row
        if rows and isinstance(rows[0], dict):
            return rows[0]
    return {}


def _provider_not_ready(error_class: Any, result: Any = None) -> bool:
    text = f"{error_class or ''} {json.dumps(result or {}, sort_keys=True)}".lower()
    return any(marker in text for marker in PROVIDER_NOT_READY_MARKERS)


def classify_terminal(
    job: Dict[str, Any],
    before: Dict[str, Any],
    after: Dict[str, Any],
    expected_date: str,
) -> str:
    status = str(job.get("status") or "").lower()
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if status == "completed":
        if str(result.get("resultClassification") or "").lower() == "provider_not_ready":
            return "provider_not_ready"
        before_date = _date(before.get("breadthNewestDate"))
        after_date = _date(after.get("breadthNewestDate"))
        if after_date and (not before_date or after_date > before_date):
            return "success"
        if after_date and after_date >= expected_date:
            return "no_new_session"
        if _provider_not_ready(job.get("errorClass"), result):
            return "provider_not_ready"
        return "no_new_session"
    if _provider_not_ready(job.get("errorClass"), result):
        return "provider_not_ready"
    return "failure"


def _read_optional(
    base: str,
    path: str,
    request: Callable[..., Dict[str, Any]] = _request,
) -> Optional[Dict[str, Any]]:
    try:
        return request(f"{base}{path}", timeout=180)
    except RequestFailure:
        return None


def _write_artifact(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def run(
    *,
    base_url: str,
    token: str,
    artifact_path: Path,
    attempts: int,
    retry_seconds: int,
    poll_seconds: int,
    max_wait_seconds: int,
    now: Optional[dt.datetime] = None,
    request: Callable[..., Dict[str, Any]] = _request,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    base = base_url.rstrip("/")
    observed_at = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    report: Dict[str, Any] = {
        "schemaVersion": "argus-breadth-freshness-evidence-v1",
        "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
        "classification": "failure",
        "providerAvailability": "unknown",
        "contract": {
            "backendDeploy": False,
            "renderRestart": False,
            "manualTick": False,
            "manualHeartbeat": False,
            "preserveBackendSoak": True,
            "workerConcurrency": 1,
        },
        "attempts": [],
    }
    try:
        health_before = request(f"{base}/healthz", timeout=180)
        ready_before = request(f"{base}/readyz", timeout=180)
        ledger_before = request(f"{base}/api/argus/market-ledger", timeout=240)
        quality_before = _read_optional(base, "/api/argus/data-quality", request)
        before = ledger_summary(ledger_before)
        expected_date, expected_source = _expected_date(ledger_before, observed_at)
        if before.get("lagTradingDays") is None:
            before["lagTradingDays"] = _weekday_gap(
                before.get("breadthNewestDate"), expected_date)
        backend_before = _data_quality_identity(quality_before)
        health_identity = _identity(health_before)
        backend_before["version"] = backend_before["version"] or health_identity["version"]
        backend_before["sha"] = backend_before["sha"] or health_identity["sha"]
        report.update({
            "expectedTradingDate": expected_date,
            "expectedTradingDateSource": expected_source,
            "before": before,
            "backendBefore": backend_before,
            "soakBefore": _soak_identity(quality_before),
            "readyBefore": ready_before.get("ready"),
        })
        already_published = (
            _date(before.get("breadthNewestDate")) is not None
            and before["breadthNewestDate"] >= expected_date
        )
        if already_published:
            report["classification"] = "no_new_session"
            report["providerAvailability"] = "already_published"
            report["after"] = before
        else:
            final_job: Dict[str, Any] = {}
            after = before
            for attempt in range(1, max(1, attempts) + 1):
                started = request(
                    f"{base}/api/argus/admin/foundation-jobs",
                    token=token,
                    payload={
                        "jobType": "JQUANTS_BREADTH_INCREMENTAL",
                        "confirm": True,
                        "triggerSource": "github_schedule",
                        "resume": False,
                        "parameters": {"to": expected_date},
                    },
                    timeout=180,
                )
                started_job = started.get("job") if isinstance(started.get("job"), dict) else {}
                job_id = str(started_job.get("jobId") or "")
                if started.get("ok") is not True or not job_id:
                    raise RequestFailure("job_start_failed")
                deadline = time.monotonic() + max_wait_seconds
                final_job = {}
                while time.monotonic() < deadline:
                    status_body = request(
                        f"{base}/api/argus/foundation-jobs?"
                        + urllib.parse.urlencode({"jobId": job_id}),
                        timeout=180,
                    )
                    final_job = _job_row(status_body, job_id)
                    if str(final_job.get("status") or "").lower() in TERMINAL:
                        break
                    sleeper(max(1, poll_seconds))
                else:
                    final_job = {"jobId": job_id, "status": "failed",
                                 "errorClass": "bounded_poll_timeout"}

                ledger_after = request(f"{base}/api/argus/market-ledger", timeout=240)
                after = ledger_summary(ledger_after)
                if after.get("lagTradingDays") is None:
                    after["lagTradingDays"] = _weekday_gap(
                        after.get("breadthNewestDate"), expected_date)
                classification = classify_terminal(final_job, before, after, expected_date)
                result = final_job.get("result") if isinstance(final_job.get("result"), dict) else {}
                report["attempts"].append({
                    "attempt": attempt,
                    "jobId": job_id,
                    "status": final_job.get("status"),
                    "errorClass": final_job.get("errorClass"),
                    "resultClassification": result.get("resultClassification"),
                    "providerResponseClass": result.get("providerResponseClass"),
                    "rowCount": result.get("rowCount"),
                    "stateHash": result.get("stateHash"),
                    "classification": classification,
                })
                if classification != "provider_not_ready" or attempt >= max(1, attempts):
                    report["classification"] = classification
                    break
                sleeper(max(0, retry_seconds))

            report["after"] = after
            report["providerAvailability"] = (
                "available" if report["classification"] == "success"
                else "not_ready" if report["classification"] == "provider_not_ready"
                else "no_new_session" if report["classification"] == "no_new_session"
                else "failure"
            )
        health_after = request(f"{base}/healthz", timeout=180)
        ready_after = request(f"{base}/readyz", timeout=180)
        quality_after = _read_optional(base, "/api/argus/data-quality", request)
        backend_after = _data_quality_identity(quality_after)
        after_health_identity = _identity(health_after)
        backend_after["version"] = backend_after["version"] or after_health_identity["version"]
        backend_after["sha"] = backend_after["sha"] or after_health_identity["sha"]
        report["backendAfter"] = backend_after
        report["soakAfter"] = _soak_identity(quality_after)
        report["readyAfter"] = ready_after.get("ready")
        report["backendIdentityStable"] = (
            bool(report["backendBefore"].get("sha"))
            and bool(report["backendBefore"].get("bootTime"))
            and report["backendBefore"] == report["backendAfter"]
        )
        report["soakIdentityStable"] = (
            bool(report["soakBefore"].get("soakId"))
            and bool(report["soakBefore"].get("startedAt"))
            and report["soakBefore"] == report["soakAfter"]
        )
        if quality_after is not None:
            remote = quality_after.get("remoteJournalVerification")
            if not isinstance(remote, dict):
                remote = quality_after
            report["remoteJournalReadBack"] = {
                key: remote.get(key) for key in (
                    "readBackVerified", "walReadBackVerified", "pendingCount",
                    "remotePendingCount", "errorClass", "walErrorClass",
                    "remoteCommitSha", "verifiedWalSequence",
                )
            }
        if (report["classification"] == "failure"
                or not report["backendIdentityStable"]
                or not report["soakIdentityStable"]
                or ready_before.get("ready") is not True
                or ready_after.get("ready") is not True):
            report["classification"] = "failure"
            return 1
        return 0
    except RequestFailure as exc:
        report["classification"] = "failure"
        report["errorClass"] = str(exc)
        return 1
    finally:
        _write_artifact(artifact_path, report)
        print(json.dumps({
            "classification": report.get("classification"),
            "expectedTradingDate": report.get("expectedTradingDate"),
            "before": report.get("before"),
            "after": report.get("after"),
            "backendIdentityStable": report.get("backendIdentityStable"),
            "artifact": str(artifact_path),
        }, ensure_ascii=False, separators=(",", ":")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://argus-backend-3j2m.onrender.com")
    parser.add_argument("--artifact-path", default="artifacts/breadth-freshness.json")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-wait-seconds", type=int, default=7200)
    args = parser.parse_args()
    token = os.environ.get("ARGUS_ADMIN_TOKEN", "")
    if not token:
        report = {
            "schemaVersion": "argus-breadth-freshness-evidence-v1",
            "classification": "failure",
            "errorClass": "ARGUS_ADMIN_TOKEN_missing",
            "contract": {
                "backendDeploy": False,
                "renderRestart": False,
                "manualTick": False,
                "preserveBackendSoak": True,
            },
        }
        _write_artifact(Path(args.artifact_path), report)
        print(json.dumps(report, separators=(",", ":")))
        return 2
    return run(
        base_url=args.base_url,
        token=token,
        artifact_path=Path(args.artifact_path),
        attempts=args.attempts,
        retry_seconds=args.retry_seconds,
        poll_seconds=args.poll_seconds,
        max_wait_seconds=args.max_wait_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
