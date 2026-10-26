"""Check the market position against public sources (N-19, owner 2026-10-23).

Owner: 「判断の精度が上がると思うので試してみたい。現在地をより高解像度で理解して描写してほしい」.

Before the integrated view is written, the saved market position (the
themes and their entries) is read for what it does not say: an important
report not yet confirmed, a theme with no known next release, how far a
leading theme is priced in, a theme that has gone quiet. Up to five such
questions are put to one search-backed model call that may answer only from
the allowed public sources. An answer without an allowed source URL is
dropped. Accepted answers are appended to the same market-position memory
as their own kind of entry (PUBLIC_CHECK); no new store is made.

The first week runs in shadow: the entries are kept and counted, but the
snapshot that feeds the screen and the integrated view leaves them out.

Pure functions only: no clock, no network, no model call, no store.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlparse

import argus_market_position_memory as memory_mod

SCHEMA = "argus-market-position-check-v1"
KIND = "PUBLIC_CHECK"
JST = timezone(timedelta(hours=9))

# Owner design (2026-10-24): before the integrated view on trading days,
# once on weekends and Tokyo holidays.
TRADING_DAY_SLOTS = ("07:30", "11:30", "16:30")
CLOSED_DAY_SLOTS = ("08:30",)

MAX_QUESTIONS = 5
ANSWER_TEXT_LIMIT = 240
MAX_SOURCES_PER_ANSWER = 3
STALE_DAYS = 7
CONFIRM_LOOKBACK_HOURS = 72

# Public sources the answer may cite: central banks and ministries, the
# exchange and filing systems, statistical offices and the major wires.
ALLOWED_DOMAINS = (
    "boj.or.jp", "mof.go.jp", "fsa.go.jp", "cao.go.jp", "meti.go.jp", "mhlw.go.jp",
    "stat.go.jp", "e-stat.go.jp", "kantei.go.jp",
    "jpx.co.jp", "release.tdnet.info", "edinet-fsa.go.jp",
    "federalreserve.gov", "treasury.gov", "bls.gov", "bea.gov", "census.gov",
    "whitehouse.gov", "ustr.gov", "sec.gov", "cmegroup.com",
    "ecb.europa.eu", "bankofengland.co.uk", "imf.org", "opec.org", "iea.org",
    "nikkei.com", "reuters.com", "bloomberg.com", "bloomberg.co.jp",
    "jiji.com", "kyodonews.jp", "nhk.or.jp", "apnews.com", "ft.com", "wsj.com",
)

QUESTION_TYPES = ("CONFIRM", "NEXT_EVENT", "PRICING", "STALE")
# 2026-10-27: the shadow week asked the same report three or four times with
# the same answer. A question answered within its window is not asked again;
# a CONFIRM is the same only for the same report.
REPEAT_HOURS = {"CONFIRM": 72, "NEXT_EVENT": 24, "PRICING": 8, "STALE": 72}


about_key = memory_mod.about_key
# 2026-10-27 (owner, plan A): what a CONFIRM answer found about the report.
CLAIMS = ("SUPPORTED", "CONTRADICTED", "UNVERIFIED")


def _instant(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── when to run ─────────────────────────────────────────────────────────────

def latest_slot(now: datetime, is_trading_day: Callable[[Any], bool]) -> Optional[str]:
    """The label ("YYYY-MM-DD HH:MM" in JST) of the newest slot at or before now."""
    if now.tzinfo is None:
        raise ValueError("aware_datetime_required")
    local = now.astimezone(JST)
    best = None
    for offset in (1, 0):
        day = (local - timedelta(days=offset)).date()
        slots = TRADING_DAY_SLOTS if is_trading_day(day) else CLOSED_DAY_SLOTS
        for text in slots:
            hour, minute = (int(part) for part in text.split(":"))
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=JST)
            if at <= local and (best is None or at > best[0]):
                best = (at, f"{day.isoformat()} {text}")
    return best[1] if best else None


def due(now: datetime, last_slot: Optional[str],
        is_trading_day: Callable[[Any], bool]) -> Optional[str]:
    """The slot to answer now, or None when the newest slot was already run."""
    slot = latest_slot(now, is_trading_day)
    return slot if slot and slot != last_slot else None


# ── what to ask (no model) ──────────────────────────────────────────────────

def _theme_label(theme: Mapping[str, Any]) -> str:
    return str(theme.get("labelJa") or theme.get("themeId") or "")


def _recently_answered(checks: Iterable[Mapping[str, Any]], now: datetime) -> set:
    """(themeId, type, aboutKey) of the checks still inside their repeat window."""
    out = set()
    for row in checks or ():
        ref = row.get("ref") or {}
        qtype = ref.get("questionType")
        at = _instant(row.get("at"))
        if qtype not in REPEAT_HOURS or at is None or now - at > timedelta(hours=REPEAT_HOURS[qtype]):
            continue
        out.add((row.get("themeId"), qtype, ref.get("aboutKey") if qtype == "CONFIRM" else None))
    return out


def select_questions(view: Mapping[str, Any], *, now: datetime,
                     recent_checks: Iterable[Mapping[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Up to MAX_QUESTIONS questions about what the saved position does not say.

    Order: an unconfirmed HIGH/CRITICAL report of the last three days, an
    active theme with no known next release, how far the two busiest active
    themes are priced in, an active theme with no entry for a week. A question
    answered inside its REPEAT_HOURS window (`recent_checks`, the saved
    PUBLIC_CHECK entries) is skipped.
    """
    themes = [t for t in (view.get("themes") or []) if t.get("status") == "ACTIVE"]
    asked: List[Dict[str, Any]] = []
    seen = set()
    answered = _recently_answered(recent_checks, now)

    def add(theme: Mapping[str, Any], qtype: str, text: str, about: Optional[str] = None) -> bool:
        key = (theme.get("themeId"), qtype)
        about_id = about_key(about) if qtype == "CONFIRM" else None
        if key in seen or len(asked) >= MAX_QUESTIONS or (*key, about_id) in answered:
            return False
        seen.add(key)
        asked.append({"id": f"q{len(asked) + 1}", "themeId": theme.get("themeId"),
                      "themeLabelJa": _theme_label(theme), "type": qtype,
                      "questionJa": text[:300], "aboutJa": (about or "")[:200],
                      **({"aboutKey": about_id} if about_id else {})})
        return True

    for theme in themes:
        for row in theme.get("externalRecent") or theme.get("recent") or []:
            ref = row.get("ref") or {}
            at = _instant(row.get("at"))
            if (row.get("kind") == "NEWS" and row.get("severity") in ("HIGH", "CRITICAL")
                    and ref.get("confirmationState") not in ("CONFIRMED", "OFFICIAL")
                    and at is not None and now - at <= timedelta(hours=CONFIRM_LOOKBACK_HOURS)):
                if add(theme, "CONFIRM",
                       f"「{_theme_label(theme)}」の次の報道は、公式の発表や一次情報で確認できますか。"
                       "確認できた事実と、まだ確認できない点を分けてください。",
                       about=str(row.get("textJa") or "")):
                    break
    for theme in themes:
        if not theme.get("nextEvent"):
            add(theme, "NEXT_EVENT",
                f"「{_theme_label(theme)}」について、今後2週間以内に予定されている重要な発表・会合・期限は"
                "ありますか。日付(日本時間)と名前を挙げてください。無ければ無いと答えてください。")
    ranked = sorted(themes, key=lambda t: (-int(t.get("entryCount") or 0), str(t.get("themeId"))))
    for theme in ranked[:2]:
        add(theme, "PRICING",
            f"「{_theme_label(theme)}」について、市場は今どこまで織り込んでいますか。"
            "先物・金利・為替・オプションなど、公表されている指標の数字で答えてください。")
    for theme in themes:
        last = _instant(theme.get("lastUpdatedAt"))
        if last is not None and now - last >= timedelta(days=STALE_DAYS):
            add(theme, "STALE",
                f"「{_theme_label(theme)}」について、直近1週間で市場に影響した新しい事実はありますか。")
    return asked


