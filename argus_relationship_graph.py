"""ARGUS — §15 Cross-Market Relationship Graph (pure, deterministic, versioned).

A small, hand-curated graph connecting assets, themes and macro sensitivities so
ARGUS can REASON about how a move in one name might propagate across US / Japan /
crypto / FX desks. It answers "what is structurally adjacent to X?" — NOT "X moved,
therefore Y will move."

Hard epistemic rule (mirrors argus_attribution.classify_contagion):
  * GRAPH MEMBERSHIP IS NOT CAUSATION. Two names sharing a theme, an ETF, or a
    supplier link are *candidates* for co-movement; whether they actually move
    together must be confirmed from real, timestamped price/flow data elsewhere.
    Every propagation candidate this module emits carries that caveat in Japanese.
  * No trade instruction, ever. Decision-support only. UNCALIBRATED adjacency.

Stdlib-only; no network, no LLM, no secrets. Pure functions: all inputs are
arguments; nothing reaches into scanner.py. May reference argus_research_mesh for
the shared 5-category vocabulary, but does not require it at runtime.
"""
from __future__ import annotations

from typing import Any, Dict, List

# argus_research_mesh is the sibling Phase-1 engine. We import it only to stay
# aligned with the shared schema vocabulary; the graph itself is self-contained.
try:  # pragma: no cover - import shim
    import argus_research_mesh as M  # noqa: F401
except Exception:  # pragma: no cover
    M = None  # type: ignore

GRAPH_VERSION = "graph-v1"

# Honest, fixed caveat attached to EVERY propagation candidate. Membership in the
# graph is a structural hint, never a causal claim or a prediction.
PROPAGATION_CAVEAT_JA = (
    "グラフ上の関連は構造的な隣接にすぎず、因果でも予測でもない。"
    "実際に同時に動いているかは、別途の時刻付き価格・フローで確認すること。"
)

# ── Edge types (§15) ─────────────────────────────────────────────────────────
EDGE_TYPES = {
    "competitor",       # same product market, rival
    "supplier",         # sells into the other / upstream
    "customer",         # buys from the other / downstream
    "sector",           # same operating sector
    "theme",            # shares a narrative/demand theme
    "etf_index",        # constituent of / proxied by an index/ETF
    "macro_sensitivity",# sensitive to a macro factor (rates, energy, FX...)
    "sentiment_proxy",  # widely read as a barometer for a broader mood
}

# ── Themes (§15) — narrative / demand clusters, market-neutral labels ─────────
THEMES: Dict[str, Dict[str, str]] = {
    "memory_semis":     {"label": "メモリ半導体(DRAM/NAND)", "market": "global"},
    "ai_compute":       {"label": "AI計算(GPU/アクセラレータ)", "market": "global"},
    "datacenter":       {"label": "データセンター/インフラ", "market": "global"},
    "jp_tech_sentiment":{"label": "日本テックの地合い", "market": "jp"},
    "rates_growth":     {"label": "金利・グロース感応度", "market": "macro"},
    "energy":           {"label": "エネルギー", "market": "macro"},
    "banks":            {"label": "銀行/金融", "market": "global"},
    "defense":          {"label": "防衛", "market": "global"},
    "utilities":        {"label": "公益", "market": "macro"},
    "crypto_liquidity": {"label": "暗号資産の流動性", "market": "crypto"},
}

