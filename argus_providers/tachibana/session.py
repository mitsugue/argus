"""Secret-safe v4r10 authentication and ephemeral session lifecycle."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import requests

from .config import TachibanaConfig
from .models import (
    AuthDiagnostic,
    Diagnostics,
    ErrorClass,
    ProviderHealth,
    SessionState,
    TachibanaError,
    VirtualEndpoints,
)
from .redaction import install_transport_log_redaction


_VIRTUAL_RESPONSE_FIELDS = {
    "request": "sUrlRequest",
    "master": "sUrlMaster",
    "price": "sUrlPrice",
    "event": "sUrlEvent",
    "event_websocket": "sUrlEventWebSocket",
}
_ALLOWED_HOSTS = frozenset({
    "kabuka.e-shiten.jp",
    "price-kabuka.e-shiten.jp",
    "demo-kabuka.e-shiten.jp",
})
_VIRTUAL_PATH_KIND = {
    "request": "request",
    "master": "master",
    "price": "price",
    "event": "event",
    "event_websocket": "event_ws",
}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_LARGE_RESPONSE_BYTES = {
    "CLMMfdsGetMarketPriceHistory": 4 * 1024 * 1024,
    "CLMStkGetIssueMstKabu": 8 * 1024 * 1024,
}
_AUTH_MAINTENANCE_ERRNOS = frozenset({"9", "-12"})
_AUTH_MAINTENANCE_RESULTS = frozenset({"990002", "990003", "990004"})
_AUTH_OUTSIDE_HOURS_RESULTS = frozenset({"990005"})
_AUTH_IP_REJECTED_RESULTS = frozenset({"10005"})
_AUTH_LOCKED_RESULTS = frozenset({"10033"})
_AUTH_OFFICIAL_REASONS = {
    "10005": "IP_ADDRESS_INVALID",
    "10033": "USER_MANAGEMENT_LOGIN_LOCKED",
    "990002": "SYSTEM_TEMPORARILY_STOPPED",
    "990003": "SYSTEM_SERVICE_STOPPED_TEST_MODE",
    "990004": "SYSTEM_SERVICE_STOPPED_MAINTENANCE",
    "990005": "SYSTEM_OUTSIDE_SERVICE_HOURS",
    "990006": "SYSTEM_LOGIN_FAILED",
    "990007": "SYSTEM_ENVIRONMENT_ERROR",
}


def _safe_result_code(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value):
        return value
    return None


def _safe_clmid(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{1,128}", value):
        return value
    return None


def _protocol_auth_diagnostic(response: Any) -> AuthDiagnostic:
    if not isinstance(response, Mapping):
        return AuthDiagnostic(
            classification="AUTH_PROTOCOL_FAILED",
            boundary="PROTOCOL_FAILED",
        )
    clmid = _safe_clmid(response.get("sCLMID"))
    result = _safe_result_code(response.get("sResultCode"))
    present = tuple(
        isinstance(response.get(field), str) and bool(response.get(field))
        for field in _VIRTUAL_RESPONSE_FIELDS.values()
    )
    return AuthDiagnostic(
        classification="AUTH_PROTOCOL_FAILED",
        boundary="PROTOCOL_FAILED",
        response_clmid=clmid,
        result_code=result,
        response_matched_ack=clmid == "CLMAuthLoginAck",
        encrypted_virtual_urls_present=all(present) if any(present) else False,
    )


def _auth_result_classification(result: str) -> tuple[ErrorClass, str, str]:
    reason = _AUTH_OFFICIAL_REASONS.get(
        result, "UNMAPPED_OFFICIAL_RESULT_CODE"
    )
    if result in _AUTH_MAINTENANCE_RESULTS:
        return ErrorClass.AUTH_MAINTENANCE, "AUTH_MAINTENANCE", reason
    if result in _AUTH_OUTSIDE_HOURS_RESULTS:
        return ErrorClass.OUTSIDE_HOURS, "AUTH_SERVER_REJECTED_" + result, reason
    if result in _AUTH_IP_REJECTED_RESULTS:
        return ErrorClass.AUTH_IP_REJECTED, "AUTH_IP_REJECTED", reason
    if result in _AUTH_LOCKED_RESULTS:
        return ErrorClass.AUTH_LOCKED, "AUTH_LOCKED", reason
    return (
        ErrorClass.AUTH_SERVER_REJECTED,
        "AUTH_SERVER_REJECTED_" + result,
        reason,
    )


def _inspect_auth_response(
    response: Mapping[str, Any], *, expected_p_no: str
) -> tuple[ErrorClass | None, AuthDiagnostic]:
    """Validate the common auth envelope before inspecting success-only fields.

    Provider error responses legitimately omit ``sResultCode`` and the five
    virtual URLs.  Requiring success-only fields first masks maintenance and
    outside-hours truth as a schema error, which makes a bounded operator
    smoke test misleading.
    """
    if (
        not isinstance(response, Mapping)
        or not isinstance(response.get("p_no"), str)
        or not isinstance(response.get("p_errno"), str)
        or response.get("p_no") != expected_p_no
    ):
        return ErrorClass.AUTH_PROTOCOL_FAILED, _protocol_auth_diagnostic(response)
    errno = response["p_errno"]
    if errno != "0":
        if errno in _AUTH_MAINTENANCE_ERRNOS:
            classification = ErrorClass.AUTH_MAINTENANCE
            normalized = "AUTH_MAINTENANCE"
        elif errno == "-2":
            classification = ErrorClass.RATE_LIMITED
            normalized = "AUTH_RATE_LIMITED"
        elif errno == "-62":
            classification = ErrorClass.OUTSIDE_HOURS
            normalized = "AUTH_OUTSIDE_HOURS"
        elif errno == "8":
            classification = ErrorClass.CLOCK_SKEW
            normalized = "AUTH_CLOCK_SKEW"
        elif errno == "6":
            classification = ErrorClass.SEQUENCE_DESYNC
            normalized = "AUTH_SEQUENCE_DESYNC"
        else:
            classification = ErrorClass.AUTH_PROTOCOL_FAILED
            normalized = "AUTH_PROTOCOL_FAILED"
        return classification, replace(
            _protocol_auth_diagnostic(response),
            classification=normalized,
        )
    clmid = _safe_clmid(response.get("sCLMID"))
    if clmid != "CLMAuthLoginAck":
        return ErrorClass.AUTH_PROTOCOL_FAILED, _protocol_auth_diagnostic(response)
    result_value = response.get("sResultCode", "0")
    result = _safe_result_code(result_value)
    if result is None:
        return ErrorClass.AUTH_PROTOCOL_FAILED, _protocol_auth_diagnostic(response)
    present = tuple(
        isinstance(response.get(field), str) and bool(response.get(field))
        for field in _VIRTUAL_RESPONSE_FIELDS.values()
    )
    all_present = all(present)
    none_present = not any(present)
    if result != "0":
        error_class, normalized, reason = _auth_result_classification(result)
        return error_class, AuthDiagnostic(
            classification=normalized,
            boundary="SERVER_AUTH_REJECTED",
            response_clmid="CLMAuthLoginAck",
            result_code=result,
            official_reason=reason,
            response_matched_ack=True,
            encrypted_virtual_urls_present=all_present,
        )
    if none_present:
        return ErrorClass.AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD, AuthDiagnostic(
            classification="AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD",
            boundary="AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD",
            response_clmid="CLMAuthLoginAck",
            result_code="0",
            official_reason="SUCCESS_VIRTUAL_URLS_WITHHELD",
            response_matched_ack=True,
            encrypted_virtual_urls_present=False,
        )
    if not all_present:
        return ErrorClass.AUTH_PROTOCOL_FAILED, AuthDiagnostic(
            classification="AUTH_PROTOCOL_FAILED",
            boundary="PROTOCOL_FAILED",
            response_clmid="CLMAuthLoginAck",
            result_code="0",
            official_reason="SUCCESS_RESPONSE_PARTIAL_VIRTUAL_URLS",
            response_matched_ack=True,
            encrypted_virtual_urls_present=False,
        )
    return None, AuthDiagnostic(
        classification="AUTH_RESPONSE_SUCCESS",
        boundary="AUTH_RESPONSE_SUCCESS",
        response_clmid="CLMAuthLoginAck",
        result_code="0",
        official_reason="SUCCESS",
        response_matched_ack=True,
        encrypted_virtual_urls_present=True,
    )


def _classify_auth_failure(
    response: Mapping[str, Any], *, expected_p_no: str
) -> ErrorClass | None:
    """Compatibility wrapper for callers that only need the closed class."""
    classification, _ = _inspect_auth_response(
        response, expected_p_no=expected_p_no
    )
    return classification


class JsonTransport(Protocol):
    def post_json(
        self, url: str, payload: Mapping[str, str], timeout: int
    ) -> Mapping[str, Any]: ...


class RequestsJsonTransport:
    """No-retry HTTP transport with bounded response size and scrubbed failures."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        install_transport_log_redaction()
        self._session = session or requests.Session()
        self._monotonic = monotonic
        self.last_http_status: int | None = None
        # Owner credentials and credential-equivalent virtual URLs must never
        # be forwarded to a proxy inherited from the process environment.
        self._session.trust_env = False

    def post_json(
        self, url: str, payload: Mapping[str, str], timeout: int
    ) -> Mapping[str, Any]:
        response = None
        self.last_http_status = None
        is_auth = payload.get("sCLMID") == "CLMAuthLoginRequest"
        if type(timeout) is not int or not 1 <= timeout <= 30:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        try:
            started_at = float(self._monotonic())
        except (TypeError, ValueError, OverflowError):
            raise TachibanaError(ErrorClass.CONFIGURATION) from None
        if not math.isfinite(started_at):
            raise TachibanaError(ErrorClass.CONFIGURATION)
        deadline = started_at + timeout
        maximum_response_bytes = _LARGE_RESPONSE_BYTES.get(
            payload.get("sCLMID"), _MAX_RESPONSE_BYTES
        )
        try:
            response = self._session.post(
                url,
                json=dict(payload),
                headers={"Accept": "application/json", "Cache-Control": "no-store"},
                # Requests' read timeout is an inter-byte timeout, not a total
                # deadline.  Poll at one second and independently enforce the
                # monotonic wall-clock deadline below so a slow drip cannot
                # retain the serialized session lock indefinitely.
                timeout=(min(4, timeout), min(1, timeout)),
                allow_redirects=False,
                stream=True,
            )
            self.last_http_status = response.status_code
            if is_auth and response.status_code != 200:
                raise TachibanaError(ErrorClass.AUTH_HTTP_FAILED)
            if response.status_code == 429:
                raise TachibanaError(ErrorClass.RATE_LIMITED)
            if response.status_code == 503:
                raise TachibanaError(ErrorClass.MAINTENANCE)
            if response.status_code != 200:
                raise TachibanaError(ErrorClass.HTTP)
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError):
                    raise TachibanaError(
                        ErrorClass.AUTH_PROTOCOL_FAILED
                        if is_auth else ErrorClass.PROVIDER
                    ) from None
                if declared_length < 0 or declared_length > maximum_response_bytes:
                    raise TachibanaError(
                        ErrorClass.AUTH_PROTOCOL_FAILED
                        if is_auth else ErrorClass.PROVIDER
                    )
            raw_buffer = bytearray()
            chunks = iter(response.iter_content(chunk_size=64 * 1024))
            while True:
                if self._monotonic() >= deadline:
                    raise TachibanaError(
                        ErrorClass.AUTH_TIMEOUT if is_auth else ErrorClass.NETWORK
                    )
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
                if self._monotonic() >= deadline:
                    raise TachibanaError(
                        ErrorClass.AUTH_TIMEOUT if is_auth else ErrorClass.NETWORK
                    )
                if not isinstance(chunk, bytes):
                    raise TachibanaError(
                        ErrorClass.AUTH_PROTOCOL_FAILED
                        if is_auth else ErrorClass.PROVIDER
                    )
                if len(raw_buffer) + len(chunk) > maximum_response_bytes:
                    raise TachibanaError(
                        ErrorClass.AUTH_PROTOCOL_FAILED
                        if is_auth else ErrorClass.PROVIDER
                    )
                raw_buffer.extend(chunk)
            raw = bytes(raw_buffer)
            decoded = raw.decode("shift_jis")
            parsed = json.loads(decoded)
        except TachibanaError:
            raise
        except requests.Timeout:
            raise TachibanaError(
                ErrorClass.AUTH_TIMEOUT if is_auth else ErrorClass.NETWORK
            ) from None
        except requests.RequestException:
            raise TachibanaError(
                ErrorClass.AUTH_HTTP_FAILED if is_auth else ErrorClass.NETWORK
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TachibanaError(
                ErrorClass.AUTH_PROTOCOL_FAILED if is_auth else ErrorClass.PROVIDER
            ) from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    # A dependency/socket cleanup failure must never replace the
                    # bounded provider result or expose a credential-equivalent
                    # virtual URL embedded in third-party exception text.
                    pass
        if not isinstance(parsed, dict):
            raise TachibanaError(
                ErrorClass.AUTH_PROTOCOL_FAILED if is_auth else ErrorClass.PROVIDER
            )
        return parsed


def _timestamp(now: datetime) -> str:
    local = now.astimezone(ZoneInfo("Asia/Tokyo"))
    return local.strftime("%Y.%m.%d-%H:%M:%S.000")


# Platform-managed secret mounts (Render "Secret Files", Kubernetes-style
# projections) expose secrets through symlinks and may not grant the process
# permission to chmod them to 0600.  Under this root only, a symlink is
# resolved before the O_NOFOLLOW open and group/other READ bits are tolerated;
# WRITE or EXEC bits for group/other are never accepted anywhere.
PLATFORM_SECRET_ROOTS = (Path("/etc/secrets"),)


def _under_platform_secret_root(path: Path) -> bool:
    try:
        candidate = Path(os.path.realpath(path))
    except (OSError, ValueError):
        return False
    return any(
        candidate == root or root in candidate.parents
        for root in PLATFORM_SECRET_ROOTS
    )


def _read_secret(path: Path, missing_class: ErrorClass) -> bytes:
    platform_managed = _under_platform_secret_root(path)
    target = Path(os.path.realpath(path)) if platform_managed else path
    try:
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise TachibanaError(missing_class) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise TachibanaError(missing_class)
        forbidden_bits = (
            stat.S_IWGRP | stat.S_IXGRP | stat.S_IWOTH | stat.S_IXOTH
            if platform_managed else (stat.S_IRWXG | stat.S_IRWXO)
        )
        if info.st_mode & forbidden_bits:
            raise TachibanaError(ErrorClass.SECRET_PERMISSIONS)
        if info.st_size > 64 * 1024:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks).strip()
        if not value:
            raise TachibanaError(missing_class)
        return value
    finally:
        os.close(descriptor)


