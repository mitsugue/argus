"""ARGUS V11.5 — news headline i18n helpers (pure, deterministic).

Public GETs must not call an LLM, so English→Japanese translation happens on the
admin/cron path and is cached by content hash. These pure helpers decide WHAT needs
translation and provide the cache lookup/merge. The scanner owns the (admin-only)
LLM translate call and the cache persistence.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

# A headline "looks translatable" (i.e. probably English) when it is mostly Latin
# letters and contains no CJK — Japanese text is left as-is.
_CJK = re.compile(r"[぀-ヿ㐀-䶵一-鿋豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")


def text_hash(text: str) -> str:
    return hashlib.md5((text or "").strip().encode("utf-8")).hexdigest()[:16]


def looks_translatable(text: Optional[str]) -> bool:
    s = (text or "").strip()
    if len(s) < 4:
        return False
    if _CJK.search(s):
        return False                      # already contains Japanese
    letters = _LATIN.findall(s)
    return len(letters) >= 4              # enough Latin letters to be English prose


def pick_ja(text: Optional[str], cache: Dict[str, Dict[str, Any]]) -> str:
    """Return the Japanese headline: the cached translation if present, else the
    original text (Japanese text passes straight through; untranslated English is
    returned as-is until the admin cron fills the cache)."""
    s = (text or "").strip()
    if not looks_translatable(s):
        return s
    hit = (cache or {}).get(text_hash(s))
    if hit and hit.get("ja"):
        return str(hit["ja"])
    return s


def is_translated(text: Optional[str], cache: Dict[str, Dict[str, Any]]) -> bool:
    s = (text or "").strip()
    if not looks_translatable(s):
        return True                       # nothing to translate
    hit = (cache or {}).get(text_hash(s))
    return bool(hit and hit.get("ja"))


def collect_pending(texts: List[str], cache: Dict[str, Dict[str, Any]],
                    cap: int = 40) -> List[str]:
    """Distinct English headlines not yet in the cache (for the admin translate run)."""
    out, seen = [], set()
    for t in texts or []:
        s = (t or "").strip()
        if not looks_translatable(s):
            continue
        h = text_hash(s)
        if h in seen or (cache or {}).get(h, {}).get("ja"):
            continue
        seen.add(h)
        out.append(s)
        if len(out) >= cap:
            break
    return out


def merge_translations(cache: Dict[str, Dict[str, Any]], originals: List[str],
                       translations: Dict[int, str], now_iso: str,
                       max_entries: int = 2000) -> Dict[str, Dict[str, Any]]:
    """Fold {index → ja} back into the hash-keyed cache. Bounded size (LRU-ish by at)."""
    out = dict(cache or {})
    for i, orig in enumerate(originals or []):
        ja = translations.get(i)
        if ja and str(ja).strip():
            out[text_hash(orig)] = {"ja": str(ja)[:200], "at": now_iso}
    if len(out) > max_entries:
        for k in sorted(out, key=lambda k: str(out[k].get("at")))[:len(out) - max_entries]:
            out.pop(k, None)
    return out


# ── V11.5.1: UI display fields (Japanese-first; NEVER raw English as primary) ──
_FALLBACK_LABEL = {"pending": "翻訳待ち", "failed": "翻訳未取得"}


def translation_status(text: Optional[str], cache: Dict[str, Dict[str, Any]]) -> str:
    """not_needed (already Japanese) | translated (cached) | pending (English, no cache)."""
    s = (text or "").strip()
    if not looks_translatable(s):
        return "not_needed"
    return "translated" if is_translated(s, cache) else "pending"


def display_title_ja(text: Optional[str], cache: Dict[str, Dict[str, Any]],
                     source: str = "", status: Optional[str] = None) -> str:
    """The headline to SHOW. Japanese passes through; cached English → its translation;
    untranslated English → a Japanese fallback (never the raw English as primary)."""
    s = (text or "").strip()
    st = status or translation_status(s, cache)
    if st == "not_needed":
        return s
    if st == "translated":
        return pick_ja(s, cache)
    src = (source or "").strip()
    return f"{_FALLBACK_LABEL.get(st, '翻訳待ち')}: {src + 'の' if src else ''}関連ニュース"


def decorate(text: Optional[str], cache: Dict[str, Dict[str, Any]], source: str = "") -> Dict[str, Any]:
    """Display fields for one news title string. `titleOriginal` (may be English) is for
    a collapsible '原文を見る'; `displayTitleJa` is always Japanese (or a JP fallback).
    `translationQueueEligible` marks an untranslated English title the UI should enqueue."""
    s = (text or "").strip()
    st = translation_status(s, cache)
    return {
        "titleOriginal": s,
        "titleJa": pick_ja(s, cache),            # backward-compat (cached JA or original)
        "displayTitleJa": display_title_ja(s, cache, source, st),
        "translationStatus": st,
        "translationQueueEligible": st == "pending",   # V11.5.2: UI auto-queues these
    }


def decorate_news_item(item: Dict[str, Any], cache: Dict[str, Dict[str, Any]], *,
                       title_keys=("titleOriginal", "titleJa", "title", "headlineJa", "headline"),
                       source_key: str = "source") -> Dict[str, Any]:
    """Add displayTitleJa/translationStatus/titleOriginal to a news dict. Prefers the
    ORIGINAL text when present so a cached-JA titleJa doesn't hide an English original."""
    if not isinstance(item, dict):
        return item
    orig = ""
    # prefer an explicit English original if the projection stored one
    for k in ("titleEn", "titleOriginal"):
        if item.get(k):
            orig = str(item[k])
            break
    if not orig:
        for k in title_keys:
            if item.get(k):
                orig = str(item[k])
                break
    out = dict(item)
    out.update(decorate(orig, cache, str(item.get(source_key) or "")))
    return out


