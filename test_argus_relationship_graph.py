"""Cross-market relationship graph (argus_relationship_graph, §15, graph-v1).

Asserts the safety/correctness contract: sane adjacency for MU and 5801, every
propagation candidate carries the non-causality caveat, and versioned metadata.
No network, no LLM.
"""
import argus_relationship_graph as G


# ── graph_meta / versioning ──
def test_graph_meta_version_and_counts():
    m = G.graph_meta()
    assert m["version"] == "graph-v1"
    assert m["nodeCount"] >= 8 and m["edgeCount"] > m["nodeCount"]
    assert m["themeCount"] == len(G.THEMES) >= 10
    # the spec's required themes are all present
    for th in ("memory_semis", "ai_compute", "datacenter", "jp_tech_sentiment",
               "rates_growth", "energy", "banks", "defense", "utilities",
               "crypto_liquidity"):
        assert th in G.THEMES


# ── themes_of ──
def test_themes_of_mu_and_5801():
    assert "memory_semis" in G.themes_of("MU")
    # case-insensitive, never invents for unknowns
    assert G.themes_of("mu") == G.themes_of("MU")
    t5801 = G.themes_of("5801")
    assert "datacenter" in t5801 and "ai_compute" in t5801
    assert G.themes_of("ZZZZ_NOT_A_SYMBOL") == []


# ── related_assets ──
def test_related_assets_mu_includes_jp_competitor():
    rel = G.related_assets("MU")
    syms = {r["symbol"] for r in rel}
    # MU <-> 285A (キオクシア) competitor link; ETF hubs present, themes excluded
    assert "285A" in syms
    assert any(r["relation"] == "competitor" for r in rel)
    assert "memory_semis" not in syms  # themes are not assets
    for r in rel:
        assert set(r.keys()) == {"symbol", "relation", "note"}
        assert r["relation"] in G.EDGE_TYPES


def test_related_assets_5801_has_competitor_and_reverse():
    rel = G.related_assets("5801")
    syms = {r["symbol"] for r in rel}
    # 5803 (フジクラ) is a co-member competitor; reverse edge from 5803 surfaces it
    assert "5803" in syms


# ── propagation_candidates: the core safety property ──
def test_every_candidate_carries_non_causality_caveat():
    for sym in ("MU", "5801", "NVDA", "9984", "BTC"):
        cands = G.propagation_candidates(sym)
        assert cands, f"expected candidates for {sym}"
        for c in cands:
            assert set(c.keys()) == {"symbol", "via", "caveatJa"}
            assert c["symbol"] != sym  # never proposes itself
            # caveat must explicitly disclaim causation
            assert c["caveatJa"] == G.PROPAGATION_CAVEAT_JA
            assert "因果" in c["caveatJa"]


def test_propagation_mu_reaches_jp_via_memory_theme():
    syms = {c["symbol"] for c in G.propagation_candidates("MU")}
    # MU should reach the JP memory name 285A via the shared memory_semis theme
    assert "285A" in syms


def test_propagation_5801_reaches_peer():
    syms = {c["symbol"] for c in G.propagation_candidates("5801")}
    assert "5803" in syms


def test_unknown_symbol_is_empty_not_invented():
    assert G.propagation_candidates("ZZZZ_NOT_A_SYMBOL") == []
    assert G.related_assets("ZZZZ_NOT_A_SYMBOL") == []


# ── honesty: caveat present in module surface ──
def test_caveat_disclaims_causation_and_prediction():
    cav = G.PROPAGATION_CAVEAT_JA
    assert "因果" in cav and "予測" in cav
    assert G.graph_meta()["caveatJa"] == cav