_PEM_LABELS = ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY",
               "ENCRYPTED PRIVATE KEY")
_PEM_BEGIN_RE = re.compile(rb"-----BEGIN ([A-Z ]{3,40})-----")
_PEM_END_RE = re.compile(rb"-----END ([A-Z ]{3,40})-----")
_BASE64_BODY_RE = re.compile(rb"^[A-Za-z0-9+/=]+$")


def _key_text_variants(key_bytes: bytes) -> list[tuple[str, bytes]]:
    """Candidate encodings of one secret file, most literal first.

    Platform secret-file editors routinely re-flow a pasted PEM (CRLF, a
    single line, lost armor, a UTF-8 BOM).  Each candidate is rebuilt from
    the same bytes; nothing is fetched, guessed or logged.
    """
    raw = key_bytes
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").strip()
    variants: list[tuple[str, bytes]] = [("PEM", text)]
    begin = _PEM_BEGIN_RE.search(text)
    end = _PEM_END_RE.search(text)
    if begin and end and end.start() > begin.end():
        label = begin.group(1)
        body = b"".join(text[begin.end():end.start()].split())
        if body and _BASE64_BODY_RE.match(body):
            lines = [body[i:i + 64] for i in range(0, len(body), 64)]
            rebuilt = (b"-----BEGIN " + label + b"-----\n"
                       + b"\n".join(lines) + b"\n-----END " + label + b"-----\n")
            variants.append(("NORMALIZED_PEM", rebuilt))
    else:
        body = b"".join(text.split())
        if body and _BASE64_BODY_RE.match(body) and len(body) % 4 == 0:
            lines = [body[i:i + 64] for i in range(0, len(body), 64)]
            for label in (b"PRIVATE KEY", b"RSA PRIVATE KEY"):
                variants.append(("ARMORED_BASE64", b"-----BEGIN " + label + b"-----\n"
                                 + b"\n".join(lines) + b"\n-----END " + label + b"-----\n"))
    variants.append(("DER", key_bytes))
    return variants