def collect_visible_pending(items: List[Any], cache: Dict[str, Dict[str, Any]],
                            cap: int = 60) -> List[str]:
    """Distinct untranslated English strings from an ORDERED (priority-first) list of
    title strings — the admin translate run drains these first."""
    return collect_pending([str(t) for t in (items or []) if t], cache, cap=cap)


def decorate_from_ja(original: Optional[str], ja: Optional[str], source: str = "") -> Dict[str, Any]:
    """Display fields when the translation is already attached to the item (e.g. the
    market-news pipeline that fills headlineJa via its own cached translate). Uses no
    global cache: JP original → not_needed; a real ja → translated; else JP fallback."""
    orig = (original or "").strip()
    if not looks_translatable(orig):
        return {"titleOriginal": orig, "displayTitleJa": (ja or orig),
                "translationStatus": "not_needed"}
    if ja and str(ja).strip() and str(ja).strip() != orig:
        return {"titleOriginal": orig, "displayTitleJa": str(ja),
                "translationStatus": "translated", "translationQueueEligible": False}
    src = (source or "").strip()
    return {"titleOriginal": orig,
            "displayTitleJa": f"翻訳待ち: {src + 'の' if src else ''}関連ニュース",
            "translationStatus": "pending", "translationQueueEligible": True}


# ── V11.5.2: visible-news translation request queue (bounded, dedupe by title hash) ──
# The public POST endpoint enqueues on-screen English titles; the admin/cron
# translate-visible run drains this FIRST. Only titleOriginal/source/publishedAt/hash/
# context/symbol are stored — never article bodies, prompts, secrets, or provider blobs.

def queue_key_for_title(title_original: Optional[str], source: str = "") -> str:
    """Stable dedupe key for a queued title (same hash the translation cache uses, so a
    title translated via any path is recognised as already-done)."""
    return text_hash(title_original or "")


def visible_queue_add(queue: Dict[str, Dict[str, Any]], items: List[Any],
                      cache: Dict[str, Dict[str, Any]], *, context: str = "",
                      symbol: str = "", market: str = "", now_iso: str = "",
                      max_len: int = 200) -> Dict[str, int]:
    """Enqueue on-screen English news titles for the admin translate-visible run.
    Skips Japanese titles, already-translated titles, and duplicates. Mutates `queue`
    (hash → minimal entry) in place, bounded to max_len (oldest dropped). Returns stats."""
    stats = {"queued": 0, "alreadyTranslated": 0, "alreadyQueued": 0, "ignored": 0}
    for it in (items or []):
        if isinstance(it, dict):
            title = str(it.get("titleOriginal") or it.get("title") or it.get("headline") or "").strip()
            src = str(it.get("source") or source or "")
            pub = str(it.get("publishedAt") or it.get("datetime") or "")
        else:
            title, src, pub = str(it or "").strip(), "", ""
        title = title[:200]
        if not looks_translatable(title):
            stats["ignored"] += 1                 # Japanese / too short → nothing to queue
            continue
        if is_translated(title, cache):
            stats["alreadyTranslated"] += 1
            continue
        h = text_hash(title)
        if h in queue:
            stats["alreadyQueued"] += 1
            queue[h]["lastSeenAt"] = now_iso
            continue
        queue[h] = {
            "hash": h, "titleOriginal": title, "source": src[:40],
            "publishedAt": pub[:40], "context": str(context or "")[:40],
            "symbol": str(symbol or "")[:16].upper(), "market": str(market or "")[:4].upper(),
            "queuedAt": now_iso,
        }
        stats["queued"] += 1
    if len(queue) > max_len:                       # bound: drop oldest by queuedAt
        for k in sorted(queue, key=lambda k: str(queue[k].get("queuedAt")))[:len(queue) - max_len]:
            queue.pop(k, None)
    return stats


def visible_queue_drain(queue: Dict[str, Dict[str, Any]], cache: Dict[str, Dict[str, Any]],
                        max_items: int = 60) -> List[str]:
    """Oldest-first titleOriginal strings still needing translation (peek — does NOT
    mutate; the caller prunes after a successful translate/merge)."""
    out = []
    for k in sorted(queue, key=lambda k: str(queue[k].get("queuedAt"))):
        title = queue[k].get("titleOriginal") or ""
        if is_translated(title, cache):
            continue
        out.append(title)
        if len(out) >= max_items:
            break
    return out


def visible_queue_prune(queue: Dict[str, Dict[str, Any]], cache: Dict[str, Dict[str, Any]]) -> int:
    """Drop entries whose translation is now in the cache. Returns removed count."""
    stale = [k for k in queue if is_translated(queue[k].get("titleOriginal") or "", cache)]
    for k in stale:
        queue.pop(k, None)
    return len(stale)


def translation_queue_status(queue: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Public-safe queue summary (counts + timestamps only — no article bodies)."""
    ats = sorted(str(e.get("queuedAt")) for e in queue.values() if e.get("queuedAt"))
    return {"queuedCount": len(queue),
            "oldestQueuedAt": ats[0] if ats else None,
            "lastQueuedAt": ats[-1] if ats else None}


def queue_samples(queue: Dict[str, Dict[str, Any]], cap: int = 5) -> List[Dict[str, Any]]:
    """Public-safe samples of what's pending: source + short title hash + a truncated
    PUBLIC headline (news headlines are public; no article body). Oldest-first."""
    out = []
    for k in sorted(queue, key=lambda k: str(queue[k].get("queuedAt")))[:cap]:
        e = queue[k]
        out.append({"hash": e.get("hash"), "source": e.get("source"),
                    "symbol": e.get("symbol"), "context": e.get("context"),
                    "titlePreview": str(e.get("titleOriginal") or "")[:80]})
    return out
