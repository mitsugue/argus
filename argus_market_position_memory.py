"""Market position memory: the themes investors are watching, accumulated.

Owner direction 2026-10-03 (docs/V13_8_REQUIREMENTS.md §3-1): the integrated
explanation must first know where the market stands — which themes are in
play, what is expected, what is feared, what is scheduled next — and only then
read each function's numbers. This module keeps that memory. It is
deterministic and calls no model: entries come from the existing stores
(trusted-mail news events, measured release reactions, the pre-release
policy-rate pricing, the event calendar) and are appended with their source
reference, never rewritten. The explanation facts it emits are evidence for
the integrated AI, not conclusions of their own.

Stage one keeps measured and reported facts per theme. Stage two (below,
validate_views / ingest_views) lets the integrated AI write, per active
theme, what the market expects, fears and would change its mind on — bound
to the same evidence ids and checked by the same rules as the six sections,
then appended to the memory as its own kind of entry.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

SCHEMA = "argus-market-position-memory-v1"
MAX_ENTRIES = 2000
ACTIVE_DAYS = 14          # a theme with no entry for this long is QUIET
RECENT_ENTRIES = 3

THEMES: Dict[str, Dict[str, Any]] = {
    "US_POLICY_RATE": {"labelJa": "米国の利上げ・利下げ観測",
                       "families": ("FED", "CENTRAL_BANK", "INFLATION", "EMPLOYMENT"),
                       "eventCodes": ("FOMC", "CPI", "NFP", "PCE", "PPI", "JOLTS", "GDP")},
    "AI_SEMIS": {"labelJa": "AI・半導体相場", "families": ("SEMICONDUCTORS", "AI_DATACENTER"), "eventCodes": ()},
    "MIDDLE_EAST": {"labelJa": "中東・イラン情勢",
                    "families": ("IRAN", "HORMUZ", "WAR_ESCALATION", "CEASEFIRE", "SANCTIONS", "GEOPOLITICS", "OIL"),
                    "eventCodes": ()},
    "US_LONG_RATES": {"labelJa": "米長期金利・財政", "families": ("RATES", "US_FISCAL"), "eventCodes": ("AUCTION",)},
    "BOJ": {"labelJa": "日銀・日本の金融政策", "families": ("BOJ", "JAPAN_POLICY"), "eventCodes": ("BOJ",)},
    "JPY": {"labelJa": "円相場", "families": ("FX",), "eventCodes": ()},
    "TRADE": {"labelJa": "関税・貿易", "families": ("TARIFFS", "TRADE"), "eventCodes": ()},
}
SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "WATCH": 1, "INFO": 0}


def _instant(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def theme_for_family(family: Any) -> Optional[str]:
    text = str(family or "").upper()
    for theme_id, spec in THEMES.items():
        if text in spec["families"]:
            return theme_id
    return None


def theme_for_event_code(code: Any) -> Optional[str]:
    text = str(code or "").upper()
    for theme_id, spec in THEMES.items():
        if text in spec["eventCodes"]:
            return theme_id
    return None


def empty() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA, "entries": [], "actionAuthority": False}


def _entry(theme_id: str, kind: str, at: str, text: str, *, ref: Mapping[str, Any],
           severity: str = "INFO", measured: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    body = {"themeId": theme_id, "kind": kind, "at": at, "textJa": str(text)[:160],
            "severity": severity if severity in SEVERITY_RANK else "INFO",
            "ref": dict(ref), "measured": dict(measured) if measured else None}
    return {"entryId": "mpm-" + _digest({k: v for k, v in body.items() if k != "at"})[:24], **body}


def append(memory: Dict[str, Any], entry: Mapping[str, Any]) -> bool:
    """Append once; the same fact from the same source is never duplicated."""
    if any(row["entryId"] == entry["entryId"] for row in memory["entries"]):
        return False
    memory["entries"].append(dict(entry))
    if len(memory["entries"]) > MAX_ENTRIES:
        memory["entries"] = memory["entries"][-MAX_ENTRIES:]
    return True


def ingest_news(memory: Dict[str, Any], events: Iterable[Mapping[str, Any]]) -> int:
    """HIGH/CRITICAL trusted-mail events become theme entries keyed by their event id."""
    added = 0
    for event in events:
        severity = str(event.get("severity") or "")
        if severity not in ("HIGH", "CRITICAL"):
            continue
        family = event.get("eventType") or (event.get("taxonomy") or {}).get("eventType")
        theme_id = theme_for_family(family)
        at = event.get("sourceReceivedAt") or event.get("receivedAt")
        if theme_id is None or _instant(at) is None:
            continue
        headline = str(event.get("headlineJa") or event.get("headline") or event.get("titleOriginal") or "").strip()
        if not headline or headline == "翻訳処理中":
            continue
        entry = _entry(theme_id, "NEWS", _instant(at).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                       f"{event.get('sourceLabelJa') or event.get('sourceFamily') or '公式'}: {headline}",
                       ref={"eventId": str(event.get("eventId") or ""), "source": "trusted_mail",
                            "confirmationState": event.get("confirmationState")},
                       severity=severity)
        added += append(memory, entry)
    return added


def ingest_release_reaction(memory: Dict[str, Any], record: Mapping[str, Any]) -> int:
    """A measured reaction (argus_macro_release_reaction) becomes one entry per window."""
    from argus_macro_release_reaction import revalidate
    reaction = revalidate((record or {}).get("releaseReaction"))
    theme_id = theme_for_event_code(record.get("eventCode"))
    if theme_id is None or not reaction.get("windows"):
        return 0
    added = 0
    base = (reaction.get("baselineComparisonValues") or {}).get("ZQ=F") or {}
    for name, window in reaction["windows"].items():
        move = window.get("moves") or {}
        read = window.get("reading") or {}
        measured = {"window": name, "ffImpliedRateMoveBp": move.get("ffImpliedRateMoveBp"),
                    "ffImpliedRateAfterPct": move.get("ffImpliedRateAfterPct"),
                    "nasdaqFuturesMovePct": move.get("nasdaqFuturesMovePct"),
                    "nikkeiFuturesMovePct": move.get("nikkeiFuturesMovePct"), "readingCode": read.get("code")}
        text = f"{record.get('title') or record.get('eventCode')}の発表{name}: {read.get('labelJa') or '反応を測れていない'}"
        if move.get("ffImpliedRateMoveBp") is not None:
            text += f"(政策金利の予想{move['ffImpliedRateMoveBp']:+.1f}bp→{move['ffImpliedRateAfterPct']:.3f}%)"
        entry = _entry(theme_id, "RELEASE_REACTION", str(window.get("observedAt") or reaction.get("eventTimeUtc")),
                       text, ref={"eventId": str(record.get("eventId") or ""), "source": "release_reaction",
                                  "basis": reaction.get("basis"), "sourceTimeValidation": "source-time-v2",
                                  "hasComparableMoves": any(v is not None for k, v in move.items() if "Move" in k)},
                       severity="HIGH", measured=measured)
        added += append(memory, entry)
    if base.get("price") is not None:
        entry = _entry("US_POLICY_RATE", "PRICING", str((reaction.get("baseline") or {}).get("capturedAt")),
                       f"発表前の織り込み: FF金利先物の示す政策金利の予想 {100 - float(base['price']):.3f}%",
                       ref={"eventId": str(record.get("eventId") or ""), "source": "release_baseline", "symbol": "ZQ=F",
                            "sourceTimeValidation": "source-time-v2"},
                       measured={"ffImpliedRatePct": round(100 - float(base["price"]), 3)})
        added += append(memory, entry)
    return added


RADAR_THEMES = {"geopolitics": "MIDDLE_EAST", "energy_geopolitics": "MIDDLE_EAST",
                "rates_shock": "US_LONG_RATES", "fx_policy": "JPY"}
PUBLIC_HEADLINE_DAYS = 3
PUBLIC_HEADLINE_LIMIT = 30


def ingest_public_headlines(memory: Dict[str, Any], items: Iterable[Mapping[str, Any]],
                            classify: Callable[[str], Mapping[str, Any]], *, now_iso: str) -> int:
    """Public RSS headlines (metadata only) become WATCH entries on a theme.

    They are weaker than trusted mail: severity stays WATCH, and only headlines
    the deterministic taxonomy puts on a theme are kept. Bounded per update.
    """
    now = _instant(now_iso)
    added = 0; considered = 0
    for item in items:
        if considered >= PUBLIC_HEADLINE_LIMIT:
            break
        title = str(item.get("title") or "").strip()
        at = _instant(item.get("publishedAt") or item.get("firstDetectedAt"))
        if not title or at is None or (now and now - at > timedelta(days=PUBLIC_HEADLINE_DAYS)):
            continue
        try:
            taxonomy = classify(title)
        except Exception:
            continue
        theme_id = theme_for_family((taxonomy or {}).get("eventType"))
        if theme_id is None:
            continue
        considered += 1
        entry = _entry(theme_id, "PUBLIC_HEADLINE", at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                       f"{item.get('sourceId') or '公開ニュース'}: {title}",
                       ref={"source": "public_rss", "sourceId": item.get("sourceId"),
                            "url": item.get("canonicalUrl") if str(item.get("canonicalUrl") or "").startswith("https://") else None,
                            "eventType": (taxonomy or {}).get("eventType")}, severity="WATCH")
        added += append(memory, entry)
    return added


def ingest_radar(memory: Dict[str, Any], radar: Optional[Mapping[str, Any]]) -> int:
    """GDELT headline counts per radar theme (cached document, never fetched here)."""
    if not isinstance(radar, Mapping) or radar.get("status") != "live":
        return 0
    at = _instant(radar.get("asOf") or radar.get("generatedAt"))
    if at is None:
        return 0
    bucket = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00Z")   # one entry per theme per hour
    added = 0
    for theme in radar.get("themes") or []:
        theme_id = RADAR_THEMES.get(str(theme.get("key") or ""))
        count = theme.get("count")
        if theme_id is None or not isinstance(count, int) or count <= 0 or str(theme.get("level") or "") in ("", "none", "low"):
            continue
        entry = _entry(theme_id, "RADAR", bucket,
                       f"公開ニュースの件数: {theme.get('labelJa') or theme.get('key')} {count}件(6時間・{theme.get('level')})",
                       ref={"source": "news_radar", "key": theme.get("key"), "bucket": bucket},
                       severity="WATCH", measured={"count": count, "level": theme.get("level")})
        added += append(memory, entry)
    return added


def ingest_policy_rate_quote(memory: Dict[str, Any], quote: Optional[Mapping[str, Any]]) -> int:
    """The fed funds future read between releases: one PRICING entry per UTC day."""
    if not isinstance(quote, Mapping):
        return 0
    at = _instant(quote.get("tradedAt"))
    rate = quote.get("impliedRatePct")
    if at is None or isinstance(rate, bool) or not isinstance(rate, (int, float)):
        return 0
    day = at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if any(row.get("kind") == "PRICING" and (row.get("ref") or {}).get("source") == "policy_rate_futures"
           and (row.get("ref") or {}).get("day") == day for row in memory["entries"]):
        return 0
    entry = _entry("US_POLICY_RATE", "PRICING", day + "T00:00:00Z",
                   f"FF金利先物の示す政策金利の予想 {float(rate):.3f}%({day}の取引)",
                   ref={"source": "policy_rate_futures", "symbol": quote.get("symbol"), "day": day},
                   measured={"ffImpliedRatePct": round(float(rate), 3)})
    return append(memory, entry)


VIEW_FIELDS = ("expectationJa", "fearJa", "triggerJa")
VIEW_TEXT_LIMIT = 160


def ingest_views(memory: Dict[str, Any], views: Iterable[Mapping[str, Any]], *, context_id: str,
                 generated_at: str) -> int:
    """Validated AI views become AI_VIEW entries; an unchanged view is not re-appended."""
    added = 0
    for view in views or []:
        body = {f: view.get(f) for f in VIEW_FIELDS}
        last = next((r for r in reversed(memory["entries"]) if r.get("themeId") == view["themeId"]
                     and r.get("kind") == "AI_VIEW"), None)
        if last and (last.get("measured") or {}).get("view") == body:
            continue
        text = "期待: " + (body["expectationJa"] or "—") + " / 警戒: " + (body["fearJa"] or "—") + " / 引き金: " + (body["triggerJa"] or "—")
        entry = _entry(view["themeId"], "AI_VIEW", generated_at, text,
                       ref={"source": "integrated_ai", "contextId": context_id, "evidenceIds": list(view.get("evidenceIds") or []),
                            "kind": view.get("kind")}, measured={"view": body})
        added += append(memory, entry)
    return added


def _theme_entries(memory: Mapping[str, Any], theme_id: str) -> List[Dict[str, Any]]:
    rows = [row for row in memory.get("entries") or [] if row.get("themeId") == theme_id]
    rows.sort(key=lambda row: str(row.get("at") or ""))
    return rows


def _next_event(theme_id: str, events: Iterable[Mapping[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    best = None
    for event in events or []:
        if theme_for_event_code(event.get("eventCode")) != theme_id:
            continue
        at = _instant(event.get("eventTimeUtc"))
        if at is None or at < now:
            continue
        if best is None or at < best[0]:
            best = (at, event)
    if best is None:
        return None
    at, event = best
    return {"title": str(event.get("title") or event.get("eventCode") or "")[:60],
            "eventTimeUtc": at.isoformat().replace("+00:00", "Z"), "eventCode": event.get("eventCode")}


def snapshot(memory: Mapping[str, Any], *, now_iso: str,
             scheduled_events: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """Per-theme state for display and for the integrated explanation."""
    now = _instant(now_iso) or datetime.now(timezone.utc)
    themes = []
    for theme_id, spec in THEMES.items():
        original_rows = _theme_entries(memory, theme_id)
        # Old derived readings do not retain their source clocks. Preserve
        # them in storage, but do not cite them as current measured evidence.
        rows = [row for row in original_rows if
                not (row.get("kind") == "RELEASE_REACTION" or
                     (row.get("kind") == "PRICING" and (row.get("ref") or {}).get("source") == "release_baseline"))
                or (row.get("ref") or {}).get("sourceTimeValidation") == "source-time-v2"]
        # AI assessments remain in the append-only history and display, but
        # cannot refresh source freshness or become their own new evidence.
        external = [row for row in rows if row.get("kind") != "AI_VIEW"]
        last = external[-1] if external else None
        last_at = _instant(last["at"]) if last else None
        status = "EMPTY" if not external else ("ACTIVE" if last_at and now - last_at <= timedelta(days=ACTIVE_DAYS) else "QUIET")
        pricing = next((r for r in reversed(rows) if r.get("kind") == "PRICING"), None)
        reaction = next((r for r in reversed(rows) if r.get("kind") == "RELEASE_REACTION"), None)
        ai_view = next((r for r in reversed(rows) if r.get("kind") == "AI_VIEW"), None)
        themes.append({
            "themeId": theme_id, "labelJa": spec["labelJa"], "status": status,
            "entryCount": len(original_rows), "excludedUnverifiedReleaseEntries": len(original_rows) - len(rows),
            "lastUpdatedAt": last["at"] if last else None,
            "recent": [{k: r.get(k) for k in ("entryId", "kind", "at", "textJa", "severity", "ref")}
                       for r in rows[-RECENT_ENTRIES:]][::-1],
            "pricing": pricing["measured"] if pricing else None,
            "lastReaction": {"at": reaction["at"], "textJa": reaction["textJa"],
                             "hasComparableMoves": (reaction.get("ref") or {}).get("hasComparableMoves") is True,
                             **(reaction.get("measured") or {})}
                            if reaction else None,
            "nextEvent": _next_event(theme_id, scheduled_events, now),
            "view": ({**((ai_view.get("measured") or {}).get("view") or {}), "at": ai_view["at"],
                      "contextId": (ai_view.get("ref") or {}).get("contextId"), "kind": (ai_view.get("ref") or {}).get("kind")}
                     if ai_view else None),
            "externalRecent": [{k: r.get(k) for k in ("entryId", "kind", "at", "textJa", "severity", "ref")}
                               for r in external[-RECENT_ENTRIES:]][::-1],
        })
    return {"schemaVersion": SCHEMA, "asOf": now_iso, "themes": themes,
            "entryCount": len(memory.get("entries") or []), "actionAuthority": False, "automaticAiCalls": 0}


def explanation_facts(view: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One bounded fact per theme with entries, for the integrated explanation.

    The text names the theme, the latest measured reading and the next check;
    the AI reads the market's position from these before the other evidence.
    """
    facts = []
    for theme in view.get("themes") or []:
        if theme["status"] == "EMPTY":
            continue
        bits = [f"現在位置・{theme['labelJa']}"]
        if theme.get("lastReaction"):
            bits.append(theme["lastReaction"]["textJa"])
        elif theme.get("externalRecent"):
            bits.append(theme["externalRecent"][0]["textJa"])
        if theme.get("pricing") and theme["pricing"].get("ffImpliedRatePct") is not None:
            bits.append(f"政策金利の予想{theme['pricing']['ffImpliedRatePct']:.3f}%")
        if theme.get("nextEvent"):
            bits.append(f"次: {theme['nextEvent']['title']}（{theme['nextEvent']['eventTimeUtc'][:16].replace('T', ' ')}Z）")
        if theme["status"] == "QUIET":
            bits.append("最近の動きなし")
        measured = bool((theme.get("lastReaction") or {}).get("hasComparableMoves") or theme.get("pricing"))
        recent = theme.get("externalRecent") or []
        latest = recent[0] if recent else {}
        facts.append({"text": "。".join(bits)[:160], "priority": "P1", "source": "market_position",
                      "verification": "VERIFIED" if measured else "CORROBORATED",
                      # The shape every brief fact's provenance carries (the page
                      # rejects the whole brief otherwise; 2026-10-04 incident).
                      "provenance": {"scope": "published_metadata_snapshot", "revision": None,
                                     "sourceLabel": "ARGUSの市場の現在位置メモ", "publishedAt": None,
                                     "receivedAt": theme.get("lastUpdatedAt"), "observedAt": None, "url": None,
                                     "eventId": f"market-position-{theme['themeId']}",
                                     "asOf": theme.get("lastUpdatedAt"),
                                     "sourceLabelJa": "ARGUSの市場の現在位置メモ",
                                     "sourceRowSha256": _digest(recent),
                                     "sourceReceivedAt": theme.get("lastUpdatedAt"),
                                     "latestEntryId": latest.get("entryId")}})
    return facts


def generation_inputs(view: Mapping[str, Any]) -> Dict[str, Any]:
    """Project the display snapshot onto external materials for paid reuse.

    Keep unknown fields significant. Source clocks, eligibility, stale state,
    pricing, release reactions and schedules remain bound to the digest.
    """
    import copy
    result = copy.deepcopy(view)
    for key in ("asOf", "entryCount", "persistence"):
        result.pop(key, None)
    for theme in result.get("themes") or []:
        theme.pop("view", None)
        theme.pop("entryCount", None)
        if "externalRecent" in theme:
            theme["recent"] = theme.pop("externalRecent")
    return result


def load(raw: Any) -> Dict[str, Any]:
    """Accept only this schema; anything else starts empty (never partial)."""
    if (not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA
            or not isinstance(raw.get("entries"), list)):
        return empty()
    rows = [row for row in raw["entries"] if isinstance(row, dict) and row.get("entryId") and row.get("themeId") in THEMES]
    return {"schemaVersion": SCHEMA, "entries": rows[-MAX_ENTRIES:], "actionAuthority": False}