def load_private_key(key_bytes: bytes) -> tuple[Any, str]:
    """Parse an RSA private key from PEM / re-flowed PEM / bare base64 / DER.

    Returns (key, encoding_used).  Raises TachibanaError(PRIVATE_KEY_INVALID)
    when no candidate parses to an RSA key of 2048..4096 bits.
    """
    for encoding, candidate in _key_text_variants(key_bytes):
        try:
            if encoding == "DER":
                key = serialization.load_der_private_key(candidate, password=None)
            else:
                key = serialization.load_pem_private_key(candidate, password=None)
        except (TypeError, ValueError):
            continue
        if isinstance(key, rsa.RSAPrivateKey) and 2048 <= key.key_size <= 4096:
            return key, encoding
        raise TachibanaError(ErrorClass.PRIVATE_KEY_INVALID)
    raise TachibanaError(ErrorClass.PRIVATE_KEY_INVALID)


def private_key_shape(key_bytes: bytes) -> dict[str, Any]:
    """Secret-safe structural facts about a private key file.

    Only shape: byte count class, line count, CRLF/BOM presence, whether PEM
    armor is present and which standard label it carries, whether the body
    is base64, and which encoding (if any) parses.  Never key material,
    never a hash of it.
    """
    raw = key_bytes
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:] if has_bom else raw
    begin = _PEM_BEGIN_RE.search(text)
    end = _PEM_END_RE.search(text)
    label = begin.group(1).decode("ascii", "replace") if begin else None
    body = b"".join(text[begin.end():end.start()].split()) if (begin and end and end.start() > begin.end()) \
        else b"".join(text.split())
    shape: dict[str, Any] = {
        "bytes": len(raw),
        "lineCount": text.count(b"\n") + (0 if text.endswith(b"\n") or not text else 1),
        "crlf": b"\r\n" in text,
        "bom": has_bom,
        "armored": bool(begin and end),
        "beginLabel": label if label in _PEM_LABELS else ("OTHER" if label else None),
        "base64Body": bool(body) and _BASE64_BODY_RE.match(body) is not None,
        "parsed": "FAILED",
        "keyType": None,
        "keySize": None,
    }
    try:
        key, encoding = load_private_key(key_bytes)
    except TachibanaError:
        return shape
    shape.update({"parsed": encoding, "keyType": "RSA", "keySize": key.key_size})
    return shape


