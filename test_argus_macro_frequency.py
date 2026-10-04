import argus_macro_frequency as m


def monthly(levels, start_year=2024, start_month=1):
    rows, year, month = [], start_year, start_month
    for value in levels:
        rows.append({"date": f"{year}-{month:02d}-01", "value": value})
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return rows


def test_cpi_state_uses_only_published_months_and_the_three_month_trend():
    # 2024-01 .. 2026-08: 3 % a year, then 4.3 % in May 2026 falling to 3.7 % in August.
    levels = [100 * (1.03 ** (i / 12)) for i in range(32)]
    rows = monthly(levels)
    year_ago = {r["date"][:7]: r["value"] for r in rows}
    for month, yoy in (("2026-05", 4.3), ("2026-06", 4.1), ("2026-07", 3.9), ("2026-08", 3.7)):
        rows = [r for r in rows if r["date"][:7] != month]
        rows.append({"date": month + "-01", "value": year_ago[f"2025-{month[5:]}"] * (1 + yoy / 100)})
    state = m.cpi_state(rows, today="2026-10-04")
    assert state["month"] == "2026-08" and state["yoyPct"] == 3.7
    assert state["yoyThreeMonthsEarlierPct"] == 4.3 and state["rising"] is False
    assert state["knownFrom"] == "2026-09-20"
    # On 2026-09-19 the August figure was not yet published.
    assert m.cpi_state(rows, today="2026-09-19")["month"] == "2026-07"


def test_facts_name_the_base_rates_and_never_a_probability():
    falling = {"month": "2026-08", "yoyPct": 3.7, "yoyThreeMonthsEarlierPct": 4.3, "rising": False, "knownFrom": "2026-09-20"}
    rising = {**falling, "yoyThreeMonthsEarlierPct": 3.2, "rising": True}
    calm = {**falling, "yoyPct": 2.4}
    text = m.explanation_facts(falling, 18.0)[0]["text"]
    assert "3.7%" in text and "低下中" in text and "15.7%" in text and "11.8%" in text and "確率ではありません" in text
    assert "23.0%" in m.explanation_facts(rising, None)[0]["text"]
    assert "9.4%" in m.explanation_facts(calm, None)[0]["text"]
    assert len(m.explanation_facts(falling, 18.0)) == 1                    # VIX below 25: no VIX line
    vix = m.explanation_facts(None, 27.4)
    assert len(vix) == 1 and "93.5%" in vix[0]["text"] and "75.2%" in vix[0]["text"] and "日経平均には当てはまりません" in vix[0]["text"]
    for fact in m.explanation_facts(rising, 30.0):
        assert fact["source"] == "macro_frequency" and fact["priority"] == "P2"
        assert fact["verification"] == "CORROBORATED" and "第二の点検は未了" in fact["provenance"]["sourceLabelJa"]
        for word in ("買い", "売り", "必ず", "100%"):
            assert word not in fact["text"]
