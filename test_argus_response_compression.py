import gzip
import json

import scanner


def _run(payload, *, accept="gzip, deflate, br", **kwargs):
    headers = {"Accept-Encoding": accept} if accept else {}
    with scanner.app.test_request_context("/api/argus/market-brief", headers=headers):
        response = scanner.jsonify(payload)
        for key, value in kwargs.items():
            response.headers[key] = value
        return scanner._compress_large_json(response)


PAYLOAD = {"rows": [{"i": i, "text": "見立て" * 20} for i in range(800)]}


def test_large_json_is_gzipped_only_when_accepted():
    """2026-10-04: the 4.9 MB market brief timed out on the phone. Large JSON
    is compressed for clients that accept gzip; others get the same bytes."""
    plain = _run(PAYLOAD, accept=None)
    assert plain.headers.get("Content-Encoding") is None
    packed = _run(PAYLOAD)
    assert packed.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in packed.headers["Vary"]
    body = packed.get_data()
    assert int(packed.headers["Content-Length"]) == len(body) < len(plain.get_data()) / 5
    assert json.loads(gzip.decompress(body)) == json.loads(plain.get_data())


def test_small_json_etag_and_encoded_bodies_are_left_alone():
    assert _run({"ok": True}).headers.get("Content-Encoding") is None
    assert _run(PAYLOAD, ETag='"abc"').headers.get("Content-Encoding") is None
    assert _run(PAYLOAD, **{"Content-Encoding": "br"}).headers["Content-Encoding"] == "br"
