"""Bind an existing BLS HTTP receipt to parsed metrics, without publication claims.

No IO, response bodies, request headers, keys, or event-time substitutions are
stored here. requests.content contains decoded HTTP response body bytes, not
transport wire bytes. Its hash and the canonical parsed-response hash identify
different evidence. A hash alone does not prove retained original bytes.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re

BLS_API = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class FetchResult(tuple):
    """Keep the original two-value fetch contract; add optional receipt metadata."""
    def __new__(cls, raw, status, evidence):
        instance = super().__new__(cls, (raw, status))
        instance.receipt = deepcopy(evidence)
        return instance


def receipt(raw_bytes, parsed, *, received_at, response_url, status, redirected):
    if (not isinstance(raw_bytes, bytes) or not raw_bytes
            or len(raw_bytes) > MAX_RESPONSE_BYTES or status != 200
            or isinstance(status, bool) or redirected is not False
            or response_url != BLS_API):
        raise ValueError('original_http_receipt_invalid')
    at = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('receipt_timezone_required')
    decoded = json.loads(raw_bytes)
    if not isinstance(parsed, dict) or decoded != parsed:
        raise ValueError('http_parsed_input_mismatch')
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode()
    return {'schemaVersion': 'macro-http-response-receipt-v1',
            'sourceRef': BLS_API, 'httpStatus': 200, 'receivedAt': received_at,
            'availableFrom': received_at, 'responseBytes': len(raw_bytes),
            'rawHttpResponseSha256': hashlib.sha256(raw_bytes).hexdigest(),
            'parsedResponseSha256': hashlib.sha256(canonical).hexdigest(),
            'timeBasis': 'OBSERVED_RESPONSE_RECEIPT_NOT_PUBLICATION',
            'rawHttpBodyRetained': False, 'actualPublicationTimeVerified': False,
            'historicalVintageVerified': False}


def bind(actual, evidence):
    """Attach metadata only to metrics from the same parsed response and receipt.

    Invalid optional metadata cannot erase an already parsed result. It also
    cannot populate eventTimeEvidence or turn a schedule into publication proof.
    """
    out = deepcopy(actual)
    if not isinstance(evidence, dict) or actual.get('available') is not True:
        return out
    if (evidence.get('parsedResponseSha256') != actual.get('sourceResponseSha256')
            or evidence.get('receivedAt') != actual.get('receivedAt')
            or evidence.get('availableFrom') != actual.get('availableFrom')
            or evidence.get('sourceRef') != BLS_API
            or evidence.get('actualPublicationTimeVerified') is not False
            or evidence.get('historicalVintageVerified') is not False):
        return out
    # An allow-list prevents caller additions from carrying protected contents.
    keys = ('schemaVersion', 'sourceRef', 'httpStatus', 'receivedAt', 'availableFrom',
            'responseBytes', 'rawHttpResponseSha256', 'parsedResponseSha256',
            'timeBasis', 'rawHttpBodyRetained', 'actualPublicationTimeVerified',
            'historicalVintageVerified')
    if (any(key not in evidence for key in keys)
            or evidence['schemaVersion'] != 'macro-http-response-receipt-v1'
            or evidence['timeBasis'] != 'OBSERVED_RESPONSE_RECEIPT_NOT_PUBLICATION'
            or evidence['httpStatus'] != 200 or isinstance(evidence['httpStatus'], bool)
            or not isinstance(evidence['responseBytes'], int)
            or isinstance(evidence['responseBytes'], bool)
            or not 0 < evidence['responseBytes'] <= MAX_RESPONSE_BYTES
            or evidence['rawHttpBodyRetained'] is not False
            or any(not isinstance(evidence[key], str) or not re.fullmatch('[0-9a-f]{64}', evidence[key])
                   for key in ('rawHttpResponseSha256', 'parsedResponseSha256'))):
        return out
    out['sourceHttpReceipt'] = {key: deepcopy(evidence[key]) for key in keys}
    return out