def _validate_virtual_url(value: str, category: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID) from None
    expected = "wss" if category == "event_websocket" else "https"
    if parsed.scheme != expected or hostname not in _ALLOWED_HOSTS:
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID)
    if (
        parsed.username or parsed.password or parsed.fragment or parsed.query
        or port not in {None, 443}
    ):
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID)
    segments = parsed.path.split("/")
    expected_kind = _VIRTUAL_PATH_KIND.get(category)
    if (
        expected_kind is None
        or len(segments) != 5
        or segments[0] != ""
        or segments[1] != "e_api_v4r10"
        or segments[2] != expected_kind
        or not segments[3]
        or len(segments[3]) > 1024
        or segments[4] != ""
        or not all(character.isalnum() or character in "+=_-"
                   for character in segments[3])
    ):
        raise TachibanaError(ErrorClass.VIRTUAL_URL_INVALID)
    return value


class TachibanaSession:
    """One serialized session. Authentication is never retried automatically."""

    def __init__(
        self,
        config: TachibanaConfig,
        transport: JsonTransport | None = None,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.config = config
        self._transport = transport or RequestsJsonTransport()
        self._clock = clock
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._sequence = 0
        self._endpoints: VirtualEndpoints | None = None
        self.state = SessionState.UNINITIALIZED
        self.diagnostics = Diagnostics()
        self.auth_diagnostic = AuthDiagnostic()

    @property
    def request_lock(self) -> threading.Lock:
        return self._request_lock

    def _next_header(self) -> dict[str, str]:
        with self._lock:
            self._sequence += 1
            return {
                "p_no": str(self._sequence),
                "p_sd_date": _timestamp(self._clock()),
                "sJsonOfmt": "5",
            }

    def authenticate(self) -> None:
        # The provider sequence and all credential-equivalent URLs belong to
        # one session. Serialize authentication with every read and logout.
        with self._request_lock:
            with self._lock:
                if not self.config.enabled:
                    self.state = SessionState.UNAVAILABLE
                    self.diagnostics.last_error_class = ErrorClass.DISABLED
                    raise TachibanaError(ErrorClass.DISABLED)
                if self.state in {
                    SessionState.AUTHENTICATING, SessionState.AVAILABLE,
                }:
                    self.auth_diagnostic = AuthDiagnostic(
                        classification="AUTH_LOCAL_STATE_REJECTED",
                        boundary="NOT_SENT",
                    )
                    self.diagnostics.last_error_class = (
                        ErrorClass.AUTH_LOCAL_STATE_REJECTED
                    )
                    raise TachibanaError(ErrorClass.AUTH_LOCAL_STATE_REJECTED)
                self._clear_endpoints()
                self._sequence = 0
                self.state = SessionState.AUTHENTICATING
                self.auth_diagnostic = AuthDiagnostic(
                    classification="AUTH_IN_PROGRESS",
                    boundary="NOT_COMPLETED",
                )
                try:
                    auth_id_bytes = _read_secret(
                        self.config.auth_id_path, ErrorClass.SECRET_MISSING
                    )
                    key_bytes = _read_secret(
                        self.config.private_key_path, ErrorClass.SECRET_MISSING
                    )
                    try:
                        auth_id = auth_id_bytes.decode("utf-8-sig").strip()
                    except UnicodeDecodeError:
                        raise TachibanaError(ErrorClass.SECRET_MISSING) from None
                    if not auth_id or len(auth_id) > 4096:
                        raise TachibanaError(ErrorClass.SECRET_MISSING)
                    private_key, _key_encoding = load_private_key(key_bytes)

                    payload = self._next_header()
                    payload.update({
                        "sCLMID": "CLMAuthLoginRequest",
                        "sAuthId": auth_id,
                    })
                    try:
                        response = self._transport.post_json(
                            self.config.auth_endpoint,
                            payload,
                            self.config.request_timeout_seconds,
                        )
                    except TachibanaError as exc:
                        boundary = {
                            ErrorClass.AUTH_TIMEOUT: "HTTP_FAILED",
                            ErrorClass.AUTH_HTTP_FAILED: "HTTP_FAILED",
                            ErrorClass.AUTH_PROTOCOL_FAILED: "PROTOCOL_FAILED",
                        }.get(exc.classification)
                        if boundary is not None:
                            self.auth_diagnostic = AuthDiagnostic(
                                classification=exc.classification.value,
                                boundary=boundary,
                                http_status=getattr(
                                    self._transport, "last_http_status", None
                                ),
                            )
                        raise
                    failure, inspected = _inspect_auth_response(
                        response, expected_p_no=payload["p_no"]
                    )
                    self.auth_diagnostic = replace(
                        inspected,
                        http_status=getattr(
                            self._transport, "last_http_status", None
                        ),
                    )
                    if failure is not None:
                        raise TachibanaError(failure)
                    decrypted: dict[str, str] = {}
                    for name, field_name in _VIRTUAL_RESPONSE_FIELDS.items():
                        encrypted = response.get(field_name)
                        if not isinstance(encrypted, str) or not encrypted:
                            raise TachibanaError(ErrorClass.AUTH_PROTOCOL_FAILED)
                        try:
                            ciphertext = base64.b64decode(encrypted, validate=True)
                            plaintext = private_key.decrypt(
                                ciphertext,
                                padding.OAEP(
                                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                    algorithm=hashes.SHA256(),
                                    label=None,
                                ),
                            ).decode("ascii").strip()
                        except Exception:
                            self.auth_diagnostic = AuthDiagnostic(
                                classification="AUTH_SUCCESS_DECRYPT_FAILED",
                                boundary="DECRYPT_FAILED",
                                http_status=getattr(
                                    self._transport, "last_http_status", None
                                ),
                                response_clmid="CLMAuthLoginAck",
                                result_code="0",
                                official_reason="SUCCESS",
                                response_matched_ack=True,
                                encrypted_virtual_urls_present=True,
                            )
                            raise TachibanaError(
                                ErrorClass.AUTH_SUCCESS_DECRYPT_FAILED
                            ) from None
                        try:
                            decrypted[name] = _validate_virtual_url(plaintext, name)
                        except TachibanaError:
                            self.auth_diagnostic = AuthDiagnostic(
                                classification="AUTH_PROTOCOL_FAILED",
                                boundary="PROTOCOL_FAILED",
                                http_status=getattr(
                                    self._transport, "last_http_status", None
                                ),
                                response_clmid="CLMAuthLoginAck",
                                result_code="0",
                                official_reason="SUCCESS_INVALID_VIRTUAL_URL",
                                response_matched_ack=True,
                                encrypted_virtual_urls_present=True,
                            )
                            raise TachibanaError(
                                ErrorClass.AUTH_PROTOCOL_FAILED
                            ) from None
                    self._endpoints = VirtualEndpoints(**decrypted)
                    self.state = SessionState.AVAILABLE
                    self.diagnostics.session_started_at = self._clock()
                    self.diagnostics.health = ProviderHealth.AVAILABLE
                    self.diagnostics.last_error_class = ErrorClass.NONE
                    self.auth_diagnostic = AuthDiagnostic(
                        classification="AUTH_SUCCEEDED",
                        boundary="AUTH_SUCCEEDED",
                        http_status=getattr(
                            self._transport, "last_http_status", None
                        ),
                        response_clmid="CLMAuthLoginAck",
                        result_code="0",
                        official_reason="SUCCESS",
                        response_matched_ack=True,
                        encrypted_virtual_urls_present=True,
                    )
                except TachibanaError as exc:
                    self._clear_endpoints()
                    self.state = (
                        SessionState.AUTH_FAILED
                        if exc.classification in {
                            ErrorClass.SECRET_MISSING,
                            ErrorClass.SECRET_PERMISSIONS,
                            ErrorClass.PRIVATE_KEY_INVALID,
                            ErrorClass.AUTH_REJECTED,
                            ErrorClass.AUTH_RESPONSE_INVALID,
                            ErrorClass.AUTH_SERVER_REJECTED,
                            ErrorClass.AUTH_SUCCESS_DECRYPT_FAILED,
                            ErrorClass.AUTH_PROTOCOL_FAILED,
                            ErrorClass.AUTH_IP_REJECTED,
                            ErrorClass.AUTH_LOCKED,
                            ErrorClass.VIRTUAL_URL_INVALID,
                        }
                        else SessionState.UNAVAILABLE
                    )
                    self.diagnostics.health = (
                        ProviderHealth.AUTH_FAILED
                        if self.state == SessionState.AUTH_FAILED
                        else ProviderHealth.UNAVAILABLE
                    )
                    self.diagnostics.last_error_class = exc.classification
                    raise

    def _market_data_endpoint(self, category: str) -> str:
        with self._lock:
            if self.state != SessionState.AVAILABLE or self._endpoints is None:
                raise TachibanaError(ErrorClass.SESSION_EXPIRED)
            if category not in {"master", "price", "event", "event_websocket"}:
                raise TachibanaError(ErrorClass.CONFIGURATION)
            value = getattr(self._endpoints, category)
            if not value:
                raise TachibanaError(ErrorClass.SESSION_EXPIRED)
            return value

    def logout(self) -> bool:
        """Attempt one session teardown request and always erase URL references."""
        with self._request_lock:
            try:
                with self._lock:
                    if self.state != SessionState.AVAILABLE or self._endpoints is None:
                        raise TachibanaError(ErrorClass.SESSION_EXPIRED)
                    url = self._endpoints.request
                    if not url:
                        raise TachibanaError(ErrorClass.SESSION_EXPIRED)
                payload = self._next_header()
                payload["sCLMID"] = "CLMAuthLogoutRequest"
                response = self._transport.post_json(
                    url, payload, self.config.request_timeout_seconds
                )
                if not isinstance(response, Mapping):
                    return False
                return (
                    response.get("p_no") == payload["p_no"]
                    and response.get("p_errno") == "0"
                    and response.get("sResultCode", "0") == "0"
                    and response.get("sCLMID") == "CLMAuthLogoutAck"
                )
            except TachibanaError:
                return False
            finally:
                with self._lock:
                    self._clear_endpoints()
                    self.state = SessionState.EXPIRED
                    self.diagnostics.health = ProviderHealth.UNAVAILABLE

    def expire(self) -> None:
        with self._lock:
            self._clear_endpoints()
            self.state = SessionState.EXPIRED
            self.diagnostics.health = ProviderHealth.UNAVAILABLE

    def _clear_endpoints(self) -> None:
        if self._endpoints is not None:
            self._endpoints.clear()
        self._endpoints = None
