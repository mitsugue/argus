"""Fail-closed configuration for the Tachibana live sensor."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


PRODUCTION_AUTH_ENDPOINT = "https://kabuka.e-shiten.jp/e_api_v4r10/auth/"
DEMO_AUTH_ENDPOINT = "https://demo-kabuka.e-shiten.jp/e_api_v4r10/auth/"
_AUTH_ENDPOINTS = frozenset({PRODUCTION_AUTH_ENDPOINT, DEMO_AUTH_ENDPOINT})


def _boolean(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("invalid_boolean_configuration")


def _integer(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_integer_configuration") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError("configuration_out_of_bounds")
    return parsed


@dataclass(frozen=True)
class TachibanaConfig:
    """Configuration contains secret *paths*, never secret values."""

    enabled: bool = False
    shadow_only: bool = True
    authoritative: bool = False
    auth_endpoint: str = PRODUCTION_AUTH_ENDPOINT
    auth_id_path: Path = Path("~/.argus/secrets/tachibana/e_api_authid.txt")
    private_key_path: Path = Path("~/.argus/secrets/tachibana/e_api_private_key.pem")
    max_symbols: int = 32
    max_requests_per_minute: int = 30
    request_timeout_seconds: int = 8
    max_read_attempts: int = 2
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 60
    rolling_window_size: int = 120
    rolling_window_seconds: int = 300
    fresh_for_seconds: int = 15
    websocket_enabled: bool = False
    max_event_reconnects_per_day: int = 10

    def __post_init__(self) -> None:
        # Dataclass construction is also a supported configuration path.  Keep
        # its path semantics identical to ``from_env`` so a literal ``~`` can
        # never silently become a relative directory name.
        object.__setattr__(self, "auth_id_path", Path(self.auth_id_path).expanduser())
        object.__setattr__(
            self, "private_key_path", Path(self.private_key_path).expanduser()
        )
        if any(type(value) is not bool for value in (
            self.enabled, self.shadow_only, self.authoritative,
            self.websocket_enabled,
        )):
            raise ValueError("invalid_boolean_configuration")
        if self.authoritative:
            raise ValueError("tachibana_authority_is_not_permitted_in_phase_1")
        if not self.shadow_only:
            raise ValueError("tachibana_must_remain_shadow_only_in_phase_1")
        if (
            not isinstance(self.auth_endpoint, str)
            or self.auth_endpoint not in _AUTH_ENDPOINTS
        ):
            raise ValueError("unapproved_tachibana_auth_endpoint")
        bounded = {
            "max_symbols": (self.max_symbols, 1, 64),
            "max_requests_per_minute": (self.max_requests_per_minute, 1, 60),
            "request_timeout_seconds": (self.request_timeout_seconds, 2, 30),
            "max_read_attempts": (self.max_read_attempts, 1, 2),
            "circuit_failure_threshold": (self.circuit_failure_threshold, 1, 10),
            "circuit_cooldown_seconds": (self.circuit_cooldown_seconds, 10, 900),
            "rolling_window_size": (self.rolling_window_size, 2, 600),
            "rolling_window_seconds": (self.rolling_window_seconds, 30, 3600),
            "fresh_for_seconds": (self.fresh_for_seconds, 1, 60),
            "max_event_reconnects_per_day": (
                self.max_event_reconnects_per_day, 1, 10,
            ),
        }
        if any(type(value) is not int or not minimum <= value <= maximum
               for value, minimum, maximum in bounded.values()):
            raise ValueError("tachibana_configuration_out_of_bounds")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "TachibanaConfig":
        env = os.environ if environ is None else environ
        return cls(
            enabled=_boolean(env.get("ARGUS_TACHIBANA_ENABLED"), False),
            shadow_only=_boolean(env.get("ARGUS_TACHIBANA_SHADOW_ONLY"), True),
            authoritative=_boolean(env.get("ARGUS_TACHIBANA_AUTHORITATIVE"), False),
            auth_endpoint=env.get(
                "ARGUS_TACHIBANA_AUTH_ENDPOINT", PRODUCTION_AUTH_ENDPOINT
            ).strip(),
            auth_id_path=Path(env.get(
                "ARGUS_TACHIBANA_AUTH_ID_PATH",
                "~/.argus/secrets/tachibana/e_api_authid.txt",
            )).expanduser(),
            private_key_path=Path(env.get(
                "ARGUS_TACHIBANA_PRIVATE_KEY_PATH",
                "~/.argus/secrets/tachibana/e_api_private_key.pem",
            )).expanduser(),
            max_symbols=_integer(env.get("ARGUS_TACHIBANA_MAX_SYMBOLS"), 32,
                                 minimum=1, maximum=64),
            max_requests_per_minute=_integer(
                env.get("ARGUS_TACHIBANA_REQUESTS_PER_MINUTE"), 30,
                minimum=1, maximum=60,
            ),
            request_timeout_seconds=_integer(
                env.get("ARGUS_TACHIBANA_TIMEOUT_SECONDS"), 8,
                minimum=2, maximum=30,
            ),
            max_read_attempts=_integer(
                env.get("ARGUS_TACHIBANA_MAX_READ_ATTEMPTS"), 2,
                minimum=1, maximum=2,
            ),
            circuit_failure_threshold=_integer(
                env.get("ARGUS_TACHIBANA_CIRCUIT_FAILURES"), 3,
                minimum=1, maximum=10,
            ),
            circuit_cooldown_seconds=_integer(
                env.get("ARGUS_TACHIBANA_CIRCUIT_COOLDOWN_SECONDS"), 60,
                minimum=10, maximum=900,
            ),
            rolling_window_size=_integer(
                env.get("ARGUS_TACHIBANA_WINDOW_SIZE"), 120,
                minimum=2, maximum=600,
            ),
            rolling_window_seconds=_integer(
                env.get("ARGUS_TACHIBANA_WINDOW_SECONDS"), 300,
                minimum=30, maximum=3600,
            ),
            fresh_for_seconds=_integer(
                env.get("ARGUS_TACHIBANA_FRESH_SECONDS"), 15,
                minimum=1, maximum=60,
            ),
            websocket_enabled=_boolean(
                env.get("ARGUS_TACHIBANA_WEBSOCKET_ENABLED"), False
            ),
            max_event_reconnects_per_day=_integer(
                env.get("ARGUS_TACHIBANA_EVENT_RECONNECTS_PER_DAY"), 10,
                minimum=1, maximum=10,
            ),
        )
