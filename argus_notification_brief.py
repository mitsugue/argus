"""Read-only notification projection of the same complete edition as Today.

No collection, generation, trading authority or new persistence. Old digest
fields remain evidence-only compatibility fields; they never supply the text.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

SCHEMA = "argus-notification-brief-v2"
SECTIONS = ("view", "reasons", "changes", "impact", "next", "invalidation")
LABELS = {"view": "今の見立て", "reasons": "重要な理由",
          "changes": "前回からの変化", "next": "次に確認すること",
          "invalidation": "見方を変える条件"}
JST = timezone(timedelta(hours=9))


def _instant(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def _readable(edition, now):
    """The generated six-section boundary used by readableBriefEdition."""
    if not isinstance(edition, dict):
        return False
    def text(value, limit=1000):
        return isinstance(value, str) and len(value) <= limit

    def fact(row):
        if (not isinstance(row, dict) or not text(row.get("text"), 500)
                or not text(row.get("source"), 100)
                or row.get("priority") not in ("P0", "P1", "P2", "P3")
                or row.get("verification") not in ("VERIFIED", "CORROBORATED", "UNCONFIRMED")):
            return False
        origin = row.get("provenance")
        if origin is None:
            return "provenance" not in row
        if not isinstance(origin, dict) or origin.get("scope") != "published_metadata_snapshot":
            return False
        for key in ("publishedAt", "receivedAt", "observedAt"):
            value = origin.get(key)
            if value is None or _instant(value):
                continue
            # Market observations may carry only a source date, exactly as
            # _source_reference and Today's provenance reader permit. This
            # date never becomes a publication or receipt clock instant.
            try:
                date_only = (key == "observedAt" and isinstance(value, str)
                             and len(value) == 10 and datetime.fromisoformat(value))
            except ValueError:
                date_only = False
            if not date_only:
                return False
        # The server has already validated public provenance. Never project it
        # into the message or use a bare hash as proof of a retrieved original.
        return True

    chips, facts = edition.get("chips"), edition.get("facts")
    if (not all(text(edition.get(k)) for k in ("now", "why", "next"))
            or not isinstance(chips, dict) or not all(text(chips.get(k))
                for k in ("chart", "news", "nextEvent", "mainRisk"))
            or not isinstance(facts, list) or len(facts) > 64 or not all(fact(r) for r in facts)):
        return False
    summary, context = edition.get("unifiedSummary"), edition.get("unifiedContext")
    at = _instant(edition.get("generatedAt"))
    if (edition.get("schemaVersion") != "argus-market-brief-v1"
            or edition.get("status") == "unavailable" or edition.get("sdaAuthority") is not False
            or edition.get("unifiedStatus") != "GENERATED" or not at or at > now
            or not isinstance(summary, dict) or not isinstance(context, dict)):
        return False
    cid = context.get("contextId")
    if (not isinstance(cid, str) or not re.fullmatch(r"[a-f0-9]{64}", cid)
            or summary.get("contextId") != cid
            or summary.get("schemaVersion") != "argus-unified-brief-v1"
            or summary.get("actionAuthority") is not False
            or summary.get("ownerContextAvailable") is not False
            or summary.get("historyStatus") not in ("PROCESS_MEMORY_ONLY", "LOCAL_DURABLE")):
        return False
    refs = {}
    for key in ("facts", "previousFacts"):
        rows = context.get(key)
        if not isinstance(rows, list) or len(rows) > 64 or not all(fact(r) for r in rows):
            return False
        ids = [r.get("evidenceId") for r in rows if isinstance(r, dict)]
        if len(ids) != len(rows) or any(not isinstance(i, str) or not re.fullmatch(
                r"brief-fact-[a-f0-9]{64}", i) for i in ids) or len(set(ids)) != len(ids):
            return False
        refs[key] = {r["evidenceId"]: r for r in rows}
    sections = summary.get("sections")
    if not isinstance(sections, dict) or set(sections) != set(SECTIONS):
        return False
    for key, row in sections.items():
        if not isinstance(row, dict):
            return False
        text, ids, kind = row.get("textJa"), row.get("evidenceIds"), row.get("kind")
        allowed = {**refs["previousFacts"], **refs["facts"]} if key == "changes" else refs["facts"]
        if (not isinstance(text, str) or not text.strip() or len(text) > 240
                or kind not in ("FACT", "INFERENCE", "UNKNOWN")
                or not isinstance(ids, list) or len(ids) > 6
                or any(not isinstance(i, str) or i not in allowed for i in ids)
                or len(set(ids)) != len(ids) or (kind != "UNKNOWN" and not ids)
                or (key == "impact" and kind != "UNKNOWN")
                or (key == "changes" and not refs["previousFacts"] and kind != "UNKNOWN")
                or (kind == "FACT" and (key in ("view", "impact", "next", "invalidation")
                    or any(allowed[i].get("verification") != "VERIFIED" for i in ids)))):
            return False
    return True


def event_title(event):
    raw = str(event.get("title") or "").strip()
    patterns = [(r"^US Treasury (\d+)-Year Auction$", lambda m: f"米{m[1]}年債入札"),
                (r"^US CPI", lambda m: "米消費者物価指数(CPI)"),
                (r"^US PPI", lambda m: "米生産者物価指数(PPI)"),
                (r"^US PCE", lambda m: "米PCE物価指数(個人所得・支出)"),
                (r"^US Employment Situation$", lambda m: "米雇用統計"),
                (r"^FOMC", lambda m: "FOMC(米政策金利)"),
                (r"^(BOJ|Bank of Japan)", lambda m: "日銀金融政策決定会合")]
    for pattern, render in patterns:
        match = re.match(pattern, raw, re.I)
        if match:
            return render(match)
    return raw


def compose(response, events, *, now):
    response = response if isinstance(response, dict) else {}
    edition = response if _readable(response, now) else response.get("retainedPresentation")
    if not _readable(edition, now):
        edition = None
    worker = (response.get("generationWorker") or {}).get("status")
    retained = bool(edition and (edition is not response or worker in (
        "RUNNING", "FAILED", "INVALID_RESPONSE", "UNAVAILABLE")))
    state = ("更新失敗・保存版" if worker in ("FAILED", "INVALID_RESPONSE", "UNAVAILABLE")
             else "作成中・保存版" if worker == "RUNNING" else "保存版") if retained else "保存した見立て"
    lines = ["ARGUSの今日の見立て"]
    selected = {}
    if edition:
        selected = {k: edition["unifiedSummary"]["sections"][k]["textJa"] for k in LABELS}
        at = _instant(edition["generatedAt"])
        lines += [f"{state}・作成 {at.astimezone(JST):%m/%d %H:%M}（日本時間）"]
        if now - at > timedelta(hours=1):
            lines.append("作成から1時間以上経過しています。現在の価格・受領とは別です。")
        # Keep whole sections inside ntfy's 4096-byte budget, including
        # multibyte symbols. Never cut a sentence midway through a word.
        for key in ("view", "reasons", "next", "invalidation"):
            candidate = lines + ["", LABELS[key], selected[key]]
            if len("\n".join(candidate).encode("utf-8")) > 3700:
                lines += ["", "続きはTodayの同じ保存版で確認できます。"]
                break
            lines = candidate
    else:
        lines += ["統合AIの見立ては更新待ちです。現在の見立ては未確認です。"]
    top_events = []
    calendar_available = (events or {}).get("status") in ("live", "partial")
    for event in (events or {}).get("events", []) if calendar_available else []:
        if not isinstance(event, dict) or event.get("status") != "live" or event.get("impact") != "high":
            continue
        days = event.get("daysUntil")
        if type(days) is not int or days < 0 or not event.get("id"):
            continue
        at = _instant(event.get("eventTimeUtc"))
        date = event.get("eventDate")
        if at:
            if at < now:
                continue
            when = at.astimezone(JST).strftime("%m/%d %H:%M（日本時間・予定）")
        elif isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            when = date.replace("-", "/") + "（予定・時刻未確認）"
        else:
            continue
        top_events.append({"id": event["id"], "title": event_title(event),
                           "escalation": event.get("escalation"), "daysUntil": days, "whenJa": when})
    top_events.sort(key=lambda e: (e["daysUntil"], e["id"]))
    lines += ["", "Todayと同じ保存版の要約です。売買指示ではありません。"]
    text = "\n".join(lines)
    assert len(text.encode("utf-8")) <= 4096
    signature = hashlib.sha256(json.dumps(selected.get("view"), ensure_ascii=False).encode()).hexdigest() if edition else None
    return {"engineVersion": SCHEMA, "status": "live" if edition else "unavailable",
            "dateJst": now.astimezone(JST).strftime("%Y-%m-%d"), "asOf": now.isoformat(),
            "textJa": text, "edition": {"status": state if edition else "更新待ち",
                "generatedAt": edition.get("generatedAt") if edition else None,
                "contextId": edition["unifiedSummary"]["contextId"] if edition else None,
                "viewSignature": signature, "retained": retained, "sections": selected},
            "topEvents": top_events[:5], "calendarAvailable": calendar_available,
            "automaticAiCalls": 0, "externalFetches": 0,
            "finalDecisionAuthorityActive": False}


def diff(digest, previous):
    """Existing Actions state cache only. Migration quietly seeds new authority."""
    if digest.get("engineVersion") != SCHEMA:
        return previous, None
    edition = digest.get("edition") or {}
    urgent = {f"{e['id']}@{e['escalation']}": e for e in digest.get("topEvents", [])
              if e.get("escalation") in ("D", "D-1")}
    state = {"schemaVersion": SCHEMA, "viewSignature": edition.get("viewSignature"),
             "urgent": sorted(urgent)}
    if previous.get("schemaVersion") != SCHEMA:
        return state, None
    changes = []
    old = previous.get("viewSignature")
    if old and state["viewSignature"] and old != state["viewSignature"]:
        changes.append("統合AIの見立てが変わりました。")
    if not state["viewSignature"]:
        state["viewSignature"] = old  # Missing edition is not a posture flip.
    for identity, event in urgent.items():
        if identity not in previous.get("urgent", []):
            changes.append(f"重要イベント接近: {event['title']} — {event['whenJa']}")
    if not digest.get("calendarAvailable"):
        state["urgent"] = previous.get("urgent", [])
    if not changes:
        return state, None
    # Event notice and saved market edition are explicitly separate facts.
    text = "【ARGUSの更新】\n" + "\n".join(changes) + "\n\n" + digest["textJa"]
    if len(text.encode("utf-8")) > 4096:
        text = "【ARGUSの更新】\n" + "\n".join(changes) + "\n\n今の見立て\n" + str(
            edition.get("sections", {}).get("view") or "統合AIの見立ては更新待ちです。") + "\n作成: " + str(
            edition.get("generatedAt") or "未確認") + "\n続きはTodayの同じ保存版で確認できます。売買指示ではありません。"
    return state, text
