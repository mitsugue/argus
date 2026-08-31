#!/usr/bin/env python3
"""Deterministic, crash-safe EC2 dispatcher for the Watchtower writer.

The process owns scheduling admission only.  It checks public backend
readiness and issues one GitHub workflow_dispatch for the most recent
canonical UTC slot.  Durable per-slot state prevents blind retry across
process crashes, EC2 reboot, duplicate timer delivery, and ambiguous POSTs.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping


REPOSITORY = "mitsugue/argus"
WORKFLOW = "caos-watchtower.yml"
REF = "main"
DISPATCH_MODE = "ec2_systemd_writer"
OWNER_MANUAL_MODE = "owner_manual"
DEFAULT_BACKEND_URL = "https://argus-backend-3j2m.onrender.com"
STATE_ROOT = pathlib.Path("/var/lib/argus-watchtower-writer")
DISPATCH_URL = (
    f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/"
    f"{WORKFLOW}/dispatches"
)
RUNS_URL = (
    f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/"
    f"{WORKFLOW}/runs?event=workflow_dispatch&branch={REF}&per_page=20"
)
MAX_PUBLIC_RESPONSE_BYTES = 64 * 1024
MAX_GITHUB_RESPONSE_BYTES = 1024 * 1024
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
TOKEN_RE = re.compile(r"^(?:github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,})$")
DISPATCH_ID_RE = re.compile(r"^awwd-[0-9a-f]{32}$")
STATE_SCHEMA = "argus-watchtower-writer-slot-v1"
PHASES = {
    "PREPARED", "DISPATCH_ACCEPTED", "FAILED_DEFINITE",
    "FAILED_AMBIGUOUS",
}
WEEKDAY_MINUTES = (4, 11, 19, 26, 34, 41, 49, 56)
WEEKEND_MINUTES = (4, 34)


class WriterDispatchError(RuntimeError):
    """Stable, secret-free scheduler failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _emit(**fields: object) -> None:
    allowed = {
        "status", "reason", "errorClass", "phase", "scheduledFor",
        "writerDispatchId", "httpStatus", "reconciled", "duplicate",
        "executionProven",
    }
    safe = {key: value for key, value in fields.items() if key in allowed}
    safe.update({
        "schemaVersion": "argus-watchtower-writer-dispatch-result-v1",
        "component": "argus-watchtower-writer",
    })
    print(json.dumps(safe, sort_keys=True), flush=True)


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WriterDispatchError("utc_time_required")
    return value.astimezone(dt.timezone.utc)


def _slot_minutes(value: dt.datetime) -> tuple[int, ...]:
    return WEEKDAY_MINUTES if value.weekday() < 5 else WEEKEND_MINUTES


def canonical_slot(value: dt.datetime) -> dt.datetime:
    """Return the latest canonical UTC opportunity at or before ``value``."""
    cursor = _utc(value).replace(second=0, microsecond=0)
    for offset in range(24 * 60 + 1):
        candidate = cursor - dt.timedelta(minutes=offset)
        if candidate.minute in _slot_minutes(candidate):
            return candidate
    raise WriterDispatchError("canonical_slot_unavailable")


