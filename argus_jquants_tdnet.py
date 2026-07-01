"""ARGUS V11.1 — official J-Quants TDnet Document Add-on: pure classify/map/status.

Stdlib-only, no network. The authenticated fetch lives in scanner.py (it owns the
J-Quants v2 auth: header {"x-api-key": JQUANTS_API_KEY}, base https://api.jquants.com/v2).
This module normalises a TDnet /td/list row, decides whether a disclosure is MATERIAL
enough to be an official_catalyst (vs a mere official_fact), maps HTTP codes to an honest
status, and separates official J-Quants from the third-party yanoshin fallback.

Discipline: an official disclosure is an OFFICIAL CONFIRMATION of the fact. Only clearly
material categories can be an official_catalyst, and even then only if the disclosure did
NOT post-date the price move (timing gates immediate-trigger). Ambiguous titles stay
official_fact — never a confirmed cause.
"""
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "jquants-tdnet-v1"

# Categories (from argus_tdnet.classify_disclosure) that are material enough that the
# disclosure TITLE alone can be an official_catalyst.
MATERIAL_CATEGORIES = {
    "guidance_down", "guidance_up", "dividend_cut", "dividend_up", "dilution",
    "buyback", "delisting", "impairment", "special_loss", "restatement",
    "audit_issue", "insolvency",
}

# HTTP → honest status vocabulary.
def status_from_http(http_status: Optional[int], *, has_rows: bool = False) -> str:
    if http_status == 200:
        return "official_tdnet_live" if has_rows else "live"
    if http_status in (401, 403):
        return "entitlement_missing"
    if http_status == 404:
        return "endpoint_not_found"
    if http_status == 429:
        return "rate_limited"
    return "unavailable"


def is_material(category: Optional[str]) -> bool:
    return (category or "") in MATERIAL_CATEGORIES


def normalize_row(raw: Dict[str, Any], classify_fn) -> Dict[str, Any]:
    """Map ONE J-Quants TDnet /td/list row → normalized item. `classify_fn` is
    argus_tdnet.classify_disclosure (injected to keep this module network/dep-free).
    J-Quants v2 fields vary; read defensively and never fabricate a field."""
    def pick(*keys):
        for k in keys:
            v = raw.get(k)
            if v not in (None, ""):
                return v
        return None
    title = pick("Title", "title", "DisclosureTitle", "DocumentTitle") or ""
    code = pick("Code", "code", "LocalCode", "SecuritiesCode")
    if code:
        code = str(code)[:4] if str(code).isdigit() and len(str(code)) == 5 else str(code)
    cls = classify_fn(title) if title else {"category": "other", "sentiment": "neutral", "categoryJa": "適時開示"}
    return {
        "symbol": code,
        "company": pick("CompanyName", "companyName", "Name"),
        "title": title,
        "disclosedAt": pick("PubDate", "DisclosedDate", "DisclosedTime", "disclosedAt", "Date"),
        "documentId": pick("DocumentID", "documentId", "DisclosureNumber", "Id"),
        "category": cls.get("category"),
        "categoryJa": cls.get("categoryJa"),
        "sentiment": cls.get("sentiment"),
        "material": is_material(cls.get("category")),
        "provider": "jquants-tdnet",
        "official": True,
    }


def event_confirmation(item: Dict[str, Any], *, move_started_at: Optional[str] = None) -> Dict[str, Any]:
    """How an official TDnet item attaches to an EventCard. Official = a real official
    confirmation. triggerRole:
      - material + (timing unknown or disclosure BEFORE the move) → official_catalyst
      - material but disclosure AFTER the move → amplifier/background (never immediate trigger)
      - not material → official_fact (confirmation of a fact, not a cause)."""
    disclosed = str(item.get("disclosedAt") or "")
    after_move = bool(move_started_at and disclosed and disclosed > str(move_started_at))
    if not item.get("material"):
        role = "official_fact"
    elif after_move:
        role = "background_confirmation"          # post-move → not an immediate trigger
    else:
        role = "official_catalyst"
    return {
        "corroborationLevel": "official",
        "triggerRole": role,
        "isOfficial": True,
        "sourceTier": "exchange_or_listing_venue",   # TDnet = the listing venue's disclosure system
        "caveatJa": ("材料性のある公式開示（official_catalyst候補）。ただし値動きより後の開示は引き金にしません。"
                     if item.get("material") else "公式の事実開示（official_fact）。単独では原因確定にしません。"),
    }


def build_snapshot(items: List[Dict[str, Any]], *, status: str, official: bool,
                   provider: str, entitlement: str, as_of: str, note_ja: str = "") -> Dict[str, Any]:
    """Assemble the get_tdnet_recent() return shape (official or fallback)."""
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        s = it.get("symbol")
        if s:
            by_symbol.setdefault(str(s), []).append(it)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "provider": provider,
        "official": official,
        "asOf": as_of,
        "items": items,
        "bySymbol": by_symbol,
        "entitlement": entitlement,
        "noteJa": note_ja,
    }
