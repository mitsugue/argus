"""原本のSHA-256全検査を保ち、入力の分割だけを検査する。"""
import hashlib
from types import SimpleNamespace
import pytest
import argus_earnings_history as history


@pytest.mark.parametrize('size', [0, 1, 2047, 2048, 4094, 65537, 1024*1024+1])
def test_all_bytes_match_standard_sha256_and_one_byte_change_is_detected(size):
    raw = bytes((i*17+3)%256 for i in range(size))
    assert history._receipt_sha256(raw).digest() == hashlib.sha256(raw).digest()
    assert history._receipt_sha256(raw).hexdigest() == hashlib.sha256(raw).hexdigest()
    if size:
        changed = raw[:-1]+bytes([raw[-1]^1])
        assert history._receipt_sha256(changed).digest() != hashlib.sha256(raw).digest()


def test_constructor_and_updates_consume_every_byte_without_large_forced_handoffs(monkeypatch):
    raw = bytes(range(256))*37
    expected = hashlib.sha256(raw).hexdigest()
    parts = []
    original = hashlib.sha256
    class Observed:
        def __init__(self, first=b''):
            parts.append(bytes(first));self.hash=original(first)
        def update(self, part):
            parts.append(bytes(part));self.hash.update(part)
        def hexdigest(self):return self.hash.hexdigest()
    monkeypatch.setattr(history, 'hashlib', SimpleNamespace(sha256=Observed))
    assert history._receipt_sha256(raw).hexdigest() == expected
    assert b''.join(parts) == raw
    assert all(len(part)<=2047 for part in parts)
