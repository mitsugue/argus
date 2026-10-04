"""Analyst target-price changes read from news headlines (2026-10-04).

Only what a headline states is kept: the company, the firm named in the
headline (never inferred from wording such as "a mid-sized Japanese
broker"), the direction (raised, cut, kept, initiated), the prices when the
headline gives them, the date and the source. Coverage is partial by
nature: a change no headline reports is not known. Reprints of the same
change are counted once. Nothing here is a forecast or a trading signal.
Pure: no network, no clock.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "argus-target-price-news-v1"
# Firms written out in headlines. A headline naming none of these keeps the
# firm as unknown rather than guessing.
FIRMS = (
    "ゴールドマン・サックス", "ゴールドマン", "モルガン・スタンレーMUFG", "モルガンMUFG", "モルガン・スタンレー",
    "JPモルガン", "シティグループ", "シティ", "UBS", "バークレイズ", "BofA", "メリルリンチ", "ジェフリーズ",
    "マッコーリー", "CLSA", "ドイツ証券", "野村證券", "野村証券", "野村", "大和証券", "大和", "SMBC日興証券",
    "SMBC日興", "みずほ証券", "みずほ", "三菱UFJモルガン・スタンレー", "岡三証券", "岡三", "東海東京証券",
    "東海東京", "いちよし証券", "いちよし", "SBI証券", "SBI", "楽天証券", "マネックス証券", "水戸証券",
)
DIRECTIONS = (
    ("引き上げ", "RAISED"), ("上げ", "RAISED"), ("引き下げ", "CUT"), ("下げ", "CUT"),
    ("据え置き", "KEPT"), ("据え置", "KEPT"), ("新規", "INITIATED"), ("カバレッジ開始", "INITIATED"),
)
_PRICE_PAIR = re.compile(r"([0-9][0-9,]*)円?\s*(?:→|から|->|⇒)\s*([0-9][0-9,]*)円")
_PRICE_ONE = re.compile(r"目標株価\s*([0-9][0-9,]*)円")


def _yen(text: str) -> Optional[int]:
    try:
        return int(text.replace(",", ""))
    except ValueError:
        return None


def parse_headline(title: str, *, company: str, code: str) -> Optional[Dict[str, Any]]:
    """One change from one headline, or None when it is not one."""
    text = unicodedata.normalize("NFKC", title or "")
    if "目標株価" not in text or (company not in text and code not in text):
        return None
    direction = next((value for word, value in DIRECTIONS if word in text), None)
    pair = _PRICE_PAIR.search(text)
    single = _PRICE_ONE.search(text)
    if direction is None and not pair and not single:
        return None
    firm = next((name for name in FIRMS if unicodedata.normalize("NFKC", name) in text
                 and unicodedata.normalize("NFKC", name) not in unicodedata.normalize("NFKC", company)), None)
    before = _yen(pair.group(1)) if pair else None
    after = _yen(pair.group(2)) if pair else (_yen(single.group(1)) if single else None)
    if direction is None and before and after:
        direction = "RAISED" if after > before else "CUT" if after < before else "KEPT"
    return {"code": code, "company": company, "firm": firm, "direction": direction,
            "before": before, "after": after}


def collect(items: Iterable[Mapping[str, Any]], *, company: str, code: str) -> List[Dict[str, Any]]:
    """Changes from feed items {title, link, published (ISO), source}, newest first, reprints merged."""
    seen, out = set(), []
    for item in items or ():
        change = parse_headline(str(item.get("title") or ""), company=company, code=code)
        if not change:
            continue
        day = str(item.get("published") or "")[:10]
        # The same firm, direction and prices on the same day is one change.
        key = (change["firm"], change["direction"], change["before"], change["after"], day)
        if key in seen:
            continue
        seen.add(key)
        out.append({**change, "date": day or None, "headline": str(item.get("title"))[:160],
                    "sourceRef": str(item.get("link") or "")[:300], "sourceName": str(item.get("source") or "")[:60],
                    "changeId": "tp-" + hashlib.sha256(repr(key + (code,)).encode()).hexdigest()[:24],
                    "coverage": "HEADLINES_ONLY", "actionAuthority": False})
    return sorted(out, key=lambda row: row["date"] or "", reverse=True)
