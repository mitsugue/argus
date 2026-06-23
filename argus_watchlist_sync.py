"""A.R.G.U.S. — Calibration Ledger v4: owner dynamic watchlist (Layer 2B) sync.

Pure-stdlib validation + immutable daily membership snapshots for scoring the
OWNER'S real watchlist — WITHOUT ever accepting portfolio details. The server may
receive only membership metadata (symbol/market/enabled/timestamps). Quantities,
cost basis, P/L, allocations, notes and trades are HARD-REJECTED.

Privacy rule (the repo is public): owner watchlist symbols must NEVER be written
to the public `ledger` branch. The actual storage is a PRIVATE durable store
(separate private repo) configured out-of-band; until that exists, Layer 2B
server scoring stays DISABLED — this module only validates + shapes data, it does
not persist anything itself.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

SYNC_SCHEMA_VERSION = "layer2b-sync-v1"
MAX_SYMBOLS = 200

# Optional NON-MONETARY flags (v10.100). These carry only "is this held / watched
# / how strict / how important" — NEVER quantity, cost, P/L, or any amount. Each
# is whitelisted to a fixed enum; anything else falls back to the safe default.
OWNER_STATES = ("watch", "active", "held", "protected")
DOWNSIDE_STRICTNESS = ("normal", "strict")
PRIORITIES = ("low", "normal", "high")
_DEFAULT_FLAGS = {"ownerState": "watch", "downsideStrictness": "normal", "priority": "normal"}

# Fields that must NEVER be uploaded. Presence of ANY of these rejects the payload.
FORBIDDEN_FIELDS = frozenset({
    "quantity", "qty", "shares", "averageCost", "avgCost", "purchasePrice",
    "costBasis", "portfolioValue", "value", "unrealizedPL", "unrealizedPnl",
    "pnl", "targetAllocation", "allocation", "notes", "note", "research",
    "trades", "trade", "encryptedPayload", "vault", "holdings",
})

_JP_RE = re.compile(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$")          # 7203 / 285A
_US_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")       # AAPL / BRK.B
_CRYPTO = frozenset({"bitcoin", "ethereum", "solana"})


def _valid_symbol(symbol: str, market: str) -> bool:
    s = (symbol or "").strip()
    m = (market or "").upper()
    if m == "JP":
        return bool(_JP_RE.match(s))
    if m == "US":
        return bool(_US_RE.match(s.upper()))
    if m in ("CRYPTO", "FUND"):
        return bool(s) and len(s) <= 24
    return False


def validate_sync_payload(payload: Any) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """Validate an owner watchlist-sync payload. Returns (ok, cleaned, errors).

    Accepts ONLY: {items: [{symbol, market, enabled?, name?, assetId?,
    includedAt?, removedAt?}], clientAt?}. Rejects any forbidden portfolio field
    anywhere in the structure.
    """
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, None, ["payload must be an object"]

    # Deep scan for forbidden fields (defense in depth)
    def scan(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in FORBIDDEN_FIELDS:
                    errors.append(f"forbidden field rejected: {k}")
                scan(v)
        elif isinstance(obj, list):
            for v in obj:
                scan(v)
    scan(payload)

    items = payload.get("items")
    if not isinstance(items, list):
        errors.append("items must be a list")
        items = []
    if len(items) > MAX_SYMBOLS:
        errors.append(f"too many symbols ({len(items)} > {MAX_SYMBOLS})")

    cleaned_items: List[Dict[str, Any]] = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            errors.append("each item must be an object")
            continue
        sym, mkt = it.get("symbol"), it.get("market")
        if not _valid_symbol(sym, mkt):
            errors.append(f"invalid symbol/market: {sym!r}/{mkt!r}")
            continue
        key = (mkt.upper(), sym)
        if key in seen:
            continue  # idempotent: drop duplicates silently
        seen.add(key)
        ci = {"symbol": sym, "market": mkt.upper(),
              "enabled": bool(it.get("enabled", True))}
        # Non-monetary flags, enum-whitelisted (anything else → safe default).
        ci["ownerState"] = it["ownerState"] if it.get("ownerState") in OWNER_STATES else _DEFAULT_FLAGS["ownerState"]
        ci["downsideStrictness"] = (it["downsideStrictness"] if it.get("downsideStrictness") in DOWNSIDE_STRICTNESS
                                    else _DEFAULT_FLAGS["downsideStrictness"])
        ci["priority"] = it["priority"] if it.get("priority") in PRIORITIES else _DEFAULT_FLAGS["priority"]
        if isinstance(it.get("name"), str):
            ci["name"] = it["name"][:48]
        if isinstance(it.get("assetId"), str) and re.match(r"^[A-Za-z0-9_-]{1,40}$", it["assetId"]):
            ci["assetId"] = it["assetId"]
        for ts in ("includedAt", "removedAt"):
            if isinstance(it.get(ts), str) and len(it[ts]) <= 40:
                ci[ts] = it[ts]
        cleaned_items.append(ci)

    if errors:
        return False, None, errors
    return True, {"items": cleaned_items}, []


def content_hash(items: List[Dict[str, Any]]) -> str:
    """Stable hash of the membership set (order-independent). Includes ownerState
    so a held↔watch change registers as a material membership change."""
    norm = sorted((i["market"], i["symbol"], bool(i.get("enabled", True)),
                   i.get("ownerState", "watch")) for i in items)
    raw = json.dumps(norm, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_membership_snapshot(
    cleaned_items: List[Dict[str, Any]],
    *,
    effective_date: str,
    generated_at: str,
    snapshot_id: str,
) -> Dict[str, Any]:
    """An IMMUTABLE daily membership snapshot. Past snapshots are never rewritten;
    changes after the forecast cutoff apply to the next eligible cycle."""
    enabled = [i for i in cleaned_items if i.get("enabled", True)]
    return {
        "schemaVersion": SYNC_SCHEMA_VERSION,
        "watchlistSnapshotId": snapshot_id,
        "effectiveFrom": effective_date,
        "generatedAt": generated_at,
        "symbolCount": len(enabled),
        "contentHash": content_hash(enabled),
        "members": [{"symbol": i["symbol"], "market": i["market"],
                     "assetId": i.get("assetId"), "name": i.get("name"),
                     "ownerState": i.get("ownerState", "watch"),
                     "downsideStrictness": i.get("downsideStrictness", "normal"),
                     "priority": i.get("priority", "normal")}
                    for i in enabled],
        "cohortId": "owner_watchlist_dynamic",
        "immutable": True,
    }
