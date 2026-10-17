"""MARKET_MOVER push timing gate (v10.133): only push while the market trades."""
import scanner


def test_jp_mover_suppressed_when_closed(monkeypatch):
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)
    assert scanner._mover_push_allowed("JP") is False


def test_jp_mover_allowed_when_open(monkeypatch):
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    assert scanner._mover_push_allowed("JP") is True


def test_us_mover_follows_us_session(monkeypatch):
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: False)
    assert scanner._mover_push_allowed("US") is False
    monkeypatch.setattr(scanner, "_us_market_open", lambda *a, **k: True)
    assert scanner._mover_push_allowed("US") is True


def test_crypto_always_allowed():
    assert scanner._mover_push_allowed("CRYPTO") is True
    assert scanner._mover_push_allowed(None) is True
