"""Events a Japanese index ETF holder needs, each with what it means (owner 2026-10-02).

The owner holds Nikkei 225 bull and bear ETFs for several days. Listing a
name and a time is not enough: every event here says what happens, what it
usually does to the Nikkei and to the bull/bear ETFs, and what to check. The
text is a fixed reading of how each event works; it is never a forecast and
carries no action authority.

Sources, all without external calls or AI at request time:
- monthly SQ dates from the shipped JPX schedule (``jp_market_events``);
- Japanese macro releases from the shipped official schedule file;
- dividend record, last-cum and ex-dividend dates derived from the exchange
  calendar (``argus_market_clock``), for the March, June, September and
  December month ends when most Japanese companies set dividend rights;
- Japanese and US market holidays from the same calendar.
Missing coverage is reported as a gap, never filled by extrapolation.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import argus_market_clock as clock
import jp_market_events

SCHEMA_VERSION = "jp-equity-event-calendar-v1"
JST = timezone(timedelta(hours=9))
DEFAULT_HORIZON_DAYS = 45
MACRO_SCHEDULE = Path(__file__).parent / "ops/calendar/jp_macro_2026.json"

# What each Japanese release is, why it moves Japanese stocks and what to look at.
MACRO_TEXT = {
    "JP_CPI": {
        "titleJa": "日本 全国消費者物価指数(CPI)", "importance": "high",
        "whatJa": "日本全体の物価の伸びです。",
        "soWhatJa": "強いと日銀の利上げ観測が強まり、円高・金利上昇で輸出株や日経全体の重しになりやすく、銀行株には追い風です。弱いと逆です。",
        "watchJa": "生鮮食品を除く総合の前年比と、発表直後のドル円・日本10年金利の動き。",
    },
    "JP_TOKYO_CPI": {
        "titleJa": "東京都区部 消費者物価指数(CPI)", "importance": "medium",
        "whatJa": "全国より約3週間早く出る東京の物価で、全国CPIの先行指標です。",
        "soWhatJa": "全国CPIの方向を先取りして、日銀の利上げ観測と円相場を動かします。強いと円高・日経の重し、弱いと円安・日経の支えになりやすい。",
        "watchJa": "生鮮食品を除く総合の前年比が前月より上か下か、発表直後のドル円。",
    },
    "JP_TANKAN": {
        "titleJa": "日銀短観(全国企業短期経済観測調査)", "importance": "high",
        "whatJa": "日銀が約1万社に聞く景況感の調査で、四半期に一度出ます。",
        "soWhatJa": "大企業製造業の景況感が上向くと日本株の支えになります。同時に日銀の利上げ判断の材料にもなるため、強すぎると円高を通じて輸出株の重しにもなります。",
        "watchJa": "大企業製造業の業況判断DIの前回比と先行き、企業の想定為替レート。",
    },
    "JP_GDP": {
        "titleJa": "日本 GDP速報", "importance": "medium",
        "whatJa": "日本経済の成長率(四半期)です。",
        "soWhatJa": "予想より強いと景気への安心感と日銀の利上げ観測が同時に強まります。日経への影響は円相場の反応次第で一方向ではありません。",
        "watchJa": "実質GDPの前期比年率、個人消費と設備投資、発表直後のドル円。",
    },
    "JP_WAGES": {
        "titleJa": "毎月勤労統計(賃金)", "importance": "medium",
        "whatJa": "働く人の給料の伸びです。日銀が利上げ判断で重視しています。",
        "soWhatJa": "賃金の伸びが強いと日銀の利上げ観測が強まり、円高・金利上昇を通じて日経の重しになりやすい。",
        "watchJa": "実質賃金の前年比と、所定内給与の伸び。",
    },
}

SQ_TEXT = {
    "whatJa": "日経225先物・オプションの清算日です。当日の寄付きの値で清算価格(SQ値)が決まります。",
    "soWhatJa": "前日から当日朝にかけて先物主導で値が振れやすく、寄付きに大口の売買が集中します。決まったSQ値はその後数日の上値・下値の目安として意識されます。",
    "majorJa": "3・6・9・12月はメジャーSQで、先物とオプションが同時に清算されるため振れが特に大きくなりやすい日です。",
    "watchJa": "前日の夜間先物の動きと、当日寄付きのSQ値が日経の終値より上か下か。",
}


def _now(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    return now.astimezone(JST)


def _event(*, event_id, kind, at, date_only, title_ja, importance, what_ja, so_what_ja, watch_ja,
           source, today) -> dict[str, Any]:
    day = date.fromisoformat(at[:10])
    return {"eventId": event_id, "kind": kind, "at": at, "dateOnly": date_only, "date": at[:10],
            "daysUntil": (day - today).days, "titleJa": title_ja, "importance": importance,
            "whatJa": what_ja, "soWhatJa": so_what_ja, "watchJa": watch_ja, "source": source,
            "actionAuthority": False}


def _trading(day: date) -> bool:
    return clock.is_trading_day(clock.JP_EQUITY, day)


def _last_trading_day_of_month(year: int, month: int) -> date:
    day = (date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    while not _trading(day):
        day -= timedelta(days=1)
    return day


def _previous_trading_day(day: date, count: int = 1) -> date:
    while count:
        day -= timedelta(days=1)
        if _trading(day):
            count -= 1
    return day


def dividend_events(today: date, end: date) -> list[dict[str, Any]]:
    """Last cum-dividend and ex-dividend sessions for the quarter-end record dates."""
    out = []
    for year in (today.year, today.year + 1):
        for month in (3, 6, 9, 12):
            record = _last_trading_day_of_month(year, month)
            last_cum = _previous_trading_day(record, 2)
            ex_day = _previous_trading_day(record, 1)
            major = month in (3, 9)
            size_ja = ("3月・9月は多くの企業の配当の基準日で、配当落ちが大きい月です。" if major else
                       "6月・12月は基準日の企業が少なく、配当落ちは小さめです。")
            stamp = f"{year}-{month:02d}"
            if today <= last_cum <= end:
                out.append(_event(
                    event_id=f"jp-last-cum-{stamp}", kind="LAST_CUM_DIVIDEND",
                    at=last_cum.isoformat(), date_only=True,
                    title_ja=f"権利付き最終日({month}月末の配当・優待)", importance="high" if major else "medium",
                    what_ja=f"この日の大引けまでに買うと{month}月末の配当・株主優待の権利が得られます。" + size_ja,
                    so_what_ja="配当狙いの買いが入りやすく、日経は底堅くなりやすい日です。翌日の権利落ちで指数が配当分だけ下がることは先物価格に織り込まれています。",
                    watch_ja="翌営業日(権利落ち日)の下げのうち、配当落ち分を除いた実質の値動き。",
                    source="rule:jp-record-date-last-session-t-plus-2", today=today))
            if today <= ex_day <= end:
                out.append(_event(
                    event_id=f"jp-ex-dividend-{stamp}", kind="EX_DIVIDEND",
                    at=ex_day.isoformat(), date_only=True,
                    title_ja=f"権利落ち日({month}月末の配当)", importance="high" if major else "medium",
                    what_ja="配当の権利がなくなった分だけ、多くの株価が朝から安く始まります。" + size_ja,
                    so_what_ja="日経平均は配当の分だけ機械的に下がります(配当落ち)。日経ブルETFは配当を受け取らないので見かけ上その分下がり、ベアETFは上がります。相場の悪化と取り違えないことが大事です。",
                    watch_ja="当日の日経の下げ幅が配当落ち分より大きいか小さいか(小さければ実質は上昇)。",
                    source="rule:jp-record-date-last-session-t-plus-2", today=today))
    return out


US_HOLIDAY_JA = {
    "New Year's Day": "元日", "Martin Luther King Jr. Day": "キング牧師記念日",
    "Washington's Birthday": "大統領の日", "Good Friday": "聖金曜日", "Memorial Day": "戦没者追悼記念日",
    "Juneteenth National Independence Day": "奴隷解放記念日", "Independence Day": "独立記念日",
    "Labor Day": "労働者の日", "Thanksgiving Day": "感謝祭", "Christmas Day": "クリスマス",
}


def _us_holiday_ja(name: str) -> str:
    base = name.replace(" (Observed)", "")
    return US_HOLIDAY_JA.get(base, base) + ("・振替" if name.endswith("(Observed)") else "")


def holiday_events(today: date, end: date) -> list[dict[str, Any]]:
    out = []
    day = today
    while day <= end:
        if day.weekday() < 5:
            name_jp = clock._HOLIDAY_NAMES.get(clock.JP_EQUITY, {}).get(day.isoformat())
            name_us = clock._HOLIDAY_NAMES.get(clock.US_EQUITY, {}).get(day.isoformat())
            if name_jp:
                out.append(_event(
                    event_id=f"jp-market-closed-{day.isoformat()}", kind="JP_MARKET_CLOSED",
                    at=day.isoformat(), date_only=True, title_ja=f"東京市場 休場({name_jp.split(' / ')[-1]})",
                    importance="medium", what_ja="東京証券取引所が休みで、日本株・ETFは売買できません。",
                    so_what_ja="休みの間に起きた海外の値動きや材料を、休み明けの寄付きでまとめて織り込みます。休み前に持ち高を調整する動きも出やすい。",
                    watch_ja="休み中の米国株・ドル円・日経先物(海外市場)の動き。",
                    source="exchange-calendar", today=today))
            if name_us:
                out.append(_event(
                    event_id=f"us-market-closed-{day.isoformat()}", kind="US_MARKET_CLOSED",
                    at=day.isoformat(), date_only=True, title_ja=f"米国市場 休場({_us_holiday_ja(name_us)})",
                    importance="low", what_ja="米国の株式市場が休みです。",
                    so_what_ja="翌日の東京は手がかりが少なく、海外勢の売買も細るため方向感が出にくくなります。",
                    watch_ja="休み明けの米国市場の動き。",
                    source="exchange-calendar", today=today))
        day += timedelta(days=1)
    return out


def macro_events(today: date, end: date, schedule: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    gaps = []
    if schedule.get("schemaVersion") != "jp-official-macro-release-schedule-v1" or not schedule.get("sourceRef"):
        raise ValueError("macro_schedule_invalid")
    if end.isoformat() > str(schedule.get("coverageEnd")):
        gaps.append("jp_macro_schedule_not_published_beyond_" + str(schedule.get("coverageEnd")))
    out = []
    for row in schedule.get("rows", []):
        text = MACRO_TEXT.get(row.get("code"))
        day = date.fromisoformat(str(row.get("date")))
        if text is None or not today <= day <= end:
            continue
        at = f"{day.isoformat()}T{row.get('time', '08:30')}:00+09:00"
        out.append(_event(
            event_id=f"jp-{row['code'].lower().replace('_', '-')}-{day.isoformat()}", kind=row["code"],
            at=at, date_only=False, title_ja=f"{text['titleJa']} {row.get('referenceJa', '')}".strip(),
            importance=text["importance"], what_ja=text["whatJa"], so_what_ja=text["soWhatJa"],
            watch_ja=text["watchJa"], source=str(schedule["sourceRef"]), today=today))
    return out, gaps


SQ_SCHEDULE = Path(__file__).parent / "ops/calendar/jp_index_sq_2026.json"


def sq_events(now: datetime, horizon_days: int) -> tuple[list[dict[str, Any]], list[str]]:
    schedule = jp_market_events.load_published_sq_schedule(now)
    calendar = jp_market_events.sq_calendar(now=now, schedule=schedule, horizon_days=horizon_days)
    today = _now(now).date()
    out = []
    for row in calendar.get("events") or []:
        major = row.get("kind") == "MAJOR_SQ"
        out.append(_event(
            event_id=str(row.get("eventId")), kind="MAJOR_SQ" if major else "SQ",
            at=f"{row['sqDate']}T08:45:00+09:00", date_only=False,
            title_ja=("メジャーSQ" if major else "SQ") + "(日経225先物・オプションの清算)",
            importance="high" if major else "medium", what_ja=SQ_TEXT["whatJa"],
            so_what_ja=SQ_TEXT["soWhatJa"] + (SQ_TEXT["majorJa"] if major else ""),
            watch_ja=SQ_TEXT["watchJa"], source="JPX", today=today))
    return out, list(calendar.get("gaps") or [])


def equity_event_calendar(*, now: datetime, horizon_days: int = DEFAULT_HORIZON_DAYS,
                          macro_schedule: Mapping[str, Any] | None = None) -> dict[str, Any]:
    current = _now(now)
    today = current.date()
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not 1 <= horizon_days <= 90:
        raise ValueError("invalid_calendar_horizon")
    end = today + timedelta(days=horizon_days)
    gaps: list[str] = []
    events: list[dict[str, Any]] = []
    try:
        schedule = macro_schedule if macro_schedule is not None else json.loads(MACRO_SCHEDULE.read_text())
        macro, macro_gaps = macro_events(today, end, schedule)
        events += macro
        gaps += macro_gaps
    except (OSError, ValueError, TypeError, KeyError):
        gaps.append("jp_macro_schedule_unavailable")
    try:
        sq, sq_gaps = sq_events(now, horizon_days)
        events += sq
        gaps += sq_gaps
    except (OSError, ValueError, TypeError, KeyError):
        gaps.append("sq_schedule_unavailable")
    try:
        events += dividend_events(today, end)
        events += holiday_events(today, end)
    except clock.CalendarUnavailableError:
        gaps.append("exchange_calendar_unavailable")
    events.sort(key=lambda row: (row["at"][:10], row["at"], row["eventId"]))
    return {"schemaVersion": SCHEMA_VERSION, "asOf": current.isoformat(), "timezone": "Asia/Tokyo",
            "rangeStart": today.isoformat(), "rangeEnd": end.isoformat(),
            "status": "PARTIAL" if gaps else "AVAILABLE", "gaps": sorted(set(gaps)),
            "events": events, "dependsOnAi": False, "automaticAiCalls": 0, "actionAuthority": False}
