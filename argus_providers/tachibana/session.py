"""Secret-safe v4r10 authentication and ephemeral session lifecycle."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
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
        # Owner credentials and credential-equivalent virtual URLs must never
        # be forwarded to a proxy inherited from the process environment.
        self._session.trust_env = False

    def post_json(
        self, url: str, payload: Mapping[str, str], timeout: int
    ) -> Mapping[str, Any]:
        response = None
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
                    raise TachibanaError(ErrorClass.PROVIDER) from None
                if declared_length < 0 or declared_length > maximum_response_bytes:
                    raise TachibanaError(ErrorClass.PROVIDER)
            raw_buffer = bytearray()
            chunks = iter(response.iter_content(chunk_size=64 * 1024))
            while True:
                if self._monotonic() >= deadline:
                    raise TachibanaError(ErrorClass.NETWORK)
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
                if self._monotonic() >= deadline:
                    raise TachibanaError(ErrorClass.NETWORK)
                if not isinstance(chunk, bytes):
                    raise TachibanaError(ErrorClass.PROVIDER)
                if len(raw_buffer) + len(chunk) > maximum_response_bytes:
                    raise TachibanaError(ErrorClass.PROVIDER)
                raw_buffer.extend(chunk)
            raw = bytes(raw_buffer)
            decoded = raw.decode("shift_jis")
            parsed = json.loads(decoded)
        except TachibanaError:
            raise
        except requests.RequestException:
            raise TachibanaError(ErrorClass.NETWORK) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TachibanaError(ErrorClass.PROVIDER) from None
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
            raise TachibanaError(ErrorClass.PROVIDER)
        return parsed


def _timestamp(now: datetime) -> str:
    local = now.astimezone(ZoneInfo("Asia/Tokyo"))
    return local.strftime("%Y.%m.%d-%H:%M:%S.000")


def _read_secret(path: Path, missing_class: ErrorClass) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise TachibanaError(missing_class) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise TachibanaError(missing_class)
        if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
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
                    self.diagnostics.last_error_class = ErrorClass.AUTH_REJECTED
                    raise TachibanaError(ErrorClass.AUTH_REJECTED)
                self._clear_endpoints()
                self._sequence = 0
                self.state = SessionState.AUTHENTICATING
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
                    try:
                        private_key = serialization.load_pem_private_key(
                            key_bytes, password=None
                        )
                    except (TypeError, ValueError):
                        raise TachibanaError(ErrorClass.PRIVATE_KEY_INVALID) from None
                    if (
                        not isinstance(private_key, rsa.RSAPrivateKey)
                        or not 2048 <= private_key.key_size <= 4096
                    ):
                        raise TachibanaError(ErrorClass.PRIVATE_KEY_INVALID)

                    payload = self._next_header()
                    payload.update({
                        "sCLMID": "CLMAuthLoginRequest",
                        "sAuthId": auth_id,
                    })
                    response = self._transport.post_json(
                        self.config.auth_endpoint,
                        payload,
                        self.config.request_timeout_seconds,
                    )
                    if (
                        not isinstance(response, Mapping)
                        or response.get("p_no") != payload["p_no"]
                        or not isinstance(response.get("p_errno"), str)
                        or not isinstance(response.get("sResultCode"), str)
                        or not isinstance(response.get("sCLMID"), str)
                    ):
                        raise TachibanaError(ErrorClass.AUTH_RESPONSE_INVALID)
                    if response["p_errno"] != "0" or response["sResultCode"] != "0":
                        raise TachibanaError(ErrorClass.AUTH_REJECTED)
                    if response.get("sCLMID") != "CLMAuthLoginAck":
                        raise TachibanaError(ErrorClass.AUTH_RESPONSE_INVALID)
                    decrypted: dict[str, str] = {}
                    for name, field_name in _VIRTUAL_RESPONSE_FIELDS.items():
                        encrypted = response.get(field_name)
                        if not isinstance(encrypted, str) or not encrypted:
                            raise TachibanaError(ErrorClass.AUTH_RESPONSE_INVALID)
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
                            raise TachibanaError(
                                ErrorClass.AUTH_RESPONSE_INVALID
                            ) from None
                        decrypted[name] = _validate_virtual_url(plaintext, name)
                    self._endpoints = VirtualEndpoints(**decrypted)
                    self.state = SessionState.AVAILABLE
                    self.diagnostics.session_started_at = self._clock()
                    self.diagnostics.health = ProviderHealth.AVAILABLE
                    self.diagnostics.last_error_class = ErrorClass.NONE
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
                    and response.get("sResultCode") == "0"
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
