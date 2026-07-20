"""v11.9.1 — translation cache is deploy-proof and drains 24/365.

Owner report: 「ニュースが全部翻訳待ち」. Two roots: (1) the only translate cron
lived in the weekday-only watchtower → weekends never drained; (2) the JA cache
was /tmp-only → every Render deploy wiped ALL past translations. This file
locks in the ledger restore stage + the public-safe snapshot artifact.
"""
import json

import scanner


class _LedgerResp:
    status_code = 200
    text = json.dumps({"schemaVersion": "news-ja-cache-v1",
                       "cache": {"h1": {"ja": "テスト見出し1", "at": "2026-07-04T09:00:00Z"},
                                 "h2": {"ja": "テスト見出し2", "at": "2026-07-04T09:01:00Z"}},
                       "state": {"lastTranslateAt": "2026-07-04T09:01:00Z"}})


def _fresh_state(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_NEWS_JA_FILE", str(tmp_path / "none.json"))
    scanner._NEWS_JA_STATE["restored"] = False
    scanner._NEWS_JA_STATE["lastTranslateAt"] = None
    scanner._NEWS_JA_CACHE.clear()


def test_restore_falls_back_to_ledger(monkeypatch, tmp_path):
    _fresh_state(monkeypatch, tmp_path)

    class _Req:
        @staticmethod
        def get(url, timeout=None, **kw):
            assert "news-ja/latest.json" in url
            return _LedgerResp()
    monkeypatch.setattr(scanner, "requests", _Req())
    scanner._news_ja_restore_once()
    assert scanner._NEWS_JA_CACHE["h1"]["ja"] == "テスト見出し1"
    assert scanner._NEWS_JA_STATE["lastTranslateAt"] == "2026-07-04T09:01:00Z"
    assert "ledger" in scanner._NEWS_JA_STATE["restoredFrom"]


def test_tmp_entries_win_over_ledger(monkeypatch, tmp_path):
    _fresh_state(monkeypatch, tmp_path)
    f = tmp_path / "ja.json"
    f.write_text(json.dumps({"cache": {"h1": {"ja": "新しい方", "at": "2026-07-04T10:00:00Z"}}}))
    monkeypatch.setattr(scanner, "_NEWS_JA_FILE", str(f))

    class _Req:
        @staticmethod
        def get(url, timeout=None, **kw):
            return _LedgerResp()
    monkeypatch.setattr(scanner, "requests", _Req())
    scanner._news_ja_restore_once()
    assert scanner._NEWS_JA_CACHE["h1"]["ja"] == "新しい方"     # /tmp wins
    assert scanner._NEWS_JA_CACHE["h2"]["ja"] == "テスト見出し2"  # ledger fills gaps


def test_restore_survives_ledger_outage(monkeypatch, tmp_path):
    _fresh_state(monkeypatch, tmp_path)

    class _Req:
        @staticmethod
        def get(url, timeout=None, **kw):
            raise OSError("network down")
    monkeypatch.setattr(scanner, "requests", _Req())
    scanner._news_ja_restore_once()            # must not raise
    assert scanner._NEWS_JA_STATE["restoredFrom"] == ["empty"]


def test_ja_cache_snapshot_public_safe(monkeypatch, tmp_path):
    _fresh_state(monkeypatch, tmp_path)
    scanner._NEWS_JA_STATE["restored"] = True
    scanner._NEWS_JA_CACHE.update({f"h{i}": {"ja": f"見出し{i}", "at": f"2026-07-04T0{i%10}:00:00Z"}
                                   for i in range(5)})
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/news/ja-cache-snapshot")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "news-ja-cache-v1"
        assert d["count"] == 5 and len(d["cache"]) == 5
        blob = json.dumps(d, ensure_ascii=False).lower()
        for banned in ("token", "secret", "hmac", "apikey", "passphrase",
                       "quantity", "averagecost"):
            assert banned not in blob, banned


def test_ja_cache_snapshot_bounded(monkeypatch, tmp_path):
    _fresh_state(monkeypatch, tmp_path)
    scanner._NEWS_JA_STATE["restored"] = True
    scanner._NEWS_JA_CACHE.update({f"x{i}": {"ja": f"t{i}", "at": f"2026-07-04T00:00:{i:02d}Z"}
                                   for i in range(1500)})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/news/ja-cache-snapshot").get_json()
        assert d["count"] == 1200                    # newest ~1200, bounded


def test_caos_scan_workflow_has_247_drain_and_persist():
    y = open(".github/workflows/caos-scan.yml", encoding="utf-8").read()
    assert "'7,37 * * * *'" in y                     # still 30min, 24/365
    assert "translate-visible" in y                  # drains every run
    assert "ja-cache-snapshot" in y and "ledger/news-ja" in y
    assert "never overwrite the ledger with an empty cache" in y