CONFIRMATIONS = ("CONFIRMED", "PARTIAL", "NONE")


def build_prompt(questions: List[Mapping[str, Any]], *, now: datetime) -> str:
    """The single search-backed request. The answer is data, never instructions."""
    lines = [
        f"今の時刻(日本時間): {now.astimezone(JST).strftime('%Y-%m-%d %H:%M')}",
        "次の問いに、公開情報を検索して答えてください。",
        "使ってよい出典は、次のドメインの公開ページだけです: " + ", ".join(ALLOWED_DOMAINS),
        "confirmation は次の3つから選んでください: CONFIRMED=出典で問いに答えられた / "
        "PARTIAL=一部だけ出典で確かめられた(確かめられた事実と、まだ確かめられない点を分けて書く) / "
        "NONE=何も確かめられなかった。NONE の時だけ unknown を true にしてください。"
        "出典の URL が無い事実は確かめられたことにしないでください。推測で埋めないでください。",
        "「対象の報道」がある問いだけ、claim に報道の主な主張の判定を入れてください: SUPPORTED=出典が主張を裏付けた / "
        "CONTRADICTED=出典が主張と食い違う(数字・国・日付・主体の違いを含む。answerJa の最初に正しい事実を書く) / "
        "UNVERIFIED=出典で確かめられなかった。対象の報道が無い問いは claim を null にしてください。",
        "売買の勧め・目標価格・利益の約束は書かないでください。事実と数字だけを短く書いてください。",
        "答えは次の JSON だけで返してください(前後に文章を付けない):",
        '{"answers":[{"id":"q1","answerJa":"200字以内","confirmation":"CONFIRMED","unknown":false,"claim":null,'
        '"nextEventDate":"YYYY-MM-DD または null",'
        '"sources":[{"url":"https://...","title":"見出し","publishedAt":"YYYY-MM-DD"}]}]}',
        "",
    ]
    for q in questions:
        lines.append(f"{q['id']}: {q['questionJa']}")
        if q.get("aboutJa"):
            lines.append(f"  対象の報道: {q['aboutJa']}")
    return "\n".join(lines)


