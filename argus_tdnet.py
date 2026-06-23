"""ARGUS — TDnet (適時開示) disclosure classifier (pure, deterministic).

ARGUS previously had NO TDnet feed (only metrics measuring whether one would
help). This module classifies TDnet disclosure TITLES into a category + a
coarse sentiment so the Downside layer can attribute a same-day drop to a real,
confirmed corporate disclosure (e.g. 下方修正) instead of "原因未確認".

Pure stdlib — the network fetch lives in scanner (get_tdnet_recent). Sentiment is
a conservative keyword classifier: it only returns "negative" for disclosures
that are clearly bad for holders; ambiguous titles stay "neutral" (要確認). It
never fabricates and never asserts beyond the title text.
"""
from __future__ import annotations

# Order matters: the FIRST matching rule wins, so put specific/severe before
# generic (e.g. 上方修正/下方修正 before the generic 業績予想修正).
# (substrings, category, sentiment)
_RULES = [
    # severe negative
    ("上場廃止", "delisting", "negative"),
    ("債務超過", "insolvency", "negative"),
    ("特別損失", "special_loss", "negative"),
    ("減損", "impairment", "negative"),
    ("下方修正", "guidance_down", "negative"),
    ("業績予想の修正" + "（下方", "guidance_down", "negative"),
    ("無配", "dividend_cut", "negative"),
    ("減配", "dividend_cut", "negative"),
    ("公募増資", "dilution", "negative"),
    ("第三者割当", "dilution", "negative"),
    ("新株式発行", "dilution", "negative"),
    ("新株予約権", "dilution", "negative"),
    ("不適正", "audit_issue", "negative"),
    ("訂正", "restatement", "negative"),
    # positive
    ("上方修正", "guidance_up", "positive"),
    ("増配", "dividend_up", "positive"),
    ("自己株式の取得", "buyback", "positive"),
    ("自己株式取得", "buyback", "positive"),
    ("自社株買", "buyback", "positive"),
    ("株式分割", "split", "positive"),
    # neutral / event
    ("決算短信", "earnings", "neutral"),
    ("業績予想", "guidance", "neutral"),
    ("配当予想", "dividend_forecast", "neutral"),
    ("月次", "monthly", "neutral"),
]

_CATEGORY_JA = {
    "delisting": "上場廃止関連", "insolvency": "債務超過", "special_loss": "特別損失",
    "impairment": "減損", "guidance_down": "業績下方修正", "dividend_cut": "減配/無配",
    "dilution": "増資/希薄化", "audit_issue": "監査問題", "restatement": "訂正開示",
    "guidance_up": "業績上方修正", "dividend_up": "増配", "buyback": "自社株買い",
    "split": "株式分割", "earnings": "決算短信", "guidance": "業績予想", "dividend_forecast": "配当予想",
    "monthly": "月次開示", "other": "適時開示",
}


def classify_disclosure(title: str):
    """Return {category, sentiment, categoryJa} for a TDnet disclosure title.
    Conservative: only clearly-bad titles → 'negative'; ambiguous → 'neutral'."""
    t = title or ""
    # explicit 下方/上方 inside a 業績予想の修正 title
    if "修正" in t and "業績予想" in t:
        if "下方" in t:
            return {"category": "guidance_down", "sentiment": "negative",
                    "categoryJa": _CATEGORY_JA["guidance_down"]}
        if "上方" in t:
            return {"category": "guidance_up", "sentiment": "positive",
                    "categoryJa": _CATEGORY_JA["guidance_up"]}
    for kw, cat, sent in _RULES:
        if kw in t:
            return {"category": cat, "sentiment": sent, "categoryJa": _CATEGORY_JA.get(cat, cat)}
    return {"category": "other", "sentiment": "neutral", "categoryJa": _CATEGORY_JA["other"]}


def is_negative(title: str) -> bool:
    return classify_disclosure(title)["sentiment"] == "negative"


def summarize_for_symbol(disclosures):
    """Collapse a symbol's disclosures into one catalyst summary.
    Returns None if empty. confirmedNegative iff any clearly-negative disclosure."""
    items = [d for d in (disclosures or []) if d.get("title")]
    if not items:
        return None
    cats, negative = [], False
    for d in items[:3]:
        c = classify_disclosure(d["title"])
        cats.append(c["categoryJa"])
        if c["sentiment"] == "negative":
            negative = True
    # de-dup categories, keep order
    seen, uniq = set(), []
    for c in cats:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return {"recent": True, "detail": "TDnet: " + "・".join(uniq),
            "confirmedNegative": negative, "source": "tdnet"}