def format_slot(value: dt.datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:00Z")


def parse_slot(value: str) -> dt.datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z", value or ""):
        raise WriterDispatchError("writer_scheduled_for_invalid")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:00Z").replace(
            tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise WriterDispatchError("writer_scheduled_for_invalid") from exc
    if parsed.minute not in _slot_minutes(parsed):
        raise WriterDispatchError("writer_slot_not_canonical")
    return parsed


def writer_dispatch_id(scheduled_for: str, *, repository: str = REPOSITORY,
                       workflow: str = WORKFLOW, ref: str = REF) -> str:
    parse_slot(scheduled_for)
    material = "\0".join((
        "argus-watchtower-writer-v1", repository, workflow, ref,
        scheduled_for,
    )).encode("utf-8")
    return "awwd-" + hashlib.sha256(material).hexdigest()[:32]


def validate_dispatch_inputs(*, remote_journal_rearm: bool,
                             dispatch_mode: str, writer_scheduled_for: str,
                             supplied_dispatch_id: str,
                             repository: str = REPOSITORY,
                             workflow: str = WORKFLOW,
                             ref: str = REF) -> dict[str, object]:
    """Validate the three disjoint workflow_dispatch identities."""
    mode = str(dispatch_mode or "")
    scheduled = str(writer_scheduled_for or "")
    dispatch_id = str(supplied_dispatch_id or "")
    if repository != REPOSITORY:
        raise WriterDispatchError("writer_repository_invalid")
    if workflow != WORKFLOW:
        raise WriterDispatchError("writer_workflow_invalid")
    if ref != REF:
        raise WriterDispatchError("writer_ref_invalid")
    if remote_journal_rearm:
        if mode != OWNER_MANUAL_MODE or scheduled or dispatch_id:
            raise WriterDispatchError("rearm_dispatch_inputs_mixed")
        return {"natural": True, "policySource": "remote_journal_rearm"}
    if mode == OWNER_MANUAL_MODE:
        if scheduled or dispatch_id:
            raise WriterDispatchError("manual_dispatch_inputs_mixed")
        return {"natural": False, "policySource": OWNER_MANUAL_MODE}
    if mode != DISPATCH_MODE:
        raise WriterDispatchError("writer_dispatch_mode_invalid")
    parse_slot(scheduled)
    expected = writer_dispatch_id(
        scheduled, repository=repository, workflow=workflow, ref=ref)
    if not DISPATCH_ID_RE.fullmatch(dispatch_id) or dispatch_id != expected:
        raise WriterDispatchError("writer_dispatch_id_invalid")
    return {
        "natural": True,
        "policySource": DISPATCH_MODE,
        "writerScheduledFor": scheduled,
        "writerDispatchId": dispatch_id,
    }


def _request_json(url: str, *, timeout: int, maximum: int,
                  token: str | None = None,
                  opener: Callable[..., Any] | None = None) -> Mapping[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json" if token else "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "argus-watchtower-writer/1",
    }
    if token:
        headers.update({
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
        })
    request = urllib.request.Request(url, headers=headers)
    safe_opener = opener or urllib.request.build_opener(_NoRedirect()).open
    with safe_opener(request, timeout=timeout) as response:
        if int(response.status) != 200:
            raise WriterDispatchError("http_status_invalid")
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise WriterDispatchError("http_response_oversized")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WriterDispatchError("http_response_malformed") from exc
    if not isinstance(value, Mapping):
        raise WriterDispatchError("http_response_malformed")
    return value


def verify_public_ready(base: str, *, timeout: int,
                        opener: Callable[..., Any] | None = None) -> None:
    health = _request_json(
        base.rstrip("/") + "/healthz", timeout=timeout,
        maximum=MAX_PUBLIC_RESPONSE_BYTES, opener=opener)
    ready = _request_json(
        base.rstrip("/") + "/readyz", timeout=timeout,
        maximum=MAX_PUBLIC_RESPONSE_BYTES, opener=opener)
    if health.get("status") != "ok" or ready.get("ready") is not True:
        raise WriterDispatchError("backend_not_ready")
    health_sha = str(health.get("buildSha") or "").lower()
    ready_sha = str(ready.get("buildSha") or "").lower()
    version = str(health.get("backendVersion") or "")
    if not FULL_SHA_RE.fullmatch(health_sha) or ready_sha != health_sha:
        raise WriterDispatchError("backend_identity_mismatch")
    if not SEMVER_RE.fullmatch(version) or ready.get("backendVersion") != version:
        raise WriterDispatchError("backend_version_mismatch")


def _token(value: str) -> str:
    candidate = str(value or "").strip()
    if not TOKEN_RE.fullmatch(candidate):
        raise WriterDispatchError("workflow_pat_invalid")
    return candidate


def _state_path(root: pathlib.Path, scheduled_for: str) -> pathlib.Path:
    safe = scheduled_for.replace(":", "").replace("-", "")
    return root / (safe + ".json")


def _verify_directory(root: pathlib.Path) -> None:
    try:
        info = root.lstat()
    except FileNotFoundError as exc:
        raise WriterDispatchError("writer_state_root_missing") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise WriterDispatchError("writer_state_root_type_invalid")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise WriterDispatchError("writer_state_root_mode_invalid")
    if info.st_uid != os.geteuid() or info.st_gid != os.getegid():
        raise WriterDispatchError("writer_state_root_owner_invalid")


@contextlib.contextmanager
def state_lock(root: pathlib.Path):
    _verify_directory(root)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(root / ".lock", flags, 0o600)
    except OSError as exc:
        raise WriterDispatchError("writer_state_lock_invalid") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 \
                or info.st_uid != os.geteuid() or info.st_gid != os.getegid():
            raise WriterDispatchError("writer_state_lock_metadata_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise WriterDispatchError("writer_state_lock_contended") from exc
            raise
        yield
    finally:
        os.close(descriptor)


def _validate_state(value: object, *, scheduled_for: str,
                    dispatch_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != STATE_SCHEMA:
        raise WriterDispatchError("writer_state_corrupt")
    expected = {
        "repository": REPOSITORY, "workflow": WORKFLOW, "ref": REF,
        "writerScheduledFor": scheduled_for, "writerDispatchId": dispatch_id,
    }
    if any(value.get(key) != expected_value
           for key, expected_value in expected.items()):
        raise WriterDispatchError("writer_state_identity_mismatch")
    if value.get("phase") not in PHASES or \
            not isinstance(value.get("dispatchAttempted"), bool) or \
            value.get("executionProven") is not False:
        raise WriterDispatchError("writer_state_corrupt")
    return value


def read_state(root: pathlib.Path, scheduled_for: str,
               dispatch_id: str) -> dict[str, Any] | None:
    path = _state_path(root, scheduled_for)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or \
            stat.S_IMODE(info.st_mode) != 0o600 or \
            info.st_uid != os.geteuid() or info.st_gid != os.getegid():
        raise WriterDispatchError("writer_state_metadata_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WriterDispatchError("writer_state_corrupt") from exc
    return _validate_state(
        value, scheduled_for=scheduled_for, dispatch_id=dispatch_id)


def write_state(root: pathlib.Path, value: Mapping[str, Any]) -> None:
    scheduled_for = str(value.get("writerScheduledFor") or "")
    dispatch_id = str(value.get("writerDispatchId") or "")
    checked = _validate_state(
        dict(value), scheduled_for=scheduled_for, dispatch_id=dispatch_id)
    destination = _state_path(root, scheduled_for)
    temporary = root / (destination.name + f".tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(
                checked, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _new_state(scheduled_for: str, dispatch_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": STATE_SCHEMA,
        "repository": REPOSITORY,
        "workflow": WORKFLOW,
        "ref": REF,
        "writerScheduledFor": scheduled_for,
        "writerDispatchId": dispatch_id,
        "phase": "PREPARED",
        "dispatchAttempted": False,
        # A 204 or run-object reconciliation proves dispatch admission only.
        # The GitHub job and resulting keyed write require separate evidence.
        "executionProven": False,
        "failureClass": None,
    }


def _post_dispatch(token: str, *, scheduled_for: str, dispatch_id: str,
                   timeout: int,
                   opener: Callable[..., Any] | None = None) -> int:
    body = json.dumps({
        "ref": REF,
        "inputs": {
            "remoteJournalRearm": "false",
            "dispatchMode": DISPATCH_MODE,
            "writerScheduledFor": scheduled_for,
            "writerDispatchId": dispatch_id,
        },
    }, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        DISPATCH_URL, data=body, method="POST", headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "argus-watchtower-writer/1",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    safe_opener = opener or urllib.request.build_opener(_NoRedirect()).open
    with safe_opener(request, timeout=timeout) as response:
        status_code = int(response.status)
    if status_code != 204:
        raise WriterDispatchError("workflow_dispatch_rejected")
    return status_code


def reconcile_dispatch(token: str, dispatch_id: str, *, timeout: int,
                       opener: Callable[..., Any] | None = None) -> bool:
    """Perform one bounded read-only reconciliation; never poll or resend."""
    value = _request_json(
        RUNS_URL, timeout=timeout, maximum=MAX_GITHUB_RESPONSE_BYTES,
        token=token, opener=opener)
    runs = value.get("workflow_runs")
    if not isinstance(runs, list) or len(runs) > 20:
        raise WriterDispatchError("github_runs_response_invalid")
    for run in runs:
        if not isinstance(run, Mapping):
            raise WriterDispatchError("github_runs_response_invalid")
        name = str(run.get("display_title") or run.get("name") or "")
        if dispatch_id in name and run.get("event") == "workflow_dispatch" \
                and run.get("head_branch") == REF:
            return True
    return False


def dispatch_slot(*, now: dt.datetime, token: str, root: pathlib.Path,
                  backend_url: str = DEFAULT_BACKEND_URL, timeout: int = 6,
                  public_opener: Callable[..., Any] | None = None,
                  post_opener: Callable[..., Any] | None = None,
                  reconcile_opener: Callable[..., Any] | None = None,
                  before_attempt: Callable[[], None] | None = None,
                  before_post: Callable[[], None] | None = None,
                  after_post: Callable[[], None] | None = None) -> dict[str, Any]:
    scheduled_for = format_slot(canonical_slot(now))
    dispatch_id = writer_dispatch_id(scheduled_for)
    secret = _token(token)
    with state_lock(root):
        state = read_state(root, scheduled_for, dispatch_id)
        if state is None:
            state = _new_state(scheduled_for, dispatch_id)
            write_state(root, state)
        phase = state["phase"]
        if phase == "DISPATCH_ACCEPTED":
            return {**state, "status": "duplicate_suppressed", "duplicate": True}
        if phase in {"FAILED_DEFINITE", "FAILED_AMBIGUOUS"}:
            raise WriterDispatchError("writer_slot_terminal_failure")
        if state["dispatchAttempted"]:
            try:
                reconciled = reconcile_dispatch(
                    secret, dispatch_id, timeout=timeout,
                    opener=reconcile_opener)
            except (WriterDispatchError, urllib.error.HTTPError,
                    urllib.error.URLError, TimeoutError):
                reconciled = False
            state["phase"] = (
                "DISPATCH_ACCEPTED" if reconciled else "FAILED_AMBIGUOUS")
            state["failureClass"] = None if reconciled else \
                "prior_dispatch_acceptance_unproven"
            write_state(root, state)
            if reconciled:
                return {
                    **state, "status": "dispatch_acceptance_reconciled",
                    "reconciled": True,
                }
            raise WriterDispatchError("prior_dispatch_acceptance_unproven")
        try:
            verify_public_ready(
                backend_url, timeout=timeout, opener=public_opener)
        except (WriterDispatchError, urllib.error.HTTPError,
                urllib.error.URLError, TimeoutError):
            state["phase"] = "FAILED_DEFINITE"
            state["failureClass"] = "public_readiness_failed"
            write_state(root, state)
            raise WriterDispatchError("public_readiness_failed") from None
        if before_attempt is not None:
            before_attempt()
        state["dispatchAttempted"] = True
        write_state(root, state)

        def finish_ambiguous(failure_class: str) -> dict[str, Any]:
            try:
                accepted = reconcile_dispatch(
                    secret, dispatch_id, timeout=timeout,
                    opener=reconcile_opener)
            except (WriterDispatchError, urllib.error.HTTPError,
                    urllib.error.URLError, TimeoutError):
                accepted = False
            state["phase"] = (
                "DISPATCH_ACCEPTED" if accepted else "FAILED_AMBIGUOUS")
            state["failureClass"] = None if accepted else failure_class
            write_state(root, state)
            if accepted:
                return {
                    **state, "status": "dispatch_acceptance_reconciled",
                    "reconciled": True,
                }
            raise WriterDispatchError(failure_class)

        if before_post is not None:
            before_post()
        try:
            status_code = _post_dispatch(
                secret, scheduled_for=scheduled_for, dispatch_id=dispatch_id,
                timeout=timeout, opener=post_opener)
            if after_post is not None:
                after_post()
        except urllib.error.HTTPError as exc:
            if 400 <= int(exc.code) < 500:
                state["phase"] = "FAILED_DEFINITE"
                state["failureClass"] = "workflow_dispatch_http_error"
                write_state(root, state)
                raise WriterDispatchError(
                    "workflow_dispatch_http_error") from None
            return finish_ambiguous("workflow_dispatch_http_error")
        except (urllib.error.URLError, TimeoutError):
            return finish_ambiguous("workflow_dispatch_ambiguous")
        except WriterDispatchError:
            return finish_ambiguous("workflow_dispatch_response_invalid")
        state["phase"] = "DISPATCH_ACCEPTED"
        state["failureClass"] = None
        write_state(root, state)
        return {
            **state, "status": "dispatch_accepted",
            "httpStatus": status_code,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command")
    validate = subcommands.add_parser("validate-inputs")
    validate.add_argument("--remote-journal-rearm", choices=("true", "false"),
                          required=True)
    validate.add_argument("--dispatch-mode", required=True)
    validate.add_argument("--writer-scheduled-for", default="")
    validate.add_argument("--writer-dispatch-id", default="")
    validate.add_argument("--repository", required=True)
    validate.add_argument("--workflow", required=True)
    validate.add_argument("--ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments and arguments[0] == "validate-inputs":
            args = _parser().parse_args(arguments)
            result = validate_dispatch_inputs(
                remote_journal_rearm=args.remote_journal_rearm == "true",
                dispatch_mode=args.dispatch_mode,
                writer_scheduled_for=args.writer_scheduled_for,
                supplied_dispatch_id=args.writer_dispatch_id,
                repository=args.repository, workflow=args.workflow, ref=args.ref)
            _emit(status="validated", reason=str(result["policySource"]),
                  scheduledFor=result.get("writerScheduledFor"),
                  writerDispatchId=result.get("writerDispatchId"))
            return 0
        if arguments:
            raise WriterDispatchError("writer_arguments_invalid")
        try:
            timeout = min(10, max(3, int(os.environ.get(
                "ARGUS_WATCHTOWER_WRITER_TIMEOUT_SECONDS", "6"))))
        except ValueError:
            raise WriterDispatchError("writer_configuration_invalid") from None
        state_root = pathlib.Path(os.environ.get(
            "ARGUS_WATCHTOWER_WRITER_STATE_ROOT", str(STATE_ROOT)))
        result = dispatch_slot(
            now=dt.datetime.now(dt.timezone.utc),
            token=os.environ.get("ARGUS_REMOTE_JOURNAL_REARM_PAT", ""),
            root=state_root,
            backend_url=os.environ.get(
                "ARGUS_BACKEND_URL", DEFAULT_BACKEND_URL),
            timeout=timeout)
        _emit(
            status=result["status"], phase=result["phase"],
            scheduledFor=result["writerScheduledFor"],
            writerDispatchId=result["writerDispatchId"],
            httpStatus=result.get("httpStatus"),
            reconciled=result.get("reconciled"),
            duplicate=result.get("duplicate"),
            executionProven=result["executionProven"])
        return 0
    except WriterDispatchError as exc:
        _emit(status="failure", errorClass=str(exc)[:96])
        return 1
    except Exception:
        _emit(status="failure", errorClass="writer_unexpected_failure")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
