"""JP whole-market mover 3-tier waterfall (v10.135): moomoo realtime → Yahoo →
J-Quants EOD. Higher tier wins per symbol; ranked by |move|."""
import scanner


def _capture(monkeypatch):
    """Capture what _record_event is asked to record (symbol, session, source)."""
    rec = []
    def fake_record(market, symbol, trig, now, session, bucket_minutes=1440, source=None):
        rec.append({"symbol": symbol, "session": session, "source": source})
        return {"symbol": symbol}
    monkeypatch.setattr(scanner, "_record_event", fake_record)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_MARKET_MOVER_NOTIFY_MAX", 10)
    # detect_market_mover returns a trigger for any qualifying move
    monkeypatch.setattr(scanner.argus_events, "detect_market_mover",
                        lambda sym, chg, price, **k: [{"type": "MARKET_MOVER", "severity": 4}])
    return rec


def test_open_uses_moomoo_then_yahoo_dedup(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: True)
    # moomoo realtime: 7203 (+12%); yahoo also reports 7203 (+11.5%, delayed) + 9999 (+20%)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers",
                        lambda: [{"symbol": "7203", "changePct": 12.0, "price": 100}])
    monkeypatch.setattr(scanner, "_yahoo_jp_movers",
                        lambda: {"status": "live",
                                 "gainers": [{"symbol": "7203", "changePct": 11.5, "price": 100},
                                             {"symbol": "9999", "changePct": 20.0, "price": 50}],
                                 "losers": []})
    monkeypatch.setattr(scanner, "_jq_market_movers", lambda: {"status": "live", "gainers": [], "losers": []})
    n = scanner._scan_jp_market_movers()
    by = {r["symbol"]: r for r in rec}
    assert "7203" in by and "9999" in by
    assert by["7203"]["source"] == "moomoo-rt"      # moomoo wins the dup
    assert by["7203"]["session"] == "JP_RT"
    assert by["9999"]["source"] == "yahoo-jp"        # yahoo fills the broader market
    # ranked by |move|: 9999 (20) before 7203 (12)
    assert rec[0]["symbol"] == "9999"


def test_closed_uses_jquants_not_yahoo(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(scanner, "_jp_market_open", lambda *a, **k: False)
    monkeypatch.setattr(scanner, "_moomoo_jp_movers", lambda: [])   # bridge idle after close
    monkeypatch.setattr(scanner, "_jq_market_movers",
                        lambda: {"status": "live",
                                 "gainers": [{"symbol": "6758", "changePct": 9.0, "price": 200}], "losers": []})
    # yahoo must NOT be consulted when closed
    def _boom(): raise AssertionError("yahoo should not be called when closed")
    monkeypatch.setattr(scanner, "_yahoo_jp_movers", _boom)
    n = scanner._scan_jp_market_movers()
    assert n == 1 and rec[0]["symbol"] == "6758" and rec[0]["source"] == "jquants-eod"
