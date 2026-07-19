#!/usr/bin/env python3
"""GitHub Actions用HTTP実行・判定（stdlibのみ、秘密値を出力しない）。"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Optional, Tuple

SUCCESS = "success"
EXPECTED_SKIP = "expected_skip"
DEGRADED = "degraded"
FAILURE = "failure"

_FAIL_STATUSES = {"error", "failed", "failure", "unreachable", "unauthorized",
                  "forbidden", "blocked", "invalid"}
_DEGRADED_STATUSES = {"degraded", "partial"}
_SKIP_STATUSES = {"expected_skip", "skipped", "no_work", "noop"}
_SECRET_KEYS = ("token", "secret", "password", "passphrase", "credential",
                "authorization", "apikey", "api_key", "hmac")
_SAFE_OUTPUT_KEYS = ("ok", "status", "count", "translated", "pending", "made",
                     "created", "updated", "generated", "queued", "recovered")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if any(s in k.lower() for s in _SECRET_KEYS)
                    else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _safe_summary(body: Any, outcome: str, http_status: Any) -> Dict[str, Any]:
    summary = {"workflowOutcome": outcome, "httpStatus": http_status}
    if isinstance(body, dict):
        for key in _SAFE_OUTPUT_KEYS:
            if key not in body:
                continue
            value = body.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
    return _redact(summary)


def classify_response(http_status: int, raw_body: str, *,
                      expected_statuses: Iterable[str] = (),
                      expected_values: Iterable[str] = ()) -> Dict[str, Any]:
    """HTTP到達と業務結果を分離。failure/degradedはCLIで非0終了する。"""
    try:
        body = json.loads(raw_body)
    except (TypeError, json.JSONDecodeError):
        return {"outcome": FAILURE, "reason": "invalid_json",
                "httpStatus": http_status, "body": None}
    if not isinstance(body, (dict, list)):
        return {"outcome": FAILURE, "reason": "invalid_json_shape",
                "httpStatus": http_status, "body": body}
    status = str(body.get("status") or "").lower() if isinstance(body, dict) else ""
    expected = {str(s).lower() for s in expected_statuses}
    values = ({str(body.get(k)).lower() for k in ("status", "reason", "error")
               if isinstance(body, dict) and body.get(k) not in (None, "")})
    explicit_skip = status in expected or bool(values & {
        str(v).lower() for v in expected_values})
    # 429 is an endpoint-level budget/rate gate and may be an explicitly declared
    # expected skip. Authentication failures and server failures can never be green.
    if not 200 <= int(http_status) < 300 and not (int(http_status) == 429 and explicit_skip):
        return {"outcome": FAILURE, "reason": f"http_{http_status}",
                "httpStatus": http_status, "body": body}
    if explicit_skip:
        return {"outcome": EXPECTED_SKIP, "reason": "explicit_expected_skip",
                "httpStatus": http_status, "body": body}
    if isinstance(body, dict):
        if body.get("error") not in (None, "", False):
            return {"outcome": FAILURE, "reason": "business_error",
                    "httpStatus": http_status, "body": body}
        if body.get("ok") is False or status in _FAIL_STATUSES:
            return {"outcome": FAILURE, "reason": f"business_{status or 'not_ok'}",
                    "httpStatus": http_status, "body": body}
        if status in _DEGRADED_STATUSES:
            return {"outcome": DEGRADED, "reason": f"business_{status}",
                    "httpStatus": http_status, "body": body}
        if status in _SKIP_STATUSES:
            return {"outcome": EXPECTED_SKIP, "reason": f"business_{status}",
                    "httpStatus": http_status, "body": body}
    return {"outcome": SUCCESS, "reason": "http_and_business_ok",
            "httpStatus": http_status, "body": body}


def request_json(*, url: str, method: str = "GET", timeout: int = 60,
                 headers: Optional[Dict[str, str]] = None,
                 data: Optional[str] = None) -> Tuple[int, str]:
    payload = data.encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, method=method.upper(),
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode() or 200
            return int(status), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", "replace")


def _headers_from_env(specs: Iterable[str]) -> Dict[str, str]:
    headers = {}
    for spec in specs:
        name, sep, env_name = spec.partition("=")
        if not sep or not name or not env_name:
            raise ValueError("--header-env must be Header=ENV_NAME")
        value = os.environ.get(env_name, "")
        if value:
            headers[name] = value
    return headers


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--method", default="GET")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--data")
    p.add_argument("--header-env", action="append", default=[])
    p.add_argument("--header", action="append", default=[])
    p.add_argument("--expected-status", action="append", default=[])
    p.add_argument("--expected-value", action="append", default=[])
    args = p.parse_args(argv)
    try:
        headers = _headers_from_env(args.header_env)
        for spec in args.header:
            name, sep, value = spec.partition(":")
            if not sep:
                raise ValueError("--header must be Header: value")
            headers[name.strip()] = value.strip()
        code, raw = request_json(url=args.url, method=args.method,
                                 timeout=args.timeout, headers=headers,
                                 data=args.data)
        result = classify_response(code, raw,
                                   expected_statuses=args.expected_status,
                                   expected_values=args.expected_value)
    except (TimeoutError, socket.timeout):
        result = {"outcome": FAILURE, "reason": "timeout",
                  "httpStatus": None, "body": None}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result = {"outcome": FAILURE,
                  "reason": f"transport:{type(exc).__name__}",
                  "httpStatus": None, "body": None}
    safe_body = _safe_summary(result.get("body"), result["outcome"],
                              result.get("httpStatus"))
    print(json.dumps(safe_body,
                     ensure_ascii=False, separators=(",", ":")))
    print(f"[workflow-http] name={args.name} outcome={result['outcome']} "
          f"http={result.get('httpStatus')} reason={result['reason']}",
          file=sys.stderr)
    if result["outcome"] in (SUCCESS, EXPECTED_SKIP):
        return 0
    return 2 if result["outcome"] == DEGRADED else 1


if __name__ == "__main__":
    raise SystemExit(main())
