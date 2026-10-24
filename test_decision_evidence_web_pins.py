"""2026-10-25: the browser rejects decision evidence whose policy identity is
not the one pinned in web/src/domain/canonicalDecisionEvidence.ts (fail
closed). The Market Truth priority changed on 10/23 and 10/24 and the
Japanese market engine registry had drifted earlier, so every evidence entry
was rejected and Today's current decision showed "データ待ち" while the
server reported all references AVAILABLE. A policy change must now update
the browser pin in the same change."""
import pathlib
import re

import argus_market_data_truth
import argus_single_decision
import jp_market_engine as jp_market_engine_authority

WEB_PINS = pathlib.Path(__file__).resolve().parent / "web" / "src" / "domain" / "canonicalDecisionEvidence.ts"


def _pin(name):
    text = WEB_PINS.read_text(encoding="utf-8")
    block = re.search(name + r" = Object\.freeze\(\{(.*?)\}\);", text, re.S)
    assert block, name
    policy_id = re.search(r"policyId: '([^']+)'", block.group(1)).group(1)
    sha = re.search(r"policySha256: '([0-9a-f]{64})'", block.group(1)).group(1)
    return policy_id, sha


def test_market_truth_pin_matches_the_server_reference():
    assert _pin("MARKET_TRUTH_POLICY") == (
        argus_market_data_truth.AUTHORITY_POLICY_ID,
        argus_single_decision._canonical_sha(argus_market_data_truth.repository_authority_policy()),
    )


def test_jp_market_engine_pin_matches_the_server_reference():
    assert _pin("JP_MARKET_ENGINE_POLICY") == (
        jp_market_engine_authority.JP_MARKET_ENGINE_REGISTRY_VERSION,
        jp_market_engine_authority.JP_MARKET_ENGINE_REGISTRY_SHA256,
    )
