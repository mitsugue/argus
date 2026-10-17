"""Cached price evidence for the existing owner-gated JP quote reader."""

FIELDS = ("schemaVersion", "provider", "authority", "status", "enabled",
          "displayApproved", "mode", "shadowOnly", "authoritative",
          "executionCapability", "providerHealth", "marketPhase", "updatedAt")
ROW_FIELDS = ("provider", "authority", "symbol", "price", "previousClose",
              "changeAbs", "changePct", "volume", "vwap", "bestBid", "bestAsk",
              "bidQty", "askQty", "sourceTimestamp",
              "sourceTimestampPrecision", "receivedAt", "freshUntil",
              "freshness", "marketStatus", "realtimeClassification")


def quote_document(evidence, requested, *, read_at):
    """No I/O/start/normalization; preserve original source and receipt times."""
    if not isinstance(evidence, dict) or evidence.get("provider") != "TACHIBANA":
        return None
    out = {key: evidence.get(key) for key in FIELDS}
    out["readAt"] = read_at  # This cache read's time, never the price's time.
    from datetime import datetime
    import argus_market_clock
    moment = datetime.fromisoformat(read_at.replace('Z', '+00:00'))
    session = argus_market_clock.market_session(argus_market_clock.JP_EQUITY, moment)
    out["cashSessionOpen"] = session['session'] in ('MORNING_SESSION', 'AFTERNOON_SESSION')
    out["quoteRequestedSymbols"] = list(dict.fromkeys(requested))[:50]
    rows = evidence.get("symbols")
    rows = rows if isinstance(rows, dict) else {}
    out["symbols"] = {
        symbol: {key: rows[symbol].get(key) for key in ROW_FIELDS}
        for symbol in tuple(dict.fromkeys(requested))[:50]
        if symbol in rows and isinstance(rows[symbol], dict)
        and rows[symbol].get("provider") == "TACHIBANA"
    }
    return out
