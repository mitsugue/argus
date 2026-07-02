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
