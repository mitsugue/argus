"""Credential redaction utilities; provider payloads must never reach logs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable


REDACTED = "[REDACTED]"
_KEY_PATTERN = re.compile(
    r"(?i)(sAuthId|auth(?:entication)?[_-]?id|private[_-]?key|"
    r"sUrl(?:Request|Master|Price|Event|EventWebSocket))"
)
_PEM_PATTERN = re.compile(
    r"-----BEGIN [^-]*(?:PRIVATE KEY|RSA PRIVATE KEY)-----.*?"
    r"-----END [^-]*(?:PRIVATE KEY|RSA PRIVATE KEY)-----",
    re.DOTALL,
)
_VIRTUAL_URL_PATTERN = re.compile(
    r"(?i)(?:https|wss)://(?:kabuka|price-kabuka|demo-kabuka)"
    r"\.e-shiten\.jp/[^\s\"'<>]+"
)
_VIRTUAL_PATH_PATTERN = re.compile(
    r"(?i)/e_api_v4r10/(?:request|master|price|event|event_ws)/"
    r"[^/\s\"'<>]+/"
)


class _CredentialLogFilter(logging.Filter):
    """Scrub credential-equivalent virtual paths before handlers see them."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_text(item) if isinstance(item, str) else item
                for item in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_text(item) if isinstance(item, str) else item
                for key, item in record.args.items()
            }
        return True


_CREDENTIAL_LOG_FILTER = _CredentialLogFilter()


def install_transport_log_redaction() -> None:
    """Permanently filter dependency DEBUG logs that can include request paths."""

    # urllib3 logs the request target separately from the host, so a virtual URL
    # can appear as only ``/e_api_v4r10/price/<opaque-token>/``. A permanent
    # filter avoids a process-wide logger-level race between concurrent requests.
    for name in (
        "urllib3.connectionpool",
        "requests.packages.urllib3.connectionpool",
    ):
        logger = logging.getLogger(name)
        if not any(item is _CREDENTIAL_LOG_FILTER for item in logger.filters):
            logger.addFilter(_CREDENTIAL_LOG_FILTER)


def redact_text(value: object, sensitive_values: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in sensitive_values:
        if secret:
            text = text.replace(secret, REDACTED)
    text = _PEM_PATTERN.sub(REDACTED, text)
    text = _VIRTUAL_URL_PATTERN.sub(REDACTED, text)
    text = _VIRTUAL_PATH_PATTERN.sub(REDACTED, text)
    text = re.sub(
        r'(?i)("?(?:sAuthId|auth(?:entication)?[_-]?id|private[_-]?key|'
        r'sUrl(?:Request|Master|Price|Event|EventWebSocket))"?\s*[:=]\s*)'
        r'("[^\"]*"|[^,}\s]+)',
        lambda match: match.group(1) + REDACTED,
        text,
    )
    return text


def redact_structure(value: Any, sensitive_values: Iterable[str] = ()) -> Any:
    secrets = tuple(item for item in sensitive_values if item)
    if isinstance(value, dict):
        return {
            key: (REDACTED if _KEY_PATTERN.search(str(key))
                  else redact_structure(item, secrets))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_structure(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_structure(item, secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def safe_json(value: Any, sensitive_values: Iterable[str] = ()) -> str:
    """Serialize a redacted diagnostic object; never use for provider payload logging."""
    return json.dumps(
        redact_structure(value, sensitive_values),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
