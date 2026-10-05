#!/usr/bin/env python3
"""Weekly JPX two-market margin balance (信用取引現在高) → Market Ledger rows.

v13.5.65 (stabilization item 5). The committed CSV
`ops/imports/jpx_two_market_credit_20020802_20260710.csv` ends on 2026-07-10;
later weeks were meant to arrive through `/api/argus/admin/market-ledger/import`
but nothing produced them, so the conditioning engine's 45-day window dropped
the credit features (信用倍率 / 売り残高) from every forecast after August 24.

This tool fetches the official weekly workbook for each Friday after `--since`
(`https://www.jpx.co.jp/markets/statistics-equities/margin/tvdivq0000001rk9-att/
mtseisanYYYYMMDD00.xls`), reads the two-market TOTAL value columns (委託+自己,
金額, 百万円 → JPY) exactly as the committed CSV does, and emits rows in the
ledger's CSV contract. With `--import` it posts them to the admin import route
(dry run, then commit) and reads the ledger back. Weeks whose workbook is not
published (404) are reported as gaps, never filled.

New imports use the actual successful fetch time as availableFrom. The
publication time is not guessed from the week end. Stored observations retain
their original availability and are never rewritten by this collector.
The format from 2026-09-25 is XLSX; older weeks retain the XLS adapter.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import zipfile
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

URL_TEMPLATE = ("https://www.jpx.co.jp/markets/statistics-equities/margin/"
                "tvdivq0000001rk9-att/mtseisan{ymd}00.xls")
NEW_FORMAT_FROM = "2026-09-25"
NEW_URL_TEMPLATE = ("https://www.jpx.co.jp/markets/statistics-equities/margin/"
                    "tvdivq0000001rk9-att/{ymd}_mtcurrent.xlsx")
MAX_WORKBOOK_BYTES = 4 * 1024 * 1024
CSV_COLUMNS = ("seriesId", "periodEnd", "publishedAt", "availableFrom",
               "observedAt", "value", "unit", "source", "sourceKind", "status")
SERIES = {"short": "credit.short_balance", "long": "credit.long_balance"}
MILLION = 1_000_000
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TITLE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def fridays_after(since: str, today: Optional[date] = None) -> List[str]:
    start = date.fromisoformat(since)
    end = today or datetime.now(timezone(timedelta(hours=9))).date()
    if start > end or (end - start).days > 2 * 366:
        raise ValueError("jpx_period_range_invalid")
    out: List[str] = []
    day = start + timedelta(days=1)
    while day <= end:
        if day.weekday() == 4:
            # A closed Friday uses the week's last actual TSE session.
            import argus_market_clock as clock
            period = day
            try:
                while period.weekday() > 0 and not clock.canonical_trading_day(clock.JP_EQUITY, period):
                    period -= timedelta(days=1)
                if not clock.canonical_trading_day(clock.JP_EQUITY, period):
                    day += timedelta(days=1)
                    continue
            except clock.CalendarUnavailableError:
                period = day  # Never invent a holiday outside known coverage.
            if period > start:
                out.append(period.isoformat())
        day += timedelta(days=1)
    return out


def parse_sheet(grid: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """Pure: the two-market TOTAL value row of the JPX weekly layout.

    grid[r][c] are cell values. The title row carries the period date; the
    header row containing 「合計」 fixes the column of the total block whose
    first two value columns are 売残高 (sales) and 買残高 (purchases) with a
    weekly-change column between them; the 二市場計 block has a 株数 row and
    a 金額 row (百万円)."""
    text = [[str(cell if cell is not None else "") for cell in row] for row in grid]
    period = None
    for row in text[:3]:
        for cell in row:
            match = TITLE_RE.search(cell)
            if match:
                period = date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
                break
        if period:
            break
    if not period:
        raise ValueError("jpx_period_not_found")
    if any("Total Outstanding Margin Trading" in cell for row in text for cell in row):
        return parse_current_sheet(grid, text, period)
    total_col = None
    for row in text:
        for index, cell in enumerate(row):
            if "合" in cell and "計" in cell and "Total" in cell:
                total_col = index
                break
        if total_col is not None:
            break
    if total_col is None:
        raise ValueError("jpx_total_column_not_found")
    value_row = None
    for index, row in enumerate(text):
        if any("二市場計" in cell for cell in row):
            for candidate in range(index, min(index + 3, len(text))):
                if any("金額" in cell for cell in text[candidate]):
                    value_row = candidate
                    break
            break
    if value_row is None:
        raise ValueError("jpx_value_row_not_found")

    def number(cell: Any) -> float:
        value = float(str(cell).replace(",", "").replace("▲", "-").strip())
        if not math.isfinite(value) or value <= 0:
            raise ValueError("jpx_non_positive_value")
        return value

    short_million = number(grid[value_row][total_col])
    long_million = number(grid[value_row][total_col + 2])
    return {"periodEnd": period,
            "shortJpy": int(round(short_million * MILLION)),
            "longJpy": int(round(long_million * MILLION))}


def parse_current_sheet(grid, text, period):
    """Read two-market amounts, never the separate Tokyo or share columns."""
    market_cols = [i for row in text[:8] for i, cell in enumerate(row)
                   if "Tokyo&Nagoya" in cell and "二市場" in cell]
    if len(market_cols) != 1:
        raise ValueError("jpx_two_market_column_not_found")
    col = market_cols[0]
    headers = text[6] if len(text) > 6 else []
    if len(headers) <= col + 2 or "Sales" not in headers[col] or "Purchases" not in headers[col + 2]:
        raise ValueError("jpx_amount_columns_not_found")
    total_rows = [i for i, row in enumerate(text)
                  if any("Total Outstanding Margin Trading" in cell for cell in row)]
    if len(total_rows) != 1:
        raise ValueError("jpx_total_row_not_found")
    row = total_rows[0] + 1
    if row >= len(text) or not any("金額" in cell and "Val." in cell for cell in text[row]):
        raise ValueError("jpx_total_amount_row_not_found")
    if not any("百万円" in cell for cells in text[:6] for cell in cells):
        raise ValueError("jpx_amount_unit_not_found")
    values = []
    for c in (col, col + 2):
        value = float(grid[row][c])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("jpx_non_positive_value")
        values.append(int(round(value * MILLION)))
    return {"periodEnd": period, "shortJpy": values[0], "longJpy": values[1]}


def load_workbook_grid(payload: bytes) -> List[List[Any]]:
    if len(payload) > MAX_WORKBOOK_BYTES:
        raise ValueError("jpx_workbook_too_large")
    if payload.startswith(b"PK"):
        # The spreadsheet library is loaded only by this scheduled tool.
        import openpyxl
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if len(archive.infolist()) > 100 or sum(x.file_size for x in archive.infolist()) > 16 * 1024 * 1024:
                raise ValueError("jpx_workbook_too_large")
        book = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        try:
            sheet = book.worksheets[0]
            if sheet.max_row > 200 or sheet.max_column > 64:
                raise ValueError("jpx_workbook_shape_changed")
            return [[cell.strftime("%Y/%m/%d") if isinstance(cell, (date, datetime)) else cell
                     for cell in row] for row in sheet.iter_rows(values_only=True)]
        finally:
            book.close()
    import xlrd
    if payload.lstrip().lower().startswith((b"<!doc", b"<html")):
        raise ValueError("jpx_not_a_workbook")
    book = xlrd.open_workbook(file_contents=payload)
    sheet = book.sheet_by_index(0)
    if sheet.nrows > 200 or sheet.ncols > 64:
        raise ValueError("jpx_workbook_shape_changed")
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]


def build_rows(parsed: Dict[str, Any], *, url: str, sha256: str,
               observed_at: str) -> List[Dict[str, Any]]:
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.date() < date.fromisoformat(parsed["periodEnd"]):
        raise ValueError("jpx_invalid_fetch_time")
    stamp = observed_at
    source = (f"JPX official | {url} | sha256={sha256} | "
              "publication=weekly_final | availability=successful_fetch")
    return [{
        "seriesId": SERIES[key], "periodEnd": parsed["periodEnd"],
        "publishedAt": "", "availableFrom": stamp, "observedAt": observed_at,
        "value": parsed["shortJpy"] if key == "short" else parsed["longJpy"],
        "unit": "JPY", "source": source, "sourceKind": "official", "status": "live",
    } for key in ("short", "long")]


def rows_to_csv(rows: Iterable[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
    return buffer.getvalue()


def fetch(url: str, timeout: int = 60) -> Optional[bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ARGUS jpx-credit-weekly)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_WORKBOOK_BYTES + 1)
            if len(payload) > MAX_WORKBOOK_BYTES:
                raise ValueError("jpx_workbook_too_large")
            return payload
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def collect(since: str, *, today: Optional[date] = None,
            fetcher=fetch, now_iso: Optional[str] = None) -> Dict[str, Any]:
    observed = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: List[Dict[str, Any]] = []
    gaps: List[str] = []
    fetched: List[str] = []
    for friday in fridays_after(since, today):
        template = NEW_URL_TEMPLATE if friday >= NEW_FORMAT_FROM else URL_TEMPLATE
        url = template.format(ymd=friday.replace("-", ""))
        payload = fetcher(url)
        if payload is None:
            gaps.append(friday)
            continue
        try:
            parsed = parse_sheet(load_workbook_grid(payload))
        except ValueError as error:
            gaps.append(f"{friday}:{error}")
            continue
        if parsed["periodEnd"] != friday:
            gaps.append(f"{friday}:period_mismatch:{parsed['periodEnd']}")
            continue
        observed = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.extend(build_rows(parsed, url=url, sha256=hashlib.sha256(payload).hexdigest(),
                               observed_at=observed))
        fetched.append(friday)
    return {"since": since, "fetched": fetched, "gaps": gaps, "rows": rows,
            "csv": rows_to_csv(rows), "observedAt": observed}


def post_json(url: str, body: Dict[str, Any], token: str, timeout: int = 600) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "X-ARGUS-ADMIN-TOKEN": token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def import_rows(csv_text: str, *, backend: str, token: str,
                expected_newest: Optional[str] = None) -> Dict[str, Any]:
    """Dry run, commit, read back. The commit rebuilds the ledger and can
    outlive the proxy's response window (2026-09-08: the rows landed but the
    client saw a transport error) — so a transport error on the commit is
    settled by the read-back: the import is a success when the ledger now
    holds the newest period we sent, and a failure otherwise."""
    endpoint = backend.rstrip("/") + "/api/argus/admin/market-ledger/import"
    dry = post_json(endpoint, {"csv": csv_text, "dryRun": True}, token)
    if not dry.get("ok") or dry.get("errors"):
        return {"ok": False, "stage": "dry_run", "errors": (dry.get("errors") or [])[:5]}
    try:
        commit = post_json(endpoint, {"csv": csv_text, "dryRun": False}, token)
    except Exception as error:                     # transport only; verified below
        commit = {"ok": None, "transportError": type(error).__name__}
    if commit.get("ok") is False or commit.get("errors"):
        return {"ok": False, "stage": "commit", "errors": (commit.get("errors") or [])[:5]}
    readback = ledger_newest_credit(backend, token=token)
    held = min((str(readback.get(sid, {}).get("periodEnd") or "") for sid in SERIES.values()), default="")
    if expected_newest and held < expected_newest:
        return {"ok": False, "stage": "readback", "expectedNewest": expected_newest,
                "ledger": readback, "transportError": commit.get("transportError")}
    expected = {r["seriesId"]: r for r in csv.DictReader(io.StringIO(csv_text))
                if r.get("periodEnd") == expected_newest and r.get("seriesId") in SERIES.values()}
    if expected_newest:
        verified = set()
        for sid, row in expected.items():
            seen = readback.get(sid, {})
            observations = [{"periodEnd": seen.get("periodEnd"), "value": seen.get("latestValue"),
                             "availableFrom": seen.get("availableFrom")}, *seen.get("history", [])]
            if any(x.get("periodEnd") == expected_newest and x.get("value") == float(row["value"])
                   and x.get("availableFrom") == row["availableFrom"] for x in observations):
                verified.add(sid)
        if verified != set(SERIES.values()):
            return {"ok": False, "stage": "readback_content", "ledger": readback}
    return {"ok": True, "importId": commit.get("importId"),
            "rowCount": len(commit.get("preview") or []),
            "settledByReadback": commit.get("ok") is None,
            "transportError": commit.get("transportError"), "ledger": readback}


def ledger_newest_credit(backend: str, *, token: str) -> Dict[str, Any]:
    if not token:
        raise ValueError("jpx_admin_token_missing")
    request = urllib.request.Request(backend.rstrip("/") + "/api/argus/market-ledger",
                                    headers={"X-ARGUS-ADMIN-TOKEN": token})
    with urllib.request.urlopen(request, timeout=180) as response:
        doc = json.loads(response.read().decode("utf-8"))
    out: Dict[str, Any] = {}
    for row in doc.get("table") or []:
        if row.get("seriesId") in SERIES.values():
            out[row["seriesId"]] = {"periodEnd": row.get("periodEnd"),
                                    "latestValue": row.get("latestValue"),
                                    "availableFrom": row.get("availableFrom"),
                                    "history": row.get("history") or []}
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", default="2026-07-10", help="last period already held (exclusive)")
    parser.add_argument("--out", default=None, help="write the CSV rows here")
    parser.add_argument("--import", dest="do_import", action="store_true")
    parser.add_argument("--backend", default="https://argus-backend-3j2m.onrender.com")
    parser.add_argument("--token-env", default="ARGUS_ADMIN_TOKEN")
    parser.add_argument("--summary", default=None, help="write a JSON summary here")
    args = parser.parse_args(argv)
    result = collect(args.since)
    summary: Dict[str, Any] = {"since": args.since, "fetched": result["fetched"],
                               "gaps": result["gaps"], "rowCount": len(result["rows"]),
                               "newestPeriod": (result["fetched"] or [None])[-1]}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(result["csv"])
    if args.do_import and result["rows"]:
        token = os.environ.get(args.token_env, "")
        if not token:
            summary["import"] = {"ok": False, "stage": "token_missing"}
        else:
            summary["import"] = import_rows(result["csv"], backend=args.backend, token=token,
                                            expected_newest=(result["fetched"] or [None])[-1])
            summary["ledger"] = (summary["import"] or {}).get("ledger") or ledger_newest_credit(args.backend, token=token)
    if result["gaps"]:
        # A fixed warning does not expose rows or protected readback.
        print("::warning title=jpx-credit-weekly::取得待ちまたは書式を確認できない週があります")
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": not args.do_import or not result["rows"] or bool((summary.get("import") or {}).get("ok")),
                      "stage": (summary.get("import") or {}).get("stage", "complete")}, ensure_ascii=False))
    if args.do_import and result["rows"] and not (summary.get("import") or {}).get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
