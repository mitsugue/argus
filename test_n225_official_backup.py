"""2026-10-27 (owner): the Nikkei official daily CSV backs up Yahoo's Nikkei 225
bars. Yahoo stays first; the file fills only sessions Yahoo did not return."""
from datetime import datetime

import pytz

import scanner

CSV = ("データ日付,終値,始値,高値,安値\n"
       '"2026/10/23","62693.16","62900.00","63100.00","62500.00"\n'
       '"2026/10/26","62189.65","62449.96","62902.95","62094.34"\n'
       '"2026/10/27","63268.37","62569.08","63684.69","62389.47"\n'
       '"本資料は日経の著作物であり、無断で複写することができません。"\n').encode("shift_jis")


def yahoo(day, close):
    return {"instrumentId": "NIKKEI_225_INDEX", "date": day, "open": close, "high": close + 10, "low": close - 10,
            "close": close, "volume": 0.0, "availableFrom": day + "T07:00:00Z", "adjusted": False,
            "sourceRef": "yahoo:chart:^N225"}


def test_parse_keeps_complete_final_sessions_only():
    before_close = datetime(2026, 10, 27, 6, 10, tzinfo=pytz.utc)        # 15:10 JST
    rows = scanner._n225_official_parse(CSV, available_hour_utc=7, now_utc=before_close)
    assert [r["date"] for r in rows] == ["2026-10-23", "2026-10-26"]
    assert rows[-1] == {**rows[-1], "open": 62449.96, "high": 62902.95, "low": 62094.34, "close": 62189.65,
                        "volume": 0.0, "sourceRef": "nikkei:official-daily-csv", "availableFrom": "2026-10-26T07:00:00Z"}
    evening = datetime(2026, 10, 27, 8, 0, tzinfo=pytz.utc)               # 17:00 JST
    assert scanner._n225_official_parse(CSV, available_hour_utc=7, now_utc=evening)[-1]["date"] == "2026-10-27"


def test_yahoo_first_and_the_file_fills_only_what_is_missing(monkeypatch):
    evening = datetime(2026, 10, 27, 8, 0, tzinfo=pytz.utc)
    official = scanner._n225_official_parse(CSV, available_hour_utc=7, now_utc=evening)
    monkeypatch.setattr(scanner, "_n225_official_rows", lambda hour: official)
    held = [yahoo("2026-10-23", 62700.0), yahoo("2026-10-26", 62190.0)]
    # Yahoo returned through 10/26: only 10/27 comes from the file, Yahoo's own bars stay.
    rows, added = scanner._n225_with_official_backup(held, None, 7)
    assert added == 1 and [r["sourceRef"] for r in rows] == ["yahoo:chart:^N225"] * 2 + ["nikkei:official-daily-csv"]
    assert rows[1]["close"] == 62190.0
    # Yahoo failed this time: the cached history plus the missing sessions.
    rows, added = scanner._n225_with_official_backup([], {"data": held[:1]}, 7)
    assert added == 2 and rows[-1]["date"] == "2026-10-27"
    # Nothing missing: Yahoo's rows unchanged and the file adds nothing.
    full = held + [yahoo("2026-10-27", 63268.0)]
    assert scanner._n225_with_official_backup(full, None, 7) == (full, 0)
