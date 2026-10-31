"""正規化済みの予測失敗入力を既存の非公開診断保存へ渡す。"""
from datetime import datetime
import hashlib
import json
import re

import argus_market_data_truth as truth


MAX_OBSERVATIONS = 512
MAX_INPUT_BYTES = 512 * 1024
_REQUEST_FIELDS = frozenset(("instrumentId", "market", "factType", "currency", "required"))


def _request_valid(row):
    if not isinstance(row, dict) or set(row) != _REQUEST_FIELDS:
        return False
    market = row.get("market")
    instrument = row.get("instrumentId")
    return (isinstance(market, str) and market in ("JP", "US", "CRYPTO")
            and isinstance(instrument, str)
            and re.fullmatch(re.escape(market) + r":[A-Z0-9._-]{1,64}", instrument) is not None
            and row.get("factType") == "QUOTE" and row.get("required") is True
            and row.get("currency") == ("JPY" if market == "JP" else "USD"))


def _instant(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def capture(observations, requests, *, decision_at, generated_at, build_identity):
    """All or nothing; no raw source bodies, partial prefix or exception text.

    The caller invokes this only after the real snapshot builder rejected a
    conflicting revision. Its verdict, issuance and source selection are not
    retried or modified. The existing owner boundary and private rejected-run
    store carry this optional diagnostic alongside the rejected snapshot.
    """
    out = {"schemaVersion": "prediction-truth-failure-input-v1", "complete": False}
    if not isinstance(observations, (list, tuple)) or not isinstance(requests, (list, tuple)):
        return {**out, "status": "SEQUENCE_UNAVAILABLE"}
    out.update(observationCount=len(observations), requestCount=len(requests))
    if len(observations) > MAX_OBSERVATIONS or not 1 <= len(requests) <= truth.MAX_SNAPSHOT_REQUESTS:
        return {**out, "status": "COUNT_BOUND_EXCEEDED"}
    if any(not _request_valid(row) for row in requests):
        return {**out, "status": "REQUEST_SHAPE_UNAVAILABLE"}
    decision, generated = _instant(decision_at), _instant(generated_at)
    if (decision is None or generated is None or decision > generated
            or not isinstance(build_identity, str)
            or re.fullmatch(r"[a-f0-9]{40}", build_identity) is None):
        return {**out, "status": "IDENTITY_UNAVAILABLE"}
    try:
        if any(not truth.validate_observation(row)[0] for row in observations):
            return {**out, "status": "OBSERVATION_SHAPE_UNAVAILABLE"}
        body = {"values": observations, "requests": requests, "decision_at": decision_at,
                "generated_at": generated_at, "build_identity": build_identity}
        chunks, size = [], 0
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False)
        for part in encoder.iterencode(body):
            raw = part.encode("utf-8")
            size += len(raw)
            if size > MAX_INPUT_BYTES:
                return {**out, "status": "BYTE_BOUND_EXCEEDED"}
            chunks.append(raw)
        encoded = b"".join(chunks)
        return {**out, "status": "CAPTURED", "complete": True, "inputBytes": len(encoded),
                "inputSha256": hashlib.sha256(encoded).hexdigest(), "input": json.loads(encoded)}
    except (TypeError, ValueError, OverflowError, UnicodeError):
        return {**out, "status": "ENCODING_UNAVAILABLE"}
