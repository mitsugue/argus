"""Ex-dividend drop estimate: arithmetic on the J-Quants forecast fields (shape confirmed on production 2026-10-03)."""
from datetime import date

import argus_ex_dividend as ex


def row(**kw):
    base = {"Code": "72030", "CurPerType": "1Q", "CurFYEn": "2027-03-31", "DiscDate": "2026-08-07", "DocType": "1QFinancialStatements_Consolidated_JP",
            "FDiv1Q": "", "FDiv2Q": "40.0", "FDiv3Q": "", "FDivFY": "50.0", "FDivAnn": "90.0"}
    return {**base, **kw}


def test_the_field_follows_the_record_month_and_the_fiscal_year_end():
    r = row()
    assert ex.applicable_dividend(r, date(2026, 9, 30)) == 40.0      # interim: 6 months before the March year end
    assert ex.applicable_dividend(r, date(2027, 3, 31)) == 50.0      # year end
    assert ex.applicable_dividend(r, date(2026, 12, 31)) is None     # 3Q empty: unknown, not zero
    assert ex.applicable_dividend(r, date(2026, 6, 30)) is None      # before this fiscal year's interim
    # A second-quarter disclosure has no interim forecast left; its year-end forecast still applies.
    q2 = row(CurPerType="2Q", FDiv2Q="", FDivFY="55.0")
    assert ex.applicable_dividend(q2, date(2026, 9, 30)) is None and ex.applicable_dividend(q2, date(2027, 3, 31)) == 55.0
    # A full-year disclosure forecasts the NEXT fiscal year: CurFYEn is the year just reported.
    fy = row(CurPerType="FY", CurFYEn="2026-03-31", DiscDate="2026-05-13", FDiv2Q="30.0", FDivFY="35.0", NxFDiv2Q="33.0", NxFDivFY="38.0")
    assert ex.applicable_dividend(fy, date(2026, 9, 30)) == 30.0     # FY ending 2027-03 interim
    assert ex.applicable_dividend(fy, date(2027, 3, 31)) == 35.0
    assert ex.applicable_dividend(fy, date(2027, 9, 30)) == 33.0     # the year after, from Nx*
    assert ex.applicable_dividend(fy, date(2028, 3, 31)) == 38.0
    # A December year end: the interim record is end of June, the year-end record end of December.
    dec = row(CurFYEn="2026-12-31", FDiv2Q="20.0", FDivFY="25.0")
    assert ex.applicable_dividend(dec, date(2026, 6, 30)) == 20.0 and ex.applicable_dividend(dec, date(2026, 12, 31)) == 25.0
    assert ex.applicable_dividend(row(CurFYEn=None), date(2026, 9, 30)) is None
    assert ex.applicable_dividend(row(FDiv2Q="0.0"), date(2026, 9, 30)) == 0.0     # an explicit zero is a forecast


def test_latest_disclosure_wins_per_code():
    rows = [row(DiscDate="2026-05-13", FDiv2Q="30.0"), row(DiscDate="2026-08-07", FDiv2Q="40.0"),
            row(Code="67580", DiscDate="2026-08-01", FDiv2Q="10.0"), {"Code": "1", "DiscDate": "2026-08-01"}, {"Code": "99990"}]
    latest = ex.latest_disclosures(rows)
    assert set(latest) == {"7203", "6758"} and latest["7203"]["FDiv2Q"] == "40.0"


def test_the_drop_is_the_yield_on_the_index_own_weights_and_reports_coverage():
    # Two members, factors 1 and 0.5. P*f = 3000 and 1000. D*f = 40 and 10 → yield 50/4000 = 1.25%.
    factors = {"7203": 1.0, "6758": 0.5, "9984": 1.0}
    closes = {"7203": 3000.0, "6758": 2000.0, "9984": 500.0}
    disclosures = {"7203": row(FDiv2Q="40.0"), "6758": row(Code="67580", FDiv2Q="20.0")}
    out = ex.estimate(record_day=date(2026, 9, 30), factors=factors, closes=closes, disclosures=disclosures, index_close=60000.0)
    assert out["membersCovered"] == 2 and out["membersMissing"] == 1
    assert out["dropPct"] == 1.25 and out["dropYen"] == 750.0
    assert abs(out["coveredPriceWeightShare"] - 4000 / 4500) < 1e-3 and out["actionAuthority"] is False
    # Too little coverage: no number, the reason is stated.
    low = ex.estimate(record_day=date(2026, 9, 30), factors=factors, closes=closes, disclosures={"9984": row(Code="99840", FDiv2Q="5.0")}, index_close=60000.0)
    assert low["dropYen"] is None and low["reason"] == "covered_share_too_low"
    # A member that pays nothing counts as covered (explicit zero) and lowers the yield.
    zero = ex.estimate(record_day=date(2026, 9, 30), factors={"7203": 1.0}, closes={"7203": 3000.0},
                       disclosures={"7203": row(FDiv2Q="0.0")}, index_close=60000.0)
    assert zero["dropYen"] == 0.0 and zero["membersZero"] == 1


def test_record_days_are_the_next_quarter_ends():
    assert ex.next_record_days(date(2026, 10, 3)) == [date(2026, 12, 31), date(2027, 3, 31), date(2027, 6, 30), date(2027, 9, 30), date(2027, 12, 31)]
    assert ex.next_record_days(date(2026, 12, 31))[0] == date(2026, 12, 31)