# ── Asset nodes + outbound edges ─────────────────────────────────────────────
# Each edge: {"to": <symbol|theme>, "type": <EDGE_TYPES>, "note": <ja, optional>}.
# Edges are DIRECTED as authored; related_assets() also surfaces reverse links so
# adjacency is symmetric for reasoning. Theme edges point at THEMES keys.
GRAPH: Dict[str, List[Dict[str, str]]] = {
    # ── US semis / AI complex ──
    "MU": [
        {"to": "memory_semis", "type": "theme"},
        {"to": "SMH", "type": "etf_index"},
        {"to": "SOX", "type": "etf_index"},
        {"to": "285A", "type": "competitor", "note": "DRAM/NANDで競合(キオクシア)"},
        {"to": "rates_growth", "type": "macro_sensitivity"},
    ],
    "NVDA": [
        {"to": "ai_compute", "type": "theme"},
        {"to": "datacenter", "type": "theme"},
        {"to": "SMH", "type": "etf_index"},
        {"to": "SOX", "type": "etf_index"},
        {"to": "rates_growth", "type": "macro_sensitivity"},
    ],
    # ETF / index nodes acting as the semiconductor-complex hub.
    "SMH": [
        {"to": "us_semis", "type": "sector", "note": "米半導体コンプレックスの代理"},
        {"to": "ai_compute", "type": "theme"},
        {"to": "memory_semis", "type": "theme"},
    ],
    "SOX": [
        {"to": "us_semis", "type": "sector", "note": "フィラデルフィア半導体指数"},
        {"to": "SMH", "type": "etf_index"},
    ],
    # ── Japan watchlist ──
    "285A": [  # キオクシア — JP memory
        {"to": "memory_semis", "type": "theme"},
        {"to": "MU", "type": "competitor", "note": "DRAM/NANDで競合"},
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
    ],
    "5801": [  # 古河電工 — AI/datacenter infra (光配線・電線)
        {"to": "datacenter", "type": "theme"},
        {"to": "ai_compute", "type": "theme", "note": "AI向け光インフラ需要"},
        {"to": "SMH", "type": "macro_sensitivity", "note": "米半導体地合いに感応"},
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
    ],
    "5803": [  # フジクラ — AI/datacenter infra (光ファイバ)
        {"to": "datacenter", "type": "theme"},
        {"to": "ai_compute", "type": "theme", "note": "AI向け光インフラ需要"},
        {"to": "5801", "type": "competitor", "note": "光インフラで同業"},
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
    ],
    "9984": [  # ソフトバンクG — global tech sentiment proxy
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
        {"to": "ai_compute", "type": "theme", "note": "AI関連投資ポートフォリオ"},
        {"to": "rates_growth", "type": "macro_sensitivity"},
    ],
    "6920": [  # レーザーテック — semi inspection equipment
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
        {"to": "memory_semis", "type": "customer", "note": "半導体製造装置(検査)"},
        {"to": "SMH", "type": "macro_sensitivity"},
    ],
    "6857": [  # アドバンテスト — semi test equipment
        {"to": "ai_compute", "type": "customer", "note": "AI半導体テスタ需要"},
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
        {"to": "SMH", "type": "macro_sensitivity"},
    ],
    "8035": [  # 東京エレクトロン — semi production equipment
        {"to": "memory_semis", "type": "supplier", "note": "前工程製造装置"},
        {"to": "jp_tech_sentiment", "type": "sentiment_proxy"},
        {"to": "SMH", "type": "macro_sensitivity"},
    ],
    "8306": [  # 三菱UFJ — JP bank
        {"to": "banks", "type": "sector"},
        {"to": "rates_growth", "type": "macro_sensitivity", "note": "金利に正の感応(逆向き)"},
    ],
    # ── crypto / FX adjacency (kept minimal, honest) ──
    "BTC": [
        {"to": "crypto_liquidity", "type": "theme"},
        {"to": "rates_growth", "type": "macro_sensitivity", "note": "リスク資産・流動性に感応"},
    ],
    "ETH": [
        {"to": "crypto_liquidity", "type": "theme"},
        {"to": "BTC", "type": "sentiment_proxy", "note": "暗号資産の地合いの代理"},
    ],
}

# ── reverse index: theme/symbol -> [symbols that point at it] ────────────────
_REVERSE: Dict[str, List[Dict[str, str]]] = {}
for _src, _edges in GRAPH.items():
    for _e in _edges:
        _REVERSE.setdefault(_e["to"], []).append(
            {"from": _src, "type": _e["type"], "note": _e.get("note", "")}
        )


def _sym(symbol: str) -> str:
    return (symbol or "").strip().upper()


# ── Public API ───────────────────────────────────────────────────────────────
def themes_of(symbol: str) -> List[str]:
    """All THEMES keys this symbol is attached to (via any theme/sentiment edge).
    Empty list for unknown symbols — never invented."""
    s = _sym(symbol)
    out: List[str] = []
    for e in GRAPH.get(s, []):
        to = e["to"]
        if to in THEMES and to not in out:
            out.append(to)
    return out


def related_assets(symbol: str) -> List[Dict[str, Any]]:
    """Adjacent ASSET nodes (not themes) — forward edges plus reverse edges so the
    relationship is usable in both directions. Each: {symbol, relation, note}.
    Theme co-membership is handled by propagation_candidates(), not here."""
    s = _sym(symbol)
    out: List[Dict[str, Any]] = []
    seen = set()
    for e in GRAPH.get(s, []):
        to = e["to"]
        if to in THEMES:
            continue
        key = (to, e["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"symbol": to, "relation": e["type"], "note": e.get("note", "")})
    for r in _REVERSE.get(s, []):
        src = r["from"]
        key = (src, r["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"symbol": src, "relation": r["type"],
                    "note": r.get("note", "") or "逆方向の関連"})
    return out


def propagation_candidates(symbol: str) -> List[Dict[str, Any]]:
    """Names structurally adjacent to `symbol` that are CANDIDATES for co-movement.
    Combines (a) direct asset edges and (b) theme co-members. EVERY candidate
    carries `caveatJa` restating that graph membership is not causality and must be
    confirmed from real price/flow. Returns [] for unknown symbols."""
    s = _sym(symbol)
    out: List[Dict[str, Any]] = []
    seen = set()

    def _add(sym: str, via: str):
        if sym == s or sym in seen:
            return
        seen.add(sym)
        out.append({"symbol": sym, "via": via, "caveatJa": PROPAGATION_CAVEAT_JA})

    # (a) direct asset relations (competitor/supplier/customer/etf/sentiment...)
    for r in related_assets(s):
        _add(r["symbol"], r["relation"])

    # (b) theme co-members: any other asset on a shared theme is a candidate.
    for th in themes_of(s):
        for r in _REVERSE.get(th, []):
            _add(r["from"], th)

    return out


def graph_meta() -> Dict[str, Any]:
    """Versioned summary for provenance/UI. nodeCount = asset nodes; edgeCount =
    authored directed edges; themeCount = THEMES."""
    edge_count = sum(len(v) for v in GRAPH.values())
    return {
        "version": GRAPH_VERSION,
        "nodeCount": len(GRAPH),
        "edgeCount": edge_count,
        "themeCount": len(THEMES),
        "edgeTypes": sorted(EDGE_TYPES),
        "caveatJa": PROPAGATION_CAVEAT_JA,
    }
