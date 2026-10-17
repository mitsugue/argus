#!/usr/bin/env python3
"""Verify authoritative manifest storage before polling mutable raw bytes."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping


class PublicationVerificationError(RuntimeError):
    """Stable publication verification failure classification."""


@dataclass(frozen=True)
class PublicationVerification:
    authoritativeCommit: str
    authoritativeBytesExact: bool
    rawConverged: bool
    rawAttempts: int


def verify_authoritative(
    *,
    expected_bytes: bytes,
    fetch_ref: Callable[[], Any],
    fetch_content: Callable[[str], Any],
) -> str:
    """Verify a commit-aware branch ref and exact content object."""
    ref = fetch_ref()
    if not isinstance(ref, Mapping):
        raise PublicationVerificationError("authoritative_ref_invalid")
    obj = ref.get("object")
    commit = str(obj.get("sha") or "") if isinstance(obj, Mapping) else ""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PublicationVerificationError("authoritative_commit_invalid")
    content = fetch_content(commit)
    if not isinstance(content, Mapping):
        raise PublicationVerificationError("authoritative_content_invalid")
    if str(content.get("type") or "") != "file":
        raise PublicationVerificationError("authoritative_content_not_file")
    if str(content.get("encoding") or "") != "base64":
        raise PublicationVerificationError("authoritative_encoding_invalid")
    try:
        encoded = "".join(str(content.get("content") or "").split())
        actual = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise PublicationVerificationError(
            "authoritative_content_decode_failed") from exc
    if actual != expected_bytes:
        raise PublicationVerificationError("authoritative_bytes_mismatch")
    return commit


def wait_for_raw(
    *,
    expected_bytes: bytes,
    fetch_raw: Callable[[int], bytes],
    timeout_seconds: int = 300,
    poll_seconds: int = 5,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Bounded raw convergence check.  Never republishes stale bytes."""
    deadline = monotonic() + max(0, int(timeout_seconds))
    attempts = 0
    while True:
        attempts += 1
        try:
            if fetch_raw(attempts) == expected_bytes:
                return attempts
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            pass
        if monotonic() >= deadline:
            raise PublicationVerificationError("public_raw_convergence_timeout")
        sleep(max(0.0, float(poll_seconds)))


def _github_json(
    url: str,
    *,
    token: str,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "argus-manifest-publication-verifier/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if int(response.status) != 200:
                raise PublicationVerificationError(
                    "authoritative_api_status_" + str(response.status))
            return json.loads(response.read().decode("utf-8"))
    except PublicationVerificationError:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PublicationVerificationError(
            "authoritative_api_unavailable:" + type(exc).__name__) from exc


def _raw_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "argus-manifest-publication-verifier/1",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if int(response.status) != 200:
            raise urllib.error.HTTPError(
                url, int(response.status), "unexpected status", {}, None)
        return response.read()


def _write_github_output(
    path: pathlib.Path,
    result: PublicationVerification,
) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"authoritativeCommit={result.authoritativeCommit}\n")
        handle.write("authoritativeBytesExact=true\n")
        handle.write("rawConverged=true\n")
        handle.write(f"rawAttempts={result.rawAttempts}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=pathlib.Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", default="production-release")
    parser.add_argument("--path", default="production/argus-backend.json")
    parser.add_argument("--raw-url", required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--github-output", type=pathlib.Path)
    args = parser.parse_args(argv)
    expected = args.expected.read_bytes()
    api = "https://api.github.com/repos/" + args.repo
    branch_path = urllib.parse.quote(args.branch, safe="")
    content_path = urllib.parse.quote(args.path, safe="/")
    token = os.environ.get(args.token_env, "")
    commit = verify_authoritative(
        expected_bytes=expected,
        fetch_ref=lambda: _github_json(
            f"{api}/git/ref/heads/{branch_path}", token=token),
        fetch_content=lambda sha: _github_json(
            f"{api}/contents/{content_path}?ref={sha}", token=token),
    )
    attempts = wait_for_raw(
        expected_bytes=expected,
        fetch_raw=lambda attempt: _raw_bytes(
            args.raw_url
            + ("&" if "?" in args.raw_url else "?")
            + f"commit={commit}&attempt={attempt}"),
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    result = PublicationVerification(
        authoritativeCommit=commit,
        authoritativeBytesExact=True,
        rawConverged=True,
        rawAttempts=attempts,
    )
    payload = asdict(result)
    if args.output:
        args.output.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    if args.github_output:
        _write_github_output(args.github_output, result)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