# ── what to keep ────────────────────────────────────────────────────────────

def allowed_url(url: Any) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return (parsed.scheme == "https" and bool(host)
            and any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS))


def _json_object(text: str) -> Optional[Dict[str, Any]]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_answers(text: Any, questions: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Accepted answers and the reasons the others were dropped (counts only)."""
    by_id = {q["id"]: q for q in questions}
    result: Dict[str, Any] = {"accepted": [], "rejected": {}}

    def reject(reason: str) -> None:
        result["rejected"][reason] = result["rejected"].get(reason, 0) + 1

    payload = _json_object(str(text or ""))
    if payload is None or not isinstance(payload.get("answers"), list):
        reject("not_json")
        return result
    for raw in payload["answers"][:MAX_QUESTIONS]:
        if not isinstance(raw, dict) or raw.get("id") not in by_id:
            reject("unknown_question")
            continue
        question = by_id[raw["id"]]
        # 2026-10-25: the first answers marked a partly confirmed answer
        # unknown; "unknown" now means nothing could be confirmed.
        confirmation = str(raw.get("confirmation") or "").upper()
        if confirmation not in CONFIRMATIONS:
            confirmation = "NONE" if raw.get("unknown") is True else "CONFIRMED"
        unknown = confirmation == "NONE"
        answer = str(raw.get("answerJa") or "").strip()
        sources = []
        for source in raw.get("sources") or []:
            if isinstance(source, dict) and allowed_url(source.get("url")):
                sources.append({"url": str(source["url"])[:300],
                                "title": str(source.get("title") or "")[:120],
                                "publishedAt": (str(source.get("publishedAt"))
                                                if _DATE.match(str(source.get("publishedAt") or "")) else None)})
        if not unknown and not answer:
            reject("empty")
            continue
        if not unknown and not sources:
            reject("no_allowed_source")
            continue
        next_date = raw.get("nextEventDate")
        claim = str(raw.get("claim") or "").upper()
        if question.get("type") != "CONFIRM":
            claim = None
        elif claim not in CLAIMS:
            # An unanswered report is unverified; otherwise say nothing rather than guess.
            claim = "UNVERIFIED" if unknown else None
        elif claim != "UNVERIFIED" and not sources:
            claim = "UNVERIFIED"
        result["accepted"].append({
            "question": question, "unknown": unknown, "confirmation": confirmation, "claim": claim,
            "answerJa": (answer or "確かめられませんでした")[:ANSWER_TEXT_LIMIT],
            "sources": sources[:MAX_SOURCES_PER_ANSWER],
            "nextEventDate": next_date if isinstance(next_date, str) and _DATE.match(next_date) else None,
        })
    return result


def entries(accepted: Iterable[Mapping[str, Any]], *, checked_at: str, slot: str) -> List[Dict[str, Any]]:
    """Market-position entries (kind PUBLIC_CHECK) for the accepted answers."""
    out = []
    for answer in accepted:
        question = answer["question"]
        if question.get("themeId") not in memory_mod.THEMES:
            continue
        out.append(memory_mod._entry(
            question["themeId"], KIND, checked_at, answer["answerJa"],
            ref={"source": "public_check", "questionId": question["id"],
                 "questionType": question["type"], "questionJa": question["questionJa"],
                 "slot": slot, "sources": list(answer["sources"]),
                 **({"aboutKey": question["aboutKey"]} if question.get("aboutKey") else {})},
            measured={"unknown": bool(answer["unknown"]), "nextEventDate": answer["nextEventDate"],
                      **({"claim": answer["claim"]} if answer.get("claim") else {}),
                      "confirmation": answer.get("confirmation") or ("NONE" if answer["unknown"] else "CONFIRMED")},
            text_limit=ANSWER_TEXT_LIMIT))
    return out


def summary(memory: Mapping[str, Any], *, now: datetime, days: int = 7) -> Dict[str, Any]:
    """Counts only, for the diagnostics (no answer text)."""
    rows = [r for r in memory.get("entries") or [] if r.get("kind") == KIND]
    recent = [r for r in rows if (_instant(r.get("at")) or now) >= now - timedelta(days=days)]
    return {"schemaVersion": SCHEMA, "entries": len(rows), "lastDays": days,
            "recent": len(recent),
            "recentUnknown": sum(1 for r in recent if (r.get("measured") or {}).get("unknown")),
            "recentPartial": sum(1 for r in recent if (r.get("measured") or {}).get("confirmation") == "PARTIAL"),
            "byType": {t: sum(1 for r in recent if (r.get("ref") or {}).get("questionType") == t)
                       for t in QUESTION_TYPES},
            "lastAt": rows[-1]["at"] if rows else None}


__all__ = ["SCHEMA", "KIND", "TRADING_DAY_SLOTS", "CLOSED_DAY_SLOTS", "ALLOWED_DOMAINS",
           "latest_slot", "due", "select_questions", "build_prompt", "allowed_url",
           "parse_answers", "entries", "summary"]
