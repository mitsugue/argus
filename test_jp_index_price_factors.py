"""Official Nikkei 225 price adjustment factors from the owner's file (2026-10-20).

The real file is Nikkei's copyrighted material and is never committed; these
tests use a synthetic list of the same shape."""
from decimal import Decimal

import pytest

import jp_index_contribution
import jp_index_price_factors as paf
import scanner

CODES = [f"{1000 + i:04d}" for i in range(225)]


def csv_text(day="2026/10/07", codes=CODES, factor=lambda i: "1.0" if i % 3 else "2.4", note=True):
    lines = ["対象日付,コード,銘柄名,株価換算係数,業種,セクター"]
    lines += [f'"{day}","{c}","銘柄{i}","{factor(i)}","業種","セクター"' for i, c in enumerate(codes)]
    if note:
        lines.append('"本資料は著作物です。"')
    return "\n".join(lines) + "\n"


def test_the_whole_list_of_one_date_is_read():
    table = paf.parse(csv_text())
    assert table["asOf"] == "2026-10-07" and table["members"] == 225
    assert table["factors"]["1000"] == "2.4" and table["factors"]["1001"] == "1.0"
    assert paf.looks_like(csv_text()) and paf.parse(paf.decode(csv_text().encode("cp932")))["members"] == 225


@pytest.mark.parametrize("text, reason", [
    (csv_text().replace("株価換算係数", "係数", 1), "price_factor_header"),
    (csv_text(codes=CODES[:224]), "price_factor_member_count"),
    (csv_text(codes=CODES[:224] + ["1000"]), "price_factor_duplicate"),
    (csv_text(factor=lambda i: "0" if i == 5 else "1.0"), "price_factor_value"),
    (csv_text(factor=lambda i: "x" if i == 5 else "1.0"), "price_factor_value"),
    (csv_text().replace('"2026/10/07","1005"', '"2026/10/08","1005"'), "price_factor_single_date"),
])
def test_a_damaged_list_is_rejected_whole(text, reason):
    with pytest.raises(ValueError, match=reason):
        paf.parse(text)


def test_official_factors_apply_only_from_their_date_and_for_their_members():
    table = paf.parse(csv_text())
    assert paf.applies(table, start="2026-10-07", members_start=CODES, members_end=CODES)
    assert not paf.applies(table, start="2026-10-06", members_start=CODES, members_end=CODES)
    assert not paf.applies(table, start="2026-10-08", members_start=CODES[:-1] + ["9999"], members_end=CODES)


def test_contributions_with_the_official_factors_sum_to_the_index_move(tmp_path, monkeypatch):
    table = paf.parse(csv_text())
    factors = {c: Decimal(f) for c, f in table["factors"].items()}
    start = {c: 1000 + i for i, c in enumerate(CODES)}
    end = {c: p * (1.02 if i % 2 else 0.99) for i, (c, p) in enumerate(start.items())}
    divisor = Decimal("29.6643584")
    close = lambda prices: float((sum(Decimal(str(prices[c])) * factors[c] for c in CODES) / divisor).quantize(Decimal("0.01")))
    result = jp_index_contribution.period(
        start="2026-10-08", end="2026-10-09", members_start=CODES, members_end=CODES,
        closes={"2026-10-08": start, "2026-10-09": end},
        index_close={"2026-10-08": close(start), "2026-10-09": close(end)},
        derived_factors=table["factors"], factors_as_of=table["asOf"], factor_basis=paf.FACTOR_BASIS)
    assert result["status"] == "AVAILABLE" and result["factorBasis"] == paf.FACTOR_BASIS
    assert result["estimate"] is False and abs(result["residualPoints"]) <= 0.02
    assert abs(result["impliedDivisor"] - float(divisor)) < 1e-4


def test_the_server_reads_the_owner_file_by_content_and_reports_no_values(tmp_path, monkeypatch):
    (tmp_path / "some_other_name.csv").write_bytes(csv_text().encode("cp932"))
    monkeypatch.setattr(scanner, "_NK225_SECRET_DIR", str(tmp_path))
    monkeypatch.setattr(scanner, "_JP_INDEX_OFFICIAL_FACTORS",
                        {"sha256": None, "table": None, "status": "NOT_CONFIGURED", "reason": None})
    monkeypatch.chdir(tmp_path)
    table = scanner._jp_index_official_factors()
    assert table["asOf"] == "2026-10-07" and table["members"] == 225
    status = scanner._jp_index_official_factor_status()
    assert status["status"] == "AVAILABLE" and status["members"] == 225 and "factors" not in status
    assert "銘柄" not in str(status)
    (tmp_path / "some_other_name.csv").write_bytes(csv_text(codes=CODES[:200]).encode("cp932"))
    assert scanner._jp_index_official_factors() is None
    assert scanner._jp_index_official_factor_status()["status"] in ("INVALID", "NOT_CONFIGURED")
