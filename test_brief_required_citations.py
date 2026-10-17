"""Fewer correction calls (2026-10-17): the citation rule is stated up front."""
import json
import pathlib
import sqlite3

import argus_analysis_history as history
import argus_macro_material as material

ROOT = pathlib.Path(__file__).resolve().parent


def test_the_required_ids_are_the_ones_the_check_requires():
    facts = [{"evidenceId": "ref-1", "source": "official_macro_result", "priority": "P0"},
             {"evidenceId": "ref-2", "source": "official_macro_result", "priority": "P0"},
             {"evidenceId": "ref-3", "source": "macro_release_news", "priority": "P0"},
             {"evidenceId": "ref-4", "source": "macro_release_news", "priority": "P1"},
             {"evidenceId": "ref-5", "source": "trusted_mail", "priority": "P0"}]
    line = material.required_citation_line(facts)
    assert line.startswith("必須: viewまたはreasonsのevidenceIdsに")
    assert "ref-1 を必ず含める" in line and "ref-2" not in line          # the first official result only
    assert "(ref-3)から少なくとも1つ" in line and "ref-4" not in line and "ref-5" not in line
    assert material.required_citation_line([facts[4]]) == ""
    assert material.required_citation_line(None) == ""


def test_the_line_follows_the_data_so_the_reusable_prefix_is_unchanged():
    source = (ROOT / "scanner.py").read_text(encoding="utf-8")
    at = source.index('required = argus_macro_material.required_citation_line(prompt_context.get("facts"))')
    assert source.index('json.dumps(prompt_context, ensure_ascii=False, separators=(",", ":")))') < at
    assert 'cache_prefix_chars=len(instructions)' in source


def test_presentation_rejections_are_counted_by_rule(tmp_path):
    path = tmp_path / "market_analysis_history.sqlite3"
    history.initialize(path)
    conn = sqlite3.connect(path, isolation_level=None)
    attempt = lambda v: {"provider": {"inputTokens": 1, "outputTokens": 1}, "validation": v}
    for i, detail in enumerate(["presentation_evidence_invalid", "presentation_evidence_invalid", None]):
        first = {"status": "REJECTED", "reason": "presentation_invalid", **({"detail": detail} if detail else {})}
        body = {"brief": {"aiDiagnostics": {"attempts": [attempt(first), attempt({"status": "ACCEPTED"})]}},
                "recordedAt": "2026-10-18T01:00:00Z"}
        conn.execute("INSERT INTO views(record_id,recorded_at,body) VALUES(?,?,?)",
                     (f"p-{i}", "2026-10-18T01:00:00Z", json.dumps(body)))
    conn.close()
    day = history.call_report(path, since_day="2026-10-01")["days"][0]
    assert day["firstRejectionReasons"] == {"presentation_invalid:presentation_evidence_invalid": 2,
                                            "presentation_invalid": 1}
