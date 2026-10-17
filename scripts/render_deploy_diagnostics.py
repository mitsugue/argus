#!/usr/bin/env python3
"""Read-only Render deploy diagnostics: recent deploys and the failed build log.

Why: a Render build/deploy failure is only visible in the Render dashboard.
The repository already resolves deploy identity through the Render API
(`scripts/render_deployment_identity.py`); this script reuses the same
read-only API key to list the newest deploys of the backend service and to
fetch the build log of the newest failed one, so the failure can be read
from a GitHub Actions run without dashboard access.

Nothing here triggers, cancels or retries a deploy.  Output is bounded and
token-like strings are masked before printing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional

API = "https://api.render.com/v1"
FAILED_STATUSES = frozenset({
    "build_failed", "update_failed", "pre_deploy_failed", "canceled",
    "deactivated"})
LIVE_STATUS = "live"
MAX_PAGES = 5
MAX_LINES = 160
_SERVICE_RE = re.compile(r"srv-[0-9a-z]+")
_MASKS = (
    re.compile(r"rnd_[A-Za-z0-9]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+\S+"),
)


class DiagnosticsError(RuntimeError):
    pass


def mask(text: str) -> str:
    out = str(text)
    for pattern in _MASKS:
        out = pattern.sub("[masked]", out)
    return out


def _request(url: str, api_key: str) -> Any:
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": "Bearer " + api_key,
        "User-Agent": "argus-render-deploy-diagnostics/1",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DiagnosticsError(f"render_api_status_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
            UnicodeDecodeError) as exc:
        raise DiagnosticsError("render_api_transport") from exc


def normalize_deploys(payload: Any) -> List[Dict[str, Any]]:
    """Accept either ``[{deploy:{..}}, ..]`` or ``[{..}, ..]``."""
    rows: List[Dict[str, Any]] = []
    items = payload.get("deploys") if isinstance(payload, dict) else payload
    for item in items or []:
        row = item.get("deploy") if isinstance(item, dict) and isinstance(
            item.get("deploy"), dict) else item
        if not isinstance(row, dict):
            continue
        commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        message = str(commit.get("message") or "").splitlines()
        rows.append({
            "id": str(row.get("id") or ""),
            "status": str(row.get("status") or ""),
            "trigger": str(row.get("trigger") or ""),
            "commit": str(commit.get("id") or "")[:40],
            "subject": mask(message[0][:120] if message else ""),
            "createdAt": row.get("createdAt"),
            "startedAt": row.get("startedAt"),
            "finishedAt": row.get("finishedAt"),
        })
    return rows


def newest_failed(rows: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: str(r.get("createdAt") or ""),
                     reverse=True)
    for row in ordered:
        if row.get("status") in FAILED_STATUSES:
            return row
    return None


def normalize_logs(payload: Any) -> Dict[str, Any]:
    logs = payload.get("logs") if isinstance(payload, dict) else payload
    lines = []
    for entry in logs or []:
        if isinstance(entry, dict):
            lines.append({"timestamp": entry.get("timestamp"),
                          "message": mask(str(entry.get("message") or ""))})
    meta = payload if isinstance(payload, dict) else {}
    return {"lines": lines, "hasMore": bool(meta.get("hasMore")),
            "nextStartTime": meta.get("nextStartTime"),
            "nextEndTime": meta.get("nextEndTime")}


def fetch_build_log(fetch: Callable[[str], Any], *, owner_id: str,
                    service_id: str, start: Optional[str], end: Optional[str],
                    max_pages: int = MAX_PAGES) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    start_time, end_time = start, end
    for _ in range(max(1, int(max_pages))):
        query = {"ownerId": owner_id, "resource": service_id, "type": "build",
                 "limit": "100", "direction": "backward"}
        if start_time:
            query["startTime"] = start_time
        if end_time:
            query["endTime"] = end_time
        page = normalize_logs(fetch(API + "/logs?" + urllib.parse.urlencode(query)))
        collected = page["lines"] + collected
        if not page["hasMore"] or not page.get("nextEndTime"):
            break
        start_time, end_time = page.get("nextStartTime") or start_time, page["nextEndTime"]
    collected.sort(key=lambda row: str(row.get("timestamp") or ""))
    return collected[-MAX_LINES:]


def diagnose(fetch: Callable[[str], Any], *, service_id: str, limit: int = 5
             ) -> Dict[str, Any]:
    if not _SERVICE_RE.fullmatch(service_id):
        raise DiagnosticsError("render_service_id_invalid")
    service = fetch(API + "/services/" + urllib.parse.quote(service_id, safe=""))
    owner_id = str((service or {}).get("ownerId") or "") if isinstance(
        service, dict) else ""
    deploys = normalize_deploys(fetch(
        API + "/services/" + urllib.parse.quote(service_id, safe="")
        + "/deploys?limit=" + str(max(1, min(int(limit), 20)))))
    failed = newest_failed(deploys)
    result: Dict[str, Any] = {
        "schemaVersion": "argus-render-deploy-diagnostics-v1",
        "serviceId": service_id,
        "serviceName": mask(str((service or {}).get("name") or "")) if isinstance(
            service, dict) else None,
        "deploys": deploys, "newestFailed": failed, "buildLog": [],
        "buildLogStatus": "no_failed_deploy",
    }
    if failed:
        if not owner_id:
            result["buildLogStatus"] = "owner_id_unavailable"
        else:
            try:
                result["buildLog"] = fetch_build_log(
                    fetch, owner_id=owner_id, service_id=service_id,
                    start=failed.get("createdAt") or failed.get("startedAt"),
                    end=failed.get("finishedAt"))
                result["buildLogStatus"] = "fetched" if result["buildLog"] else "empty"
            except DiagnosticsError as exc:
                result["buildLogStatus"] = str(exc)
    return result


def summarize(result: Dict[str, Any]) -> str:
    out = ["# Render deploy diagnostics", "",
           f"service: `{result.get('serviceId')}` {result.get('serviceName') or ''}", "",
           "| status | commit | created | finished | trigger | subject |",
           "|---|---|---|---|---|---|"]
    for row in result.get("deploys") or []:
        out.append(f"| **{row['status']}** | `{row['commit'][:8]}` | {row.get('createdAt')} | "
                   f"{row.get('finishedAt')} | {row.get('trigger')} | {row.get('subject')} |")
    failed = result.get("newestFailed")
    out.append("")
    if failed:
        out.append(f"## Newest failed deploy `{failed['id']}` ({failed['status']}, "
                   f"commit `{failed['commit'][:8]}`) — build log: {result.get('buildLogStatus')}")
        out.append("")
        out.append("```text")
        for line in result.get("buildLog") or []:
            out.append(f"{line.get('timestamp')} {line.get('message')}"[:400])
        out.append("```")
    else:
        out.append("No failed deploy among the listed rows.")
    return "\n".join(out) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    api_key = os.environ.get("RENDER_API_KEY", "")
    if not api_key:
        print("render_api_key_missing", file=sys.stderr)
        return 2
    try:
        result = diagnose(lambda url: _request(url, api_key),
                          service_id=args.service_id, limit=args.limit)
    except DiagnosticsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    sys.stdout.write(summarize(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
